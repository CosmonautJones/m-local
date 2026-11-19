import from services.qr_auth { configured_owners }
import from unittest.mock { patch }
import os;
import json;
import tempfile;
import from pathlib { Path }
import from services.models { samples_visible }
import from services.release_channel { forget_channel }

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
            "is_demo_student": lambda (_actor: str) -> bool { return True; },
            "account_name": lambda (_actor: str, _fallback: str) -> str { return "Owner"; }
        }) {
            view = current_session();
            assert view.role == "merchant" and view.email_verified;
            assert view.business_account == (kind == "business");
        }
    }
}

test "verified allowlisted test inbox gets a student demo session" {
    actor = "0123456789abcdef0123456789abcdef";
    for kind in ["business", "student"] {
        account = {"kind": kind, "name": "Original account name"};
        with patch.dict(os.environ, {"MLOCAL_DEMO_STUDENTS": '["' + actor + '"]'}),
            patch.dict(current_session.__globals__, {
                "_actor_id": lambda () -> str { return actor; },
                "_ensure_seed": lambda () {},
                "_merchant_for_actor": lambda (_actor: str) {},
                "verified_account": lambda (_actor: str) -> dict[str, any] { return account; },
                "account_name": lambda (_actor: str, _fallback: str) -> str { return "Updated test name"; }
            }) {
            view = current_session();
            assert view.authenticated and view.actor_id == actor;
            assert view.role == "student" and view.is_demo;
            assert view.email_verified and not view.business_account;
            assert view.display_name == "Updated test name";
            assert account.get("kind") == kind;
        }
    }
}

test "unverified allowlisted test actor keeps accurate email verification" {
    actor = "0123456789abcdef0123456789abcdef";
    with patch.dict(os.environ, {"MLOCAL_DEMO_STUDENTS": '["' + actor + '"]'}),
        patch.dict(current_session.__globals__, {
            "_actor_id": lambda () -> str { return actor; },
            "_ensure_seed": lambda () {},
            "_merchant_for_actor": lambda (_actor: str) {},
            "verified_account": lambda (_actor: str) -> dict[str, any] { return {}; },
            "account_name": lambda (_actor: str, _fallback: str) -> str { return "Preview student"; }
        }) {
        view = current_session();
        assert view.role == "student" and view.is_demo;
        assert not view.email_verified and not view.business_account;
        assert view.display_name == "Preview student";
    }
}

test "ordinary verified business and student accounts keep their roles" {
    for kind in ["business", "student"] {
        with patch.dict(os.environ, {"MLOCAL_DEMO_STUDENTS": "[]"}),
            patch.dict(current_session.__globals__, {
                "_actor_id": lambda () -> str { return "0123456789abcdef0123456789abcdef"; },
                "_ensure_seed": lambda () {},
                "_merchant_for_actor": lambda (_actor: str) {},
                "verified_account": lambda (_actor: str) -> dict[str, any] { return {"kind": kind, "name": "Verified name"}; }
            }) {
            view = current_session();
            assert view.role == kind and not view.is_demo;
            assert view.email_verified and view.business_account == (kind == "business");
            assert view.display_name == "Verified name";
        }
    }
}

test "a production build ignores the demo-student allowlist and the sample switch" {
    actor = "0123456789abcdef0123456789abcdef";
    settings = {"MLOCAL_DEMO_STUDENTS": '["' + actor + '"]', "MLOCAL_SHOW_SAMPLES": "1"};
    with tempfile.TemporaryDirectory() as directory {
        for (name, demo) in [("preview", True), ("production", False)] {
            stamp = Path(directory) / (name + ".json");
            stamp.write_text(json.dumps({"channel": name}));
            forget_channel();
            with patch("services.release_channel.STAMP", stamp),
                patch.dict(os.environ, settings),
                patch.dict(current_session.__globals__, {
                    "_actor_id": lambda () -> str { return actor; },
                    "_ensure_seed": lambda () {},
                    "_merchant_for_actor": lambda (_actor: str) {},
                    "verified_account": lambda (_actor: str) -> dict[str, any] { return {"kind": "business", "name": "Tester"}; },
                    "account_name": lambda (_actor: str, _fallback: str) -> str { return "Tester"; }
                }) {
                view = current_session();
                assert view.is_demo == demo;
                assert view.role == ("student" if demo else "business");
                assert samples_visible() == demo;
            }
        }
    }
    forget_channel();
}
