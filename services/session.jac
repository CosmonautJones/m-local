"""Server-derived identity and restaurant membership.

Nobody submits their own identity or role. The actor id is the id of the
caller's graph root, which the Jac server binds from the login token:
anonymous callers run on the shared guest graph (actor ""), signed-in callers
on their own root (actor = jid(root)).

A merchant is an actor named as a restaurant's owner_actor_id. Only trusted
server-side provisioning assigns it: the MLOCAL_MERCHANT_OWNERS environment
variable read at request time, or _provision_owner from tests and local
setup code. Nothing here is served: these are plain (private) defs, and the
underscore marks them as internal for readers.
"""

import os;
import from services.models { Restaurant }


obj SessionView {
    has authenticated: bool = False,
        actor_id: str = "",
        role: str = "guest",
        restaurant_id: str = "",
        display_name: str = "",
        is_demo: bool = False;
}


glob OWNERS_ENV: str = "MLOCAL_MERCHANT_OWNERS";


"""The caller's actor id, or "" for an anonymous guest."""
def _caller_actor -> str {
    rid = jid(root);
    if rid == jid(root.shared) {
        return "";
    }
    return rid;
}


def _restaurants -> list[Restaurant] {
    return [root.shared-->[?:Restaurant]];
}


def _restaurant_for_actor(actor_id: str) -> Restaurant | None {
    if not actor_id {
        return None;
    }
    for r in _restaurants() {
        if r.owner_actor_id == actor_id {
            return r;
        }
    }
    return None;
}


def _session_for(actor_id: str) -> SessionView {
    if not actor_id {
        return SessionView();
    }
    r = _restaurant_for_actor(actor_id);
    if r is not None {
        return SessionView(
            authenticated=True,
            actor_id=actor_id,
            role="merchant",
            restaurant_id=jid(r),
            display_name=r.name,
            is_demo=r.is_demo
        );
    }
    return SessionView(
        authenticated=True,
        actor_id=actor_id,
        role="student",
        display_name="Student " + actor_id[-4:].upper(),
        is_demo=False
    );
}


"""Make actor_id the single owner of the restaurant with this slug. Trusted
server-side use only (tests, local provisioning). An actor owns at most one
restaurant in this build, so any other membership is cleared."""
def _provision_owner(slug: str, actor_id: str) -> bool {
    if not slug.strip() or not actor_id.strip() {
        return False;
    }
    matches = [r for r in _restaurants() if r.slug == slug.strip()];
    if not matches {
        return False;
    }
    target: Restaurant = matches[0];
    for r in _restaurants() {
        if r.owner_actor_id == actor_id.strip() and r.slug != target.slug {
            r.owner_actor_id = "";
        }
    }
    target.owner_actor_id = actor_id.strip();
    return True;
}


"""Parse "slug=actor_id,slug=actor_id" pairs; malformed entries are skipped."""
def _parse_owner_pairs(text: str) -> list[list[str]] {
    pairs: list[list[str]] = [];
    for part in text.split(",") {
        bits: list[str] = part.split("=", 1);
        if len(bits) == 2 and bits[0].strip() and bits[1].strip() {
            pairs.append([bits[0].strip(), bits[1].strip()]);
        }
    }
    return pairs;
}


"""Apply MLOCAL_MERCHANT_OWNERS, if set. The operator's environment is the
authority, so it runs on every request and is cheap for a handful of
restaurants. Unset means no merchants, which is the safe default."""
def _apply_owner_provisioning -> None {
    text = os.environ.get(OWNERS_ENV, "");
    if not text.strip() {
        return;
    }
    for pair in _parse_owner_pairs(text) {
        for r in _restaurants() {
            if r.slug == pair[0] and r.owner_actor_id != pair[1] {
                _provision_owner(pair[0], pair[1]);
            }
        }
    }
}
