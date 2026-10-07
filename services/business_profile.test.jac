"""Run only in the isolated test workspace supplied by scripts/test.sh."""

import uuid;
import os;
import tempfile;
import from unittest.mock { patch }
import from services.models { Location, HasLocation, Offer, Redemption, ClaimedAs }
import from services.session { current_session }
import from services.promo { _claim, list_offers, get_offer }
import from services.foryou { _home, DEMO_MODE_ENV }


def _profile_fixture(name: str = "Same public name") -> Restaurant {
    r = Restaurant(slug="profile-" + uuid.uuid4().hex, name=name, cuisine="Cafe",
        blurb="Lunch around the corner", merchant_key="never-public-merchant-secret",
        owner_actor_id="never-public-owner-root", source="test-fixture");
    root.shared ++> r;
    r +>:HasLocation():+> Location(address="123 Example Street", neighborhood="Kerrytown",
        entrance_note="Use the north entrance", note_date="2026-09-27");
    return r;
}


def _profile_offer(r: Restaurant, title: str, now: float, status: str = "active",
    starts_in: float = -60.0, ends_in: float = 3600.0, quantity: int = 3) -> Offer {
    o = Offer(title=title, description="Fixture offer", price=7.0, price_cents=700,
        regular_price=9.0, regular_price_cents=900, start_ts=now + starts_in,
        end_ts=now + ends_in, quantity=quantity, qr_ready=True, status=status,
        eligibility="Student ID", terms="Public terms", dietary=["vegetarian"]);
    r +>:Publishes():+> o;
    return o;
}


test "profile lookup uses exact slug or graph offer association never display name" {
    now = time.time();
    first = _profile_fixture();
    second = _profile_fixture();
    first_offer = _profile_offer(first, "First lunch", now);
    second_offer = _profile_offer(second, "Second lunch", now);
    by_slug = _public_business("  " + first.slug + "  ", "", now);
    assert by_slug.ok and by_slug.slug == first.slug and by_slug.name == first.name;
    assert [o.id for o in by_slug.offers] == [jid(first_offer)];
    by_offer = _public_business("", jid(second_offer), now);
    assert by_offer.ok and by_offer.slug == second.slug;
    assert [o.id for o in by_offer.offers] == [jid(second_offer)];
    assert not _public_business(first.name, "", now).ok;
    assert _public_business(first.slug, jid(second_offer), now).slug == first.slug;
    assert not _public_business("no-such-business", jid(second_offer), now).ok;
}

test "legacy self-service profile stays hidden until private approval and activation" {
    r = _profile_fixture();
    r.source = "business_signup";
    now = time.time();
    o = _profile_offer(r, "Unapproved legacy lunch", now);
    assert not _public_business(r.slug, "", now).ok;
    assert not _claim(jid(o), jid(root), now).ok;
    assert not [v for v in list_offers() if v.id == jid(o)];
    assert not [item for item in _home("", "", "any", "", now).items if item.offer.id == jid(o)];
    o +>:ClaimedAs():+> Redemption(actor_id=jid(root), restaurant_slug=r.slug,
        qr_payload="legacy-held-qr", status="claimed", claimed_ts=now, expires_ts=now + 1200);
    assert [item for item in _home(jid(root), "", "any", "", now).items if item.offer.id == jid(o)];
    with patch.dict(list_offers.__globals__, {"_actor_id": lambda () -> str { return jid(root); }}) {
        held = [v for v in list_offers() if v.id == jid(o)];
        assert len(held) == 1 and held[0].my_qr_payload == "legacy-held-qr";
    }
    with patch.dict(get_offer.__globals__, {"_actor_id": lambda () -> str { return jid(root); }}) {
        assert (get_offer(jid(o)) as OfferView).my_qr_payload == "legacy-held-qr";
    }
    assert not [item for item in _home("", "", "any", "", now).items if item.offer.id == jid(o)];
}


test "business offers exclude drafts paused expired and unknown statuses" {
    now = time.time();
    r = _profile_fixture();
    _profile_offer(r, "Available", now);
    _profile_offer(r, "Coming soon", now, starts_in=600.0);
    _profile_offer(r, "Sold out", now, quantity=0);
    _profile_offer(r, "Paused", now, status="paused");
    _profile_offer(r, "Draft", now, status="draft");
    _profile_offer(r, "Unknown status", now, status="unpublished");
    _profile_offer(r, "Ended", now, ends_in=-1.0);
    _profile_offer(r, "At the deadline", now, ends_in=0.0);
    v = _public_business(r.slug, "", now);
    assert v.ok;
    assert sorted([o.title for o in v.offers]) == ["Available", "Coming soon", "Sold out"];
    assert [o.state for o in v.offers if o.title == "Coming soon"] == ["scheduled"];
    assert [o.state for o in v.offers if o.title == "Sold out"] == ["sold out"];
}

test "saved QR survives offer pause or early end only until the claim expires" {
    now = time.time();
    for state in ["paused", "ended"] {
        r = _profile_fixture();
        o = _profile_offer(r, "Held lunch " + state, now);
        held = _claim(jid(o), jid(root), now);
        assert held.ok, held.message;
        c = [o ->:ClaimedAs:->][0];
        if state == "paused" { o.status = "paused"; }
        else { o.end_ts = now - 1; }
        mine = [item.offer for item in _home(jid(root), "", "any", "", now).items if item.offer.id == jid(o)];
        assert len(mine) == 1 and mine[0].my_qr_payload == held.qr_payload;
        assert not [item for item in _home("", "", "any", "", now).items if item.offer.id == jid(o)];
        with patch.dict(list_offers.__globals__, {"_actor_id": lambda () -> str { return jid(root); }}) {
            with patch.dict(get_offer.__globals__, {"_actor_id": lambda () -> str { return jid(root); }}) {
                assert [v for v in list_offers() if v.id == jid(o)];
                assert (get_offer(jid(o)) as OfferView).my_qr_payload == held.qr_payload;
                c.expires_ts = now - 1;
                assert not [item for item in _home(jid(root), "", "any", "", now).items if item.offer.id == jid(o)];
                assert not [v for v in list_offers() if v.id == jid(o)];
                assert get_offer(jid(o)) is None;
                c.expires_ts = now + 1200;
                c.status = "redeemed";
                assert not [item for item in _home(jid(root), "", "any", "", now).items if item.offer.id == jid(o)];
                assert not [v for v in list_offers() if v.id == jid(o)];
                assert get_offer(jid(o)) is None;
            }
        }
    }
}


test "profile projects public fields without ownership or claim credentials" {
    now = time.time();
    r = _profile_fixture("Public cafe");
    r.image_url = "https://images.example.test/cafe.png";
    o = _profile_offer(r, "Public lunch", now);
    o +>:ClaimedAs():+> Redemption(actor_id=jid(root),
        restaurant_slug=r.slug, qr_payload="private-qr-credential", code="legacy-secret",
        offer_title_snapshot="Private held title", terms_snapshot="Private snapshot terms",
        claimed_ts=now, expires_ts=now + 1200);
    # Prove this caller can read its credential through the existing detail
    # projection, then prove the profile endpoint still omits that credential.
    assert _view(o, now, jid(root)).my_qr_payload == "private-qr-credential";
    with patch.dict(get_business_profile.__globals__, {"_actor_id": lambda () -> str { return jid(root); }}) {
        v = get_business_profile(r.slug);
    }
    assert v.ok and v.cuisine == "Cafe" and v.blurb == "Lunch around the corner";
    assert getattr(v, "image_url", "") == r.image_url;
    assert v.address == "123 Example Street" and v.neighborhood == "Kerrytown";
    assert v.entrance_note == "Use the north entrance" and v.note_date == "2026-09-27" and not v.is_demo;
    for private_field in ["owner_actor_id", "merchant_key", "claims", "source"] {
        assert not hasattr(v, private_field);
    }
    offer = v.offers[0];
    assert offer.my_qr_payload == "" and offer.my_claim_id == "" and offer.my_status == "";
    assert offer.my_title == "" and offer.my_terms == "" and offer.my_expires_ts == 0.0;
    assert offer.my_eligibility == "" and offer.my_expires == "" and offer.my_price_cents == 0;
    for private_field in ["actor_id", "qr_payload", "code", "owner_actor_id", "merchant_key"] {
        assert not hasattr(offer, private_field);
    }
    assert offer.price == 7.0 and offer.terms == "Public terms" and offer.dietary == ["vegetarian"];
}


test "demo mode gates sample businesses and offers for both lookup paths" {
    now = time.time();
    demo = _profile_fixture("Sample cafe");
    demo.is_demo = True;
    demo_offer = _profile_offer(demo, "Sample lunch", now);
    demo_offer.is_demo = True;
    unmarked = _profile_offer(demo, "Unmarked offer at sample parent", now);
    real = _profile_fixture("Real cafe");
    regular = _profile_offer(real, "Regular lunch", now);
    sample = _profile_offer(real, "Sample at real cafe", now);
    sample.is_demo = True;
    with patch.dict(os.environ, {DEMO_MODE_ENV: "0"}) {
        assert not _public_business(demo.slug, "", now).ok;
        assert not _public_business("", jid(demo_offer), now).ok;
        assert not _public_business("", jid(sample), now).ok;
        visible = _public_business(real.slug, "", now);
        assert visible.ok and [o.id for o in visible.offers] == [jid(regular)];
    }
    with patch.dict(os.environ, {DEMO_MODE_ENV: "1"}) {
        assert _public_business(demo.slug, "", now).is_demo;
        assert _public_business("", jid(demo_offer), now).ok;
        assert _public_business("", jid(sample), now).ok;
        assert len(_public_business(real.slug, "", now).offers) == 2;
    }
    with patch.dict(os.environ, {DEMO_MODE_ENV: "0", "MLOCAL_HOSTED_DATASET": "1"}) {
        assert not _public_business(demo.slug, "", now).ok;
        assert not _public_business("", jid(demo_offer), now).ok;
        assert not _public_business("", jid(unmarked), now).ok;
    }
}


test "registered business without location or published offers still has a profile" {
    r = Restaurant(slug="empty-profile-" + uuid.uuid4().hex, name="Just opened");
    root.shared ++> r;
    v = _public_business(r.slug, "", time.time());
    assert v.ok and v.name == "Just opened" and v.offers == [];
    assert v.address == "" and v.neighborhood == "" and v.entrance_note == "";
}


test "missing or invalid identifiers return a safe empty result" {
    for (slug, offer_id) in [("", ""), (" ", " "), ("missing", ""), ("", "not-a-uuid")] {
        v = _public_business(slug, offer_id, time.time());
        assert not v.ok and v.message != "" and v.offers == [];
        assert v.slug == "" and v.name == "" and v.address == "";
    }
}


test "anonymous business lookup exposes the sanitized public projection only" {
    r = _profile_fixture();
    o = _profile_offer(r, "Guest lunch", time.time());
    with patch.dict(get_business_profile.__globals__, {"_actor_id": lambda () -> str { return ""; }}) {
        v = get_business_profile(r.slug);
        assert v.ok and v.slug == r.slug;
        assert not hasattr(v, "owner_actor_id") and not hasattr(v, "merchant_key");
        assert [item.id for item in v.offers] == [jid(o)];
        assert v.offers[0].my_qr_payload == "" and v.offers[0].my_claim_id == "";
        assert not get_business_profile().ok;
    }
}


test "signed in readers receive the public projection without account authority" {
    r = _profile_fixture();
    for actor in ["a-student-root", "a-business-root"] {
        with patch.dict(get_business_profile.__globals__, {"_actor_id": lambda () -> str { return actor; }}) {
            v = get_business_profile(r.slug);
            assert v.ok and v.slug == r.slug and not hasattr(v, "owner_actor_id");
        }
    }
}


test "merchant preview resolves owned restaurant without mistaking graph id for slug" {
    r = _profile_fixture("New merchant cafe");
    actor = uuid.uuid4().hex;
    with tempfile.TemporaryDirectory() as directory {
        with patch.dict(os.environ, {"MLOCAL_ONBOARDING_DIR": directory,
            "MLOCAL_MERCHANT_OWNERS": '{"' + r.slug + '":"' + actor + '"}'}) {
            with patch.dict(current_session.__globals__, {"_actor_id": lambda () -> str { return actor; }}) {
                session = current_session();
                assert session.role == "merchant" and session.restaurant_id == jid(r);
                assert session.restaurant_id != r.slug;
            }
            with patch.dict(get_business_profile.__globals__, {"_actor_id": lambda () -> str { return actor; }}) {
                preview = get_business_profile();
                assert preview.ok and preview.slug == r.slug and preview.name == r.name;
                assert preview.offers == [];
                assert not get_business_profile(session.restaurant_id).ok;
            }
            with patch.dict(get_business_profile.__globals__, {"_actor_id": lambda () -> str { return uuid.uuid4().hex; }}) {
                missing = get_business_profile();
                assert not missing.ok and missing.slug == "" and missing.offers == [];
            }
        }
    }
}
