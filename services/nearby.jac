"""What now? Nearby places to go after a redeemed claim.

Places are grouped as activities, coffee, dessert and bars, each with its
walking distance from the place the student just visited. Within a group the
nearest place comes first and at most four are shown. A place with a live
deal in the app says so and links to it; when one is within a walk but not
among the nearest four, it takes the fourth spot.

A restaurant that is linked to a place in the catalog has a recorded
position, so its suggestions are catalog places measured from that position.
Distances are straight lines, so walking times are estimates.

Without that link every coordinate is invented: suggestions then require
server demo mode, a demo origin and demo destinations/offers. Reading this
never writes anything and never records who looked.
"""

import os;
import math;
import time;
import hashlib;
import from services.models { Restaurant, Offer, Publishes, HasLocation }
import from services.places { Place, LocatedAt }
import from services.qr_catalog { _ensure_seed }
import from services.promo { _state, _remaining, _find_offer, _restaurant_of, _location_of }
import from services.taste { categories_for }
import from services.nearby_data { AREA_CENTERS, DEFAULT_AREA, SAMPLE_PLACES }


glob:pub KINDS: list[list[str]] = [
    ["activity", "Activities"], ["coffee", "Coffee"], ["dessert", "Dessert"], ["bars", "Bars"]
];

glob:pub MAX_METERS: float = 1300.0;

glob:pub MAX_PER_KIND: int = 4;

glob:pub METERS_PER_MINUTE: float = 80.0;

glob DEMO_MODE: str = "MLOCAL_DEMO_MODE";

glob HOSTED_DATASET: str = "MLOCAL_HOSTED_DATASET";

glob:pub PLACE_KINDS: dict[str, list[str]] = {
    "cafe": ["coffee", "Cafe"],
    "bakery": ["dessert", "Bakery"],
    "dessert": ["dessert", "Dessert"],
    "ice_cream": ["dessert", "Ice cream"],
    "bar": ["bars", "Bar"],
    "pub": ["bars", "Pub"],
    "bookshop": ["activity", "Bookstore"],
    "museum": ["activity", "Museum"],
    "gallery": ["activity", "Gallery"],
    "entertainment": ["activity", "Entertainment"],
    "park": ["activity", "Park"],
    "retail": ["activity", "Shop"]
};

glob:pub ATTRIBUTION: str = "Place data from OpenStreetMap contributors (ODbL). Distances are straight lines; walking times are estimates.";


obj NearbyCard {
    has name: str = "",
        kind: str = "",
        what: str = "",
        meters: int = 0,
        distance: str = "",
        minutes: int = 0,
        deal: str = "",
        deal_offer_id: str = "",
        is_sample: bool = False,
        sample_deal: bool = False,
        adults_only: bool = False;
}

obj NearbyGroup {
    has kind: str = "",
        label: str = "",
        cards: list[NearbyCard] = [];
}

obj NearbyView {
    has ok: bool = False,
        heading: str = "What now?",
        origin: str = "",
        has_samples: bool = False,
        sample_deals: bool = False,
        from_catalog: bool = False,
        attribution: str = "",
        groups: list[NearbyGroup] = [],
        note: str = "";
}


def samples_on(text: str) -> bool {
    return text.strip().lower() in ["1", "true", "yes", "on"];
}


def meters_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float {
    radius = 6371000.0;
    p1 = math.radians(lat1);
    p2 = math.radians(lat2);
    dp = math.radians(lat2 - lat1);
    dl = math.radians(lng2 - lng1);
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2;
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)));
}


def distance_label(meters: float) -> str {
    miles = meters / 1609.344;
    if miles < 0.1 {
        feet = int(round(meters * 3.28084 / 50.0)) * 50;
        return f"{max(50, feet)} ft";
    }
    return f"{miles:.1f} mi";
}


def walk_minutes(meters: float) -> int {
    return max(1, int(round(meters / METERS_PER_MINUTE)));
}


def center_of(neighborhood: str) -> list[float] {
    return AREA_CENTERS.get(neighborhood.strip().lower(), AREA_CENTERS[DEFAULT_AREA]);
}


"""A steady, invented position for a listed place: its neighborhood's center
moved by up to about 150 meters, the same every time for the same place."""
def position_of(slug: str, neighborhood: str) -> list[float] {
    center = center_of(neighborhood);
    digest = hashlib.sha256(slug.encode()).hexdigest();
    north = (int(digest[:4], 16) / 65535.0 - 0.5) * 300.0;
    east = (int(digest[4:8], 16) / 65535.0 - 0.5) * 300.0;
    return [center[0] + north / 111320.0, center[1] + east / (111320.0 * math.cos(math.radians(center[0])))];
}


def kind_for(cuisine: str, title: str) -> str {
    found = categories_for(cuisine, title);
    if "coffee" in found {
        return "coffee";
    }
    if "dessert" in found or "bakery" in found {
        return "dessert";
    }
    return "";
}


def _card(kind: str, what: str, name: str, meters: float, deal: str = "", offer_id: str = "", sample: bool = False) -> NearbyCard {
    return NearbyCard(
        name=name, kind=kind, what=what, meters=int(round(meters)), distance=distance_label(meters),
        minutes=walk_minutes(meters), deal=deal, deal_offer_id=offer_id, is_sample=sample, adults_only=kind == "bars"
    );
}


def sample_cards(lat: float, lng: float) -> list[NearbyCard] {
    out: list[NearbyCard] = [];
    for row in SAMPLE_PLACES {
        meters = meters_between(lat, lng, float(row[3]), float(row[4]));
        out.append(_card(str(row[0]), str(row[1]), str(row[2]), meters, ("Sample deal: " + str(row[5])) if row[5] else "", "", True));
    }
    return out;
}


def _price(cents: int) -> str {
    return f"${cents // 100}" + ("" if cents % 100 == 0 else f".{cents % 100:02d}");
}


"""The catalog place a restaurant has been linked to, if any."""
def place_of(r: Restaurant) -> Place | None {
    for loc in [r ->:HasLocation:->] {
        linked = [loc ->:LocatedAt:->];
        if linked {
            return linked[0];
        }
    }
    return None;
}


"""The cheapest deal a restaurant has running right now, if any. Demo deals
count only in demo mode."""
def live_deal(r: Restaurant, now: float, samples: bool) -> Offer | None {
    if r.is_demo and not samples {
        return None;
    }
    live = [o for o in [r ->:Publishes:->] if _state(o, now) == "active" and (samples or not o.is_demo)];
    if not live {
        return None;
    }
    return sorted(live, key=lambda (o: any) -> int { return int(o.price_cents); })[0];
}


"""Catalog places within a walk of a recorded position, other than the one
just visited. A place whose restaurant has a live deal carries that deal."""
def catalog_cards(origin_slug: str, origin_place_id: str, lat: float, lng: float, now: float, samples: bool) -> list[NearbyCard] {
    near: list[list[any]] = [];
    for p in [root.shared -->[?:Place]] {
        if p.place_id == origin_place_id or "restricted_access_tag" in p.quality_flags or p.category not in PLACE_KINDS {
            continue;
        }
        meters = meters_between(lat, lng, p.lat, p.lon);
        if meters <= MAX_METERS {
            near.append([p.place_id, p, meters]);
        }
    }
    wanted = set([str(row[0]) for row in near]);
    owners: dict[str, Restaurant] = {};
    for r in [root.shared -->[?:Restaurant]] {
        if r.slug == origin_slug {
            continue;
        }
        linked = place_of(r);
        if linked is not None and linked.place_id in wanted {
            owners[linked.place_id] = r;
        }
    }
    out: list[NearbyCard] = [];
    for row in near {
        p = row[1];
        kind = PLACE_KINDS[p.category];
        deal = "";
        offer_id = "";
        fictional = False;
        if p.place_id in owners {
            best = live_deal(owners[p.place_id], now, samples);
            if best is not None {
                deal = f"Deal on now: {best.title}" + (f" ({_price(best.price_cents)})" if best.price_cents >= 0 and _price(best.price_cents) not in best.title else "");
                offer_id = jid(best);
                fictional = best.is_demo or owners[p.place_id].is_demo;
            }
        }
        card = _card(kind[0], kind[1], p.name, float(row[2]), deal, offer_id, False);
        card.sample_deal = fictional;
        out.append(card);
    }
    return out;
}


"""Demo places with a demo deal running now, other than the one just visited.
Real businesses never receive invented coordinates for these cards."""
def listed_cards(origin_slug: str, lat: float, lng: float, now: float, samples: bool) -> list[NearbyCard] {
    out: list[NearbyCard] = [];
    for r in [root.shared -->[?:Restaurant]] {
        if not samples or not r.is_demo or r.slug == origin_slug {
            continue;
        }
        live = [o for o in [r ->:Publishes:->] if _state(o, now) == "active" and o.is_demo];
        if not live {
            continue;
        }
        best = sorted(live, key=lambda (o: any) -> int { return int(o.price_cents); })[0];
        kind = kind_for(r.cuisine, best.title);
        if not kind {
            continue;
        }
        loc = _location_of(r);
        spot = position_of(r.slug, loc.neighborhood if loc else "");
        out.append(_card(
            kind, r.cuisine or "Listed place", r.name, meters_between(lat, lng, spot[0], spot[1]),
            f"Deal on now: {best.title}" + (f" ({_price(best.price_cents)})" if best.price_cents >= 0 and _price(best.price_cents) not in best.title else ""),
            jid(best), r.is_demo
        ));
    }
    return out;
}


"""The nearest places, with room kept for one that has a live deal."""
def nearest(cards: list[NearbyCard], most: int) -> list[NearbyCard] {
    kept = cards[:most];
    if most > 0 and len(cards) > most and not [c for c in kept if c.deal_offer_id] {
        listed = [c for c in cards[most:] if c.deal_offer_id];
        if listed {
            kept = kept[:most - 1] + [listed[0]];
        }
    }
    return kept;
}


"""Group, keep what is within a walk, and put the nearest first."""
def build_groups(cards: list[NearbyCard]) -> list[NearbyGroup] {
    out: list[NearbyGroup] = [];
    for pair in KINDS {
        mine = [c for c in cards if c.kind == pair[0] and c.meters <= MAX_METERS];
        mine = sorted(mine, key=lambda (c: NearbyCard) -> tuple[int, str] { return (c.meters, c.name); });
        if mine {
            out.append(NearbyGroup(kind=pair[0], label=pair[1], cards=nearest(mine, MAX_PER_KIND)));
        }
    }
    return out;
}


def _nearby(offer_id: str, now: float, samples: bool, dataset: bool = False) -> NearbyView {
    o = _find_offer(offer_id);
    r = _restaurant_of(o) if o is not None else None;
    if o is None or r is None {
        return NearbyView(note="That offer no longer exists.");
    }
    home = place_of(r);
    if home is not None {
        found = build_groups(catalog_cards(r.slug, home.place_id, home.lat, home.lon, now, samples or dataset));
        if not found {
            return NearbyView(origin=r.name, from_catalog=True, attribution=ATTRIBUTION, note="No places are recorded within a short walk.");
        }
        return NearbyView(
            ok=True, origin=r.name, groups=found, from_catalog=True, attribution=ATTRIBUTION,
            sample_deals=any([c.sample_deal for g in found for c in g.cards])
        );
    }
    if not samples or not r.is_demo or not o.is_demo {
        return NearbyView(origin=r.name, note="Walking suggestions require verified locations. Demo cards are available only for demo offers.");
    }
    loc = _location_of(r);
    here = position_of(r.slug, loc.neighborhood if loc else "");
    cards = listed_cards(r.slug, here[0], here[1], now, samples);
    if samples {
        cards += sample_cards(here[0], here[1]);
    }
    groups = build_groups(cards);
    if not groups {
        return NearbyView(origin=r.name, note="No nearby places are listed yet.");
    }
    return NearbyView(
        ok=True, origin=r.name, groups=groups,
        has_samples=any([c.is_sample for g in groups for c in g.cards]),
        note="Sample places with invented distances and deals." if samples else ""
    );
}


"""Nearby places to go after the offer's place, for the What now? cards."""
def:pub nearby_after(offer_id: str) -> NearbyView {
    _ensure_seed();
    return _nearby(
        offer_id, time.time(), samples_on(os.environ.get(DEMO_MODE, "")),
        os.environ.get(HOSTED_DATASET, "") == "1"
    );
}
