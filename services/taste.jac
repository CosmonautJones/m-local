"""For you: preference-aware ranking that never hides a deal.

Pure logic, no graph and no model call. Three well-known ideas, each reduced
to its simplest honest form:

- Stated preferences (as a delivery app asks at sign-up): categories, dietary
  needs and a price range the student picked. A match raises a deal.
- Learned affinity (as a social feed weighs interactions): each past claim,
  redemption or favorite counts toward its category, weighted by how strong
  the action is and halved every 14 days.
- Exploration (as a short-video feed tests new content): every fourth slot goes
  to a deal outside the student's tastes, least-shown first, so other places
  are still seen and the feed can learn.

Every live deal appears exactly once. Preferences reorder; they never filter.
"""

import hashlib;


glob:pub CATEGORIES: list[str] = [
    "noodles", "pizza", "bowls", "burgers", "tacos", "sandwiches", "breakfast",
    "sushi", "curry", "salads", "bbq", "coffee", "dessert", "bakery"
];

glob:pub DIETS: list[str] = ["vegetarian", "vegan", "gluten-free", "halal"];

# key, label, lowest cents, highest cents
glob:pub PRICE_RANGES: list[list[any]] = [
    ["under5", "Under $5", 0, 499],
    ["5to8", "$5 to $8", 500, 800],
    ["8to12", "$8 to $12", 801, 1200],
    ["12plus", "$12 and up", 1201, 100000000]
];

glob CATEGORY_WORDS: dict[str, list[str]] = {
    "noodles": ["noodle", "noodles", "ramen", "pho", "udon", "dumpling", "dumplings", "pasta"],
    "pizza": ["pizza", "slice", "slices", "pizzeria"],
    "bowls": ["bowl", "bowls", "grain", "poke"],
    "burgers": ["burger", "burgers", "smashburger"],
    "tacos": ["taco", "tacos", "burrito", "burritos", "taqueria", "quesadilla"],
    "sandwiches": ["sandwich", "sandwiches", "deli", "sub", "subs", "panini", "wrap", "wraps"],
    "breakfast": ["breakfast", "brunch", "diner", "pancake", "pancakes", "egg", "eggs", "bagel", "bagels"],
    "sushi": ["sushi", "maki", "nigiri"],
    "curry": ["curry", "curries", "tikka", "masala"],
    "salads": ["salad", "salads", "plant", "greens"],
    "bbq": ["bbq", "barbecue", "brisket", "wings"],
    "coffee": ["coffee", "latte", "espresso", "cafe", "tea", "matcha", "chai"],
    "dessert": ["dessert", "cone", "gelato", "cookie", "cookies", "cake", "sundae", "waffle"],
    "bakery": ["bakery", "pastry", "pastries", "bread", "donut", "donuts", "croissant"]
};

glob:pub ACTION_WEIGHTS: dict[str, float] = {"view": 0.5, "claim": 2.0, "favorite": 2.5, "redeem": 3.0};

glob:pub HALF_LIFE_DAYS: float = 14.0;

glob:pub EXPLORE_EVERY: int = 4;

glob:pub PINNED_FAVORITES: int = 2;


"""One past interaction with a category."""
obj Signal {
    has category: str,
        action: str,
        age_days: float = 0.0;
}

"""What is known about one student. Empty lists mean no stated preference."""
obj Taste {
    has categories: list[str] = [],
        diets: list[str] = [],
        price_range: str = "",
        favorites: list[str] = [],
        history: list[Signal] = [];
}

"""One live deal, reduced to what ranking needs."""
obj Candidate {
    has offer_id: str,
        place: str,
        title: str = "",
        categories: list[str] = [],
        dietary: list[str] = [],
        price_cents: int = 0,
        regular_cents: int = 0,
        remaining: int = 1,
        starts_in_hours: float = 0.0,
        ends_in_hours: float = 4.0,
        rotation: int = 0;
}

obj Ranked {
    has candidate: Candidate,
        score: float = 0.0,
        matched: bool = False,
        slot: str = "more",
        reasons: list[str] = [];
}


def _words(text: str) -> list[str] {
    clean = "".join([ch if ch.isalnum() else " " for ch in text.lower()]);
    return clean.split();
}


"""Categories for a place from its cuisine text and the names of what it sells."""
def categories_for(cuisine: str, extra: str = "") -> list[str] {
    words = _words(cuisine + " " + extra);
    return [c for c in CATEGORIES if any([w in words for w in CATEGORY_WORDS[c]])];
}


def price_range_of(cents: int) -> str {
    for r in PRICE_RANGES {
        if cents >= int(r[2]) and cents <= int(r[3]) {
            return str(r[0]);
        }
    }
    return "";
}


def price_range_label(key: str) -> str {
    for r in PRICE_RANGES {
        if str(r[0]) == key {
            return str(r[1]);
        }
    }
    return "";
}


def _range_index(key: str) -> int {
    keys = [str(r[0]) for r in PRICE_RANGES];
    return keys.index(key) if key in keys else -1;
}


"""Keep only known values, in the fixed display order, without repeats."""
def clean_choices(values: list[str], allowed: list[str]) -> list[str] {
    wanted = [v.strip().lower() for v in values];
    return [a for a in allowed if a in wanted];
}


"""Dietary tags with what they imply: anything vegan is also vegetarian."""
def with_implied(tags: list[str]) -> list[str] {
    return tags + ["vegetarian"] if "vegan" in tags and "vegetarian" not in tags else tags;
}


"""A place's dietary labels from everything it sells: "Vegetarian" when every
item qualifies, "Vegetarian options" when only some do."""
def place_labels(items: list[list[str]]) -> list[str] {
    out: list[str] = [];
    if not items {
        return out;
    }
    for d in DIETS {
        has_it = [d in with_implied(tags) for tags in items];
        name = d.capitalize();
        if all(has_it) {
            out.append(name);
        } elif any(has_it) {
            out.append(name + " options");
        }
    }
    return out;
}


"""Learned interest in a category: action weight times recency, capped at 3."""
def affinity(taste: Taste, category: str) -> float {
    total = 0.0;
    for s in taste.history {
        if s.category == category {
            total += ACTION_WEIGHTS.get(s.action, 0.0) * (0.5 ** (max(s.age_days, 0.0) / HALF_LIFE_DAYS));
        }
    }
    return min(total, 3.0);
}


def has_preferences(taste: Taste) -> bool {
    return bool(taste.categories or taste.diets or taste.price_range or taste.favorites or taste.history);
}


"""Score one deal for one student and say why in plain words."""
def score(c: Candidate, taste: Taste) -> Ranked {
    total = 0.0;
    matched = False;
    reasons: list[str] = [];
    liked = [k for k in c.categories if k in taste.categories];
    if liked {
        total += 3.0;
        matched = True;
        reasons.append("You like " + liked[0]);
    }
    favorite = c.place in taste.favorites;
    if favorite {
        total += 4.0;
        matched = True;
        reasons.append("A favorite of yours");
    }
    learned = max([affinity(taste, k) for k in c.categories] + [0.0]);
    if learned > 0.5 {
        matched = True;
        if not liked {
            reasons.append("Like places you have tried");
        }
    }
    total += learned;
    if taste.diets {
        missing = [d for d in taste.diets if d not in with_implied(c.dietary)];
        if not missing {
            total += 2.0;
            reasons.append(taste.diets[0].capitalize() if len(taste.diets) == 1 else "Fits your diet");
        } else {
            total -= 1.5;
            matched = False;
            reasons.append("Not marked " + missing[0]);
        }
    }
    if taste.price_range {
        mine = _range_index(taste.price_range);
        theirs = _range_index(price_range_of(c.price_cents));
        if theirs == mine {
            total += 2.5;
            reasons.append("In your price range");
        } elif theirs < mine {
            total += 0.5;
        } else {
            total -= 1.0;
        }
    }
    if c.regular_cents > c.price_cents and c.regular_cents > 0 {
        total += min((c.regular_cents - c.price_cents) / c.regular_cents, 1.0);
    }
    if c.starts_in_hours > 0 {
        total -= 1.5;
        reasons.append("Starts later");
    } elif c.remaining > 0 and (c.ends_in_hours <= 2.0 or c.remaining <= 3) {
        # Urgency only for deals a student can still claim: a sold-out deal is
        # neither "almost gone" nor worth moving up the feed.
        total += 0.5;
        reasons.append("Ending soon" if c.ends_in_hours <= 2.0 else "Almost gone");
    }
    return Ranked(candidate=c, score=round(total, 4), matched=matched, reasons=reasons);
}


"""A stable number for one deal and one viewer-day, so equally good deals take
turns and no two students see the same tie order."""
def rotation_for(salt: str, offer_id: str) -> int {
    return int(hashlib.sha256((salt + ":" + offer_id).encode()).hexdigest()[:8], 16);
}


"""With nothing known about the student, deals in the same half-point score
band take turns, so exposure spreads across places."""
def _by_band(items: list[Ranked]) -> list[Ranked] {
    return sorted(items, key=lambda (r: Ranked) -> tuple[int, int, str] {
        return (-int(r.score * 2), r.candidate.rotation, r.candidate.offer_id);
    });
}


def _by_score(items: list[Ranked]) -> list[Ranked] {
    return sorted(items, key=lambda (r: Ranked) -> tuple[float, int, str] {
        return (-r.score, r.candidate.rotation, r.candidate.offer_id);
    });
}


def _by_exposure(items: list[Ranked]) -> list[Ranked] {
    return sorted(items, key=lambda (r: Ranked) -> tuple[int, float, str] {
        return (r.candidate.rotation, -r.score, r.candidate.offer_id);
    });
}


"""Order every deal for one student. The best deal from up to PINNED_FAVORITES
favorite places comes first, then matches lead, every EXPLORE_EVERY-th slot is
a deal outside their tastes, and whatever is left follows by score. With no
preferences at all, deals are ordered by value with a fair rotation."""
def build_feed(
    candidates: list[Candidate], taste: Taste, salt: str = "", explore_every: int = EXPLORE_EVERY
) -> list[Ranked] {
    if salt {
        for c in candidates {
            c.rotation = rotation_for(salt, c.offer_id);
        }
    }
    ranked = [score(c, taste) for c in candidates];
    if not has_preferences(taste) {
        return _by_band(ranked);
    }
    matches = _by_score([r for r in ranked if r.matched]);
    others = _by_exposure([r for r in ranked if not r.matched]);
    if not matches and not [r for r in ranked if r.candidate.place in taste.favorites] {
        return _by_band(ranked);
    }
    feed: list[Ranked] = [];
    pinned_places: list[str] = [];
    for r in _by_score(ranked) {
        place = r.candidate.place;
        if len(pinned_places) < PINNED_FAVORITES and place in taste.favorites and place not in pinned_places {
            pinned_places.append(place);
            r.slot = "favorite";
            feed.append(r);
        }
    }
    matches = [r for r in matches if r.slot != "favorite"];
    others = [r for r in others if r.slot != "favorite"];
    # Two orders over the same leftovers: least-shown first for the exploration
    # slots, best fit first for everything else once the matches run out.
    by_fit = _by_band(others);
    # `used` only grows, so the first unused entry of each order only moves
    # forward: two cursors give the same picks as rescanning both lists every
    # turn, in linear rather than cubic time.
    used: set[str] = set();
    next_explore = 0;
    next_fit = 0;
    while matches or len(used) < len(others) {
        position = len(feed) + 1;
        explore_turn = explore_every > 0 and position % explore_every == 0;
        while next_explore < len(others) and others[next_explore].candidate.offer_id in used {
            next_explore += 1;
        }
        if next_explore < len(others) and explore_turn {
            pick = others[next_explore];
            pick.slot = "explore";
            pick.reasons = ["Something different"] + pick.reasons;
            used.add(pick.candidate.offer_id);
            feed.append(pick);
        } elif matches {
            pick = matches.pop(0);
            pick.slot = "match";
            feed.append(pick);
        } else {
            while next_fit < len(by_fit) and by_fit[next_fit].candidate.offer_id in used {
                next_fit += 1;
            }
            pick = by_fit[next_fit];
            pick.slot = "more";
            used.add(pick.candidate.offer_id);
            feed.append(pick);
        }
    }
    return feed;
}
