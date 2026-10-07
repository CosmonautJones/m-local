"""Server-rule checks. Run bash scripts/test.sh core in an isolated store."""

import time;
import from services.seed { seed_demo }
import from unittest.mock { patch }
import from jaclang { JacRuntime as Jac }


def _offer_by_title(title: str) -> Offer {
    for r in [root.shared -->[?:Restaurant]] {
        for o in [r ->:Publishes:->] {
            if o.title == title {
                return o;
            }
        }
    }
    raise Exception("missing " + title);
}


def _restaurant_by_slug(slug: str) -> Restaurant {
    for r in [root.shared -->[?:Restaurant]] {
        if r.slug == slug { return r; }
    }
    raise Exception("missing " + slug);
}


test "offer state and remaining stock use the same observation" {
    now = time.time();
    o = Offer(title="Stock observation", start_ts=now - 60, end_ts=now + 60, quantity=2, qr_ready=True);
    observations = iter([2, 0]);
    with patch.dict(_view.__globals__, {
        "_remaining": lambda (offer: Offer, at: float) -> int { return next(observations); }
    }) {
        v = _view(o, now);
        assert v.state == "active" and v.remaining == 2;
    }
}


test "seed is persistent and idempotent" {
    _ensure_seed();
    n = len([root.shared -->[?:Restaurant]]);
    seed_demo();
    assert n >= 3;
    assert len([root.shared -->[?:Restaurant]]) == n;
    assert all([r.name.endswith("(Demo)") for r in [root.shared -->[?:Restaurant]]]);
}

test "warm catalog skips ownership and money backfills but checks hosted opt in" {
    _ensure_seed();
    with patch.dict(_ensure_seed.__globals__, {
        "merchant_owner": lambda (slug: str) -> str { raise RuntimeError("repeated owner scan"); },
        "money_to_cents": lambda (value: str) -> int { raise RuntimeError("repeated money migration"); }
    }) {
        with patch.dict(_ensure_seed.__globals__, {
            "ensure_hosted_dataset": lambda () { raise RuntimeError("hosted opt in checked"); }
        }) {
            checked = False;
            try { _ensure_seed(); } except RuntimeError as e {
                checked = str(e) == "hosted opt in checked";
            }
            assert checked;
        }
        _ensure_seed();
    }
}


test "claim then merchant redeem, repeated redemption rejected" {
    _ensure_seed();
    o = _offer_by_title("$3 oat latte study break");
    now = time.time();
    res = _claim(jid(o), "check-student-1", now);
    assert res.ok, res.message;
    again = _claim(jid(o), "check-student-1", now);
    assert again.ok and again.qr_payload == res.qr_payload and again.claim_id == res.claim_id;
    ok = _redeem(_restaurant_by_slug("arbor-leaf-kitchen"), res.qr_payload, now);
    assert ok.ok, ok.message;
    twice = _redeem(_restaurant_by_slug("arbor-leaf-kitchen"), res.qr_payload, now);
    assert not twice.ok and "already redeemed" in twice.message;
    after = _claim(jid(o), "check-student-1", now);
    assert not after.ok and "already redeemed" in after.message;
}


test "merchant isolation" {
    _ensure_seed();
    o = _offer_by_title("Harvest bowl for $8");
    now = time.time();
    res = _claim(jid(o), "check-student-2", now);
    assert res.ok;
    wrong = _redeem(_restaurant_by_slug("maize-noodle-lab"), res.qr_payload, now);
    assert not wrong.ok;
    noodle = _restaurant_by_slug("maize-noodle-lab");
    denied = _save_offer(
        noodle, jid(o), "Hijack", "", "1", "2", "2026-01-01 10:00", "2026-01-01 12:00",
        "5", "Anyone", "None", "", "", now
    );
    assert not denied.ok;
    assert o.title == "Harvest bowl for $8";
    assert _merchant_for_actor("") is None;
}


test "expired and not-started offers cannot be claimed" {
    _ensure_seed();
    o = _offer_by_title("Lunch noodle bowl for $7");
    later = o.end_ts + 60;
    res = _claim(jid(o), "check-student-3", later);
    assert not res.ok and "expired" in res.message;
    early = _claim(jid(o), "check-student-3", o.start_ts - 60);
    assert not early.ok and "not started" in early.message;
}


test "quantity limit and abandoned claims release availability" {
    _ensure_seed();
    o = _offer_by_title("Slice + drink for $5");
    now = time.time();
    start = _remaining(o, now);
    codes: list[str] = [];
    for i in range(start) {
        r = _claim(jid(o), f"qty-student-{i}", now);
        assert r.ok, r.message;
        codes.append(r.qr_payload);
    }
    assert _remaining(o, now) == 0;
    blocked = _claim(jid(o), "qty-student-extra", now);
    assert not blocked.ok and "sold out" in blocked.message;
    hold_end = now + CLAIM_HOLD_MINUTES * 60 + 5;
    if hold_end < o.end_ts {
        assert _remaining(o, hold_end) == start;
        late = _redeem(_restaurant_by_slug("diag-dough-co"), codes[0], hold_end);
        assert not late.ok and "expired" in late.message;
    }
}


test "production catalog omits demo offers and refuses demo claims" {
    _ensure_seed();
    o = _offer_by_title("$3 oat latte study break");
    now = time.time();
    r = Restaurant(slug="catalog-hidden-cafe", name="Catalog Hidden Cafe", cuisine="Cafe", is_demo=True);
    root.shared ++> r;
    hidden = Offer(title="Catalog hidden lunch", price=4.0, price_cents=400, regular_price_cents=600,
        start_ts=now - 60, end_ts=now + 7200, quantity=2, qr_ready=True, is_demo=True,
        terms="One each", eligibility="Students");
    r +>:Publishes():+> hidden;
    hid = jid(hidden);
    actor = "catalog-hidden-student";
    with patch.dict(os.environ, {"MLOCAL_DEMO_MODE": "1"}) {
        claimed = _claim(hid, actor, now);
        assert claimed.ok, claimed.message;
    }
    with patch.dict(os.environ, {"MLOCAL_DEMO_MODE": ""}) {
        listed = list_offers();
        assert "$3 oat latte study break" not in [v.title for v in listed];
        assert hid not in [v.id for v in listed];
        assert all([not v.is_demo and "(Demo)" not in v.restaurant for v in listed]);
        assert get_offer(jid(o)) is None;
        with patch.dict(get_offer.__globals__, {"_actor_id": lambda () -> str { return actor; }}) {
            assert get_offer(hid) is None;
        }
        blocked = _claim(jid(o), "production-student", now);
        assert not blocked.ok and "not available" in blocked.message;
        redeemed = _redeem(r, claimed.qr_payload, now);
        assert redeemed.ok, redeemed.message;
        with patch.dict(get_offer.__globals__, {"_actor_id": lambda () -> str { return actor; }}) {
            assert get_offer(hid) is None;
        }
        assert hid not in [v.id for v in list_offers()];
    }
    hidden.status = "paused";
    hidden.end_ts = now - 30;
}


test "paused offers are hidden and unclaimable" {
    _ensure_seed();
    o = _offer_by_title("Weekend cheese slice deal");
    assert o.status == "paused";
    res = _claim(jid(o), "check-student-4", time.time());
    assert not res.ok;
    titles = [v.title for v in list_offers()];
    assert "Weekend cheese slice deal" not in titles;
}


test "public get hides paused and ended offers unless the caller holds a live claim" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    now = time.time();
    created = _save_offer(
        r, "", "Visibility lunch", "Bowl", "5", "7",
        "2020-01-01 08:00", "2027-06-01 18:00", "3", "Students", "One each", "", "", now
    );
    assert created.ok, created.message;
    offer_id = created.code;
    assert get_offer(offer_id) is not None;
    held = _claim(offer_id, "visibility-student", now);
    assert held.ok, held.message;
    o = _owned_offer(r, offer_id) as Offer;
    o.status = "paused";
    assert get_offer(offer_id) is None;
    assert offer_id not in [v.id for v in list_offers()];
    with patch.dict(get_offer.__globals__, {"_actor_id": lambda () -> str { return "visibility-student"; }}) {
        visible = get_offer(offer_id) as OfferView;
        assert visible.my_status == "claimed" and visible.title == "Visibility lunch";
    }
    redeemed = _redeem(r, held.qr_payload, now);
    assert redeemed.ok, redeemed.message;
    with patch.dict(get_offer.__globals__, {"_actor_id": lambda () -> str { return "visibility-student"; }}) {
        assert get_offer(offer_id) is None;
    }
    o.status = "active";
    o.end_ts = now - 30;
    assert get_offer(offer_id) is None;
    o.end_ts = now + 7200;
    o.status = "paused";
    portal = _portal(r, now);
    assert offer_id in [v.id for v in portal.offers];
    o.status = "active";
    resumed = get_offer(offer_id) as OfferView;
    assert resumed.title == "Visibility lunch";
    o.status = "paused";
    o.end_ts = now - 30;
}


test "filters and match explanation" {
    _ensure_seed();
    vegan = list_offers("", "any", "vegan");
    assert len(vegan) >= 1;
    assert all(["vegan" in v.dietary for v in vegan]);
    cheap = list_offers("5", "any", "");
    assert all([v.price <= 5 for v in cheap]);
    o = _offer_by_title("Harvest bowl for $8");
    v = get_offer(jid(o), "10", "now", "vegan") as OfferView;
    assert v.fits;
    assert "Under your $10.00 budget" in v.reasons;
    assert "Vegan" in v.reasons;
}


test "claim snapshot survives offer edits pause and deadline equality" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    now = time.time();
    o = Offer(qr_ready=True, title="Snapshot test", price=7.25, price_cents=725,
        regular_price_cents=1000,
        start_ts=now - 60, end_ts=now + 1800, quantity=2,
        terms="Original terms", eligibility="Original student ID");
    r +>:Publishes():+> o;
    result = _claim(jid(o), "snapshot-student", now);
    assert result.ok;
    before = _preview(r, result.qr_payload, now);
    o.title = "Changed title";
    o.price_cents = 999;
    o.regular_price_cents = 1500;
    o.terms = "Changed terms";
    o.eligibility = "Changed eligibility";
    o.end_ts = now + 10;
    o.status = "paused";
    after = _preview(r, result.qr_payload, now + 20);
    assert after.ok and after.title_snapshot == "Snapshot test";
    assert after.price_cents == 725 and after.terms == "Original terms";
    claim = _find_claim(r, result.qr_payload) as Redemption;
    assert claim.regular_price_cents_snapshot == 1000;
    assert after.eligibility == "Original student ID";
    assert after.expires_ts == before.expires_ts;
    exact = _redeem(r, result.qr_payload, before.expires_ts);
    assert not exact.ok and "expired" in exact.message;
}


test "cancellation is idempotent releases once and stale QR cannot redeem" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    now = time.time();
    o = Offer(qr_ready=True, title="Cancellation test", price_cents=100,
        start_ts=now - 60, end_ts=now + 1800, quantity=1);
    r +>:Publishes():+> o;
    first = _claim(jid(o), "cancel-student", now);
    assert first.ok and _remaining(o, now) == 0;
    assert _cancel(jid(o), "cancel-student", now + 1).ok;
    assert _cancel(jid(o), "cancel-student", now + 2).ok;
    cancelled = _find_claim(r, first.qr_payload) as Redemption;
    assert cancelled.cancelled_ts == now + 1;
    assert cancelled.redeemed_ts == 0;
    assert _remaining(o, now) == 1;
    assert not _preview(r, first.qr_payload, now).ok;
    assert not _redeem(r, first.qr_payload, now).ok;
    replacement = _claim(jid(o), "cancel-student", now);
    assert replacement.ok and replacement.qr_payload != first.qr_payload;
    assert _view(o, now, "cancel-student").my_qr_payload == replacement.qr_payload;
    assert _redeem(r, replacement.qr_payload, now).ok;
    assert not _cancel(jid(o), "cancel-student", now).ok;
}


test "preview is read only and own claim fields never cross actor boundary" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    now = time.time();
    o = Offer(qr_ready=True, title="Private view test", price_cents=100,
        start_ts=now - 60, end_ts=now + 1800, quantity=2);
    r +>:Publishes():+> o;
    result = _claim(jid(o), "view-student", now);
    assert result.ok;
    assert _preview(r, result.qr_payload, now).ok;
    assert _preview(r, result.qr_payload, now).ok;
    mine = _view(o, now, "view-student");
    assert mine.my_qr_payload == result.qr_payload and mine.my_status == "claimed";
    assert _view(o, now, "other-student").my_qr_payload == "";
    assert _view(o, now).my_claim_id == "";
    c = _find_claim(r, result.qr_payload) as Redemption;
    assert c.status == "claimed" and c.redeemed_ts == 0;
    _ = _preview(r, result.qr_payload, c.expires_ts);
    assert c.status == "claimed";
    assert not _redeem(r, "https://example.com/claim", now).ok;
    assert not _redeem(r, result.qr_payload + "=", now).ok;
}


test "pure claim deadline and repr keep credential private" {
    c = Redemption(actor_id="private-actor", qr_payload="mlocal:v1:" + "A" * 43,
        expires_ts=1000.0);
    assert _claim_status(c, 999.0) == "claimed";
    assert _claim_status(c, 1000.0) == "expired";
    assert c.status == "claimed";
    assert "private-actor" not in repr(c);
    assert c.qr_payload not in repr(c);
    c.status = "cancelled";
    assert _claim_status(c, 1001.0) == "cancelled";
    c.status = "redeemed";
    assert _claim_status(c, 1001.0) == "redeemed";
}


test "legacy consumed stock is never silently reopened by QR migration" {
    o = Offer(title="Legacy test", quantity=5, price_cents=100);
    o +>:ClaimedAs():+> Redemption(student_id="old-name", code="OLDCOD", status="redeemed");
    assert not o.qr_ready;
    assert _remaining(Offer(title="Unreconciled old offer", quantity=5), 1000.0) == 0;
    assert _remaining(o, 1000.0) == 0;
    assert _state(o, 1000.0) != "active";
}


test "offer views carry the location's access context with the server clock" {
    _ensure_seed();
    now = time.time();
    noodle = _offer_by_title("Lunch noodle bowl for $7");
    v = _view(noodle, now);
    assert v.location_id != "";
    assert v.access_context.state in ["current", "needs_recheck"], v.access_context.state;
    assert len(v.access_context.notices) >= 1;
    assert all([n.is_demo for n in v.access_context.notices]);
    for n in v.access_context.notices {
        if n.state != "current" {
            assert n.entrance_instruction == "";
        }
    }
    leaf = _offer_by_title("Harvest bowl for $8");
    other = _view(leaf, now);
    assert other.access_context.state == "none" and other.access_context.notices == [];
    stale = _view(noodle, now + 10 * 86400.0);
    assert stale.access_context.state == "needs_recheck";
    assert all([n.entrance_instruction == "" for n in stale.access_context.notices]);
}


test "offer creation rejects invalid content without publishing any nodes" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    before = len([r ->:Publishes:->]);
    now = 1790449200.0;  # 2026-09-26 19:00 UTC.
    cases = [
        ("T" * 121, "5", "7", "10", "2026-09-26 16:00", "vegan"),
        ("Valid title", "10000", "", "10", "2026-09-26 16:00", "vegan"),
        ("Valid title", "5", "4", "10", "2026-09-26 16:00", "vegan"),
        ("Valid title", "5", "0", "10", "2026-09-26 16:00", "vegan"),
        ("Valid title", "5", "7", "1_0", "2026-09-26 16:00", "vegan"),
        ("Valid title", "5", "7", "10001", "2026-09-26 16:00", "vegan"),
        ("Valid title", "5", "7", "10", "2026-09-26 10:59", "vegan"),
        ("Valid title", "5", "7", "10", "2026-09-26 16:00", "imaginary-diet")
    ];
    for (title, price, regular, qty, end, diets) in cases {
        result = _save_offer(r, "", title, "Lunch special", price, regular,
            "2026-09-26 10:00", end, qty, "Show student ID", "One per person",
            diets, "Lunch bowl", now);
        assert not result.ok, result.message;
        assert result.code == "";
        assert len([r ->:Publishes:->]) == before;
    }
}


test "local offer dates accept browser input and reject impossible Detroit times" {
    assert _parse_local("2026-09-26T11:00") == 1790434800.0;
    assert _parse_local("2026-09-26 11:00") == 1790434800.0;
    assert _parse_local("2026-03-08 02:30") is None;
    assert _parse_local("2026-11-01 01:30") is None;
    assert _parse_local("2026-02-30 12:00") is None;
}


test "offer editing keeps the same listing paused state and original claim" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    now = 1790434800.0;
    before = len([r ->:Publishes:->]);
    created = _save_offer(r, "", "New lunch", "Lunch special", "5.25", "7",
        "2026-09-26 10:00", "2026-09-26 16:00", "3", "Show student ID",
        "One per person", " Vegan, vegan ", "Lunch bowl", now);
    assert created.ok, created.message;
    o = _owned_offer(r, created.code) as Offer;
    assert o.price_cents == 525 and o.dietary == ["vegan"];
    assert o.status == "active" and o.qr_ready;
    held = _claim(created.code, "save-claim-student", now);
    assert held.ok;
    o.status = "paused";
    updated = _save_offer(r, created.code, "Updated lunch", "New description", "6", "8",
        "2026-09-26 10:00", "2026-09-26 17:00", "3", "New eligibility",
        "New terms", "vegan", "Lunch bowl", now + 60);
    assert updated.ok and updated.code == created.code;
    assert len([r ->:Publishes:->]) == before + 1;
    assert o.title == "Updated lunch" and o.status == "paused";
    assert _remaining(o, now + 60) == 2;
    snapshot = _preview(r, held.qr_payload, now + 60);
    assert snapshot.ok and snapshot.title_snapshot == "New lunch";
    assert snapshot.price_cents == 525 and snapshot.terms == "One per person";
}


test "offer publish retries keep one offer and do not overwrite later edits" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    now = 1790434800.0;
    key = "publish-retry-fixture-001";
    before = len([r ->:Publishes:->]);
    first = _save_offer(r, "", "Retry lunch", "Lunch", "5", "7",
        "2026-09-26 10:00", "2026-09-26 16:00", "2", "Students", "One each", "", "", now, key);
    assert first.ok, first.message;
    again = _save_offer(r, "", "Retry lunch", "Lunch", "5", "7",
        "2026-09-26 10:00", "2026-09-26 16:00", "2", "Students", "One each", "", "", now + 60, key);
    assert again.ok and again.code == first.code;
    equivalent = _save_offer(r, "", " Retry lunch ", "Lunch ", "5.00", "7.00",
        "2026-09-26T10:00", "2026-09-26T16:00", "02", "Students ", " One each", "", "", now, key);
    assert equivalent.ok and equivalent.code == first.code;
    assert len([r ->:Publishes:->]) == before + 1;
    changed = _save_offer(r, "", "Changed retry", "Lunch", "6", "7",
        "2026-09-26 10:00", "2026-09-26 16:00", "2", "Students", "One each", "", "", now, key);
    assert not changed.ok and "already published" in changed.message;
    o = _owned_offer(r, first.code) as Offer;
    assert o.title == "Retry lunch" and o.price_cents == 500;
    o.title = "Later edit";
    expired_retry = _save_offer(r, "", "Retry lunch", "Lunch", "5", "7",
        "2026-09-26 10:00", "2026-09-26 16:00", "2", "Students", "One each", "", "", now + 86400, key);
    assert expired_retry.ok and expired_retry.code == first.code and o.title == "Later edit";
    other = _restaurant_by_slug("maize-noodle-lab");
    separate = _save_offer(other, "", "Retry lunch", "Lunch", "5", "7",
        "2026-09-26 10:00", "2026-09-26 16:00", "2", "Students", "One each", "", "", now, key);
    assert separate.ok and separate.code != first.code;
}

test "malformed publish keys cannot create an offer" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    before = len([r ->:Publishes:->]);
    for key in ["short", "x" * 81, "invalid/publish/key/value", " " * 32] {
        saved = _save_offer(r, "", "Malformed key lunch", "Lunch", "5", "7",
            "2026-09-26 10:00", "2026-09-26 16:00", "2", "Students", "One each", "", "", 1790434800.0, key);
        assert not saved.ok;
    }
    assert len([r ->:Publishes:->]) == before;
}

test "invalid offer edits leave listing and menu relationships unchanged" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    now = 1790434800.0;
    saved = _save_offer(r, "", "Protected lunch", "Original description", "5", "7",
        "2026-09-26 10:00", "2026-09-26 16:00", "2", "Student ID",
        "Original terms", "vegan", "Original bowl", now);
    assert saved.ok;
    o = _owned_offer(r, saved.code) as Offer;
    assert _claim(saved.code, "stock-student-1", now).ok;
    assert _claim(saved.code, "stock-student-2", now).ok;
    rejected = _save_offer(r, saved.code, "Replacement", "Replacement description", "6", "8",
        "2026-09-26 10:00", "2026-09-26 17:00", "1", "New ID",
        "New terms", "vegan", "Replacement bowl", now);
    assert not rejected.ok and "quantity" in rejected.message;
    assert o.title == "Protected lunch" and o.description == "Original description";
    assert o.price_cents == 500 and o.quantity == 2 and o.terms == "Original terms";
    assert [m.name for m in [o ->:Features:->]] == ["Original bowl"];
    oversized = _save_offer(r, saved.code, "Replacement", "D" * 2001, "6", "8",
        "2026-09-26 10:00", "2026-09-26 17:00", "2", "New ID",
        "New terms", "vegan", "Replacement bowl", now);
    assert not oversized.ok;
    assert o.title == "Protected lunch" and o.description == "Original description";
}


test "merchant profile rejects invalid input with a failure and no partial write" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    original = r.name;
    original_address = (_location_of(r) as Location).address;
    with patch.dict(update_profile.__globals__, {"_merchant": lambda () -> Restaurant { return r; }}) {
        result = update_profile("", "Changed cuisine", "Changed blurb", "Changed address", "", "", "");
        assert not result.ok, "Invalid profile must not report success";
        assert result.name == public_name(original) and result.address == original_address;
        long_result = update_profile("R" * 121, "Changed cuisine", "Changed blurb", "Changed address", "", "", "");
        assert not long_result.ok;
        assert long_result.name == public_name(original) and long_result.address == original_address;
    }
}


test "expired offers must receive a future deadline before they can resume" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    now = time.time();
    o = Offer(title="Ended paused offer", qr_ready=True, status="paused", quantity=2,
        start_ts=now - 7200, end_ts=now - 3600);
    r +>:Publishes():+> o;
    with patch.dict(set_offer_status.__globals__, {"_merchant": lambda () -> Restaurant { return r; }}) {
        result = set_offer_status(jid(o), "active");
        assert not result.ok and "end" in result.message;
        assert o.status == "paused";
    }
}


test "configured merchant cannot bypass review by changing identity in legacy profile RPC" {
    r = Restaurant(slug="configured-profile-review", name="Configured Cafe", source="manual");
    root.shared ++> r;
    r +>:HasLocation():+> Location(address="123 Main St");
    with patch.dict(update_profile.__globals__, {"_merchant": lambda () -> Restaurant { return r; }}) {
        renamed = update_profile("Renamed Cafe", "Cafe", "Lunch", "123 Main St", "", "", "");
        assert not renamed.ok and "review" in renamed.message;
        moved = update_profile("Configured Cafe", "Cafe", "Lunch", "456 Main St", "", "", "");
        assert not moved.ok and "review" in moved.message;
    }
    persisted = _restaurant_by_slug("configured-profile-review");
    assert persisted.name == "Configured Cafe" and (_location_of(persisted) as Location).address == "123 Main St";
}


test "merchant profile saves normalized routine fields and is readable after commit" {
    r = Restaurant(slug="profile-test", name="Profile Test (Demo)", is_demo=True);
    root.shared ++> r;
    r +>:HasLocation():+> Location(address="123 Main St");
    with patch.dict(update_profile.__globals__, {"_merchant": lambda () -> Restaurant { return r; }}) {
        result = update_profile("  Profile Test (Demo)  ", "  Cafe  ", "  Lunch and coffee  ",
            "  123 Main St  ", "  Downtown  ", "  Use Main St door  ", "  2026-09-26  ");
        assert result.ok, result.message;
        assert result.name == "Profile Test" and result.address == "123 Main St";
        assert result.cuisine == "Cafe" and result.blurb == "Lunch and coffee";
    }
    persisted = _restaurant_by_slug("profile-test");
    loc = _location_of(persisted) as Location;
    assert persisted.name == "Profile Test (Demo)" and loc.address == "123 Main St";
    assert loc.neighborhood == "Downtown" and loc.entrance_note == "Use Main St door";
    assert loc.note_date == "2026-09-26";
}

obj _UnavailableDetailsStore {
    def update_business_details(actor: str, cuisine: str, description: str, image_url: str | None = None) -> None {
        raise RuntimeError("Private profile store unavailable");
    }
}

def _unavailable_details_store() -> any { return _UnavailableDetailsStore(); }

test "private routine draft failure prevents public profile mutation" {
    r = Restaurant(slug="private-profile-failure", name="Failure Cafe", cuisine="Cafe", blurb="Original description");
    root.shared ++> r;
    r +>:HasLocation():+> Location(address="123 Main St");
    commit();
    failed = False;
    with patch.dict(update_profile.__globals__, {"_merchant": lambda () -> Restaurant { return r; }, "store": _unavailable_details_store}) {
        try { update_profile("Failure Cafe", "Bakery", "Edited description", "123 Main St", "", "", ""); }
        except RuntimeError {
            failed = True;
            Jac.get_context().mem.abort();
        }
    }
    assert failed;
    persisted = _restaurant_by_slug("private-profile-failure");
    assert persisted.cuisine == "Cafe" and persisted.blurb == "Original description";
}


test "offer edits count all held and redeemed units even if old quantity is inconsistent" {
    _ensure_seed();
    r = _restaurant_by_slug("arbor-leaf-kitchen");
    now = 1790434800.0;
    saved = _save_offer(r, "", "Reconciled stock", "Lunch", "5", "7",
        "2026-09-26 10:00", "2026-09-26 16:00", "2", "Student ID",
        "One per student", "", "", now);
    assert saved.ok;
    redeemed = _claim(saved.code, "stock-redeemed-student", now);
    assert redeemed.ok and _redeem(r, redeemed.qr_payload, now).ok;
    assert _claim(saved.code, "stock-held-student", now).ok;
    o = _owned_offer(r, saved.code) as Offer;
    o.quantity = 1;  # Simulate an older/imported inconsistent catalog value.
    rejected = _save_offer(r, saved.code, "Edited stock", "Lunch", "5", "7",
        "2026-09-26 10:00", "2026-09-26 16:00", "1", "Student ID",
        "One per student", "", "", now);
    assert not rejected.ok and "2 already claimed or redeemed" in rejected.message;
    assert o.title == "Reconciled stock";
}


test "failed mutation releases its lock without committing an abandoned draft" {
    _ensure_seed();
    commit();
    abandoned_id = "";
    fd = _lock();
    try {
        try {
            r = _restaurant_by_slug("arbor-leaf-kitchen");
            abandoned = Offer(title="Abandoned mutation", qr_ready=True, quantity=1);
            r +>:Publishes():+> abandoned;
            abandoned_id = jid(abandoned);
            raise ValueError("Simulated request failure before completion");
        } finally {
            _unlock(fd);
        }
    } except ValueError {
        # This is the served runtime's exception lifecycle: discard the failed
        # attempt before retrying. Cleanup must not have committed it already.
        Jac.get_context().mem.abort();
    }
    assert _find_offer(abandoned_id) is None;
    next_fd = _lock();
    _unlock(next_fd);
}


def _raise_lock_test_error() {
    raise ValueError("Simulated refresh failure while acquiring mutation lock");
}


def _hold_limit_fixture(slug: str, now: float) -> list[Offer] {
    restaurant = Restaurant(slug=slug, name="Hold limit fixture", source="manual");
    root.shared ++> restaurant;
    offers: list[Offer] = [];
    for number in range(3) {
        offer = Offer(title=f"Limit offer {number}", start_ts=now - 60,
            end_ts=now + 3600, quantity=5, qr_ready=True, terms="Original promise");
        restaurant +>:Publishes():+> offer;
        offers.append(offer);
    }
    return offers;
}


test "sample restaurant cannot expose an unmarked offer through list detail or claim" {
    now = time.time();
    offers = _hold_limit_fixture("sample-parent-projection", now);
    restaurant = _restaurant_of(offers[0]) as Restaurant;
    restaurant.is_demo = True;
    assert not offers[0].is_demo;
    with patch.dict(os.environ, {"MLOCAL_SHOW_SAMPLES": "0", "MLOCAL_DEMO_MODE": ""}) {
        assert jid(offers[0]) not in [view.id for view in list_offers()];
        assert get_offer(jid(offers[0])) is None;
        blocked = _claim(jid(offers[0]), "sample-parent-student", now);
        assert not blocked.ok and "not available" in blocked.message;
        assert _remaining(offers[0], now) == 5;
    }
}


test "sample restaurant labels an unmarked offer without rewriting stored flags" {
    now = time.time();
    offers = _hold_limit_fixture("sample-parent-label", now);
    restaurant = _restaurant_of(offers[0]) as Restaurant;
    restaurant.is_demo = True;
    assert _view(offers[0], now).is_demo;
    assert not offers[0].is_demo;
}


test "samples off preserves a legitimate owner's paused claim and original snapshot" {
    now = time.time();
    offers = _hold_limit_fixture("legitimate-saved-no-samples", now);
    held = _claim(jid(offers[0]), "legitimate-saved-student", now);
    assert held.ok;
    offers[0].status = "paused";
    offers[0].terms = "Changed terms";
    with patch.dict(os.environ, {"MLOCAL_SHOW_SAMPLES": "0", "MLOCAL_DEMO_MODE": ""}) {
        with patch.dict(get_offer.__globals__, {"_actor_id": lambda () -> str { return "legitimate-saved-student"; }}) {
            view = get_offer(jid(offers[0])) as OfferView;
            assert view.my_status == "claimed" and view.my_qr_payload == held.qr_payload;
            assert view.my_terms == "Original promise";
            assert jid(offers[0]) in [item.id for item in list_offers()];
        }
    }
}


test "student active holds are capped across offers while retry retains the same claim" {
    now = time.time();
    offers = _hold_limit_fixture("hold-limit-cap", now);
    first = _claim(jid(offers[0]), "hold-limit-cap-student", now);
    second = _claim(jid(offers[1]), "hold-limit-cap-student", now);
    assert first.ok and second.ok;
    rejected = _claim(jid(offers[2]), "hold-limit-cap-student", now);
    assert not rejected.ok and "2 active holds" in rejected.message;
    assert _remaining(offers[2], now) == 5;
    retry = _claim(jid(offers[0]), "hold-limit-cap-student", now);
    assert retry.ok and retry.claim_id == first.claim_id and retry.qr_payload == first.qr_payload;
    assert _claim(jid(offers[2]), "hold-limit-other-student", now).ok;
}


test "cancellation expiry and redemption immediately free the student hold slot" {
    now = time.time();
    offers = _hold_limit_fixture("hold-limit-release", now);
    offers[1].end_ts = now + 10;
    first = _claim(jid(offers[0]), "hold-limit-release-student", now);
    second = _claim(jid(offers[1]), "hold-limit-release-student", now);
    assert first.ok and second.ok;
    assert not _claim(jid(offers[2]), "hold-limit-release-student", now).ok;
    assert _cancel(jid(offers[0]), "hold-limit-release-student", now).ok;
    third = _claim(jid(offers[2]), "hold-limit-release-student", now);
    assert third.ok;
    # At the exact deadline the second hold no longer occupies a slot.
    replaced = _claim(jid(offers[0]), "hold-limit-release-student", now + 10);
    assert replaced.ok and replaced.claim_id != first.claim_id;
    restaurant = _restaurant_of(offers[0]) as Restaurant;
    assert _redeem(restaurant, replaced.qr_payload, now + 10).ok;
    assert _cancel(jid(offers[2]), "hold-limit-release-student", now + 10).ok;
    offers[1].end_ts = now + 3600;
    assert _claim(jid(offers[1]), "hold-limit-release-student", now + 10).ok;
    preserved = _find_claim(restaurant, replaced.qr_payload) as Redemption;
    assert preserved.status == "redeemed" and preserved.terms_snapshot == "Original promise";
}


test "hold limit rollout preserves every pre-existing claim above the cap" {
    now = time.time();
    offers = _hold_limit_fixture("hold-limit-existing", now);
    preserved: list[ActionResult] = [];
    with patch.dict(_claim.__globals__, {"MAX_ACTIVE_HOLDS": 10}) {
        for offer in offers {
            held = _claim(jid(offer), "hold-limit-existing-student", now);
            assert held.ok;
            preserved.append(held);
        }
    }
    for number in range(3) {
        retry = _claim(jid(offers[number]), "hold-limit-existing-student", now);
        assert retry.ok and retry.claim_id == preserved[number].claim_id;
        assert retry.qr_payload == preserved[number].qr_payload;
        restaurant = _restaurant_of(offers[number]) as Restaurant;
        claim = _find_claim(restaurant, retry.qr_payload) as Redemption;
        assert claim.status == "claimed" and claim.terms_snapshot == "Original promise";
    }
}


test "lock refresh failure closes the file descriptor" {
    fd = os.open(mutation_lock_path(), os.O_CREAT | os.O_RDWR, 384);
    closed = False;
    try {
        with patch("os.open", return_value=fd) {
            with patch.dict(_lock.__globals__, {"commit": _raise_lock_test_error}) {
                try { _lock(); } except ValueError {}
            }
        }
        try { _ = os.fstat(fd); } except OSError { closed = True; }
        assert closed, "Failed lock acquisition must not leak its descriptor";
    } finally {
        if not closed { os.close(fd); }
    }
}
