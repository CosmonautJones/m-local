"""Authenticated offer/QR API.

Every mutating endpoint runs inside _locked_mutation: it takes an exclusive OS
file lock, refreshes its transaction so it sees the previous holder's commit,
does the work, and commits before releasing. Measured on Jac 0.37.23 with the
default worker count: without this, 20 simultaneous claims on a one-unit offer
produced several winners; with it, exactly one. The lock serializes threads and
worker processes on one machine only; several machines would need a shared lock.
"""

import os;
import from services.photo_reference { image_reference }
import fcntl;
import re;
import sys;

import time;
import secrets;
import hashlib;
import json;
import from services.qr_auth { listing_visible }
import from datetime { datetime, timedelta }
import from zoneinfo { ZoneInfo }
import from services.models {
    Restaurant,
    Location,
    MenuItem,
    Offer,
    Redemption,
    HasLocation,
    Serves,
    Publishes,
    Features,
    ClaimedAs,
    public_name,
    samples_visible,
    Reservation,
    Reserves,
    UsesReservation,
    CLAIM_HOLD_MINUTES,
    DIET_TAGS
}
import from services.qr_catalog { _ensure_seed }
import from services.qr { new_qr_payload, valid_qr_payload }
import from services.money { money_to_cents }
import from services.session { _actor_id, _merchant_for_actor }
import from services.onboarding { student_can_claim }
import from services.email_codes { store, mutation_lock_path }
import from services.context_models { AccessContextView }
import from services.context { get_access_context }

glob MAX_ACTIVE_HOLDS: int = 2;


def _lock -> int {
    fd = os.open(mutation_lock_path(), os.O_CREAT | os.O_RDWR, 384);
    try {
        fcntl.flock(fd, fcntl.LOCK_EX);
        commit();
    } except BaseException {
        try {
            fcntl.flock(fd, fcntl.LOCK_UN);
        } finally {
            os.close(fd);
        }
        raise;
    }
    return fd;
}


def _unlock(fd: int) -> None {
    try {
        # The runtime aborts and replays cold read-tier writes and conflicts.
        # Never persist the abandoned attempt while its exception unwinds.
        if sys.exc_info()[0] is None { commit(); }
    } finally {
        fcntl.flock(fd, fcntl.LOCK_UN);
        os.close(fd);
    }
}


obj OfferView {
    has id: str = "",
        title: str = "",
        description: str = "",
        restaurant: str = "",
        cuisine: str = "",
        location_id: str = "",
        address: str = "",
        neighborhood: str = "",
        entrance_note: str = "",
        note_date: str = "",
        price: float = 0.0,
        regular_price: float = 0.0,
        start_input: str = "",
        end_input: str = "",
        time_label: str = "",
        state: str = "",
        remaining: int = 0,
        quantity: int = 0,
        eligibility: str = "",
        terms: str = "",
        dietary: list[str] = [],
        menu_item: str = "",
        is_demo: bool = False,
        image_url: str = "",
        offer_image_url: str = "",
        fits: bool = True,
        reasons: list[str] = [],
        my_qr_payload: str = "",
        my_claim_id: str = "",
        my_title: str = "",
        my_price_cents: int = 0,
        my_terms: str = "",
        my_eligibility: str = "",
        my_expires_ts: float = 0.0,
        my_status: str = "",
        my_expires: str = "",
        access_context: AccessContextView = AccessContextView();
}

# Merchant history contains no actor identifier or redemption credential.
obj ClaimView {
    has claim_id: str = "",
        title_snapshot: str = "",
        price_cents: int = 0,
        terms: str = "",
        eligibility: str = "",
        status: str = "",
        claimed_label: str = "",
        expires_label: str = "";
}

obj ClaimPreview {
    has ok: bool = False,
        message: str = "",
        claim_id: str = "",
        title_snapshot: str = "",
        price_cents: int = 0,
        terms: str = "",
        eligibility: str = "",
        expires_ts: float = 0.0,
        expires_label: str = "",
        status: str = "",
        restaurant: str = "";
}

obj ActionResult {
    has ok: bool = False,
        message: str = "",
        claim_id: str = "",
        qr_payload: str = "",
        code: str = "";  # save_offer's existing offer-ID result only.
}

obj MerchantView {
    has ok: bool = False,
        message: str = "",
        name: str = "",
        cuisine: str = "",
        blurb: str = "",
        address: str = "",
        neighborhood: str = "",
        entrance_note: str = "",
        note_date: str = "",
        is_demo: bool = False,
        image_url: str = "",
        offers: list[OfferView] = [],
        claims: list[ClaimView] = [];
}


# ---------------------------------------------------------------- helpers ---

def _tz -> any {
    try {
        return ZoneInfo("America/Detroit");
    } except Exception {
        return None;
    }
}


def _local(ts: float) -> datetime {
    return datetime.fromtimestamp(ts, _tz());
}


def _clock(ts: float) -> str {
    return _local(ts).strftime("%-I:%M %p");
}


def _day_clock(ts: float) -> str {
    return _local(ts).strftime("%a %-I:%M %p");
}


def _input_fmt(ts: float) -> str {
    return _local(ts).strftime("%Y-%m-%d %H:%M");
}


def _parse_local(text: str) -> float | None {
    try {
        local_text = text.strip().replace("T", " ");
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}", local_text) is None {
            return None;
        }
        dt = datetime.strptime(local_text, "%Y-%m-%d %H:%M");
        zone = _tz();
        if zone is None { return None; }
        aware = dt.replace(tzinfo=zone);
        ts = aware.timestamp();
        # Reject the spring-forward gap and repeated fall-back hour. A local
        # editor cannot disambiguate those times, so never guess the deadline.
        if _local(ts).replace(tzinfo=None) != dt or aware.utcoffset() != dt.replace(tzinfo=zone, fold=1).utcoffset() {
            return None;
        }
        return ts;
    } except Exception {
        return None;
    }
}


def _span(seconds: float) -> str {
    mins = int(max(seconds, 0) // 60);
    if mins >= 60 {
        return f"{mins // 60}h {mins % 60}m";
    }
    return f"{mins}m";
}


def _money(v: float) -> str {
    return f"${v:.2f}";
}




def _restaurant_of(o: Offer) -> Restaurant | None {
    owners = [o <-:Publishes:<-];
    return owners[0] if owners else None;
}



def _sample_offer(o: Offer) -> bool {
    restaurant = _restaurant_of(o);
    return o.is_demo or (restaurant is not None and restaurant.is_demo);
}


def _location_of(r: Restaurant) -> Location | None {
    locs = [r ->:HasLocation:->];
    return locs[0] if locs else None;
}


def _find_offer(offer_id: str) -> Offer | None {
    for r in [root.shared -->[?:Restaurant]] {
        for o in [r ->:Publishes:->] {
            if jid(o) == offer_id {
                return o;
            }
        }
    }
    return None;
}


def _merchant() -> Restaurant | None {
    return _merchant_for_actor(_actor_id());
}


def _owned_offer(r: Restaurant, offer_id: str) -> Offer | None {
    for o in [r ->:Publishes:->] {
        if jid(o) == offer_id {
            return o;
        }
    }
    return None;
}


def _claim_status(c: Redemption, now: float) -> str {
    return "expired" if c.status == "claimed" and now >= c.expires_ts else c.status;
}

# Reads never expire/mutate claims. Counting the public reservation projection
# lets all roots see identical remaining stock without exposing private claims.
def _used_quantity(o: Offer, now: float) -> int {
    return len([s for s in [o ->:Reserves:->]
        if s.status == "redeemed" or (s.status == "claimed" and now < s.expires_ts)]);
}


def _remaining(o: Offer, now: float) -> int {
    # Existing pre-QR claims cannot be attributed to authenticated principals.
    # Fail closed instead of reclaiming historical consumed/held stock. The
    # operator must reconcile that legacy offer before enabling it for new QR
    # claims; editing or pausing it never silently discards old redemptions.
    if not o.qr_ready { return 0; }
    return max(o.quantity - _used_quantity(o, now), 0);
}


def _set_claim_status(c: Redemption, status: str, now: float) {
    c.status = status;
    if status == "redeemed" { c.redeemed_ts = now; }
    elif status == "cancelled" { c.cancelled_ts = now; }
    for s in [c ->:UsesReservation:->] { s.status = status; }
}


def _state(o: Offer, now: float, remaining: int | None = None) -> str {
    if now >= o.end_ts {
        return "expired";
    }
    if o.status == "paused" {
        return "paused";
    }
    if now < o.start_ts {
        return "scheduled";
    }
    if (remaining if remaining is not None else _remaining(o, now)) <= 0 {
        return "sold out";
    }
    return "active";
}


def _parse_diets(diets: str) -> list[str] {
    tags: list[str] = [];
    for raw in diets.split(",") {
        tag = raw.strip().lower();
        if tag and tag not in tags { tags.append(tag); }
    }
    return tags;
}


def _text_error(value: str, label: str, limit: int, required: bool = False) -> str {
    clean = value.strip();
    if required and not clean { return label + " is required"; }
    if len(clean) > limit { return f"{label} must be {limit} characters or fewer"; }
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", clean) is not None {
        return label + " contains unsupported control characters";
    }
    return "";
}


def _parse_budget(max_price: str) -> float | None {
    try {
        return float(max_price.strip().lstrip("$")) if max_price.strip() else None;
    } except Exception {
        return None;
    }
}


def _end_of_today(now: float) -> float {
    d = _local(now);
    nxt = (d + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0);
    return nxt.timestamp();
}


"""Plain-language reasons + whether the offer fits all active filters."""
def _explain(
    o: Offer,
    state: str,
    remaining: int,
    budget: float | None,
    window: str,
    wanted: list[str],
    now: float
) -> tuple[bool, list[str]] {
    # Short match tags only for the student's own filters; price, time and
    # stock are already shown on screen, so they are not repeated here.
    reasons: list[str] = [];
    fits = True;
    if budget is not None {
        if o.price_cents / 100 <= budget {
            reasons.append(f"Under your {_money(budget)} budget");
        } else {
            fits = False;
            reasons.append(f"Over your {_money(budget)} budget");
        }
    }
    if window == "now" and state == "active" {
        reasons.append("Open right now");
    } elif window == "today" and state in ["active", "scheduled"] {
        reasons.append("Available today");
    }
    if state == "scheduled" and window == "now" {
        fits = False;
    }
    if state in ["sold out", "paused", "expired"] {
        fits = False;
    }
    for w in wanted {
        if w in o.dietary {
            reasons.append(w.capitalize());
        } else {
            fits = False;
            reasons.append(f"Not marked {w}");
        }
    }
    _ = (remaining, now);
    return (fits, reasons);
}


def _view(
    o: Offer,
    now: float,
    actor_id: str = "",
    budget: float | None = None,
    window: str = "any",
    wanted: list[str] = [],
    saved_claim: Redemption | None = None,
    place_context: tuple[Restaurant, Location | None, AccessContextView] | None = None
) -> OfferView {
    r: Restaurant | None = None;
    loc: Location | None = None;
    if place_context is None {
        r = _restaurant_of(o);
        loc = _location_of(r) if r else None;
        context = get_access_context(jid(loc), now) if loc else AccessContextView();
    } else {
        (r, loc, context) = place_context;
    }
    remaining = _remaining(o, now);
    state = _state(o, now, remaining);
    (fits, reasons) = _explain(o, state, remaining, budget, window, wanted, now);
    if state == "active" {
        tlabel = f"Until {_clock(o.end_ts)} · {_span(o.end_ts - now)} left";
    } elif state == "scheduled" {
        tlabel = f"Starts {_day_clock(o.start_ts)}";
    } elif state == "expired" {
        tlabel = f"Ended {_day_clock(o.end_ts)}";
    } else {
        tlabel = f"{_day_clock(o.start_ts)} - {_clock(o.end_ts)}";
    }
    v = OfferView(
        id=jid(o),
        title=o.title,
        description=o.description,
        restaurant=public_name(r.name) if r else "",
        image_url=r.image_url if r else "",
        offer_image_url=o.image_url,
        cuisine=r.cuisine if r else "",
        location_id=jid(loc) if loc else "",
        address=loc.address if loc else "",
        neighborhood=loc.neighborhood if loc else "",
        entrance_note=loc.entrance_note if loc else "",
        note_date=loc.note_date if loc else "",
        price=o.price_cents / 100,
        regular_price=o.regular_price_cents / 100,
        start_input=_input_fmt(o.start_ts),
        end_input=_input_fmt(o.end_ts),
        time_label=tlabel,
        state=state,
        remaining=remaining,
        quantity=o.quantity,
        eligibility=o.eligibility,
        terms=o.terms,
        dietary=o.dietary,
        menu_item=o.menu_item,
        is_demo=o.is_demo or (r is not None and r.is_demo),
        access_context=context,
        fits=fits,
        reasons=reasons
    );
    c = saved_claim if saved_claim is not None else _my_claim(o, actor_id, now);
    if c is not None {
        v.my_claim_id = jid(c);
        v.my_status = _claim_status(c, now);
        v.my_expires = _clock(c.expires_ts);
        v.my_expires_ts = c.expires_ts;
        v.my_title = c.offer_title_snapshot;
        v.my_price_cents = c.price_cents_snapshot;
        v.my_terms = c.terms_snapshot;
        v.my_eligibility = c.eligibility_snapshot;
        v.my_qr_payload = c.qr_payload if v.my_status == "claimed" else "";
    }
    return v;
}


def _my_claim(o: Offer, actor_id: str, now: float) -> Redemption | None {
    if not actor_id { return None; }
    wanted_actor = actor_id;
    mine = [c for c in [o ->:ClaimedAs:->[?:Redemption, actor_id == wanted_actor]] if c.actor_id == actor_id and c.qr_payload];
    mine.sort(key=lambda (c: Redemption) -> tuple[int, float, str] {
        return (1 if _claim_status(c, now) in ["claimed", "redeemed"] else 0, c.claimed_ts, jid(c));
    }, reverse=True);
    return mine[0] if mine else None;
}


def _active_hold_count(actor_id: str, now: float) -> int {
    wanted_actor = actor_id;
    count = 0;
    for restaurant in [root.shared -->[?:Restaurant]] {
        for offer in [restaurant ->:Publishes:->] {
            count += len([claim for claim in [offer ->:ClaimedAs:->[?:Redemption, actor_id == wanted_actor]]
                if claim.actor_id == actor_id and claim.qr_payload and _claim_status(claim, now) == "claimed"]);
        }
    }
    return count;
}


def _claim(offer_id: str, actor_id: str, now: float) -> ActionResult {
    if not actor_id {
        return ActionResult(message="Sign in to claim this offer.");
    }
    o = _find_offer(offer_id);
    if o is None { return ActionResult(message="That offer no longer exists."); }
    if _sample_offer(o) and not samples_visible() {
        return ActionResult(message="That offer is not available.");
    }
    for c in [o ->:ClaimedAs:->] {
        if c.actor_id != actor_id or not c.qr_payload { continue; }
        state = _claim_status(c, now);
        if state == "redeemed" {
            return ActionResult(message="You already redeemed this offer.", claim_id=jid(c));
        }
        if state == "claimed" {
            return ActionResult(ok=True, message="Your existing claim is ready to show.",
                claim_id=jid(c), qr_payload=c.qr_payload);
        }
    }
    state = _state(o, now);
    if state != "active" {
        msgs = {
            "paused": "This offer is paused by the restaurant.",
            "expired": "This offer has expired.",
            "scheduled": "This offer has not started yet.",
            "sold out": "This offer is sold out right now."
        };
        return ActionResult(message=msgs[state]);
    }
    r = _restaurant_of(o);
    if r is None { return ActionResult(message="This offer has no restaurant."); }
    if not listing_visible(r.slug, r.source) {
        return ActionResult(message="This business is not available for new claims.");
    }
    # The public caller holds the mutation lock through this count and commit.
    # Existing live claims returned above remain idempotent, including accounts
    # that already held more than the new limit before rollout.
    if _active_hold_count(actor_id, now) >= MAX_ACTIVE_HOLDS {
        return ActionResult(message=f"The limit is {MAX_ACTIVE_HOLDS} active holds. Cancel one or wait for it to expire before claiming another offer.");
    }
    o.qr_ready = True;
    expires = min(now + CLAIM_HOLD_MINUTES * 60, o.end_ts);
    c = Redemption(actor_id=actor_id, restaurant_slug=r.slug,
        qr_payload=new_qr_payload(), status="claimed", claimed_ts=now, expires_ts=expires,
        offer_title_snapshot=o.title, price_cents_snapshot=o.price_cents,
        regular_price_cents_snapshot=o.regular_price_cents,
        terms_snapshot=o.terms, eligibility_snapshot=o.eligibility);
    o +>:ClaimedAs():+> c;
    slot = Reservation(status="claimed", expires_ts=expires);
    o +>:Reserves():+> slot;
    c +>:UsesReservation():+> slot;
    return ActionResult(ok=True, message=f"Claimed. Show your QR before {_clock(expires)}.",
        claim_id=jid(c), qr_payload=c.qr_payload);
}


def _cancel(offer_id: str, actor_id: str, now: float) -> ActionResult {
    if not actor_id { return ActionResult(message="Sign in to manage your claim."); }
    o = _find_offer(offer_id);
    if o is None { return ActionResult(message="That offer no longer exists."); }
    for c in [o ->:ClaimedAs:->] {
        if c.actor_id == actor_id and c.status == "redeemed" {
            return ActionResult(message="A redeemed claim cannot be cancelled.");
        }
    }
    for c in [o ->:ClaimedAs:->] {
        if c.actor_id == actor_id and _claim_status(c, now) == "claimed" {
            _set_claim_status(c, "cancelled", now);
            return ActionResult(ok=True, message="Claim cancelled. Your unit was released.", claim_id=jid(c));
        }
    }
    return ActionResult(ok=True, message="You have no active claim to cancel.");
}


def _find_claim(r: Restaurant, qr_payload: str) -> Redemption | None {
    if not valid_qr_payload(qr_payload) { return None; }
    for o in [r ->:Publishes:->] {
        for c in [o ->:ClaimedAs:->] {
            if c.qr_payload and secrets.compare_digest(c.qr_payload, qr_payload) {
                return c;
            }
        }
    }
    return None;
}


def _preview(r: Restaurant, qr_payload: str, now: float) -> ClaimPreview {
    if not valid_qr_payload(qr_payload) {
        return ClaimPreview(message="This is not a valid M-Local QR.");
    }
    c = _find_claim(r, qr_payload);
    if c is None { return ClaimPreview(message="No claim found for your restaurant."); }
    state = _claim_status(c, now);
    messages = {"claimed": "Check eligibility and confirm redemption.",
        "redeemed": "This claim was already redeemed.",
        "cancelled": "This claim was cancelled.", "expired": "This claim has expired."};
    return ClaimPreview(ok=state == "claimed", message=messages.get(state, "This claim is unavailable."),
        claim_id=jid(c), title_snapshot=c.offer_title_snapshot, price_cents=c.price_cents_snapshot,
        terms=c.terms_snapshot, eligibility=c.eligibility_snapshot,
        expires_ts=c.expires_ts, expires_label=_clock(c.expires_ts), status=state, restaurant=r.name);
}


def _redeem(r: Restaurant, qr_payload: str, now: float) -> ActionResult {
    preview = _preview(r, qr_payload, now);
    if not preview.ok {
        return ActionResult(message=preview.message, claim_id=preview.claim_id);
    }
    # Re-resolve and revalidate inside the mutation's own transaction. Preview
    # is not authorization: time or state can change before merchant confirms.
    c = _find_claim(r, qr_payload);
    if c is None or _claim_status(c, now) != "claimed" {
        return ActionResult(message="This claim is no longer available.");
    }
    _set_claim_status(c, "redeemed", now);
    return ActionResult(ok=True, claim_id=jid(c),
        message=f"Redeemed: {c.offer_title_snapshot}. Charge {_money(c.price_cents_snapshot / 100)}.");
}


def _save_offer(
    r: Restaurant,
    offer_id: str,
    title: str,
    description: str,
    price: str,
    regular_price: str,
    start_local: str,
    end_local: str,
    quantity: str,
    eligibility: str,
    terms: str,
    dietary: str,
    menu_item: str,
    now: float,
    create_key: str = "",
    image_url: str | None = None
) -> ActionResult {
    if not offer_id and create_key and re.fullmatch(r"[A-Za-z0-9_-]{20,80}", create_key) is None {
        return ActionResult(message="Refresh the app and try publishing again.");
    }
    errors: list[str] = [];
    photo = "";
    try { if image_url is not None { photo = image_reference(image_url.strip(), _actor_id()); } }
    except ValueError as photo_error { errors.append(str(photo_error)); }
    p = -1;
    rp = -1;
    try {
        if len(price.strip()) <= 12 { p = money_to_cents(price); }
    } except ValueError {}
    try {
        if len(regular_price.strip()) <= 12 { rp = money_to_cents(regular_price) if regular_price.strip() else 0; }
    } except ValueError {}
    st = _parse_local(start_local);
    en = _parse_local(end_local);
    qty = -1;
    if re.fullmatch(r"[0-9]{1,5}", quantity.strip()) is not None {
        qty = int(quantity.strip());
    }
    for (value, label, limit, required) in [
        (title, "title", 120, True), (description, "description", 2000, False),
        (eligibility, "eligibility", 300, True), (terms, "terms", 2000, True),
        (dietary, "dietary tags", 200, False), (menu_item, "menu item", 120, False)
    ] {
        error = _text_error(value, label, limit, required);
        if error { errors.append(error); }
    }
    if p < 0 or p > 999999 {
        errors.append("price must be between 0 and 9999.99 with at most two decimal places");
    }
    if rp < 0 or rp > 999999 {
        errors.append("regular price must be between 0 and 9999.99 with at most two decimal places");
    } elif regular_price.strip() and p >= 0 and rp < p {
        errors.append("regular price cannot be less than the offer price; leave it blank if unavailable");
    }
    if st is None or en is None {
        errors.append("use valid Ann Arbor times like 2026-09-26 14:00; avoid the repeated or skipped daylight-saving hour");
    } elif en <= st {
        errors.append("end must be after start");
    } elif en <= now {
        errors.append("end must be in the future");
    }
    if qty < 1 or qty > 10000 {
        errors.append("quantity must be a whole number from 1 to 10000");
    }
    tags = _parse_diets(dietary);
    if [tag for tag in tags if tag not in DIET_TAGS] {
        errors.append("dietary tags must be vegetarian, vegan, gluten-free, or halal");
    }
    digest = "";
    if not offer_id and create_key {
        digest = hashlib.sha256(json.dumps([title.strip(), description.strip(), p, rp, st, en, qty,
            eligibility.strip(), terms.strip(), sorted(tags), menu_item.strip(), photo]).encode()).hexdigest();
        for existing in [r ->:Publishes:->] {
            if existing.create_key != create_key { continue; }
            if existing.create_digest != digest {
                return ActionResult(message="This offer was already published with different details. Cancel this form and open it from Offers to edit.");
            }
            return ActionResult(ok=True, message="Offer already published.", code=jid(existing));
        }
    }
    o: Offer | None = None;
    if offer_id {
        o = _owned_offer(r, offer_id);
        if o is None {
            return ActionResult(ok=False, message="That offer does not belong to your restaurant.");
        }
        held = _used_quantity(o, now) if o.qr_ready else o.quantity;
        if qty >= 1 and qty < held {
            errors.append(f"quantity cannot go below {held} already claimed or redeemed");
        }
    }
    if errors {
        return ActionResult(ok=False, message="Fix: " + "; ".join(errors) + ".");
    }
    if o is None {
        o = Offer(title=title.strip(), created_ts=now, is_demo=r.is_demo, qr_ready=True,
            create_key=create_key, create_digest=digest);
        r +>:Publishes():+> o;
    }
    o.title = title.strip();
    o.description = description.strip();
    o.price_cents = p;
    o.regular_price_cents = rp;
    o.price = p / 100;
    o.regular_price = rp / 100;
    o.start_ts = st or now;
    o.end_ts = en or now;
    o.quantity = qty;
    o.eligibility = eligibility.strip();
    o.terms = terms.strip();
    o.dietary = tags;
    o.menu_item = menu_item.strip();
    if image_url is not None { o.image_url = photo; }
    for e in [edge o ->:Features:->] {
        del e;
    }
    if o.menu_item {
        items = [m for m in [r ->:Serves:->] if m.name == o.menu_item];
        item = items[0] if items else None;
        if item is None {
            item = MenuItem(name=o.menu_item, price=o.regular_price, price_cents=rp, dietary=o.dietary);
            r +>:Serves():+> item;
        }
        o +>:Features():+> item;
    }
    return ActionResult(ok=True, message="Offer saved.", code=jid(o));
}


def _portal(r: Restaurant, now: float, message: str = "") -> MerchantView {
    loc = _location_of(r);
    offers = [o for o in [r ->:Publishes:->]];
    offers.sort(key=lambda (o: Offer) -> float { return o.start_ts; });
    claims: list[tuple[float, ClaimView]] = [];
    for o in offers {
        for c in [o ->:ClaimedAs:->] {
            claims.append((c.claimed_ts, ClaimView(
                claim_id=jid(c), title_snapshot=c.offer_title_snapshot,
                price_cents=c.price_cents_snapshot, terms=c.terms_snapshot,
                eligibility=c.eligibility_snapshot, status=_claim_status(c, now),
                claimed_label=_day_clock(c.claimed_ts),
                expires_label=_clock(c.expires_ts)
            )));
        }
    }
    claims.sort(key=lambda (t: tuple[float, ClaimView]) -> float { return t[0]; }, reverse=True);
    return MerchantView(
        ok=True,
        message=message,
        name=public_name(r.name),
        image_url=r.image_url,
        cuisine=r.cuisine,
        blurb=r.blurb,
        address=loc.address if loc else "",
        neighborhood=loc.neighborhood if loc else "",
        entrance_note=loc.entrance_note if loc else "",
        note_date=loc.note_date if loc else "",
        is_demo=r.is_demo,
        offers=[_view(o, now) for o in offers],
        claims=[t[1] for t in claims[:30]]
    );
}


# --------------------------------------------------------------- endpoints ---

"""Student discovery: filter by budget ($), time window (now|today|any) and
comma-separated dietary tags. Paused and ended offers are hidden."""
def:pub list_offers(
    max_price: str = "", window: str = "any", diets: str = ""
) -> list[OfferView] {
    _ensure_seed();
    now = time.time();
    budget = _parse_budget(max_price);
    wanted = _parse_diets(diets);
    eod = _end_of_today(now);
    out: list[OfferView] = [];
    for r in [root.shared -->[?:Restaurant]] {
        visible = listing_visible(r.slug, r.source);
        for o in [r ->:Publishes:->] {
            if _sample_offer(o) and not samples_visible() { continue; }
            v = _view(o, now, _actor_id(), budget, window, wanted);
            # A saved live QR remains reachable after reload even when the
            # merchant pauses/edits an offer or student changes discovery filters.
            if v.my_status == "claimed" {
                out.append(v);
                continue;
            }
            if not visible { continue; }
            if o.status == "paused" or now >= o.end_ts { continue; }
            if budget is not None and o.price_cents / 100 > budget { continue; }
            if window == "now" and o.start_ts > now { continue; }
            if window == "today" and o.start_ts >= eod { continue; }
            if wanted and [w for w in wanted if w not in o.dietary] { continue; }
            out.append(v);
        }
    }
    rank = {"active": 0, "scheduled": 1, "sold out": 2};
    out.sort(key=lambda (v: OfferView) -> int { return rank.get(v.state, 3); });
    return out;
}


def:pub get_offer(
    offer_id: str,
    max_price: str = "",
    window: str = "any",
    diets: str = ""
) -> OfferView | None {
    _ensure_seed();
    o = _find_offer(offer_id);
    if o is None or (_sample_offer(o) and not samples_visible()) {
        return None;
    }
    now = time.time();
    v = _view(o, now, _actor_id(), _parse_budget(max_price), window, _parse_diets(diets));
    r = _restaurant_of(o);
    # A live hold stays readable. A redeemed claim does not keep a paused or ended offer public.
    if v.my_status == "claimed" {
        return v;
    }
    if r is None or not listing_visible(r.slug, r.source) { return None; }
    if o.status == "paused" or now >= o.end_ts {
        return None;
    }
    return v;
}


def:protect claim_offer(offer_id: str) -> ActionResult {
    fd = _lock();
    try {
        _ensure_seed();
        if _merchant() is not None or not student_can_claim(_actor_id()) {
            result = ActionResult(message="Verify your U-M email or use a provisioned demo student account to claim offers.");
        } else {
            result = _claim(offer_id, _actor_id(), time.time());
        }
    } finally {
        _unlock(fd);
    }
    return result;
}


def:protect cancel_claim(offer_id: str) -> ActionResult {
    fd = _lock();
    try {
        result = _cancel(offer_id, _actor_id(), time.time());
    } finally {
        _unlock(fd);
    }
    return result;
}


def:protect merchant_portal() -> MerchantView {
    _ensure_seed();
    r = _merchant();
    if r is None { return MerchantView(message="This account does not own a restaurant."); }
    return _portal(r, time.time());
}


# Jac 0.37.23 stringifies omitted RPC defaults; a string sentinel keeps the current photo.
def:protect update_profile(
    name: str,
    cuisine: str,
    blurb: str,
    address: str,
    neighborhood: str,
    entrance_note: str,
    note_date: str,
    image_url: str | None = "__keep_photo__"
) -> MerchantView {
    fd = _lock();
    try {
        _ensure_seed();
        r = _merchant();
        if r is None {
            view = MerchantView(ok=False, message="This account does not own a restaurant.");
        } else {
            loc = _location_of(r);
            errors: list[str] = [];
            for (value, label, limit, required) in [
                (name, "name", 120, True), (cuisine, "cuisine", 80, False),
                (blurb, "description", 1000, False), (address, "address", 240, True),
                (neighborhood, "neighborhood", 120, False),
                (entrance_note, "entrance note", 500, False), (note_date, "note date", 80, False)
            ] {
                error = _text_error(value, label, limit, required);
                if error { errors.append(error); }
            }
            photo = r.image_url;
            try { if image_url is not None and image_url != "__keep_photo__" { photo = image_reference(image_url.strip(), _actor_id()); } }
            except ValueError as photo_error { errors.append(str(photo_error)); }
            if errors {
                view = _portal(r, time.time(), "Fix: " + "; ".join(errors) + ".");
                view.ok = False;
            } elif name.strip() not in [r.name, public_name(r.name)] or address.strip() != (loc.address if loc is not None else "") {
                view = _portal(r, time.time(), "Name or address changes need review. Open your business profile to submit them.");
                view.ok = False;
            } else {
                # Keep the intended edits before touching the graph. A private
                # store failure cannot leave a newer public/stale private pair.
                try { store().update_business_details(_actor_id(), cuisine.strip(), blurb.strip(), photo); }
                except ValueError as error {
                    view = _portal(r, time.time(), str(error));
                    view.ok = False;
                    return view;
                }
                r.cuisine = cuisine.strip();
                r.blurb = blurb.strip();
                r.image_url = photo;
                if loc is None {
                    loc = Location(address="");
                    r +>:HasLocation():+> loc;
                }
                loc.address = address.strip();
                loc.neighborhood = neighborhood.strip();
                loc.entrance_note = entrance_note.strip();
                loc.note_date = note_date.strip();
                view = _portal(r, time.time(), "Profile saved.");
            }
        }
    } finally {
        _unlock(fd);
    }
    return view;
}


def:protect save_offer(
    offer_id: str,
    title: str,
    description: str,
    price: str,
    regular_price: str,
    start_local: str,
    end_local: str,
    quantity: str,
    eligibility: str,
    terms: str,
    dietary: str,
    menu_item: str,
    create_key: str = "",
    image_url: str | None = "__keep_photo__"
) -> ActionResult {
    fd = _lock();
    try {
        _ensure_seed();
        r = _merchant();
        if r is None {
            result = ActionResult(ok=False, message="This account does not own a restaurant.");
        } elif not offer_id and not create_key {
            result = ActionResult(message="Refresh the app before publishing a new offer.");
        } else {
            result = _save_offer(
                r,
                offer_id,
                title,
                description,
                price,
                regular_price,
                start_local,
                end_local,
                quantity,
                eligibility,
                terms,
                dietary,
                menu_item,
                time.time(),
                create_key,
                None if image_url == "__keep_photo__" else image_url
            );
        }
    } finally {
        _unlock(fd);
    }
    return result;
}


def:protect set_offer_status(offer_id: str, status: str) -> ActionResult {
    fd = _lock();
    try {
        _ensure_seed();
        r = _merchant();
        o = _owned_offer(r, offer_id) if r is not None else None;
        if r is None {
            result = ActionResult(ok=False, message="This account does not own a restaurant.");
        } elif status not in ["active", "paused"] {
            result = ActionResult(ok=False, message="Status must be active or paused.");
        } elif o is None {
            result = ActionResult(ok=False, message="That offer does not belong to your restaurant.");
        } elif status == "active" and o.end_ts <= time.time() {
            result = ActionResult(ok=False, message="Update the offer end time before resuming an expired offer.");
        } else {
            o.status = status;
            result = ActionResult(ok=True, message="Offer resumed." if status == "active" else "Offer paused.");
        }
    } finally {
        _unlock(fd);
    }
    return result;
}


"""Read-only scan resolution. Confirmation is a separate authenticated request."""
def:protect resolve_claim(qr_payload: str) -> ClaimPreview {
    r = _merchant();
    if r is None { return ClaimPreview(message="This account does not own a restaurant."); }
    return _preview(r, qr_payload, time.time());
}


def:protect redeem_claim(qr_payload: str) -> ActionResult {
    fd = _lock();
    try {
        r = _merchant();
        if r is None {
            result = ActionResult(message="This account does not own a restaurant.");
        } else {
            result = _redeem(r, qr_payload, time.time());
        }
    } finally {
        _unlock(fd);
    }
    return result;
}


"""Default start/end strings for a new offer in the editor (now .. now+3h)."""
def:pub offer_defaults() -> list[str] {
    now = time.time();
    return [_input_fmt(now), _input_fmt(now + 3 * 3600)];
}
