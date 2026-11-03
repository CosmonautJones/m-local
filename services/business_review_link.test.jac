"""Emailed business review links: signing, binding to one submission, approval."""
import tempfile;
import from unittest.mock { patch }
import from services.email_codes { business_revision }


def _env(directory: str) -> dict[str, str] {
    return {"MLOCAL_ONBOARDING_DIR": directory, "MLOCAL_MERCHANT_OWNERS": "{}",
        "MLOCAL_OPERATOR_EMAIL": "operator@fixture.test", "MLOCAL_PUBLIC_URL": "https://m-local.fixture.test",
        "MLOCAL_SMTP_FROM": "M-Local <codes@fixture.test>"};
}


def _business(actor: str, name: str, address: str) {
    store().remember_account(actor, "owner-" + actor[:4] + "@fixture.test", "business", "Owner");
    store().save_draft(actor, {"name": name, "address": address, "website": "https://cafe.fixture.test"});
}


def _token_from(body: str) -> str {
    marker = "/#approve=";
    start = body.index(marker) + len(marker);
    return body[start:].split()[0];
}


test "review tokens are signed, bound and expire" {
    actor = "0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b";
    submission = "ab" * 32;
    with tempfile.TemporaryDirectory() as directory {
        with patch.dict(os.environ, _env(directory)) {
            store();
            token = make_review_token(actor, submission, 2000);
            assert read_review_token(token, 1000.0) == (actor, submission);
            for bad in [token[:-2] + ("AA" if not token.endswith("AA") else "BB"), "", "short", token + "x"] {
                try { read_review_token(bad, 1000.0); assert False, "accepted " + bad; }
                except ValueError {}
            }
            try { read_review_token(token, 2001.0); assert False, "expired token accepted"; }
            except ValueError as error { assert "expired" in str(error); }
        }
    }
}


test "a submission emails the operator once and the link approves exactly that submission" {
    actor = "1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c";
    sent: list[any] = [];
    with tempfile.TemporaryDirectory() as directory {
        with patch.dict(os.environ, _env(directory)) {
            with patch.dict(notify_business_review.__globals__, {"deliver": lambda (m: any) { sent.append(m); }, "delivery_ready": lambda () -> bool { return True; }}) {
                _business(actor, "Link Cafe", "1 Test St");
                assert notify_business_review(actor);
                assert not notify_business_review(actor), "the same submission is emailed once";
                assert len(sent) == 1 and sent[0]["To"] == "operator@fixture.test";
                body = sent[0].get_content();
                assert "Link Cafe" in body and "1 Test St" in body;
                token = _token_from(body);
                view = review_link_details(token);
                assert view.ok and not view.approved and view.name == "Link Cafe" and view.address == "1 Test St";
                # An edited name invalidates the old link and sends a new one.
                store().save_draft(actor, {"name": "Link Cafe & Bar", "address": "1 Test St"});
                stale = approve_from_review_link(token);
                assert not stale.ok and "changed" in stale.message;
                assert not store().business_approved(actor);
                assert notify_business_review(actor) and len(sent) == 2;
                fresh = _token_from(sent[1].get_content());
                done = approve_from_review_link(fresh, "Called the cafe");
                assert done.ok and done.approved, done.message;
                assert store().approved_profile(actor)["name"] == "Link Cafe & Bar";
                assert sent[-1]["To"].startswith("owner-"), "the owner hears they are approved";
                again = approve_from_review_link(fresh);
                assert again.ok and again.approved and "already" in again.message;
            }
        }
    }
}


test "no operator settings means no email and no approval path" {
    actor = "2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d";
    sent: list[any] = [];
    with tempfile.TemporaryDirectory() as directory {
        settings = _env(directory);
        settings["MLOCAL_OPERATOR_EMAIL"] = "";
        with patch.dict(os.environ, settings) {
            with patch.dict(notify_business_review.__globals__, {"deliver": lambda (m: any) { sent.append(m); }, "delivery_ready": lambda () -> bool { return True; }}) {
                _business(actor, "Quiet Cafe", "2 Test St");
                assert not notify_business_review(actor) and sent == [];
            }
        }
        settings["MLOCAL_OPERATOR_EMAIL"] = "operator@fixture.test";
        settings["MLOCAL_PUBLIC_URL"] = "http://evil.fixture.test";
        with patch.dict(os.environ, settings) {
            assert review_link_settings()[1] == "", "only https public URLs";
        }
    }
}


test "a forged or foreign token reveals nothing" {
    with tempfile.TemporaryDirectory() as directory {
        with patch.dict(os.environ, _env(directory)) {
            store();
            view = review_link_details("A" * 118);
            assert not view.ok and view.name == "" and view.email == "";
            result = approve_from_review_link("A" * 118);
            assert not result.ok and not result.approved;
        }
    }
}
