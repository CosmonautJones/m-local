import from services.qr_auth { configured_owners }
import from unittest.mock { patch }

test "anonymous session never loads the catalog" {
    with patch.dict(current_session.__globals__, {
        "_actor_id": lambda () -> str { return ""; },
        "_ensure_seed": lambda () { raise RuntimeError("guest loaded catalog"); }
    }) {
        assert current_session().role == "guest";
    }
}

test "merchant provisioning accepts only trusted UUID mappings" {
    actor = "a1c7350c-5be2-4b78-aef1-905e7e1b6fe4";
    canonical = "a1c7350c5be24b78aef1905e7e1b6fe4";
    owners = configured_owners('{"cafe":"' + actor + '"}');
    assert owners.get("cafe") == canonical;
    assert configured_owners('{"cafe":"' + canonical + '"}').get("cafe") == canonical;
    for bad in ["", "null", "[]", "invalid json", '{"cafe":"merchant"}',
                '{"cafe":true}', '{"cafe":"' + actor + '","other":"' + actor + '"}'] {
        assert configured_owners(bad) == {};
    }
}

test "default session contains no identity or merchant authority" {
    s = SessionView();
    assert not s.authenticated;
    assert s.role == "guest" and s.actor_id == "" and s.restaurant_id == "";
    assert not s.business_account;
}

test "merchant session distinguishes verified business setup from a configured student owner" {
    r = Restaurant(slug="session-account-kind", name="Configured Cafe");
    for kind in ["student", "business"] {
        with patch.dict(current_session.__globals__, {
            "_actor_id": lambda () -> str { return "0123456789abcdef0123456789abcdef"; },
            "_ensure_seed": lambda () {},
            "_merchant_for_actor": lambda (_actor: str) -> Restaurant { return r; },
            "verified_account": lambda (_actor: str) -> dict[str, any] { return {"kind": kind}; },
            "account_name": lambda (_actor: str, _fallback: str) -> str { return "Owner"; }
        }) {
            view = current_session();
            assert view.role == "merchant" and view.email_verified;
            assert view.business_account == (kind == "business");
        }
    }
}
