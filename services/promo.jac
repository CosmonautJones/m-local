"""PromoPusher business logic and API.

Rules enforced here (never in the client):
- Identity: the caller's actor id comes from the server (services/session.jac).
  Guests browse; signed-in students claim; the one merchant provisioned as a
  restaurant's owner manages that restaurant and redeems its codes.
- Money: integer cents are authoritative (services/money.jac).
- Claimability: start_ts <= now < end_ts, status active, stock remaining.
- Quantity: remaining = quantity - redeemed - live claims.
- Claim hold: min(now + CLAIM_HOLD_MINUTES, offer end). At the deadline the
  hold is expired, its unit is released and its code can no longer redeem.
- Stable terms: a claim snapshots title, price, terms and eligibility. Later
  offer edits and pauses only affect future claims.
- Retry: claiming again while a hold is live returns the same code and uses no
  extra unit. A redeemed offer cannot be claimed again by the same student.
- Cancellation releases a live hold once; repeating it is harmless; it is
  rejected after redemption.
- Concurrency: every mutation runs under one process-wide lock and commits
  before releasing it. Safe for a single server process only.

Internal f"_" helpers take an explicit actor and f"now" so checks can simulate
time and identity.
"""

import time;
import random;
import threading;
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
    CLAIM_HOLD_MINUTES
}
import from services.money {
    money_to_cents,
    try_money_to_cents,
    cents_to_dollars,
    money_label
}
import from services.session {
    SessionView,
    _caller_actor,
    _restaurants,
    _restaurant_for_actor,
    _session_for,
    _provision_owner,
    _apply_owner_provisioning
}
import from services.seed { seed_demo }


glob MUTATION_LOCK: any = threading.Lock();

glob PRICE_NOTE: str = "Prices exclude tax unless the terms say otherwise. No payment is taken in the app.";


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
        price_cents: int = 0,
        regular_price_cents: int = 0,
        price_note: str = "",
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
        fits: bool = True,
        reasons: list[str] = [],
        my_code: str = "",
        my_status: str = "",
        my_expires: str = "",
        my_title: str = "",
        my_price_cents: int = 0,
        my_terms: str = "",
        my_eligibility: str = "";
}

obj ClaimView {
    has code: str = "",
        student_id: str = "",
        offer_title: str = "",
        status: str = "",
        claimed_label: str = "",
        expires_label: str = "",
        title_snapshot: str = "",
        price_cents: int = 0,
        terms: str = "",
        eligibility: str = "";
}

obj ActionResult {
    has ok: bool = False,
        message: str = "",
        code: str = "";
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
        dt = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M");
        return dt.replace(tzinfo=_tz()).timestamp();
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


"""Every mutating endpoint holds MUTATION_LOCK from its first read until
_finish has persisted the change, so two requests never decide on the same
stale stock count."""
def _start -> None {
    MUTATION_LOCK.acquire();
}


def _finish -> None {
    try {
        commit();
    } finally {
        MUTATION_LOCK.release();
    }
}


"""Cents for a float dollar value from older records (display fields)."""
def _cents_from_float(value: float) -> int {
    return try_money_to_cents(f"{max(value, 0.0):.2f}") or 0;
}


"""Older records (seed/importer) may carry only float prices; fill cents once."""
def _backfill_cents -> None {
    for r in _restaurants() {
        for o in [r ->:Publishes:->] {
            if o.price_cents == 0 and o.price > 0 {
                o.price_cents = _cents_from_float(o.price);
            }
            if o.regular_price_cents == 0 and o.regular_price > 0 {
                o.regular_price_cents = _cents_from_float(o.regular_price);
            }
        }
        for m in [r ->:Serves:->] {
            if m.price_cents == 0 and m.price > 0 {
                m.price_cents = _cents_from_float(m.price);
            }
        }
    }
}


"""The catalog lives on root.shared. If seeding ran on a signed-in caller's
own root, move those restaurants to the shared catalog."""
def _rehome_restaurants -> None {
    if jid(root) == jid(root.shared) {
        return;
    }
    for r in [root-->[?:Restaurant]] {
        root.shared ++> r;
        root del --> r;
    }
}


"""Nodes a signed-in user creates are private to that user until granted.
Catalog and claim nodes must be reachable by every account (a claim is read
and updated by the restaurant's merchant), so they are opened at creation.
Who may see or change what is decided by the checks in this module; the
API never exposes raw nodes."""
def _share(target: any) -> None {
    grant(target, level=WritePerm);
}


def _share_catalog -> None {
    for r in _restaurants() {
        _share(r);
        for loc in [r ->:HasLocation:->] {
            _share(loc);
        }
        for m in [r ->:Serves:->] {
            _share(m);
        }
        for o in [r ->:Publishes:->] {
            _share(o);
        }
    }
}


def _ensure_seed -> None {
    if not _restaurants() {
        seed_demo();
        _rehome_restaurants();
        _share_catalog();
    }
    _backfill_cents();
    _apply_owner_provisioning();
}


def _restaurant_of(o: Offer) -> Restaurant | None {
    owners = [o <-:Publishes:<-];
    return owners[0] if owners else None;
}


def _location_of(r: Restaurant) -> Location | None {
    locs = [r ->:HasLocation:->];
    return locs[0] if locs else None;
}


def _find_offer(offer_id: str) -> Offer | None {
    for r in _restaurants() {
        for o in [r ->:Publishes:->] {
            if jid(o) == offer_id {
                return o;
            }
        }
    }
    return None;
}


def _owned_offer(r: Restaurant, offer_id: str) -> Offer | None {
    for o in [r ->:Publishes:->] {
        if jid(o) == offer_id {
            return o;
        }
    }
    return None;
}


"""A live hold is a claimed status whose deadline has not been reached."""
def _is_live(c: Redemption, now: float) -> bool {
    return c.status == "claimed" and now < c.expires_ts;
}


"""Release abandoned claims: live claims at or past their deadline expire."""
def _sweep(o: Offer, now: float) -> None {
    for c in [o ->:ClaimedAs:->] {
        if c.status == "claimed" and now >= c.expires_ts {
            c.status = "expired";
        }
    }
}


def _held(o: Offer, now: float) -> int {
    _sweep(o, now);
    return len([c for c in [o ->:ClaimedAs:->] if c.status in ["claimed", "redeemed"]]);
}


def _remaining(o: Offer, now: float) -> int {
    return max(o.quantity - _held(o, now), 0);
}


def _state(o: Offer, now: float) -> str {
    if o.status == "paused" {
        return "paused";
    }
    if now >= o.end_ts {
        return "expired";
    }
    if now < o.start_ts {
        return "scheduled";
    }
    if _remaining(o, now) <= 0 {
        return "sold out";
    }
    return "active";
}


def _parse_diets(diets: str) -> list[str] {
    return [d.strip().lower() for d in diets.split(",") if d.strip()];
}


"""Budget filter in cents, or None when blank or not a valid amount."""
def _parse_budget(max_price: str) -> int | None {
    if not max_price.strip() {
        return None;
    }
    return try_money_to_cents(max_price);
}


def _end_of_today(now: float) -> float {
    d = _local(now);
    nxt = (d + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0);
    return nxt.timestamp();
}


"""Plain-language reasons + whether the offer fits all active filters."""
def _explain(
    o: Offer, state: str, budget: int | None, window: str, wanted: list[str]
) -> tuple {
    # Short match tags only for the student's own filters; price, time and
    # stock are already shown on screen, so they are not repeated here.
    reasons: list[str] = [];
    fits = True;
    if budget is not None {
        if o.price_cents <= budget {
            reasons.append(f"Under your {money_label(budget)} budget");
        } else {
            fits = False;
            reasons.append(f"Over your {money_label(budget)} budget");
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
    return (fits, reasons);
}


"""The actor's current claim on an offer: a live hold first, else a redemption."""
def _my_claim(o: Offer, actor_id: str, now: float) -> Redemption | None {
    if not actor_id {
        return None;
    }
    mine = [c for c in [o ->:ClaimedAs:->] if c.student_id == actor_id];
    for c in mine {
        if _is_live(c, now) {
            return c;
        }
    }
    for c in mine {
        if c.status == "redeemed" {
            return c;
        }
    }
    return None;
}


def _view(
    o: Offer,
    now: float,
    actor_id: str = "",
    budget: int | None = None,
    window: str = "any",
    wanted: list[str] = []
) -> OfferView {
    r = _restaurant_of(o);
    loc = _location_of(r) if r else None;
    state = _state(o, now);
    remaining = _remaining(o, now);
    (fits, reasons) = _explain(o, state, budget, window, wanted);
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
        restaurant=r.name if r else "",
        cuisine=r.cuisine if r else "",
        location_id=jid(loc) if loc else "",
        address=loc.address if loc else "",
        neighborhood=loc.neighborhood if loc else "",
        entrance_note=loc.entrance_note if loc else "",
        note_date=loc.note_date if loc else "",
        price=cents_to_dollars(o.price_cents),
        regular_price=cents_to_dollars(o.regular_price_cents),
        price_cents=o.price_cents,
        regular_price_cents=o.regular_price_cents,
        price_note=PRICE_NOTE,
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
        is_demo=o.is_demo,
        fits=fits,
        reasons=reasons
    );
    c = _my_claim(o, actor_id, now);
    if c is not None {
        v.my_code = c.code;
        v.my_status = c.status;
        v.my_expires = _clock(c.expires_ts);
        v.my_title = c.offer_title_snapshot;
        v.my_price_cents = c.price_cents_snapshot;
        v.my_terms = c.terms_snapshot;
        v.my_eligibility = c.eligibility_snapshot;
    }
    return v;
}


def _new_code -> str {
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    taken: list[str] = [];
    for r in _restaurants() {
        for o in [r ->:Publishes:->] {
            taken.extend([c.code for c in [o ->:ClaimedAs:->]]);
        }
    }
    code = "".join([random.choice(alphabet) for _ in range(6)]);
    while code in taken {
        code = "".join([random.choice(alphabet) for _ in range(6)]);
    }
    return code;
}


def _claim(offer_id: str, actor_id: str, now: float) -> ActionResult {
    if not actor_id {
        return ActionResult(ok=False, message="Sign in as a student to claim offers.");
    }
    if _restaurant_for_actor(actor_id) is not None {
        return ActionResult(ok=False, message="Merchant accounts cannot claim offers.");
    }
    o = _find_offer(offer_id);
    if o is None {
        return ActionResult(ok=False, message="That offer no longer exists.");
    }
    _sweep(o, now);
    mine = [c for c in [o ->:ClaimedAs:->] if c.student_id == actor_id];
    for c in mine {
        if c.status == "redeemed" {
            return ActionResult(ok=False, message="You already redeemed this offer.", code=c.code);
        }
    }
    for c in mine {
        if _is_live(c, now) {
            return ActionResult(
                ok=True,
                message=f"You already hold this offer. Show code {c.code} before {_clock(c.expires_ts)}.",
                code=c.code
            );
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
        return ActionResult(ok=False, message=msgs[state]);
    }
    expires = min(now + CLAIM_HOLD_MINUTES * 60, o.end_ts);
    code = _new_code();
    claim = Redemption(
        student_id=actor_id,
        code=code,
        status="claimed",
        claimed_ts=now,
        expires_ts=expires,
        offer_title_snapshot=o.title,
        price_cents_snapshot=o.price_cents,
        terms_snapshot=o.terms,
        eligibility_snapshot=o.eligibility
    );
    o +>:ClaimedAs():+> claim;
    _share(claim);
    return ActionResult(
        ok=True,
        message=f"Claimed. Show code {code} at the counter before {_clock(expires)}.",
        code=code
    );
}


def _cancel(offer_id: str, actor_id: str, now: float) -> ActionResult {
    if not actor_id {
        return ActionResult(ok=False, message="Sign in to manage your claims.");
    }
    o = _find_offer(offer_id);
    if o is None {
        return ActionResult(ok=False, message="That offer no longer exists.");
    }
    _sweep(o, now);
    mine = [c for c in [o ->:ClaimedAs:->] if c.student_id == actor_id];
    for c in mine {
        if _is_live(c, now) {
            c.status = "cancelled";
            c.cancelled_ts = now;
            return ActionResult(ok=True, message="Claim cancelled. The unit is available again.", code=c.code);
        }
    }
    for c in mine {
        if c.status == "redeemed" {
            return ActionResult(ok=False, message="This claim was already redeemed and cannot be cancelled.", code=c.code);
        }
    }
    return ActionResult(ok=True, message="You have no active hold on this offer.");
}


def _redeem(actor_id: str, code: str, now: float) -> ActionResult {
    r = _restaurant_for_actor(actor_id);
    if r is None {
        return ActionResult(ok=False, message="Sign in with a merchant account to redeem codes.");
    }
    want = code.strip().upper();
    if not want {
        return ActionResult(ok=False, message="Enter a claim code.");
    }
    for o in [r ->:Publishes:->] {
        for c in [o ->:ClaimedAs:->[?code == want]] {
            if c.status == "redeemed" {
                return ActionResult(
                    ok=False,
                    message=f"Code {want} was already redeemed at {_day_clock(c.redeemed_ts)}.",
                    code=want
                );
            }
            if c.status == "cancelled" {
                return ActionResult(ok=False, message=f"Code {want} was cancelled by the student.", code=want);
            }
            if c.status == "expired" or now >= c.expires_ts {
                c.status = "expired";
                return ActionResult(
                    ok=False,
                    message=f"Code {want} expired at {_clock(c.expires_ts)}. The unit was released.",
                    code=want
                );
            }
            c.status = "redeemed";
            c.redeemed_ts = now;
            return ActionResult(
                ok=True,
                message=f"Redeemed: {c.offer_title_snapshot}. Charge {money_label(c.price_cents_snapshot)}. Check: {c.eligibility_snapshot}.",
                code=want
            );
        }
    }
    return ActionResult(ok=False, message=f"No claim {want} found for {r.name}.");
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
    now: float
) -> ActionResult {
    errors: list[str] = [];
    p = try_money_to_cents(price);
    rp: int | None = try_money_to_cents(regular_price) if regular_price.strip() else 0;
    st = _parse_local(start_local);
    en = _parse_local(end_local);
    qty = -1;
    try {
        qty = int(quantity.strip());
    } except Exception {
        qty = -1;
    }
    if not title.strip() {
        errors.append("title is required");
    }
    if p is None {
        errors.append("price must be a dollar amount like 8 or 8.50");
    }
    if rp is None {
        errors.append("regular price must be a dollar amount like 12 or 12.50");
    }
    if st is None or en is None {
        errors.append("times must look like 2026-09-26 14:00");
    } elif en <= st {
        errors.append("end must be after start");
    }
    if qty < 1 {
        errors.append("quantity must be at least 1");
    }
    if not eligibility.strip() {
        errors.append("eligibility is required");
    }
    if not terms.strip() {
        errors.append("terms are required");
    }
    o: Offer | None = None;
    if offer_id {
        o = _owned_offer(r, offer_id);
        if o is None {
            return ActionResult(ok=False, message="That offer does not belong to your restaurant.");
        }
        held = _held(o, now);
        if qty >= 1 and qty < held {
            errors.append(f"quantity cannot go below {held} already claimed or redeemed");
        }
    }
    if errors {
        return ActionResult(ok=False, message="Fix: " + "; ".join(errors) + ".");
    }
    if o is None {
        o = Offer(title=title.strip(), created_ts=now, is_demo=r.is_demo);
        r +>:Publishes():+> o;
        _share(o);
    }
    price_cents = p or 0;
    regular_cents = rp or 0;
    o.title = title.strip();
    o.description = description.strip();
    o.price_cents = price_cents;
    o.regular_price_cents = regular_cents;
    o.price = cents_to_dollars(price_cents);
    o.regular_price = cents_to_dollars(regular_cents);
    o.start_ts = st or now;
    o.end_ts = en or now;
    o.quantity = qty;
    o.eligibility = eligibility.strip();
    o.terms = terms.strip();
    o.dietary = _parse_diets(dietary);
    o.menu_item = menu_item.strip();
    for e in [edge o ->:Features:->] {
        del e;
    }
    if o.menu_item {
        items = [m for m in [r ->:Serves:->] if m.name == o.menu_item];
        item = items[0] if items else None;
        if item is None {
            item = MenuItem(
                name=o.menu_item,
                price=o.regular_price,
                price_cents=regular_cents,
                dietary=o.dietary
            );
            r +>:Serves():+> item;
            _share(item);
        }
        o +>:Features():+> item;
    }
    return ActionResult(ok=True, message="Offer saved.", code=jid(o));
}


def _set_status(r: Restaurant, offer_id: str, status: str) -> ActionResult {
    if status not in ["active", "paused"] {
        return ActionResult(ok=False, message="Status must be active or paused.");
    }
    o = _owned_offer(r, offer_id);
    if o is None {
        return ActionResult(ok=False, message="That offer does not belong to your restaurant.");
    }
    o.status = status;
    return ActionResult(ok=True, message="Offer resumed." if status == "active" else "Offer paused.");
}


def _update_profile(
    r: Restaurant,
    name: str,
    cuisine: str,
    blurb: str,
    address: str,
    neighborhood: str,
    entrance_note: str,
    note_date: str
) -> str {
    if not name.strip() or not address.strip() {
        return "Name and address are required.";
    }
    r.name = name.strip();
    r.cuisine = cuisine.strip();
    r.blurb = blurb.strip();
    loc = _location_of(r);
    if loc is None {
        loc = Location(address="");
        r +>:HasLocation():+> loc;
        _share(loc);
    }
    loc.address = address.strip();
    loc.neighborhood = neighborhood.strip();
    loc.entrance_note = entrance_note.strip();
    loc.note_date = note_date.strip();
    return "Profile saved.";
}


def _student_label(actor_id: str) -> str {
    return "Student " + actor_id[-4:].upper() if actor_id else "Student";
}


def _portal(r: Restaurant, now: float, message: str = "") -> MerchantView {
    loc = _location_of(r);
    offers = [o for o in [r ->:Publishes:->]];
    offers.sort(key=lambda (o: Offer) -> float { return o.start_ts; });
    claims: list[tuple] = [];
    for o in offers {
        _sweep(o, now);
        for c in [o ->:ClaimedAs:->] {
            claims.append((c.claimed_ts, ClaimView(
                code=c.code,
                student_id=_student_label(c.student_id),
                offer_title=c.offer_title_snapshot,
                status=c.status,
                claimed_label=_day_clock(c.claimed_ts),
                expires_label=_clock(c.expires_ts),
                title_snapshot=c.offer_title_snapshot,
                price_cents=c.price_cents_snapshot,
                terms=c.terms_snapshot,
                eligibility=c.eligibility_snapshot
            )));
        }
    }
    claims.sort(key=lambda (t: tuple) -> float { return t[0]; }, reverse=True);
    return MerchantView(
        ok=True,
        message=message,
        name=r.name,
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


def _list_offers(
    actor_id: str, max_price: str, window: str, diets: str, now: float
) -> list[OfferView] {
    budget = _parse_budget(max_price);
    wanted = _parse_diets(diets);
    eod = _end_of_today(now);
    out: list[OfferView] = [];
    for r in _restaurants() {
        for o in [r ->:Publishes:->] {
            if o.status == "paused" or now >= o.end_ts {
                continue;
            }
            if budget is not None and o.price_cents > budget {
                continue;
            }
            if window == "now" and o.start_ts > now {
                continue;
            }
            if window == "today" and o.start_ts >= eod {
                continue;
            }
            if wanted and [w for w in wanted if w not in o.dietary] {
                continue;
            }
            out.append(_view(o, now, actor_id, budget, window, wanted));
        }
    }
    rank = {"active": 0, "scheduled": 1, "sold out": 2};
    out.sort(key=lambda (v: OfferView) -> int { return rank.get(v.state, 3); });
    return out;
}


def _no_merchant -> MerchantView {
    return MerchantView(ok=False, message="Sign in with a merchant account to manage a restaurant.");
}


# --------------------------------------------------------------- endpoints ---
# :pub endpoints are readable by guests. Every mutation is an authenticated
# endpoint (401 without a login) and also rechecks identity itself.

"""Who the server says the caller is: guest, student or merchant."""
def:pub current_session() -> SessionView {
    _ensure_seed();
    return _session_for(_caller_actor());
}


"""Student discovery: filter by budget ($), time window (now|today|any) and
comma-separated dietary tags. Paused and ended offers are hidden. Signed-in
students also see their own claim on each offer."""
def:pub list_offers(max_price: str = "", window: str = "any", diets: str = "") -> list[OfferView] {
    _ensure_seed();
    return _list_offers(_caller_actor(), max_price, window, diets, time.time());
}


def:pub get_offer(
    offer_id: str, max_price: str = "", window: str = "any", diets: str = ""
) -> OfferView | None {
    _ensure_seed();
    o = _find_offer(offer_id);
    if o is None {
        return None;
    }
    return _view(
        o,
        time.time(),
        _caller_actor(),
        _parse_budget(max_price),
        window,
        _parse_diets(diets)
    );
}


def:priv claim_offer(offer_id: str) -> ActionResult {
    _ensure_seed();
    _start();
    try {
        result = _claim(offer_id, _caller_actor(), time.time());
    } finally {
        _finish();
    }
    return result;
}


def:priv cancel_claim(offer_id: str) -> ActionResult {
    _ensure_seed();
    _start();
    try {
        result = _cancel(offer_id, _caller_actor(), time.time());
    } finally {
        _finish();
    }
    return result;
}


def:priv merchant_portal() -> MerchantView {
    _ensure_seed();
    found = _restaurant_for_actor(_caller_actor());
    if found is None {
        return _no_merchant();
    }
    r = found as Restaurant;
    _start();
    try {
        view = _portal(r, time.time());
    } finally {
        _finish();
    }
    return view;
}


def:priv update_profile(
    name: str,
    cuisine: str,
    blurb: str,
    address: str,
    neighborhood: str,
    entrance_note: str,
    note_date: str
) -> MerchantView {
    _ensure_seed();
    found = _restaurant_for_actor(_caller_actor());
    if found is None {
        return _no_merchant();
    }
    r = found as Restaurant;
    _start();
    try {
        msg = _update_profile(
            r, name, cuisine, blurb, address, neighborhood, entrance_note, note_date
        );
        view = _portal(r, time.time(), msg);
    } finally {
        _finish();
    }
    return view;
}


def:priv save_offer(
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
    menu_item: str
) -> ActionResult {
    _ensure_seed();
    found = _restaurant_for_actor(_caller_actor());
    if found is None {
        return ActionResult(ok=False, message="Sign in with a merchant account to edit offers.");
    }
    r = found as Restaurant;
    _start();
    try {
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
            time.time()
        );
    } finally {
        _finish();
    }
    return result;
}


def:priv set_offer_status(offer_id: str, status: str) -> ActionResult {
    _ensure_seed();
    found = _restaurant_for_actor(_caller_actor());
    if found is None {
        return ActionResult(ok=False, message="Sign in with a merchant account to edit offers.");
    }
    r = found as Restaurant;
    _start();
    try {
        result = _set_status(r, offer_id, status);
    } finally {
        _finish();
    }
    return result;
}


def:priv redeem_code(code: str) -> ActionResult {
    _ensure_seed();
    _start();
    try {
        result = _redeem(_caller_actor(), code, time.time());
    } finally {
        _finish();
    }
    return result;
}


"""Default start/end strings for a new offer in the editor (now .. now+3h)."""
def:pub offer_defaults() -> list[str] {
    now = time.time();
    return [_input_fmt(now), _input_fmt(now + 3 * 3600)];
}
