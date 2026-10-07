"""Onboarding glue between email codes, accounts, business drafts and activation."""

import secrets;
import json;
import os;
import hmac;
import from uuid { UUID }
import from services.email_codes { delivery_ready, send_code, store }
import from services.photo_reference { image_reference }
import from services.website_import { clean_url }


def request_code(value: str, kind: str, name: str) -> dict[str, any] {
    if not delivery_ready() {
        return {"ok": False, "message": "Email sign-in is not enabled yet. The host needs to configure an email sender."};
    }
    try {
        return store().request(value, kind, name, send_code);
    } except ValueError as error {
        return {"ok": False, "message": str(error)};
    } except Exception {
        return {"ok": False, "message": "Email sign-in is temporarily unavailable. Please try again later."};
    }
}


def finish_account(proof: dict[str, any], users: any, state: any) -> dict[str, any] {
    email = proof["email"];
    existing = users.find_user_by_identity(email);
    # Inbox proof never authorizes deletion, root replacement or identity relinking.
    # Missing private onboarding may be a native/provisioned account or a failed
    # restore. Only our matching interrupted-provisioning marker can recover here.
    user_id: any = None;
    if existing {
        root_id = str(existing.get("root_id", "")).replace("-", "");
        saved = state.account(root_id);
        valid_email = `any([
            i.get("type") == "email" and i.get("value_normalized") == email and i.get("verified") is True
            for i in existing.get("identities", [])
        ]);
        pending = state.provisioning(email);
        marker = (existing.get("profile") or {}).get("mlocal_provision", "");
        if (
            not saved and pending and isinstance(marker, str)
            and hmac.compare_digest(marker, pending["marker"])
            and valid_email and existing.get("role") == "user" and existing.get("status") == "active"
        ) {
            state.remember_account(root_id, email, pending["kind"], pending["name"]);
            saved = state.account(root_id);
        }
        if (
            existing.get("role") != "user" or existing.get("status") != "active"
            or not valid_email or saved.get("email") != email
        ) {
            raise ValueError("This account uses another sign-in method. Use its original sign-in or contact the host.");
        }
        user_id = existing["user_id"];
    } else {
        if not proof["name"] {
            raise ValueError("No account exists for this email yet. Choose Create account to get started.");
        }
        pending = state.provisioning(email, proof["kind"], proof["name"]);
        created = users.create_user_with_identities(
            identities=[{"type": "email", "value": email, "verified": True}],
            credential={"type": "password", "password": secrets.token_urlsafe(48)},
            profile={"firstname": pending["name"], "mlocal_provision": pending["marker"]}
        );
        if created.get("error") or not created.get("user_id") {
            raise ValueError("Could not finish creating the account. Please request a new code.");
        }
        user_id = created["user_id"];
        root_id = UUID(created["root_id"]).hex;
        state.remember_account(root_id, email, pending["kind"], pending["name"]);
    }
    token = users.create_jwt_token(user_id);
    if not token {
        raise ValueError("Could not start the session. Please request a new code.");
    }
    return {"ok": True, "token": token, "message": "Email verified."};
}


def verify_code(challenge: str, code: str) -> dict[str, any] {
    try {
        import from jaclang.server.identity.user_manager { UserManager }
        state = store();
        proof = state.consume(challenge, code);
        return finish_account(proof, UserManager(), state);
    } except ValueError as error {
        return {"ok": False, "message": str(error)};
    } except Exception {
        return {"ok": False, "message": "Could not finish signing in. Please request a new code."};
    }
}


def account_details(actor: str) -> dict[str, any] {
    return store().account(actor);
}


def account_name(actor: str, fallback: str = "") -> str {
    return store().display_name(actor, fallback);
}


def save_account_name(actor: str, name: str) -> str {
    # Called only with the authenticated Jac root, never a browser-selected actor.
    return store().save_display_name(actor, name);
}


def demo_student(actor: str) -> bool {
    try {
        configured = json.loads(os.environ.get("MLOCAL_DEMO_STUDENTS", "[]"));
        return isinstance(configured, list) and UUID(actor).hex in {UUID(value).hex for value in configured};
    } except (ValueError, TypeError, AttributeError) {
        return False;
    }
}


def may_claim(actor: str) -> bool {
    details = account_details(actor);
    return (details.get("kind") == "student" and details.get("email", "").endswith("@umich.edu")) or demo_student(actor);
}


def validate_draft(raw: dict[str, any], actor: str = "") -> dict[str, any] {
    limits: dict[str, int] = {
        "name": 120, "cuisine": 80, "description": 1000, "address": 240,
        "website": 2048, "menu_url": 2048, "image_url": 2048, "menu_text": 4000
    };
    result: dict[str, any] = {};
    for (key, limit) in limits.items() {
        value = raw.get(key, "");
        label = key.replace("_", " ");
        if not isinstance(value, str) or len(value) > limit {
            raise ValueError(f"Please shorten the {label} field.");
        }
        if `any([(ord(char) < 32 and char not in "\t\r\n") or 127 <= ord(char) < 160 for char in value]) {
            raise ValueError(f"The {label} field contains unsupported control characters.");
        }
        result[key] = value.strip();
    }
    if not result["name"] or not result["address"] {
        raise ValueError("Add the business name and address before saving.");
    }
    for key in ("website", "menu_url", "image_url") {
        if result[key] {
            result[key] = image_reference(result[key], actor) if key == "image_url" else clean_url(result[key]);
        }
    }
    result["status"] = "pending_review";
    return result;
}


def read_draft(actor: str) -> dict[str, any] {
    state = store();
    if state.account(actor).get("kind") != "business" {
        raise ValueError("Sign in with a verified business account to edit a business profile.");
    }
    return state.draft(actor);
}


def persist_draft(actor: str, raw: dict[str, any]) -> dict[str, any] {
    state = store();
    # The actor comes from Jac's authenticated request root, never request JSON.
    account = state.account(actor);
    if account.get("kind") != "business" {
        raise ValueError("Sign in with a verified business account to edit a business profile.");
    }
    result = validate_draft(raw, actor);
    state.save_draft(actor, result);
    return result;
}


def prepare_business_activation(actor: str, raw: dict[str, any]) -> dict[str, str] {
    state = store();
    if state.account(actor).get("kind") != "business" {
        raise ValueError("Sign in with a verified business account to save a business profile.");
    }
    result = validate_draft(raw, actor);
    if not state.approval_covers(actor, result) {
        raise ValueError("Your business needs host approval before publishing.");
    }
    result["status"] = "draft";
    result["slug"] = state.reserve_business(actor);
    return result;
}


def finish_business_activation(actor: str, raw: dict[str, any]) -> dict[str, str] {
    # Re-validate and retain only known metadata. Browser-selected slugs, actor
    # IDs, roles and statuses never enter the private authority registry.
    result = validate_draft(raw, actor);
    return store().activate_business(actor, result);
}
