"""In-process snapshot of the public catalog for fast reads.

Every feed, list and detail read used to walk the graph restaurant by
restaurant: offers, location, access notices, menu and stock were separate
round trips per place, thousands per request. The snapshot copies the public,
shared catalog into plain objects with a handful of batched queries and reuses
it until something changes.

Safety rules:

* Only public catalog data is cached (restaurants, locations, menu labels,
  offers, public stock reservations and access notices). Private claims are
  never shared across accounts: `actor_claims` keeps one account's own claims,
  read under that account's own access rights, for that account only.
* Reads only. Claims, cancellations, redemptions and publication still read
  and write the live graph under the mutation lock, so the cache cannot cause
  an oversell or a stale authorization decision. Suspension and ownership
  (listing_visible / merchant_operations_enabled) stay live per request.
* Writers invalidate: promo._unlock marks the whole catalog changed after
  every locked mutation; claim, cancel and redeem instead mark just the offer's
  stock and the claimant's own claims. A snapshot also expires after
  CATALOG_MAX_AGE_SECONDS as a safety net for writes outside the lock
  (seeding, imports).
* MLOCAL_CATALOG_CACHE=off rebuilds on every read (no reuse). scripts/test.sh
  sets it for in-process suites, which write the graph directly without the
  mutation lock; catalog.test.jac covers reuse and invalidation with it on.
* One process owns the cache. The supported topology is a single serialized
  backend (docs/RELEASE-HOSTING-PACKAGE.md); a second replica would serve
  displays up to the max age stale but would not change claim correctness.
"""

import os;
import threading;
import time;
import from services.models {
    Restaurant,
    Location,
    MenuItem,
    Offer,
    Redemption,
    Reservation,
    Publishes,
    HasLocation,
    Serves,
    Reserves,
    ClaimedAs
}
import from services.context_models { ContextNotice, Affects, NoticeSrc }
import from services.context { notice_src }
import from services.taste { place_labels, categories_for }
import from services.catalog_events {
    cache_state,
    actor_cache,
    cache_lock,
    catalog_changed,
    offer_stock_changed,
    actor_claims_changed,
    reset_catalog_cache
}


glob CATALOG_MAX_AGE_SECONDS: float = 600.0,
     ACTOR_CLAIMS_MAX_AGE_SECONDS: float = 120.0,
     ACTOR_CLAIMS_MAX_ENTRIES: int = 20000;


"""Public fields of one offer plus its public stock projection."""
obj OfferSrc {
    has id: str = "",
        place_slug: str = "",
        title: str = "",
        description: str = "",
        image_url: str = "",
        price_cents: int = 0,
        regular_price_cents: int = 0,
        start_ts: float = 0.0,
        end_ts: float = 0.0,
        quantity: int = 0,
        status: str = "active",
        qr_ready: bool = False,
        eligibility: str = "",
        terms: str = "",
        dietary: list[str] = [],
        menu_item: str = "",
        is_demo: bool = False,
        redeemed: int = 0,
        held: list[float] = [],
        categories: list[str] = [];
}


"""Public fields of one restaurant, its first location and its offers."""
obj PlaceSrc {
    has id: str = "",
        slug: str = "",
        name: str = "",
        source: str = "",
        is_demo: bool = False,
        image_url: str = "",
        cuisine: str = "",
        has_location: bool = False,
        loc_id: str = "",
        address: str = "",
        neighborhood: str = "",
        entrance_note: str = "",
        note_date: str = "",
        labels: list[str] = [],
        categories: list[str] = [],
        offers: list[OfferSrc] = [];
}


"""One of the caller's own claims, copied under the caller's access rights."""
obj ClaimSrc {
    has id: str = "",
        offer_id: str = "",
        status: str = "",
        claimed_ts: float = 0.0,
        expires_ts: float = 0.0,
        redeemed_ts: float = 0.0,
        offer_title_snapshot: str = "",
        price_cents_snapshot: int = 0,
        terms_snapshot: str = "",
        eligibility_snapshot: str = "",
        qr_payload: str = "";
}


obj CatalogSnapshot {
    has generation: int = 0,
        built_at: float = 0.0,
        places: list[PlaceSrc] = [],
        offers: dict[str, OfferSrc] = {},
        place_of: dict[str, PlaceSrc] = {},
        by_slug: dict[str, PlaceSrc] = {},
        notices: list[NoticeSrc] = [],
        notices_at: dict[str, list[NoticeSrc]] = {};
}


# State and change signals live in catalog_events (no project imports) so that
# seeding modules this file depends on can signal without an import cycle.


# --------------------------------------------------------------- copies ---

def _stock(reservations: list[Reservation]) -> tuple[int, list[float]] {
    redeemed = 0;
    held: list[float] = [];
    for s in reservations {
        if s.status == "redeemed" {
            redeemed += 1;
        } elif s.status == "claimed" {
            held.append(s.expires_ts);
        }
    }
    return (redeemed, held);
}


def offer_src(o: Offer, place: PlaceSrc | None, reservations: list[Reservation]) -> OfferSrc {
    (redeemed, held) = _stock(reservations);
    named = categories_for(o.title, o.menu_item);
    return OfferSrc(
        id=jid(o),
        place_slug=place.slug if place is not None else "",
        title=o.title,
        description=o.description,
        image_url=o.image_url,
        price_cents=o.price_cents,
        regular_price_cents=o.regular_price_cents,
        start_ts=o.start_ts,
        end_ts=o.end_ts,
        quantity=o.quantity,
        status=o.status,
        qr_ready=o.qr_ready,
        eligibility=o.eligibility,
        terms=o.terms,
        dietary=list(o.dietary),
        menu_item=o.menu_item,
        is_demo=o.is_demo,
        redeemed=redeemed,
        held=held,
        categories=named if named or place is None else place.categories
    );
}


def place_src(r: Restaurant, loc: Location | None, menu: list[MenuItem]) -> PlaceSrc {
    return PlaceSrc(
        id=jid(r),
        slug=r.slug,
        name=r.name,
        source=r.source,
        is_demo=r.is_demo,
        image_url=r.image_url,
        cuisine=r.cuisine,
        has_location=loc is not None,
        loc_id=jid(loc) if loc is not None else "",
        address=loc.address if loc is not None else "",
        neighborhood=loc.neighborhood if loc is not None else "",
        entrance_note=loc.entrance_note if loc is not None else "",
        note_date=loc.note_date if loc is not None else "",
        labels=place_labels([m.dietary for m in menu]),
        categories=categories_for(r.cuisine, " ".join([m.name for m in menu])),
        offers=[]
    );
}


def claim_src(c: Redemption, offer_id: str) -> ClaimSrc {
    return ClaimSrc(id=jid(c), offer_id=offer_id, status=c.status,
        claimed_ts=c.claimed_ts, expires_ts=c.expires_ts, redeemed_ts=c.redeemed_ts,
        offer_title_snapshot=c.offer_title_snapshot,
        price_cents_snapshot=c.price_cents_snapshot,
        terms_snapshot=c.terms_snapshot,
        eligibility_snapshot=c.eligibility_snapshot,
        qr_payload=c.qr_payload);
}


# ---------------------------------------------------------------- build ---

"""Hex id of an edge endpoint, matching jid() of the node."""
def _endpoint(anchor: any) -> str {
    return str(anchor.id).replace("-", "");
}


"""(source jid, target jid) per edge, in edge-creation order."""
def _pairs(edges: list[any]) -> list[tuple[str, str]] {
    out: list[tuple[str, str]] = [];
    for e in edges {
        a: any = e.__jac__;
        out.append((_endpoint(a.source), _endpoint(a.target)));
    }
    return out;
}


def _group(pairs: list[tuple[str, str]], targets: dict[str, any]) -> dict[str, list[any]] {
    grouped: dict[str, list[any]] = {};
    for (src, tgt) in pairs {
        found = targets.get(tgt);
        if found is not None {
            grouped.setdefault(src, []).append(found);
        }
    }
    return grouped;
}


"""Batched build: one query per relationship instead of one per place."""
def _build_batched(generation: int, now: float) -> CatalogSnapshot {
    restaurants = [root.shared -->[?:Restaurant]];
    offers = {jid(o): o for o in [restaurants ->:Publishes:->]};
    offers_by_place = _group(_pairs([edge restaurants ->:Publishes:->]), offers);
    locations = {jid(l): l for l in [restaurants ->:HasLocation:->]};
    locs_by_place = _group(_pairs([edge restaurants ->:HasLocation:->]), locations);
    menu = {jid(m): m for m in [restaurants ->:Serves:->]};
    menu_by_place = _group(_pairs([edge restaurants ->:Serves:->]), menu);
    offer_nodes = list(offers.values());
    slots = {jid(s): s for s in [offer_nodes ->:Reserves:->]};
    slots_by_offer = _group(_pairs([edge offer_nodes ->:Reserves:->]), slots);
    notices = [root.shared -->[?:ContextNotice]];
    affected = _group(_pairs([edge notices ->:Affects:->]), {jid(l): l for l in [notices ->:Affects:->]});
    snap = CatalogSnapshot(generation=generation, built_at=now);
    for r in restaurants {
        rid = jid(r);
        locs = locs_by_place.get(rid, []);
        p = place_src(r, locs[0] if locs else None, menu_by_place.get(rid, []));
        for o in offers_by_place.get(rid, []) {
            s = offer_src(o, p, slots_by_offer.get(jid(o), []));
            p.offers.append(s);
            snap.offers[s.id] = s;
            snap.place_of[s.id] = p;
        }
        snap.places.append(p);
        snap.by_slug.setdefault(p.slug, p);
    }
    for n in notices {
        snap.notices.append(notice_src(n, [jid(l) for l in affected.get(jid(n), [])]));
    }
    _index_notices(snap);
    return snap;
}


"""Per-place fallback with only public traversal syntax."""
def _build_walk(generation: int, now: float) -> CatalogSnapshot {
    snap = CatalogSnapshot(generation=generation, built_at=now);
    for r in [root.shared -->[?:Restaurant]] {
        locs = [r ->:HasLocation:->];
        p = place_src(r, locs[0] if locs else None, [r ->:Serves:->]);
        for o in [r ->:Publishes:->] {
            s = offer_src(o, p, [o ->:Reserves:->]);
            p.offers.append(s);
            snap.offers[s.id] = s;
            snap.place_of[s.id] = p;
        }
        snap.places.append(p);
        snap.by_slug.setdefault(p.slug, p);
    }
    for n in [root.shared -->[?:ContextNotice]] {
        snap.notices.append(notice_src(n, [jid(l) for l in [n ->:Affects:->]]));
    }
    _index_notices(snap);
    return snap;
}


"""Notices that affect exactly one location, keyed by that location (the only
notices access_context_from ever counts)."""
def _index_notices(snap: CatalogSnapshot) {
    for n in snap.notices {
        if len(n.location_ids) == 1 {
            snap.notices_at.setdefault(n.location_ids[0], []).append(n);
        }
    }
}


glob _batched_ok: dict[str, bool] = {"ok": True};


def _build(generation: int, now: float) -> CatalogSnapshot {
    if _batched_ok["ok"] {
        try {
            return _build_batched(generation, now);
        } except (AttributeError, TypeError) {
            # Edge endpoint internals differ from the pinned runtime; stay correct.
            _batched_ok["ok"] = False;
        }
    }
    return _build_walk(generation, now);
}


def _refresh_stock(snap: CatalogSnapshot, offer_ids: list[str]) {
    for offer_id in offer_ids {
        s = snap.offers.get(offer_id);
        if s is None { continue; }
        o = jobj(offer_id);
        if not isinstance(o, Offer) { continue; }
        (redeemed, held) = _stock([o ->:Reserves:->]);
        s.redeemed = redeemed;
        s.held = held;
    }
}


def _reuse_enabled -> bool {
    return os.environ.get("MLOCAL_CATALOG_CACHE", "").strip().lower() not in ["off", "0", "false", "no"];
}


"""The current snapshot, rebuilt when the catalog changed or it is too old."""
def catalog_snapshot -> CatalogSnapshot {
    now = time.time();
    if not _reuse_enabled() {
        return _build(int(cache_state["generation"]), now);
    }
    with cache_lock {
        snap: CatalogSnapshot | None = cache_state["snapshot"];
        generation = int(cache_state["generation"]);
        if snap is None or snap.generation != generation or now - snap.built_at > CATALOG_MAX_AGE_SECONDS {
            dirty: set[str] = cache_state["dirty"];
            dirty.clear();
            snap = _build(generation, now);
            cache_state["snapshot"] = snap;
            return snap;
        }
        dirty: set[str] = cache_state["dirty"];
        if dirty {
            pending = list(dirty);
            dirty.clear();
            _refresh_stock(snap, pending);
        }
        return snap;
    }
}


"""Remaining units from the public projection. Legacy offers stay at zero."""
def remaining_from(s: OfferSrc, now: float) -> int {
    if not s.qr_ready { return 0; }
    held = len([t for t in s.held if now < t]);
    return max(s.quantity - s.redeemed - held, 0);
}


# ---------------------------------------------------------- own claims ---

"""The caller's own claims by offer. `actor` must be the authenticated caller:
Redemption access rules hide other accounts' claims, and the index is only ever
returned to the account it was read for."""
def actor_claims(actor: str) -> dict[str, list[ClaimSrc]] {
    if not actor { return {}; }
    now = time.time();
    reuse = _reuse_enabled();
    with cache_lock {
        cached = actor_cache.get(actor) if reuse else None;
        if cached is not None and now - cached[0] <= ACTOR_CLAIMS_MAX_AGE_SECONDS {
            return cached[1];
        }
    }
    wanted = actor;
    index: dict[str, list[ClaimSrc]] = {};
    for c in [root.shared -->[?:Restaurant] ->:Publishes:-> ->:ClaimedAs:->[?:Redemption, actor_id == wanted]] {
        if c.actor_id != actor { continue; }
        owners = [c <-:ClaimedAs:<-];
        if not owners { continue; }
        offer_id = jid(owners[0]);
        index.setdefault(offer_id, []).append(claim_src(c, offer_id));
    }
    if reuse {
        with cache_lock {
            if len(actor_cache) >= ACTOR_CLAIMS_MAX_ENTRIES { actor_cache.clear(); }
            actor_cache[actor] = (now, index);
        }
    }
    return index;
}


def claim_status_of(c: ClaimSrc, now: float) -> str {
    return "expired" if c.status == "claimed" and now >= c.expires_ts else c.status;
}


"""Same choice as promo._my_claim: QR claims only, a live or redeemed claim
first, then newest."""
def best_claim(claims: list[ClaimSrc], now: float) -> ClaimSrc | None {
    usable = [c for c in claims if c.qr_payload];
    if not usable { return None; }
    ranked = sorted(usable, key=lambda (c: ClaimSrc) -> tuple[int, float, str] {
        return (1 if claim_status_of(c, now) in ["claimed", "redeemed"] else 0, c.claimed_ts, c.id);
    }, reverse=True);
    return ranked[0];
}
