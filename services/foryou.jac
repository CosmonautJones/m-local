"""For you: saved tastes, favorites and the personalized home feed.

A student's tastes and favorites live in their own private graph:

    root -> TasteProfile -Keeps-> Favorite

No other account can read them. The home feed walks the shared catalog, turns
each live offer into a ranking candidate, and lets services/taste.jac order
them. Guests and students with no saved tastes get every deal in a fair
rotation. Tastes reorder the feed; the only things that remove a deal are the
filters the student taps on the page.
"""

import os;
import time;
import random;
import from datetime { datetime }
import from zoneinfo { ZoneInfo }
import from services.models { Restaurant, Location, MenuItem, Offer, Redemption, HasLocation, Serves, Publishes, ClaimedAs }
import from services.qr_catalog { _ensure_seed }
import from services.session { _actor_id }
import from services.promo { OfferView, _view, _state, _find_offer, _restaurant_of, _lock, _unlock }
import from services.importer { import_restaurant }
import from services.taste_sandbox { Company, make_companies }
import from services.taste {
    CATEGORIES,
    DIETS,
    PRICE_RANGES,
    Signal,
    Taste,
    Candidate,
    Ranked,
    build_feed,
    categories_for,
    clean_choices,
    place_labels,
    price_range_of,
    with_implied
}


node TasteProfile {
    has categories: list[str] = [],
        diets: list[str] = [],
        price_range: str = "",
        completed: bool = False,
        updated_ts: float = 0.0;
}

node Favorite {
    has slug: str,
        since_ts: float = 0.0;
}

edge Keeps: TasteProfile --> Favorite {}


obj Choice {
    has key: str = "",
        label: str = "";
}

obj TasteView {
    has ok: bool = False,
        message: str = "",
        signed_in: bool = False,
        completed: bool = False,
        categories: list[str] = [],
        diets: list[str] = [],
        price_range: str = "",
        favorites: list[str] = [],
        all_categories: list[Choice] = [],
        all_diets: list[Choice] = [],
        all_price_ranges: list[Choice] = [];
}

obj FeedItem {
    has offer: OfferView,
        place: str = "",
        place_labels: list[str] = [],
        categories: list[str] = [],
        price_cents: int = 0,
        regular_cents: int = 0,
        price_range: str = "",
        reasons: list[str] = [],
        slot: str = "more",
        is_favorite: bool = False;
}

obj FavoritePlace {
    has slug: str = "",
        name: str = "",
        cuisine: str = "",
        neighborhood: str = "",
        labels: list[str] = [],
        live_offers: int = 0,
        best_offer_id: str = "",
        best_offer_title: str = "",
        best_price_cents: int = 0,
        is_demo: bool = False;
}

obj HomeView {
    has signed_in: bool = False,
        personalized: bool = False,
        completed: bool = False,
        price_range: str = "",
        favorites: list[FavoritePlace] = [],
        items: list[FeedItem] = [],
        total_deals: int = 0,
        show_samples: bool = False,
        note: str = "";
}


# ------------------------------------------------------------ profile ---

def _profile(create: bool = False) -> TasteProfile | None {
    found = [root -->[?:TasteProfile]];
    if found {
        return found[0];
    }
    if not create {
        return None;
    }
    fresh = TasteProfile(updated_ts=time.time());
    root ++> fresh;
    return fresh;
}


def _favorite_slugs(p: TasteProfile | None) -> list[str] {
    if p is None {
        return [];
    }
    marks = [f for f in [p ->:Keeps:->]];
    marks.sort(key=lambda (f: Favorite) -> float { return f.since_ts; }, reverse=True);
    return [f.slug for f in marks];
}


def _choices() -> list[list[Choice]] {
    return [
        [Choice(key=c, label=c.capitalize()) for c in CATEGORIES],
        [Choice(key=d, label=d.capitalize()) for d in DIETS],
        [Choice(key=str(r[0]), label=str(r[1])) for r in PRICE_RANGES]
    ];
}


def _taste_view(p: TasteProfile | None, signed_in: bool, message: str = "", ok: bool = True) -> TasteView {
    lists = _choices();
    return TasteView(
        ok=ok,
        message=message,
        signed_in=signed_in,
        completed=p.completed if p is not None else False,
        categories=p.categories if p is not None else [],
        diets=p.diets if p is not None else [],
        price_range=p.price_range if p is not None else "",
        favorites=_favorite_slugs(p),
        all_categories=lists[0],
        all_diets=lists[1],
        all_price_ranges=lists[2]
    );
}


def _split(text: str) -> list[str] {
    return [t for t in [x.strip() for x in text.split(",")] if t];
}


def _save_taste(categories: str, diets: str, price_range: str, now: float) -> TasteView {
    p = _profile(True);
    if p is None {
        return _taste_view(None, True, "Could not save your tastes.", False);
    }
    keys = [str(r[0]) for r in PRICE_RANGES];
    p.categories = clean_choices(_split(categories), CATEGORIES);
    p.diets = clean_choices(_split(diets), DIETS);
    p.price_range = price_range.strip() if price_range.strip() in keys else "";
    p.completed = True;
    p.updated_ts = now;
    return _taste_view(p, True, "Saved. You will still see every deal.");
}


def _toggle_favorite(slug: str, now: float) -> TasteView {
    known = [r for r in [root.shared -->[?:Restaurant]] if r.slug == slug];
    if not slug or not known {
        return _taste_view(_profile(), True, "That place is no longer listed.", False);
    }
    p = _profile(True);
    if p is None {
        return _taste_view(None, True, "Could not update favorites.", False);
    }
    existing = [f for f in [p ->:Keeps:->] if f.slug == slug];
    if existing {
        for f in existing {
            del f;
        }
        return _taste_view(p, True, "Removed from favorites.");
    }
    p +>:Keeps():+> Favorite(slug=slug, since_ts=now);
    return _taste_view(p, True, "Added to favorites.");
}


# --------------------------------------------------------------- feed ---

def _place_labels(r: Restaurant) -> list[str] {
    return place_labels([m.dietary for m in [r ->:Serves:->]]);
}


"""Categories come from the deal itself when it names a food (an oat latte at
a bowl restaurant is coffee), otherwise from the place's cuisine and menu."""
def _categories(r: Restaurant, o: Offer | None = None) -> list[str] {
    if o is not None {
        named = categories_for(o.title, o.menu_item);
        if named {
            return named;
        }
    }
    return categories_for(r.cuisine, " ".join([m.name for m in [r ->:Serves:->]]));
}


"""The caller's own claims become learning signals. Other students' claims are
private nodes this account cannot read, so they never enter the ranking."""
def _history(actor: str, now: float) -> list[Signal] {
    out: list[Signal] = [];
    if not actor {
        return out;
    }
    for r in [root.shared -->[?:Restaurant]] {
        for o in [r ->:Publishes:->] {
            for c in [o ->:ClaimedAs:->] {
                if c.actor_id != actor or c.status not in ["claimed", "redeemed"] {
                    continue;
                }
                when = c.redeemed_ts if c.status == "redeemed" else c.claimed_ts;
                for k in _categories(r, o) {
                    out.append(Signal(
                        category=k,
                        action="redeem" if c.status == "redeemed" else "claim",
                        age_days=max(now - when, 0.0) / 86400
                    ));
                }
            }
        }
    }
    return out;
}


def _taste(p: TasteProfile | None, actor: str, now: float) -> Taste {
    return Taste(
        categories=p.categories if p is not None else [],
        diets=p.diets if p is not None else [],
        price_range=p.price_range if p is not None else "",
        favorites=_favorite_slugs(p),
        history=_history(actor, now)
    );
}


def _favorite_places(slugs: list[str], now: float) -> list[FavoritePlace] {
    out: list[FavoritePlace] = [];
    for slug in slugs {
        for r in [root.shared -->[?:Restaurant]] {
            if r.slug != slug {
                continue;
            }
            locs = [r ->:HasLocation:->];
            live = [o for o in [r ->:Publishes:->] if _state(o, now) == "active"];
            live.sort(key=lambda (o: Offer) -> int { return o.price_cents; });
            out.append(FavoritePlace(
                slug=r.slug,
                name=r.name.replace(" (Demo)", ""),
                cuisine=r.cuisine,
                neighborhood=locs[0].neighborhood if locs else "",
                labels=_place_labels(r),
                live_offers=len(live),
                best_offer_id=jid(live[0]) if live else "",
                best_offer_title=live[0].title if live else "",
                best_price_cents=live[0].price_cents if live else 0,
                is_demo=r.is_demo
            ));
        }
    }
    return out;
}


def _end_of_today(now: float) -> float {
    d = datetime.fromtimestamp(now, ZoneInfo("America/Detroit"));
    return d.replace(hour=23, minute=59, second=59).timestamp();
}


"""Build the home page for one caller. price_range, window and diets are the
filters tapped on the page; saved tastes only change the order."""
def _home(actor: str, price_range: str, window: str, diets: str, now: float) -> HomeView {
    p = _profile() if actor else None;
    taste = _taste(p, actor, now);
    wanted = clean_choices(_split(diets), DIETS);
    keys = [str(r[0]) for r in PRICE_RANGES];
    chosen_range = price_range.strip() if price_range.strip() in keys else "";
    # Custom slider range "lo-hi" in whole dollars, e.g. "3-12".
    lo_cents = -1;
    hi_cents = -1;
    bounds = price_range.strip().split("-");
    if not chosen_range and len(bounds) == 2 and bounds[0].isdigit() and bounds[1].isdigit() {
        lo_cents = int(bounds[0]) * 100;
        hi_cents = int(bounds[1]) * 100;
        if lo_cents <= hi_cents { chosen_range = price_range.strip(); } else { lo_cents = -1; hi_cents = -1; }
    }
    eod = _end_of_today(now);
    candidates: list[Candidate] = [];
    views: dict[str, OfferView] = {};
    places: dict[str, Restaurant] = {};
    total = 0;
    for r in [root.shared -->[?:Restaurant]] {
        if r.archived { continue; }
        for o in [r ->:Publishes:->] {
            if o.archived { continue; }
            v = _view(o, now, actor);
            starter_fixture = os.environ.get("MLOCAL_HOSTED_DATASET", "") == "1" and r.source == "demo-seed";
            discoverable = o.status != "paused" and now < o.end_ts and not starter_fixture;
            if discoverable { total += 1; }
            # A live saved QR must remain reachable after offer edits or filter
            # changes. Only its owner bypasses discovery rules, until expiry.
            if v.my_status != "claimed" {
                if not discoverable { continue; }
                if lo_cents >= 0 {
                    if o.price_cents < lo_cents or o.price_cents > hi_cents { continue; }
                } elif chosen_range and price_range_of(o.price_cents) != chosen_range {
                    continue;
                }
                if window == "now" and o.start_ts > now {
                    continue;
                }
                if window == "today" and o.start_ts > eod {
                    continue;
                }
                if wanted and [w for w in wanted if w not in with_implied(o.dietary)] {
                    continue;
                }
            }
            oid = jid(o);
            views[oid] = v;
            places[oid] = r;
            candidates.append(Candidate(
                offer_id=oid,
                place=r.slug,
                title=o.title,
                categories=_categories(r, o),
                dietary=o.dietary,
                price_cents=o.price_cents,
                regular_cents=o.regular_price_cents,
                remaining=v.remaining,
                starts_in_hours=max(o.start_ts - now, 0.0) / 3600,
                ends_in_hours=max(o.end_ts - now, 0.0) / 3600
            ));
        }
    }
    day = datetime.fromtimestamp(now, ZoneInfo("America/Detroit")).strftime("%Y-%m-%d");
    ranked = build_feed(candidates, taste, (actor or "guest") + ":" + day);
    items: list[FeedItem] = [];
    for r in ranked {
        oid = r.candidate.offer_id;
        items.append(FeedItem(
            offer=views[oid],
            place=r.candidate.place,
            place_labels=_place_labels(places[oid]),
            categories=r.candidate.categories,
            price_cents=r.candidate.price_cents,
            regular_cents=r.candidate.regular_cents,
            price_range=price_range_of(r.candidate.price_cents),
            reasons=r.reasons,
            slot=r.slot,
            is_favorite=r.candidate.place in taste.favorites
        ));
    }
    personalized = bool(taste.categories or taste.diets or taste.price_range or taste.favorites or taste.history);
    return HomeView(
        show_samples=demo_mode(os.environ.get(DEMO_MODE_ENV, "")) or os.environ.get("MLOCAL_HOSTED_DATASET", "") == "1",
        signed_in=bool(actor),
        personalized=personalized,
        completed=p.completed if p is not None else False,
        price_range=chosen_range,
        favorites=_favorite_places(taste.favorites, now),
        items=items,
        total_deals=total,
        note="" if items else "No deals match these filters right now."
    );
}


# -------------------------------------------------------- demo catalog ---

glob DEMO_MODE_ENV: str = "MLOCAL_DEMO_MODE";


def demo_mode(text: str) -> bool {
    return text.strip().lower() in ["1", "true", "yes", "on"];
}


# Presentation aid: a server operator may set this to a number (for example 30)
# to add that many random fictional companies to the catalog. Never client-set.
glob DEMO_COMPANIES_ENV: str = "MLOCAL_DEMO_COMPANIES";

glob DEMO_HOODS: list[str] = ["State Street", "Kerrytown", "Main Street", "South University", "North Campus"];


def demo_company_count(text: str) -> int {
    try {
        value = int(text.strip());
    } except ValueError {
        return 0;
    }
    return value if value > 0 and value <= 200 else 0;
}


def _company_record(c: Company, index: int) -> dict[str, any] {
    rng = random.Random(index);
    offers: list[dict[str, any]] = [];
    menu: list[dict[str, any]] = [];
    for (j, o) in enumerate(c.offers) {
        item = f"{c.category.capitalize()} special {j + 1}";
        menu.append({"name": item, "price": o.regular_cents / 100, "dietary": o.dietary});
        offers.append({
            "title": f"{item} for ${o.price_cents // 100}" + ("" if o.price_cents % 100 == 0 else f".{o.price_cents % 100:02d}"),
            "description": "Fictional demo deal.",
            "price": o.price_cents / 100,
            "regular_price": o.regular_cents / 100,
            "start_in_h": -1,
            "end_in_h": o.ends_in_hours if o.ends_in_hours > 1.0 else 1.0,
            "quantity": o.remaining + 5,
            "eligibility": "Students with a valid university ID",
            "terms": "One per student. Fictional demo deal.",
            "dietary": o.dietary,
            "menu_item": item
        });
    }
    return {
        "slug": "sandbox-" + str(index),
        "name": c.name,
        "cuisine": c.category.capitalize(),
        "blurb": "Fictional demo business generated for testing.",
        "is_demo": True,
        "source": "sandbox",
        "location": {"address": f"{100 + index} Example Ave, Ann Arbor (fictional)", "neighborhood": rng.choice(DEMO_HOODS)},
        "menu": menu,
        "offers": offers
    };
}


"""Add random fictional companies to the shared catalog, once."""
def _seed_demo_companies(count: int) -> int {
    have = [r.slug for r in [root.shared -->[?:Restaurant]]];
    added = 0;
    for (i, c) in enumerate(make_companies(count, 442)) {
        if "sandbox-" + str(i) in have {
            continue;
        }
        r = import_restaurant(_company_record(c, i));
        if jid(root) != jid(root.shared) {
            root.shared ++> r;
        }
        for o in [r ->:Publishes:->] {
            o.qr_ready = True;
        }
        added += 1;
    }
    return added;
}


def _demo_companies_present -> int {
    return len([r for r in [root.shared -->[?:Restaurant]] if r.slug.startswith("sandbox-")]);
}


# ---------------------------------------------------------- endpoints ---

"""The home page: favorites strip plus every live deal, ordered for the caller."""
def:pub home_feed(price_range: str = "", window: str = "any", diets: str = "") -> HomeView {
    _ensure_seed();
    return _home(_actor_id(), price_range, window, diets, time.time());
}


"""Presentation aid. Adds the random fictional companies the server operator
asked for with MLOCAL_DEMO_COMPANIES, and returns how many exist. It takes no
input, only ever adds demo-flagged places, and does nothing when the setting
is absent. Kept out of home_feed so reading the feed never writes."""
def:pub prepare_demo_catalog() -> int {
    _ensure_seed();
    count = demo_company_count(os.environ.get(DEMO_COMPANIES_ENV, ""));
    if count == 0 {
        return _demo_companies_present();
    }
    fd = _lock();
    try {
        _seed_demo_companies(count);
        present = _demo_companies_present();
    } finally {
        _unlock(fd);
    }
    return present;
}


"""The choices for the tastes screen, with the caller's saved answers if any."""
def:pub taste_choices() -> TasteView {
    actor = _actor_id();
    return _taste_view(_profile() if actor else None, bool(actor));
}


def:protect save_taste(categories: str, diets: str, price_range: str) -> TasteView {
    return _save_taste(categories, diets, price_range, time.time());
}


"""Add or remove a favorite place, named by its slug or by one of its offers."""
def:protect toggle_favorite(slug: str = "", offer_id: str = "") -> TasteView {
    _ensure_seed();
    target = slug.strip();
    if not target and offer_id {
        o = _find_offer(offer_id);
        r = _restaurant_of(o) if o is not None else None;
        target = r.slug if r is not None else "";
    }
    return _toggle_favorite(target, time.time());
}
