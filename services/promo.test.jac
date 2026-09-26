"""Server-rule checks. Run: jac clean --data --force && jac test services/promo.jac

Identity is passed explicitly to the internal helpers here; outside a served
request there is only one root, so signed-in behavior is simulated with actor
ids. Tests that change stock use their own fixture restaurant so parallel
workers never compete for seeded units."""

import time;
import from uuid { uuid4 }
import from services.importer { import_restaurant }

glob DEMO_SLUGS: list[str] = ["maize-noodle-lab", "arbor-leaf-kitchen", "diag-dough-co"];


def _offer_by_title(title: str) -> Offer {
    for r in _restaurants() {
        for o in [r ->:Publishes:->] {
            if o.title == title {
                return o;
            }
        }
    }
    raise Exception("missing " + title);
}


def _demo(slug: str) -> Restaurant {
    for r in _restaurants() {
        if r.slug == slug {
            return r;
        }
    }
    raise Exception("missing " + slug);
}


obj Fixture {
    has r: Restaurant,
        o: Offer,
        owner: str;
}


"""A fresh restaurant with one live offer, owned by the returned owner actor."""
def _fixture(qty: int = 5, price: str = "8", minutes_left: float = 120.0) -> Fixture {
    tag = str(uuid4())[:8];
    owner = "owner-" + tag;
    now = time.time();
    r = Restaurant(
        slug="fixture-" + tag,
        name="Fixture " + tag + " (Demo)",
        owner_actor_id=owner,
        is_demo=True,
        source="test"
    );
    root.shared ++> r;
    o = Offer(
        title="Fixture bowl " + tag,
        price_cents=money_to_cents(price),
        regular_price_cents=1200,
        price=cents_to_dollars(money_to_cents(price)),
        regular_price=12.0,
        start_ts=now - 3600,
        end_ts=now + minutes_left * 60,
        quantity=qty,
        eligibility="Students with a valid university ID",
        terms="One per student.",
        is_demo=True,
        created_ts=now
    );
    r +>:Publishes():+> o;
    return Fixture(r=r, o=o, owner=owner);
}


def _edit(r: Restaurant, o: Offer, price: str, terms: str, end_ts: float, now: float) -> ActionResult {
    return _save_offer(
        r,
        jid(o),
        o.title + " (edited)",
        o.description,
        price,
        "12",
        _input_fmt(o.start_ts),
        _input_fmt(end_ts),
        str(o.quantity),
        "Anyone",
        terms,
        "",
        "",
        now
    );
}


test "seed is persistent and idempotent" {
    _ensure_seed();
    demo = [r for r in _restaurants() if r.slug in DEMO_SLUGS];
    seed_demo();
    assert len(demo) == 3;
    assert len([r for r in _restaurants() if r.slug in DEMO_SLUGS]) == 3;
    assert all([r.name.endswith("(Demo)") for r in _restaurants()]);
}


test "seeded prices are backfilled to exact cents" {
    _ensure_seed();
    o = _offer_by_title("Harvest bowl for $8");
    assert o.price_cents == 800;
    assert o.regular_price_cents > o.price_cents;
    v = _view(o, time.time());
    assert v.price_cents == 800 and v.price == 8.0;
}


test "money values are exact" {
    assert money_to_cents("8") == 800;
    assert money_to_cents("8.05") == 805;
    assert money_to_cents("8.5") == 850;
    assert money_to_cents("0") == 0;
    assert money_to_cents(" $12.99 ") == 1299;
    assert money_label(805) == "$8.05";
}


test "money rejects invalid" {
    for bad in ["8.001", "NaN", "nan", "Infinity", "inf", "-1", "", " ", "1e3", "8.", ".5", "8,00", "$-2"] {
        assert try_money_to_cents(bad) is None, f"accepted {bad!r}";
        try {
            money_to_cents(bad);
            assert False, f"no error for {bad!r}";
        } except ValueError {
            assert True;
        }
    }
}


test "claim then merchant redeem, repeated redemption rejected" {
    _ensure_seed();
    _provision_owner("arbor-leaf-kitchen", "merchant-leaf");
    o = _offer_by_title("$3 oat latte study break");
    now = time.time();
    student = "student-" + str(uuid4())[:8];
    res = _claim(jid(o), student, now);
    assert res.ok, res.message;
    ok = _redeem("merchant-leaf", res.qr_payload, now);
    assert ok.ok, ok.message;
    assert "$3.00" in ok.message;
    twice = _redeem("merchant-leaf", res.qr_payload, now);
    assert not twice.ok and "already redeemed" in twice.message;
    after = _claim(jid(o), student, now);
    assert not after.ok and "already redeemed" in after.message;
}


test "claim retry is idempotent" {
    fx = _fixture(qty=2);
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    now = time.time();
    first = _claim(jid(o), "student-retry", now);
    again = _claim(jid(o), "student-retry", now + 30);
    assert first.ok and again.ok, again.message;
    assert again.qr_payload == first.qr_payload and again.claim_id == first.claim_id;
    assert _remaining(o, now + 30) == 1;
    assert len([c for c in [o ->:ClaimedAs:->]]) == 1;
}


test "merchant isolation" {
    _ensure_seed();
    _provision_owner("maize-noodle-lab", "merchant-noodle");
    _provision_owner("arbor-leaf-kitchen", "merchant-leaf");
    o = _offer_by_title("Harvest bowl for $8");
    now = time.time();
    res = _claim(jid(o), "student-" + str(uuid4())[:8], now);
    assert res.ok, res.message;
    wrong = _redeem("merchant-noodle", res.qr_payload, now);
    assert not wrong.ok;
    noodle = _demo("maize-noodle-lab");
    denied = _save_offer(
        noodle, jid(o), "Hijack", "", "1", "2", "2026-01-01 10:00", "2026-01-01 12:00",
        "5", "Anyone", "None", "", "", now
    );
    assert not denied.ok;
    paused = _set_status(noodle, jid(o), "paused");
    assert not paused.ok;
    assert o.title == "Harvest bowl for $8" and o.status == "active";
    assert _restaurant_for_actor("") is None and _restaurant_for_actor("bogus") is None;
}


test "expired and not-started offers cannot be claimed" {
    _ensure_seed();
    o = _offer_by_title("Lunch noodle bowl for $7");
    later = o.end_ts + 60;
    res = _claim(jid(o), "student-expired", later);
    assert not res.ok and "expired" in res.message;
    early = _claim(jid(o), "student-expired", o.start_ts - 60);
    assert not early.ok and "not started" in early.message;
}


test "quantity limit and abandoned claims release availability" {
    fx = _fixture(qty=3, minutes_left=120.0);
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    now = time.time();
    codes: list[str] = [];
    for i in range(3) {
        res = _claim(jid(o), f"qty-student-{i}", now);
        assert res.ok, res.message;
        codes.append(res.qr_payload);
    }
    assert _remaining(o, now) == 0;
    blocked = _claim(jid(o), "qty-student-extra", now);
    assert not blocked.ok and "sold out" in blocked.message;
    hold_end = now + CLAIM_HOLD_MINUTES * 60 + 5;
    assert _remaining(o, hold_end) == 3;
    late = _redeem(owner, codes[0], hold_end);
    assert not late.ok and "expired" in late.message;
}


test "last unit goes to one student" {
    fx = _fixture(qty=1);
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    now = time.time();
    a = _claim(jid(o), "student-a", now);
    b = _claim(jid(o), "student-b", now);
    assert a.ok and not b.ok;
    assert "sold out" in b.message;
}


test "exact deadline is expired" {
    fx = _fixture(qty=1);
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    now = time.time();
    res = _claim(jid(o), "student-deadline", now);
    assert res.ok;
    c = [x for x in [o ->:ClaimedAs:->]][0];
    deadline = c.expires_ts;
    assert deadline == now + CLAIM_HOLD_MINUTES * 60;
    assert _remaining(o, deadline - 1) == 0;
    assert _remaining(o, deadline) == 1;
    late = _redeem(owner, res.qr_payload, deadline);
    assert not late.ok and "expired" in late.message;
}


test "hold never outlives the offer" {
    fx = _fixture(qty=2, minutes_left=5.0);
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    now = time.time();
    res = _claim(jid(o), "student-short", now);
    assert res.ok;
    c = [x for x in [o ->:ClaimedAs:->]][0];
    assert c.expires_ts == o.end_ts;
}


test "claimed terms survive offer edit" {
    fx = _fixture(qty=4, price="8");
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    now = time.time();
    res = _claim(jid(o), "student-terms", now);
    assert res.ok;
    original_title = o.title;
    c = [x for x in [o ->:ClaimedAs:->]][0];
    deadline = c.expires_ts;
    edited = _edit(r, o, "12", "New stricter terms.", o.end_ts + 7200, now);
    assert edited.ok, edited.message;
    assert o.price_cents == 1200;
    assert c.expires_ts == deadline;
    v = _view(o, now, "student-terms");
    assert v.my_price_cents == 800 and v.my_title == original_title;
    assert v.my_terms == "One per student.";
    assert v.price_cents == 1200;
    done = _redeem(owner, res.qr_payload, now);
    assert done.ok and "$8.00" in done.message and original_title in done.message;
    fresh = _claim(jid(o), "student-later", now);
    assert fresh.ok;
    later = [x for x in [o ->:ClaimedAs:->] if x.student_id == "student-later"][0];
    assert later.price_cents_snapshot == 1200;
}


test "cancel releases once" {
    fx = _fixture(qty=1);
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    now = time.time();
    res = _claim(jid(o), "student-cancel", now);
    assert res.ok and _remaining(o, now) == 0;
    first = _cancel(jid(o), "student-cancel", now);
    assert first.ok and "cancelled" in first.message;
    assert _remaining(o, now) == 1;
    second = _cancel(jid(o), "student-cancel", now);
    assert second.ok and "no active hold" in second.message;
    assert _remaining(o, now) == 1;
    dead = _redeem(owner, res.qr_payload, now);
    assert not dead.ok and "cancelled" in dead.message;
    again = _claim(jid(o), "student-cancel", now);
    assert again.ok and again.qr_payload != res.qr_payload;
    assert _remaining(o, now) == 0;
}


test "redeemed claim cannot cancel" {
    fx = _fixture(qty=2);
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    now = time.time();
    res = _claim(jid(o), "student-redeemed", now);
    assert _redeem(owner, res.qr_payload, now).ok;
    no = _cancel(jid(o), "student-redeemed", now);
    assert not no.ok and "already redeemed" in no.message;
    assert _remaining(o, now) == 1;
}


test "pause honors existing hold" {
    fx = _fixture(qty=3, price="6");
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    now = time.time();
    res = _claim(jid(o), "student-pause", now);
    assert res.ok;
    assert _set_status(r, jid(o), "paused").ok;
    blocked = _claim(jid(o), "student-other", now);
    assert not blocked.ok and "paused" in blocked.message;
    kept = _redeem(owner, res.qr_payload, now);
    assert kept.ok and "$6.00" in kept.message;
}


test "quantity cannot drop below held units" {
    fx = _fixture(qty=3);
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    now = time.time();
    _claim(jid(o), "student-q1", now);
    _claim(jid(o), "student-q2", now);
    o.quantity = 3;
    shrink = _save_offer(
        r, jid(o), o.title, "", "8", "12", _input_fmt(o.start_ts), _input_fmt(o.end_ts),
        "1", "Anyone", "Terms.", "", "", now
    );
    assert not shrink.ok and "cannot go below 2" in shrink.message;
}


test "offer editor rejects invalid money" {
    fx = _fixture(qty=2);
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    now = time.time();
    for bad in ["8.001", "NaN", "-1", "Infinity"] {
        res = _save_offer(
            r, jid(o), o.title, "", bad, "12", _input_fmt(o.start_ts), _input_fmt(o.end_ts),
            "2", "Anyone", "Terms.", "", "", now
        );
        assert not res.ok and "price" in res.message, bad;
    }
    assert o.price_cents == 800;
}


test "merchants cannot claim offers" {
    fx = _fixture(qty=2);
    r = fx.r;
    o = fx.o;
    owner = fx.owner;
    res = _claim(jid(o), owner, time.time());
    assert not res.ok and "Merchant" in res.message;
}


test "paused offers are hidden and unclaimable" {
    _ensure_seed();
    o = _offer_by_title("Weekend cheese slice deal");
    assert o.status == "paused";
    res = _claim(jid(o), "student-paused", time.time());
    assert not res.ok;
    titles = [v.title for v in list_offers()];
    assert "Weekend cheese slice deal" not in titles;
}


test "filters and match explanation" {
    _ensure_seed();
    vegan = list_offers("", "any", "vegan");
    assert len(vegan) >= 1;
    assert all(["vegan" in v.dietary for v in vegan]);
    cheap = list_offers("5", "any", "");
    assert all([v.price_cents <= 500 for v in cheap]);
    o = _offer_by_title("Harvest bowl for $8");
    v = get_offer(jid(o), "10", "now", "vegan") as OfferView;
    assert v.fits;
    assert "Under your $10.00 budget" in v.reasons;
    assert "Vegan" in v.reasons;
}


test "guest cannot mutate" {
    _ensure_seed();
    o = _offer_by_title("Harvest bowl for $8");
    now = time.time();
    assert _session_for("").role == "guest";
    assert not _session_for("").authenticated;
    claim = _claim(jid(o), "", now);
    assert not claim.ok and "Sign in" in claim.message;
    assert not _cancel(jid(o), "", now).ok;
    assert not _redeem("", "mlocal:v1:" + "A" * 32, now).ok;
    assert _restaurant_for_actor("") is None;
}


test "student cannot become merchant" {
    _ensure_seed();
    student = "student-" + str(uuid4())[:8];
    s = _session_for(student);
    assert s.authenticated and s.role == "student" and s.restaurant_id == "";
    assert not _redeem(student, "mlocal:v1:" + "A" * 32, time.time()).ok;
    assert _restaurant_for_actor(student) is None;
    slug = "import-" + str(uuid4())[:8];
    r = import_restaurant(
        {"slug": slug, "name": "Imported (Demo)", "owner_actor_id": student, "is_demo": True}
    );
    assert r.owner_actor_id == "";
    assert _session_for(student).role == "student";
}


test "merchant a cannot edit b" {
    _ensure_seed();
    a = "merchant-a-" + str(uuid4())[:8];
    b = "merchant-b-" + str(uuid4())[:8];
    _provision_owner("maize-noodle-lab", a);
    _provision_owner("arbor-leaf-kitchen", b);
    leaf_offer = _offer_by_title("$3 oat latte study break");
    noodle = _demo("maize-noodle-lab");
    now = time.time();
    edit = _save_offer(
        noodle, jid(leaf_offer), "Hijack", "", "1", "2",
        _input_fmt(now), _input_fmt(now + 3600), "5", "Anyone", "None", "", "", now
    );
    assert not edit.ok and "does not belong" in edit.message;
    assert not _set_status(noodle, jid(leaf_offer), "paused").ok;
    payload = _claim(jid(leaf_offer), "student-" + str(uuid4())[:8], now).qr_payload;
    wrong = _redeem(a, payload, now);
    assert not wrong.ok and "different restaurant" in wrong.message;
    assert not _preview(a, payload, now).ok;
    assert _redeem(b, payload, now).ok;
    assert leaf_offer.title == "$3 oat latte study break";
}


test "student cannot read another claim" {
    _ensure_seed();
    o = _offer_by_title("Harvest bowl for $8");
    now = time.time();
    alice = "student-alice-" + str(uuid4())[:8];
    bob = "student-bob-" + str(uuid4())[:8];
    held = _claim(jid(o), alice, now);
    assert held.ok;
    assert _view(o, now, alice).my_qr_payload == held.qr_payload;
    theirs = _view(o, now, bob);
    assert theirs.my_qr_payload == "" and theirs.my_claim_id == "" and theirs.my_status == "" and theirs.my_title == "";
    guest = _view(o, now, "");
    assert guest.my_qr_payload == "" and guest.my_claim_id == "";
    for v in _list_offers(bob, "", "any", "", now) {
        assert v.my_qr_payload != held.qr_payload;
    }
    other = "merchant-" + str(uuid4())[:8];
    _provision_owner("diag-dough-co", other);
    portal = _portal(_demo("diag-dough-co"), now);
    assert held.claim_id not in [c.claim_id for c in portal.claims];
    home = _portal(_demo("arbor-leaf-kitchen"), now);
    shown = [c for c in home.claims if c.claim_id == held.claim_id];
    assert shown and shown[0].student_id != alice;
}


test "qr payload is versioned, opaque and unique" {
    fx = _fixture(qty=3);
    o = fx.o;
    now = time.time();
    a = _claim(jid(o), "student-qr-a", now);
    b = _claim(jid(o), "student-qr-b", now);
    assert a.qr_payload.startswith("mlocal:v1:");
    assert len(a.qr_payload) == len("mlocal:v1:") + 32;
    assert a.qr_payload != b.qr_payload;
    assert "student-qr-a" not in a.qr_payload and fx.owner not in a.qr_payload;
    assert not a.qr_payload.startswith("http");
    assert a.claim_id and a.claim_id != b.claim_id;
}


test "malformed and forged payloads are rejected" {
    fx = _fixture(qty=2);
    now = time.time();
    real = _claim(jid(fx.o), "student-forge", now);
    token = real.qr_payload[len("mlocal:v1:"):];
    for bad in ["", "hello", token, "mlocal:v2:" + token, "mlocal:v1:" + token[:-1],
                "mlocal:v1:" + token + "x", "mlocal:v1:" + "A" * 32, "https://evil.test/" + token] {
        res = _redeem(fx.owner, bad, now);
        assert not res.ok, bad;
    }
    assert _redeem(fx.owner, "  " + real.qr_payload + "\n", now).ok;
}


test "preview shows locked terms and does not redeem" {
    fx = _fixture(qty=2, price="7");
    now = time.time();
    res = _claim(jid(fx.o), "student-preview", now);
    check = _preview(fx.owner, res.qr_payload, now);
    assert check.ok and check.status == "claimed", check.message;
    assert check.price_cents == 700 and check.terms == "One per student.";
    assert check.title_snapshot == fx.o.title and check.claim_id == res.claim_id;
    again = _preview(fx.owner, res.qr_payload, now);
    assert again.ok;
    assert _redeem(fx.owner, res.qr_payload, now).ok;
    after = _preview(fx.owner, res.qr_payload, now);
    assert not after.ok and "already redeemed" in after.message;
    assert not _preview("student-preview", res.qr_payload, now).ok;
}


test "claim retry returns the same qr after reload" {
    fx = _fixture(qty=2);
    now = time.time();
    first = _claim(jid(fx.o), "student-reload", now);
    v = _view(fx.o, now + 60, "student-reload");
    assert v.my_qr_payload == first.qr_payload and v.my_claim_id == first.claim_id;
    assert v.my_status == "claimed";
}
