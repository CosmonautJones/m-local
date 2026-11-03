"""Trusted provisioning and private, verified-business ownership.

MLOCAL_MERCHANT_OWNERS is a server environment JSON object mapping restaurant
slug to the root_id returned by Jac's pre-provisioned account login (either
UUID spelling; it is canonicalized to the 32-hex form jid(root) uses). Never put
passwords or tokens in this map. Missing/invalid config grants no merchant role.
Changing a mapping requires a server restart and reassigns that restaurant.
Explicit provisioning takes precedence over self-service business ownership.
"""

import os;
import from services.email_codes { registered_business_owner, registered_business_owners, configured_owners, merchant_operations_allowed, merchant_operations_allowed_many }

glob MERCHANT_PAUSED_MESSAGE: str = "This business is temporarily unavailable. Publication and redemption are paused. Contact M-Local support.";
glob CLAIM_SUPPORT_MESSAGE: str = "This business is temporarily unavailable. Your saved claim keeps its original terms and expiry, but redemption is paused. Contact M-Local support.";

def merchant_owner(slug: str) -> str {
    configured = configured_owners(os.environ.get("MLOCAL_MERCHANT_OWNERS", "{}"));
    return _owner_from(slug, configured, registered_business_owner(slug));
}

def _owner_from(slug: str, configured: dict[str, str], registered: str) -> str {
    if slug in configured {
        if slug.startswith("business-") and registered != configured[slug] { return ""; }
        return configured[slug];
    }
    # An explicitly provisioned account still owns one restaurant even if it
    # previously activated a self-service listing under another slug.
    if registered in configured.values() { return ""; }
    return registered;
}

def listing_visible(slug: str, source: str) -> bool {
    return (source != "business_signup" or bool(merchant_owner(slug))) and merchant_operations_enabled(slug);
}

def merchant_operations_enabled(slug: str) -> bool {
    actor = merchant_owner(slug);
    if actor { return merchant_operations_allowed(actor); }
    return not slug.startswith("business-");
}

"""merchant_owner for many slugs, with one read of the private store."""
def merchant_owners(slugs: list[str]) -> dict[str, str] {
    configured = configured_owners(os.environ.get("MLOCAL_MERCHANT_OWNERS", "{}"));
    registered = registered_business_owners(slugs);
    return {slug: _owner_from(slug, configured, registered.get(slug, "")) for slug in slugs};
}

"""listing_visible and merchant_operations_enabled for many places at once,
with one read of each private store instead of several per place. The rules
are the same and are read live on every call (nothing is cached), so a
suspension applies to the very next request. Maps slug to
(visible, operations_enabled)."""
def place_access(places: list[tuple[str, str]]) -> dict[str, tuple[bool, bool]] {
    owners = merchant_owners([p[0] for p in places]);
    allowed = merchant_operations_allowed_many(sorted({a for a in owners.values() if a}));
    result: dict[str, tuple[bool, bool]] = {};
    for p in places {
        (slug, source) = p;
        owner = owners[slug];
        ops = allowed.get(owner, False) if owner else not slug.startswith("business-");
        result[slug] = ((source != "business_signup" or bool(owner)) and ops, ops);
    }
    return result;
}
