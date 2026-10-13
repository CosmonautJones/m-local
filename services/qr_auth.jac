"""Trusted provisioning and private, verified-business ownership.

MLOCAL_MERCHANT_OWNERS is a server environment JSON object mapping restaurant
slug to the root_id returned by Jac's pre-provisioned account login (either
UUID spelling; it is canonicalized to the 32-hex form jid(root) uses). Never put
passwords or tokens in this map. Missing/invalid config grants no merchant role.
Changing a mapping requires a server restart and reassigns that restaurant.
Explicit provisioning takes precedence over self-service business ownership.
"""

import os;
import from services.email_codes { registered_business_owner, configured_owners, merchant_operations_allowed }

glob MERCHANT_PAUSED_MESSAGE: str = "This business is temporarily unavailable. Publication and redemption are paused. Contact M-Local support.";
glob CLAIM_SUPPORT_MESSAGE: str = "This business is temporarily unavailable. Your saved claim keeps its original terms and expiry, but redemption is paused. Contact M-Local support.";

def merchant_owner(slug: str) -> str {
    configured = configured_owners(os.environ.get("MLOCAL_MERCHANT_OWNERS", "{}"));
    registered = registered_business_owner(slug);
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
