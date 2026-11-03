"""For you ranking checks. Run: jac test services/taste.jac"""

def _deal(
    oid: str, place: str, cats: list[str], price: int = 700, regular: int = 1000,
    dietary: list[str] = [], remaining: int = 10, hours: float = 5.0, rotation: int = 0
) -> Candidate {
    return Candidate(
        offer_id=oid, place=place, title=oid, categories=cats, dietary=dietary,
        price_cents=price, regular_cents=regular, remaining=remaining,
        ends_in_hours=hours, rotation=rotation
    );
}


def _menu -> list[Candidate] {
    return [
        _deal("noodle-1", "noodle-lab", ["noodles"], 700, 1150, ["vegetarian"]),
        _deal("pizza-1", "dough-co", ["pizza"], 500, 850, ["halal"]),
        _deal("bowl-1", "leaf-kitchen", ["bowls", "salads"], 800, 1200, ["vegetarian", "vegan", "gluten-free"]),
        _deal("latte-1", "leaf-kitchen", ["coffee"], 300, 500, ["vegetarian", "vegan"]),
        _deal("taco-1", "taco-window", ["tacos"], 900, 1300, []),
        _deal("cone-1", "creamery", ["dessert"], 300, 500, ["vegetarian"]),
        _deal("bbq-1", "smokehouse", ["bbq"], 1400, 1800, []),
        _deal("sushi-1", "maki-stop", ["sushi"], 1200, 1500, ["gluten-free"])
    ];
}


def _ids(feed: list[Ranked]) -> list[str] {
    return [r.candidate.offer_id for r in feed];
}


test "cuisine text maps to categories" {
    assert categories_for("Noodles and dumplings") == ["noodles"];
    assert categories_for("Pizza by the slice") == ["pizza"];
    assert categories_for("Plant-based bowls") == ["bowls", "salads"];
    assert categories_for("Cafe", "Oat Latte") == ["coffee"];
    assert categories_for("Mystery food") == [];
    assert categories_for("Subway station snacks") == [];
}


test "price ranges cover every price exactly once" {
    assert price_range_of(0) == "under5" and price_range_of(499) == "under5";
    assert price_range_of(500) == "5to8" and price_range_of(800) == "5to8";
    assert price_range_of(801) == "8to12" and price_range_of(1200) == "8to12";
    assert price_range_of(1201) == "12plus" and price_range_of(9900) == "12plus";
    assert price_range_label("5to8") == "$5 to $8" and price_range_label("nope") == "";
}


test "choices are cleaned to known values" {
    assert clean_choices(["Pizza", " noodles ", "pizza", "lasers"], CATEGORIES) == ["noodles", "pizza"];
    assert clean_choices(["VEGAN", "keto"], DIETS) == ["vegan"];
    assert clean_choices([], DIETS) == [];
}


test "place labels say whether everything or only some items qualify" {
    assert place_labels([["vegetarian", "vegan"], ["vegetarian"]]) == ["Vegetarian", "Vegan options"];
    assert place_labels([["halal"], []]) == ["Halal options"];
    assert place_labels([["vegan", "gluten-free"], ["vegan"]]) == ["Vegetarian", "Vegan", "Gluten-free options"];
    assert with_implied(["vegan"]) == ["vegan", "vegetarian"] and with_implied(["halal"]) == ["halal"];
    veg = score(Candidate(offer_id="x", place="p", categories=["bowls"], dietary=["vegan"]), Taste(diets=["vegetarian"]));
    assert "Not marked vegetarian" not in veg.reasons and "Vegetarian" in veg.reasons;
    assert place_labels([[], []]) == [];
    assert place_labels([]) == [];
}


test "learned interest weighs the action and fades with age" {
    fresh = Taste(history=[Signal(category="pizza", action="redeem", age_days=0.0)]);
    old = Taste(history=[Signal(category="pizza", action="redeem", age_days=14.0)]);
    claim = Taste(history=[Signal(category="pizza", action="claim", age_days=0.0)]);
    assert affinity(fresh, "pizza") == 3.0;
    assert affinity(old, "pizza") == 1.5;
    assert affinity(claim, "pizza") == 2.0;
    assert affinity(fresh, "tacos") == 0.0;
    many = Taste(history=[Signal(category="pizza", action="redeem", age_days=0.0) for i in range(10)]);
    assert affinity(many, "pizza") == 3.0;
}


test "preferences reorder but never hide a deal" {
    menu = _menu();
    for taste in [
        Taste(),
        Taste(categories=["noodles"]),
        Taste(categories=["noodles", "pizza"], diets=["vegan"], price_range="under5"),
        Taste(diets=["halal"]),
        Taste(favorites=["smokehouse"]),
        Taste(history=[Signal(category="tacos", action="redeem", age_days=1.0)])
    ] {
        feed = build_feed(_menu(), taste, "viewer");
        assert sorted(_ids(feed)) == sorted([c.offer_id for c in menu]);
        assert len(set(_ids(feed))) == len(menu);
    }
}


test "stated categories lead and the fourth slot is something different" {
    feed = build_feed(_menu(), Taste(categories=["noodles", "pizza", "tacos", "sushi"]), "viewer");
    assert [r.slot for r in feed[:4]] == ["match", "match", "match", "explore"];
    assert sorted(_ids(feed[:3])) == ["noodle-1", "pizza-1", "taco-1"] or "sushi-1" in _ids(feed[:3]);
    assert all([r.candidate.categories[0] in ["noodles", "pizza", "tacos", "sushi"] for r in feed[:3]]);
    assert feed[3].candidate.categories[0] not in ["noodles", "pizza", "tacos", "sushi"];
    assert feed[3].reasons[0] == "Something different";
    assert "You like" in feed[0].reasons[0];
}


test "favorites are pinned first, two places at most" {
    taste = Taste(categories=["noodles"], favorites=["smokehouse", "maki-stop", "creamery"]);
    feed = build_feed(_menu(), taste, "viewer");
    assert [r.slot for r in feed[:2]] == ["favorite", "favorite"];
    assert all([r.candidate.place in taste.favorites for r in feed[:2]]);
    assert "A favorite of yours" in feed[0].reasons;
    assert len([r for r in feed if r.slot == "favorite"]) == 2;
}


test "dietary needs lower a deal and label it, without removing it" {
    feed = build_feed(_menu(), Taste(categories=["noodles", "bbq", "tacos"], diets=["vegetarian"]), "viewer");
    assert feed[0].candidate.offer_id == "noodle-1";
    assert "Vegetarian" in feed[0].reasons;
    bbq = [r for r in feed if r.candidate.offer_id == "bbq-1"][0];
    assert not bbq.matched and "Not marked vegetarian" in bbq.reasons;
    assert "bbq-1" in _ids(feed);    fan = build_feed(_menu(), Taste(categories=["noodles"], diets=["vegetarian"], favorites=["smokehouse"]), "viewer");
    assert fan[0].slot == "favorite" and fan[0].candidate.offer_id == "bbq-1";
    assert "Not marked vegetarian" in fan[0].reasons;
    assert all([not [d for d in ["vegetarian"] if d not in r.candidate.dietary] for r in fan if r.slot == "match"]);
}


test "price range favors deals inside it" {
    taste = Taste(categories=["coffee", "dessert", "bbq", "sushi"], price_range="under5");
    feed = build_feed(_menu(), taste, "viewer");
    assert sorted(_ids(feed[:2])) == ["cone-1", "latte-1"];
    assert "In your price range" in feed[0].reasons;
    pricey = [r for r in feed if r.candidate.offer_id == "bbq-1"][0];
    assert pricey.score < feed[0].score;
}


test "history alone personalizes the feed" {
    taste = Taste(history=[
        Signal(category="tacos", action="redeem", age_days=2.0),
        Signal(category="tacos", action="claim", age_days=5.0)
    ]);
    feed = build_feed(_menu(), taste, "viewer");
    assert feed[0].candidate.offer_id == "taco-1";
    assert feed[0].reasons[0] == "Like places you have tried";
}


test "with nothing known, equal deals take turns between viewers" {
    same = [_deal(f"deal-{i}", f"place-{i}", ["pizza"], 700, 1000) for i in range(12)];
    firsts = set([build_feed([_deal(c.offer_id, c.place, c.categories, 700, 1000) for c in same], Taste(), f"viewer-{v}")[0].candidate.offer_id for v in range(30)]);
    assert len(firsts) >= 6, firsts;
    again = build_feed([_deal(c.offer_id, c.place, c.categories, 700, 1000) for c in same], Taste(), "viewer-1");
    repeat = build_feed([_deal(c.offer_id, c.place, c.categories, 700, 1000) for c in same], Taste(), "viewer-1");
    assert _ids(again) == _ids(repeat);
}


test "urgent deals say so" {
    soon = score(_deal("a", "p", ["pizza"], hours=1.0), Taste());
    few = score(_deal("b", "p", ["pizza"], remaining=2), Taste());
    calm = score(_deal("c", "p", ["pizza"]), Taste());
    assert "Ending soon" in soon.reasons and "Almost gone" in few.reasons;
    assert calm.reasons == [] and soon.score > calm.score;
    later = score(Candidate(offer_id="d", place="p", categories=["pizza"], price_cents=700, regular_cents=1000, remaining=10, starts_in_hours=3.0, ends_in_hours=6.0), Taste());
    assert "Starts later" in later.reasons and later.score < calm.score;
}


test "sold-out deals get no urgency label or boost" {
    gone = score(_deal("a", "p", ["pizza"], remaining=0), Taste());
    gone_soon = score(_deal("b", "p", ["pizza"], hours=1.0, remaining=0), Taste());
    calm = score(_deal("c", "p", ["pizza"]), Taste());
    assert "Almost gone" not in gone.reasons and "Ending soon" not in gone_soon.reasons;
    assert gone.score == calm.score and gone_soon.score == calm.score;
}


test "when matches run out, the rest follows by fit, not by chance" {
    taste = Taste(categories=["sushi"], diets=["vegetarian"], price_range="under5");
    menu = [
        _deal("fit-both", "a", ["coffee"], 300, 500, ["vegetarian"], rotation=900),
        _deal("fit-diet", "b", ["bowls"], 900, 1200, ["vegetarian"], rotation=500),
        _deal("fit-none", "c", ["bbq"], 1400, 1800, [], rotation=1),
        _deal("match", "d", ["sushi"], 400, 600, ["vegetarian"], rotation=700)
    ];
    feed = build_feed(menu, taste);
    assert _ids(feed) == ["match", "fit-both", "fit-diet", "fit-none"], _ids(feed);
    assert [r.slot for r in feed] == ["match", "more", "more", "explore"];
    many = menu + [_deal(f"extra-{i}", f"e{i}", ["bbq"], 1500, 1900, [], rotation=i + 2) for i in range(6)];
    long = build_feed(many, taste);
    assert _ids(long)[:3] == ["match", "fit-both", "fit-diet"];
    assert [r.slot for r in long][3] == "explore" and [r.slot for r in long][7] == "explore";
    assert long[3].candidate.offer_id == "fit-none";
    assert len(set(_ids(long))) == len(many);
}
# The pre-optimization ordering loop, kept verbatim as a reference.
def _legacy_build_feed(
    candidates: list[Candidate], taste: Taste, salt: str, explore_every: int
) -> list[Ranked] {
    if salt {
        for c in candidates {
            c.rotation = rotation_for(salt, c.offer_id);
        }
    }
    ranked = [score(c, taste) for c in candidates];
    if not has_preferences(taste) {
        return _by_band(ranked);
    }
    matches = _by_score([r for r in ranked if r.matched]);
    others = _by_exposure([r for r in ranked if not r.matched]);
    if not matches and not [r for r in ranked if r.candidate.place in taste.favorites] {
        return _by_band(ranked);
    }
    feed: list[Ranked] = [];
    pinned_places: list[str] = [];
    for r in _by_score(ranked) {
        place = r.candidate.place;
        if len(pinned_places) < PINNED_FAVORITES and place in taste.favorites and place not in pinned_places {
            pinned_places.append(place);
            r.slot = "favorite";
            feed.append(r);
        }
    }
    matches = [r for r in matches if r.slot != "favorite"];
    others = [r for r in others if r.slot != "favorite"];
    # Two orders over the same leftovers: least-shown first for the exploration
    # slots, best fit first for everything else once the matches run out.
    by_fit = _by_band(others);
    used: list[str] = [];
    while matches or len(used) < len(others) {
        position = len(feed) + 1;
        explore_turn = explore_every > 0 and position % explore_every == 0;
        left = [r for r in others if r.candidate.offer_id not in used];
        if left and explore_turn {
            pick = left[0];
            pick.slot = "explore";
            pick.reasons = ["Something different"] + pick.reasons;
            used.append(pick.candidate.offer_id);
            feed.append(pick);
        } elif matches {
            pick = matches.pop(0);
            pick.slot = "match";
            feed.append(pick);
        } else {
            pick = [r for r in by_fit if r.candidate.offer_id not in used][0];
            pick.slot = "more";
            used.append(pick.candidate.offer_id);
            feed.append(pick);
        }
    }
    return feed;
}


def _fingerprint(feed: list[Ranked]) -> list[tuple[str, str, list[str]]] {
    return [(r.candidate.offer_id, r.slot, list(r.reasons)) for r in feed];
}


test "linear feed ordering picks exactly what the original loop picked" {
    import random;
    cats = ["pizza", "coffee", "sushi", "bowls", "tacos", "dessert"];
    diets = ["vegetarian", "vegan", "gluten-free", "halal"];
    for seed in range(300) {
        rng = random.Random(seed);
        n = rng.randint(0, 60);
        def make() -> list[Candidate] {
            r2 = random.Random(seed * 7919);
            out: list[Candidate] = [];
            for i in range(n) {
                out.append(Candidate(
                    offer_id=f"o{i}", place=f"p{r2.randint(0, 12)}", title=f"t{i}",
                    categories=r2.sample(cats, r2.randint(0, 2)),
                    dietary=r2.sample(diets, r2.randint(0, 2)),
                    price_cents=r2.randint(200, 1600), regular_cents=r2.randint(900, 2000),
                    remaining=r2.randint(0, 30), starts_in_hours=r2.choice([0.0, 0.0, 3.0]),
                    ends_in_hours=r2.choice([0.5, 1.5, 6.0, 48.0])
                ));
            }
            return out;
        }
        taste = Taste(
            categories=rng.sample(cats, rng.randint(0, 2)),
            diets=rng.sample(diets, rng.randint(0, 1)),
            price_range=rng.choice(["", "under5", "5to8"]),
            favorites=[f"p{rng.randint(0, 12)}" for _ in range(rng.randint(0, 3))],
            history=[Signal(category=rng.choice(cats), action=rng.choice(["claim", "redeem"]), age_days=rng.random() * 40)
                for _ in range(rng.randint(0, 4))]
        );
        every = rng.choice([EXPLORE_EVERY, 0, 1, 2, 3]);
        salt = f"viewer-{seed}";
        assert _fingerprint(build_feed(make(), taste, salt, every)) == _fingerprint(_legacy_build_feed(make(), taste, salt, every)), seed;
    }
}
