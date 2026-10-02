"""Explicit verified-business saves activate one owned public restaurant."""
import tempfile;
import from jaclang { JacRuntime as Jac }
import from unittest.mock { patch }
import from services.models { Restaurant, HasLocation }
import from services.session { _merchant_for_actor }
import from services.qr_auth { merchant_owner }
import from services.onboarding_support { prepare_business_activation, finish_business_activation }


test "verified business save activates one restaurant and repeated saves update it" {
    actor = "aaad89b4d58d4c409f30362e5fb8a910";
    with tempfile.TemporaryDirectory() as directory {
        with patch.dict(os.environ, {"MLOCAL_ONBOARDING_DIR": directory, "MLOCAL_MERCHANT_OWNERS": "{}"}) {
            state = store();
            state.remember_account(actor, "owner@fixture.test", "business", "Owner");
            state.save_draft(actor, {"name": "Pending fixture", "address": "123 Test St", "status": "pending_review"});
            with patch.dict(save_business_draft.__globals__, {"_actor_id": lambda () -> str { return actor; }}) {
                assert get_business_draft().status == "pending_review";
                assert _merchant_for_actor(actor) is None;
                declined = save_business_draft("Fixture Cafe", "Cafe", "Lunch", "123 Test St", "", "Soup $5", "", "", False);
                assert not declined.ok and _merchant_for_actor(actor) is None;
                saved = save_business_draft("Fixture Cafe", "Cafe", "Lunch", "123 Test St", "", "Soup $5", "", "", True);
                assert saved.ok and saved.status == "active", saved.message;
                r = _merchant_for_actor(actor) as Restaurant;
                restaurant_id = jid(r);
                assert r.slug == "business-" + actor and r.name == "Fixture Cafe";
                assert not r.is_demo and r.blurb == "Lunch";
                locations = [r ->:HasLocation:->];
                assert len(locations) == 1 and locations[0].address == "123 Test St";
                updated = save_business_draft("Updated Cafe", "Bakery", "New description", "456 Test St", "", "Soup $6", "", "", True);
                assert updated.ok and updated.status == "active";
                again = _merchant_for_actor(actor) as Restaurant;
                assert jid(again) == restaurant_id and again.name == "Updated Cafe";
                assert len([r for r in [root.shared -->[?:Restaurant]] if r.slug == "business-" + actor]) == 1;
                updated_locations = [again ->:HasLocation:->];
                assert len(updated_locations) == 1 and updated_locations[0].address == "456 Test St";
                assert get_business_draft().menu_text == "Soup $6";
            }
        }
    }
}


test "student and unverified actors cannot activate business profiles" {
    with tempfile.TemporaryDirectory() as directory {
        with patch.dict(os.environ, {"MLOCAL_ONBOARDING_DIR": directory, "MLOCAL_MERCHANT_OWNERS": "{}"}) {
            store().remember_account("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "student@umich.edu", "student", "Student");
            for actor in ["", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "cccccccccccccccccccccccccccccccc"] {
                with patch.dict(save_business_draft.__globals__, {"_actor_id": lambda () -> str { return actor; }}) {
                    rejected = save_business_draft("Hijack", "", "", "123 Test St", "", "", "", "", True);
                    assert not rejected.ok;
                    assert _merchant_for_actor(actor) is None;
                }
            }
        }
    }
}


test "environment ownership stays authoritative over self-service registry" {
    actor = "dddddddddddddddddddddddddddddddd";
    replacement = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
    slug = "business-" + actor;
    with tempfile.TemporaryDirectory() as directory {
        with patch.dict(os.environ, {"MLOCAL_ONBOARDING_DIR": directory, "MLOCAL_MERCHANT_OWNERS": "{}"}) {
            store().remember_account(actor, "registry@fixture.test", "business", "Owner");
            raw = prepare_business_activation(actor, {"name": "Cafe", "address": "123 Test St"});
            _ = finish_business_activation(actor, raw);
            assert merchant_owner(slug) == actor;
            with patch.dict(os.environ, {"MLOCAL_MERCHANT_OWNERS": '{"' + slug + '":"' + replacement + '"}'}) {
                assert merchant_owner(slug) == replacement;
            }
            with patch.dict(os.environ, {"MLOCAL_MERCHANT_OWNERS": '{"provisioned-cafe":"' + actor + '"}'}) {
                assert merchant_owner("provisioned-cafe") == actor;
                assert merchant_owner(slug) == "";
            }
            assert merchant_owner("unregistered-restaurant") == "";
        }
    }
}


def _activation_store_failure(_actor: str, _fields: dict[str, str]) -> dict[str, str] {
    raise RuntimeError("Simulated private-store failure after graph commit");
}


test "activation retry recovers one committed restaurant without premature authority" {
    actor = "eead89b4d58d4c409f30362e5fb8a910";
    with tempfile.TemporaryDirectory() as directory {
        with patch.dict(os.environ, {"MLOCAL_ONBOARDING_DIR": directory, "MLOCAL_MERCHANT_OWNERS": "{}"}) {
            store().remember_account(actor, "recovery@fixture.test", "business", "Owner");
            with patch.dict(save_business_draft.__globals__, {"_actor_id": lambda () -> str { return actor; }}) {
                failed = False;
                with patch.dict(activate_business_listing.__globals__, {"finish_business_activation": _activation_store_failure}) {
                    try {
                        _ = save_business_draft("Recovery Cafe", "Cafe", "Lunch", "123 Test St", "", "Soup $5", "", "", True);
                    } except RuntimeError {
                        failed = True;
                        Jac.get_context().mem.abort();
                    }
                }
                assert failed and _merchant_for_actor(actor) is None;
                interrupted = [r for r in [root.shared -->[?:Restaurant]] if r.slug == "business-" + actor];
                assert len(interrupted) == 1;
                before_id = jid(interrupted[0]);
                assert len([interrupted[0] ->:HasLocation:->]) == 1;
                recovered = save_business_draft("Recovery Cafe", "Cafe", "Lunch", "123 Test St", "", "Soup $5", "", "", True);
                assert recovered.ok and recovered.status == "active";
                owned = _merchant_for_actor(actor) as Restaurant;
                assert jid(owned) == before_id;
                assert len([r for r in [root.shared -->[?:Restaurant]] if r.slug == "business-" + actor]) == 1;
                assert len([owned ->:HasLocation:->]) == 1;
            }
        }
    }
}


def _logo_page() -> str {
    return "<title>Page Cafe</title>"
        + "<meta property=\"og:image\" content=\"https://example.com/og.jpg\">"
        + "<script type=\"application/ld+json\">"
        + "{\"@type\":\"Restaurant\",\"name\":\"Page Cafe\",\"address\":\"123 Page St\","
        + "\"logo\":{\"@type\":\"ImageObject\",\"url\":\"https://example.com/logo.png\"},"
        + "\"image\":\"https://example.com/jsonld.jpg\"}"
        + "</script>"
        + "<img src=\"https://example.com/inline.jpg\">"
        + "<img src=\"http://localhost/secret.jpg\">"
        + "<a href=\"/menu\">Menu</a><p>Soup $4</p>";
}


def _logo_fetch(url: str) -> tuple[str, str, bytes] {
    if url.endswith("/robots.txt") {
        return (url, "text/plain", "User-agent: *\nAllow: /\n".encode());
    }
    if url.endswith("/menu") {
        return (url, "text/html", "<img src=\"https://example.com/menu-photo.jpg\">".encode());
    }
    return (url, "text/html", _logo_page().encode());
}


def _collect_logo_site(url: str) -> any {
    import from services.website_import { collect_website as read_public_site }
    return read_public_site(url, fetch=_logo_fetch);
}


test "confirmed save publishes the logo and a blank save clears it" {
    import from services.models { Publishes }
    import from services.promo { save_offer, merchant_portal, get_offer, OfferView }
    actor = "ff00112233445566778899aabbccddee";
    logo = "https://example.com/logo.png";
    with tempfile.TemporaryDirectory() as directory {
        with patch.dict(os.environ, {"MLOCAL_ONBOARDING_DIR": directory, "MLOCAL_MERCHANT_OWNERS": "{}"}) {
            store().remember_account(actor, "logo@fixture.test", "business", "Owner");
            with patch.dict(save_business_draft.__globals__, {"_actor_id": lambda () -> str { return actor; }}) {
                with patch.dict(save_offer.__globals__, {"_actor_id": lambda () -> str { return actor; }}) {
                    saved = save_business_draft(
                        "Fixture Cafe", "Cafe", "Lunch", "123 Test St", "", "Soup $5", "", logo, True
                    );
                    assert saved.ok and saved.image_url == logo, saved.message;
                    owned = _merchant_for_actor(actor) as Restaurant;
                    restaurant_id = jid(owned);
                    slug = owned.slug;
                    assert owned.image_url == logo;
                    created = save_offer(
                        "", "Logo lunch", "Bowl", "5", "7",
                        "2027-01-15 11:00", "2027-01-15 15:00",
                        "4", "Students", "One each", "", ""
                    );
                    assert created.ok, created.message;
                    offer_id = created.code;
                    public = get_offer(offer_id) as OfferView;
                    portal = merchant_portal();
                    assert public.image_url == logo;
                    assert portal.image_url == logo;
                    assert len(portal.offers) == 1 and portal.offers[0].image_url == logo;
                    cleared = save_business_draft(
                        "Fixture Cafe", "Cafe", "Lunch", "123 Test St", "", "Soup $5", "", "", True
                    );
                    assert cleared.ok and cleared.image_url == "";
                    again = _merchant_for_actor(actor) as Restaurant;
                    assert jid(again) == restaurant_id and again.slug == slug;
                    assert again.image_url == "";
                    assert len([again ->:Publishes:->]) == 1;
                    public_after = get_offer(offer_id) as OfferView;
                    portal_after = merchant_portal();
                    assert public_after.title == "Logo lunch" and public_after.image_url == "";
                    assert portal_after.image_url == "" and len(portal_after.offers) == 1;
                    assert portal_after.offers[0].id == offer_id and portal_after.offers[0].image_url == "";
                }
            }
        }
    }
}


test "model facts have no image field and cannot overwrite the imported logo" {
    import from services.business_ai { extract_business, BusinessFacts }
    def _model_facts(source_text: str) -> BusinessFacts {
        return BusinessFacts(
            name="Model Cafe", cuisine="Model food", description="Model wrote this",
            address="9 Model Ave", menu_text="Model soup $99"
        );
    }
    actor = "ffaabbccddeeff001122334455667788";
    logo = "https://example.com/logo.png";
    facts = BusinessFacts(name="Fixture Cafe");
    assert not hasattr(facts, "image_url") and not hasattr(facts, "image");
    with tempfile.TemporaryDirectory() as directory {
        with patch.dict(os.environ, {"MLOCAL_ONBOARDING_DIR": directory, "MLOCAL_IMPORT_MODEL": "fixture-model"}) {
            store().remember_account(actor, "import@fixture.test", "business", "Owner");
            with patch.dict(import_business_website.__globals__, {
                "_actor_id": lambda () -> str { return actor; },
                "collect_website": _collect_logo_site
            }) {
                with patch.dict(extract_business.__globals__, {"extract_business": _model_facts}) {
                    view = import_business_website("https://example.com/");
                    assert view.ok and view.ai_used, view.message;
                    assert view.name == "Model Cafe";
                    assert view.image_url == logo;
                    assert view.image_urls[0] == logo;
                    assert "https://example.com/menu-photo.jpg" in view.image_urls;
                    assert all(["localhost" not in url for url in view.image_urls]);
                }
            }
        }
    }
}
