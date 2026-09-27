"""Signed-in catalog readers see a business's public profile and published offers.

This projection never returns merchant authority or any account's claim fields.
Offer detail remains the existing caller-scoped get_offer endpoint.
"""

import os;
import time;
import from services.models { Restaurant, Publishes }
import from services.promo { OfferView, _find_offer, _restaurant_of, _location_of, _view }
import from services.qr_catalog { _ensure_seed }
import from services.session { _actor_id, _merchant_for_actor }
import from services.foryou { DEMO_MODE_ENV, demo_mode }

obj BusinessProfileView {
    has ok: bool = False,
        message: str = "",
        slug: str = "",
        name: str = "",
        cuisine: str = "",
        blurb: str = "",
        address: str = "",
        neighborhood: str = "",
        entrance_note: str = "",
        note_date: str = "",
        is_demo: bool = False,
        offers: list[OfferView] = [];
}


def _public_business(slug: str, offer_id: str, now: float) -> BusinessProfileView {
    target = slug.strip();
    show_samples = demo_mode(os.environ.get(DEMO_MODE_ENV, "")) or os.environ.get("MLOCAL_HOSTED_DATASET", "") == "1";
    r: Restaurant | None = None;
    if target {
        matches = [item for item in [root.shared -->[?:Restaurant]] if item.slug == target and not item.archived];
        r = matches[0] if matches else None;
    } elif offer_id.strip() {
        o = _find_offer(offer_id.strip());
        r = _restaurant_of(o) if o is not None and (show_samples or not o.is_demo) else None;
    }
    if r is None or (r.is_demo and not show_samples) {
        return BusinessProfileView(message="This business could not be found.");
    }
    loc = _location_of(r);
    # Publication is explicit: malformed or future draft statuses fail closed.
    # Scheduled and sold-out published offers keep their existing view states.
    offers = [_view(o, now) for o in [r ->:Publishes:->]
        if o.status == "active" and now < o.end_ts and not o.archived and (show_samples or not o.is_demo)];
    return BusinessProfileView(
        ok=True,
        slug=r.slug,
        name=r.name,
        cuisine=r.cuisine,
        blurb=r.blurb,
        address=loc.address if loc else "",
        neighborhood=loc.neighborhood if loc else "",
        entrance_note=loc.entrance_note if loc else "",
        note_date=loc.note_date if loc else "",
        is_demo=r.is_demo,
        offers=offers
    );
}


def:protect get_business_profile(slug: str = "", offer_id: str = "") -> BusinessProfileView {
    actor = _actor_id();
    if not actor {
        return BusinessProfileView(message="Sign in to view this business.");
    }
    _ensure_seed();
    target = slug.strip();
    if not target and not offer_id.strip() {
        # SessionView.restaurant_id is a graph id, not the catalog slug.
        # An owner's preview must also work before they publish any offers.
        owned = _merchant_for_actor(actor);
        target = owned.slug if owned is not None else "";
    }
    return _public_business(target, offer_id, time.time());
}
