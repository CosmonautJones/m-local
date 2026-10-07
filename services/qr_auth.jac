"""Trusted provisioning and private, verified-business ownership.

MLOCAL_MERCHANT_OWNERS is a server environment JSON object mapping restaurant
slug to the root_id returned by Jac's pre-provisioned account login (either
UUID spelling; it is canonicalized to the 32-hex form jid(root) uses). Never put
passwords or tokens in this map. Missing/invalid config grants no merchant role.
Changing a mapping requires a server restart and reassigns that restaurant.
Explicit provisioning takes precedence over self-service business ownership.
"""

import os;
import json;
import from uuid { UUID }
import from services.email_codes { registered_business_owner }

def configured_owners(text: str) -> dict[str, str] {
    result: dict[str, str] = {};
    try {
        raw = json.loads(text);
        if not isinstance(raw, dict) {
            return result;
        }
        for (slug, actor) in raw.items() {
            if not isinstance(slug, str) or not isinstance(actor, str) or not slug {
                return {};
            }
            # Accept the hyphenated form from /user/login and the 32-hex form
            # jid(root) reports; store the canonical 32-hex form, which is what
            # every ownership comparison in the app sees.
            result[slug] = UUID(actor).hex;
        }
        # This slice permits one restaurant per merchant account.
        if len(set(result.values())) != len(result) {
            return {};
        }
        return result;
    } except Exception {
        return {};
    }
}

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
    return source != "business_signup" or bool(merchant_owner(slug));
}
