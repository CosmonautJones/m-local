"""Saved tastes, favorites and home feed checks. Run: jac test services/foryou.jac

Outside a served request there is one root, so the caller's identity is passed
to the internal helpers. Privacy between real accounts is checked over HTTP."""

import from services.promo { _claim, _redeem, list_offers }
import from services.session { _merchant_for_actor }
import from unittest.mock { patch }
import from jaclang.data.serializer { Serializer }

def _reset -> TasteProfile {
    for p in [root -->[?:TasteProfile]] {
        for f in [p ->:Keeps:->] {
            del f;
        }
        del p;
    }
    fresh = _profile(True);
    assert fresh is not None;
    return fresh as TasteProfile;
}


def _titles(h: HomeView) -> list[str] {
    return [i.offer.title for i in h.items];
}


def _seeded(h: HomeView) -> list[str] {
    known = ["Lunch noodle bowl for $7", "Late-night dumplings, 2 for 1", "Harvest bowl for $8",
             "$3 oat latte study break", "Slice + drink for $5"];
    return sorted([t for t in _titles(h) if t in known]);
}


test "tastes are cleaned, saved and listed with every choice" {
    _ensure_seed();
    _reset();
    before = _taste_view(_profile(), True);
    assert not before.completed and before.categories == [];
    assert len(before.all_categories) == 14 and len(before.all_diets) == 4 and len(before.all_price_ranges) == 4;
    assert before.all_price_ranges[1].label == "$5 to $8";
    saved = _save_taste("Pizza, noodles , lasers,pizza", "VEGAN,keto", "5to8", time.time());
    assert saved.ok and saved.completed;
    assert saved.categories == ["noodles", "pizza"] and saved.diets == ["vegan"] and saved.price_range == "5to8";
    assert _save_taste("", "", "free", time.time()).price_range == "";
    cleared = _save_taste("", "", "", time.time());
    assert cleared.completed and cleared.categories == [] and cleared.diets == [];
}


test "favorites toggle on and off and unknown places are refused" {
    _ensure_seed();
    _reset();
    on = _toggle_favorite("arbor-leaf-kitchen", time.time());
    assert on.ok and on.favorites == ["arbor-leaf-kitchen"] and on.message == "Added to favorites.";
    two = _toggle_favorite("diag-dough-co", time.time() + 1);
    assert two.favorites == ["diag-dough-co", "arbor-leaf-kitchen"];
    off = _toggle_favorite("arbor-leaf-kitchen", time.time() + 2);
    assert off.ok and off.favorites == ["diag-dough-co"] and off.message == "Removed from favorites.";
    bad = _toggle_favorite("no-such-place", time.time());
    assert not bad.ok and bad.favorites == ["diag-dough-co"];
    assert not _toggle_favorite("", time.time()).ok;
}


test "a guest sees every live deal and no favorites" {
    _ensure_seed();
    _reset();
    h = _home("", "", "any", "", time.time());
    assert not h.signed_in and not h.personalized and h.favorites == [];
    assert _seeded(h) == sorted(["Lunch noodle bowl for $7", "Late-night dumplings, 2 for 1", "Harvest bowl for $8",
                                  "$3 oat latte study break", "Slice + drink for $5"]);
    assert "Weekend cheese slice deal" not in _titles(h);
    assert h.total_deals == len(h.items);
    assert all([i.slot == "more" for i in h.items]);
}


test "home place reuse matches every offer detail field" {
    _ensure_seed();
    _reset();
    now = time.time();
    for actor in ["", "feed-place-observer"] {
        home = _home(actor, "", "any", "", now);
        assert home.items;
        for item in home.items {
            offer = _find_offer(item.offer.id);
            assert offer is not None;
            assert Serializer.serialize(item.offer) == Serializer.serialize(_view(offer, now, actor));
        }
    }
}


test "saved tastes reorder the feed but every deal is still there" {
    _ensure_seed();
    _reset();
    guest = _home("", "", "any", "", time.time());
    _save_taste("pizza", "", "", time.time());
    h = _home("student-pizza", "", "any", "", time.time());
    assert h.signed_in and h.personalized and h.completed;
    assert h.items[0].offer.title == "Slice + drink for $5";
    assert h.items[0].slot == "match" and "You like pizza" in h.items[0].reasons;
    assert h.items[0].categories == ["pizza"];
    assert sorted(_titles(h)) == sorted(_titles(guest));
    assert len([i for i in h.items if i.slot != "match"]) >= 4;
}


test "cards carry food labels for the deal and the place" {
    _ensure_seed();
    _reset();
    h = _home("", "", "any", "", time.time());
    bowl = [i for i in h.items if i.offer.title == "Harvest bowl for $8"][0];
    assert "vegan" in bowl.offer.dietary and "gluten-free" in bowl.offer.dietary;
    assert bowl.place == "arbor-leaf-kitchen";
    assert bowl.place_labels == ["Vegetarian", "Vegan", "Gluten-free options"];
    slice = [i for i in h.items if i.offer.title == "Slice + drink for $5"][0];
    assert slice.place_labels == ["Vegetarian options", "Halal options"];
    assert bowl.price_range == "5to8" and slice.price_range == "5to8";
}


test "price range and diet filters narrow the page, tastes do not" {
    _ensure_seed();
    _reset();
    everything = _home("", "", "any", "", time.time());
    cheap = _home("", "under5", "any", "", time.time());
    assert cheap.price_range == "under5" and len(cheap.items) >= 1;
    assert all([i.price_cents < 500 for i in cheap.items]);
    assert "$3 oat latte study break" in _titles(cheap);
    assert cheap.total_deals == everything.total_deals;
    mid = _home("", "5to8", "any", "", time.time());
    assert all([i.price_cents >= 500 and i.price_cents <= 800 for i in mid.items]);
    assert _home("", "nonsense", "any", "", time.time()).price_range == "";
    veg = _home("", "", "any", "vegetarian", time.time());
    assert "Harvest bowl for $8" in _titles(veg) and "Slice + drink for $5" not in _titles(veg);
    now_only = _home("", "", "now", "", time.time());
    assert "Late-night dumplings, 2 for 1" not in _titles(now_only);
    empty = _home("", "12plus", "any", "halal", time.time());
    assert empty.items == [] and empty.note != "";
}


test "favorites fill the strip and lead the feed" {
    _ensure_seed();
    _reset();
    _toggle_favorite("maize-noodle-lab", time.time());
    h = _home("student-fan", "", "any", "", time.time());
    assert len(h.favorites) == 1;
    fav = h.favorites[0];
    assert fav.name == "Maize Street Noodle Lab" and fav.slug == "maize-noodle-lab";
    assert fav.cuisine == "Noodles and dumplings" and fav.neighborhood == "State Street";
    assert fav.live_offers == 1 and fav.best_offer_title == "Lunch noodle bowl for $7" and fav.best_price_cents == 700;
    assert fav.best_offer_id == h.items[0].offer.id;
    assert h.items[0].slot == "favorite" and h.items[0].is_favorite;
    assert not [i for i in h.items if i.place != "maize-noodle-lab" and i.is_favorite];
}


test "claims and redemptions teach the feed without any saved tastes" {
    _ensure_seed();
    _reset();
    now = time.time();
    actor = "student-learner";
    offer = [i for i in _home("", "", "any", "", now).items if i.offer.title == "$3 oat latte study break"][0];
    assert _history(actor, now) == [];
    assert _claim(offer.offer.id, actor, now).ok;
    signals = _history(actor, now + 60);
    assert [s.category for s in signals] == ["coffee"] and signals[0].action == "claim";
    h = _home(actor, "", "any", "", now + 60);
    assert h.personalized and not h.completed;
    assert h.items[0].offer.title == "$3 oat latte study break";
    assert _history("someone-else", now + 60) == [];
}


test "demo companies are added once, flagged demo and claimable" {
    _ensure_seed();
    _reset();
    assert demo_company_count("30") == 30 and demo_company_count(" 5 ") == 5;
    for bad in ["", "0", "-3", "many", "201"] {
        assert demo_company_count(bad) == 0, bad;
    }
    before = len([r for r in [root.shared -->[?:Restaurant]]]);
    added = _seed_demo_companies(12);
    again = _seed_demo_companies(12);
    made = [r for r in [root.shared -->[?:Restaurant]] if r.slug.startswith("sandbox-")];
    assert added + before == len([r for r in [root.shared -->[?:Restaurant]]]) and again == 0;
    assert len(made) == 12 and all([r.is_demo and r.name.endswith("(Demo)") for r in made]);
    h = _home("", "", "any", "", time.time());
    assert h.total_deals >= 5 + 12;
    sample = [i for i in h.items if i.place.startswith("sandbox-")][0];
    assert sample.categories != [] and sample.offer.state == "active" and sample.price_cents > 0;
    _save_taste(sample.categories[0], "", "", time.time());
    mine = _home("student-demo", "", "any", "", time.time());
    assert sample.categories[0] in mine.items[0].categories;
    assert len(mine.items) == len(h.items);
    assert [i for i in mine.items[:8] if i.slot == "explore"];
}


test "sample listings show only when the server turns demo mode on" {
    assert demo_mode("1") and demo_mode(" TRUE ") and demo_mode("on");
    for off in ["", "0", "false", "no", "maybe"] {
        assert not demo_mode(off), off;
    }
    _ensure_seed();
    assert _home("", "", "any", "", time.time()).show_samples == demo_mode(os.environ.get(DEMO_MODE_ENV, ""));
    with patch.dict(os.environ, {"MLOCAL_DEMO_MODE": ""}) {
        quiet = _home("", "", "any", "", time.time());
        assert not quiet.show_samples;
        assert not [i for i in quiet.items if i.offer.is_demo or "(Demo)" in i.offer.restaurant or i.offer.title == "$3 oat latte study break"];
        assert not [p for p in quiet.favorites if p.is_demo or "(Demo)" in p.name];
    }
}


test "production home omits a demo offer the caller has claimed or redeemed" {
    _ensure_seed();
    now = time.time();
    r = Restaurant(slug="hidden-demo-cafe", name="Hidden Demo Cafe", cuisine="Cafe", is_demo=True);
    root.shared ++> r;
    o = Offer(title="Hidden demo lunch", price=4.0, price_cents=400, regular_price_cents=600,
        start_ts=now - 60, end_ts=now + 3600, quantity=3, qr_ready=True, is_demo=True,
        terms="Demo terms", eligibility="Student ID");
    r +>:Publishes():+> o;
    oid = jid(o);
    actor = "hidden-demo-student";
    with patch.dict(os.environ, {"MLOCAL_DEMO_MODE": "1"}) {
        held = _claim(oid, actor, now);
        assert held.ok, held.message;
    }
    with patch.dict(os.environ, {"MLOCAL_DEMO_MODE": ""}) {
        quiet = _home(actor, "", "any", "", now);
        assert not [i for i in quiet.items if i.offer.id == oid or i.offer.is_demo or "(Demo)" in i.offer.restaurant];
        redeemed = _redeem(r, held.qr_payload, now);
        assert redeemed.ok, redeemed.message;
        after = _home(actor, "", "any", "", now);
        assert not [i for i in after.items if i.offer.id == oid or i.offer.is_demo];
    }
    o.status = "paused";
    o.end_ts = now - 30;
}

test "hosted dataset replaces starter fixture discovery without deleting starter records" {
    _ensure_seed();
    original = [jid(r) for r in [root.shared -->[?:Restaurant]] if r.source == "demo-seed"];
    with patch.dict(os.environ, {"MLOCAL_HOSTED_DATASET": "1"}) {
        home = _home("", "", "any", "", time.time());
        assert home.show_samples;
        assert not [item for item in home.items if item.offer.restaurant.endswith(" (Demo)")];
    }
    assert [jid(r) for r in [root.shared -->[?:Restaurant]] if r.source == "demo-seed"] == original;
}


def _claim_fixture(slug: str, now: float) -> Offer {
    r = Restaurant(slug=slug, name="Claim visibility cafe", cuisine="Cafe", source="test-fixture");
    root.shared ++> r;
    o = Offer(title="Saved lunch", price=7.0, price_cents=700, regular_price_cents=900,
        start_ts=now - 60, end_ts=now + 3600, quantity=3, qr_ready=True,
        terms="Original lunch terms", eligibility="Student ID");
    r +>:Publishes():+> o;
    return o;
}


def _listed_claim(actor: str, offer_id: str, now: float, budget: str = "", window: str = "any", diets: str = "") -> list[OfferView] {
    with patch.dict(list_offers.__globals__, {"_actor_id": lambda () -> str { return actor; }}) {
        with patch.object(time, "time", return_value=now) {
            return [v for v in list_offers(budget, window, diets) if v.id == offer_id];
        }
    }
}


test "home retains a real saved QR after pause or shortened offer end until hold expiry" {
    _ensure_seed();
    _reset();
    now = time.time();
    o = _claim_fixture("paused-claim-cafe", now);
    oid = jid(o);
    actor = "saved-claim-student";
    public = [i for i in _home("", "", "any", "", now).items if i.offer.id == oid];
    assert len(public) == 1 and not public[0].offer.is_demo;
    assert public[0].offer.my_qr_payload == "";
    result = _claim(oid, actor, now);
    assert result.ok;
    expires = _view(o, now, actor).my_expires_ts;
    for status in ["paused", "active"] {
        o.status = status;
        o.end_ts = now + 3600 if status == "paused" else now + 10;
        held = [i for i in _home(actor, "", "any", "", now + 20).items if i.offer.id == oid];
        assert len(held) == 1, "Saved QR disappeared after pause or shortened end";
        assert held[0].offer.my_qr_payload == result.qr_payload and not held[0].offer.is_demo;
        assert held[0].offer.my_terms == "Original lunch terms";
        assert len(_listed_claim(actor, oid, now + 20)) == 1;
        for stranger in ["", "unrelated-student"] {
            assert not [i for i in _home(stranger, "", "any", "", now + 20).items if i.offer.id == oid];
            assert _listed_claim(stranger, oid, now + 20) == [];
        }
        assert not [i for i in _home(actor, "", "any", "", expires).items if i.offer.id == oid];
        assert _listed_claim(actor, oid, expires) == [];
    }
}


test "home retains only the owner's live claim across price diet and time filters" {
    _ensure_seed();
    _reset();
    now = time.time();
    o = _claim_fixture("filtered-claim-cafe", now);
    oid = jid(o);
    actor = "filtered-claim-student";
    result = _claim(oid, actor, now);
    assert result.ok;
    expires = _view(o, now, actor).my_expires_ts;
    for (price, budget, window, diets, scheduled) in [
        ("under5", "4.99", "any", "", False),
        ("", "", "any", "vegan", False),
        ("", "", "now", "", True),
        ("", "", "today", "", True)
    ] {
        o.start_ts = now + 86400 if scheduled else now - 60;
        o.end_ts = now + 172800;
        held = [i for i in _home(actor, price, window, diets, now + 1).items if i.offer.id == oid];
        assert len(held) == 1, "Discovery filters hid a saved QR";
        assert held[0].offer.my_qr_payload == result.qr_payload and held[0].offer.my_status == "claimed";
        assert len(_listed_claim(actor, oid, now + 1, budget, window, diets)) == 1;
        for stranger in ["", "unrelated-student"] {
            assert not [i for i in _home(stranger, price, window, diets, now + 1).items if i.offer.id == oid];
            assert _listed_claim(stranger, oid, now + 1, budget, window, diets) == [];
        }
        assert not [i for i in _home(actor, price, window, diets, expires).items if i.offer.id == oid];
        assert _listed_claim(actor, oid, expires, budget, window, diets) == [];
    }
}
