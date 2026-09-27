"""Application identity comes only from the authenticated Jac request root."""

import from services.models { Restaurant }
import from services.qr_auth { merchant_owner }
import from services.qr_catalog { _ensure_seed }
import from services.onboarding { verified_account, is_demo_student }
import from services.onboarding_support { account_name }
import from services.hosted_dataset { hosted_dataset_enabled }

obj SessionView {
    has authenticated: bool = False,
        actor_id: str = "",
        role: str = "guest",
        restaurant_id: str = "",
        display_name: str = "",
        is_demo: bool = False,
        email_verified: bool = False,
        catalog_activity: bool = False;
}

def _actor_id() -> str {
    # Anonymous requests use precisely the public commons root.
    return "" if jid(root) == jid(root.shared) else jid(root);
}

def _merchant_for_actor(actor: str) -> Restaurant | None {
    if not actor {
        return None;
    }
    for r in [root.shared -->[?:Restaurant]] {
        if merchant_owner(r.slug) == actor {
            return r;
        }
    }
    return None;
}

def:pub current_session() -> SessionView {
    actor = _actor_id();
    if not actor {
        return SessionView();
    }
    _ensure_seed();
    r = _merchant_for_actor(actor);
    account = verified_account(actor);
    if r is not None {
        return SessionView(authenticated=True, actor_id=actor, role="merchant",
            restaurant_id=jid(r), display_name=account_name(actor, r.name), is_demo=r.is_demo,
            email_verified=bool(account), catalog_activity=hosted_dataset_enabled());
    }
    if account {
        return SessionView(authenticated=True, actor_id=actor,
            role="business" if account.get("kind") == "business" else "student",
            display_name=str(account.get("name", "")), email_verified=True);
    }
    if is_demo_student(actor) {
        return SessionView(authenticated=True, actor_id=actor, role="student",
            display_name=account_name(actor, "Demo student"), is_demo=True);
    }
    return SessionView(authenticated=True, actor_id=actor, role="unverified",
        display_name=account_name(actor, "Email verification required"));
}
