"""Business submissions stay private until host approval; later saves are self-service."""
import os;
import from services.email_codes { store }
import from services.website_import { collect_website }
import from services.onboarding_support { read_draft, persist_draft }
import from services.business_listing { activate_business_listing }
import from services.promo { _lock, _unlock }
import from services.session { _actor_id }
import from services.onboarding { verified_account }

obj BusinessDraftView {
    has ok: bool = False, message: str = "", name: str = "", cuisine: str = "",
        description: str = "", address: str = "", website: str = "", menu_text: str = "",
        menu_url: str = "", image_url: str = "", status: str = "draft",
        image_urls: list[str] = [], menu_urls: list[str] = [], sources: list[str] = [],
        ai_used: bool = False, approved_name: str = "", approved_address: str = "";
}

def _draft_view(raw: dict[str, any], message: str = "") -> BusinessDraftView {
    return BusinessDraftView(ok=True, message=message,
        name=str(raw.get("name", "")), cuisine=str(raw.get("cuisine", "")),
        description=str(raw.get("description", "")), address=str(raw.get("address", "")),
        website=str(raw.get("website", "")), menu_text=str(raw.get("menu_text", "")),
        menu_url=str(raw.get("menu_url", "")), image_url=str(raw.get("image_url", "")),
        status=str(raw.get("status", "draft")),
        approved_name=str(raw.get("approved_name", raw.get("name", "") if raw.get("status") == "active" else "")),
        approved_address=str(raw.get("approved_address", raw.get("address", "") if raw.get("status") == "active" else "")),
        image_urls=raw.get("image_urls", []) as list[str],
        menu_urls=raw.get("menu_urls", []) as list[str],
        sources=raw.get("sources", []) as list[str]);
}

def:protect get_business_draft() -> BusinessDraftView {
    if verified_account(_actor_id()).get("kind") != "business" {
        return BusinessDraftView(message="Sign in with a verified business account to edit a business profile.");
    }
    try {
        raw = read_draft(_actor_id());
        approved = store().approved_profile(_actor_id());
        raw["approved_name"] = approved.get("name", "");
        raw["approved_address"] = approved.get("address", "");
        covered = store().approval_covers(_actor_id(), raw);
        if raw.get("status") == "active" and not covered {
            raw["status"] = "pending_review" if raw.get("name") and raw.get("address") else "draft";
        } elif raw.get("status") != "active" and covered {
            raw["status"] = "approved";
        }
        return _draft_view(raw);
    } except Exception {
        return BusinessDraftView(message="Could not load your business profile. Please try again.");
    }
}

def:protect import_business_website(website: str) -> BusinessDraftView {
    if verified_account(_actor_id()).get("kind") != "business" {
        return BusinessDraftView(message="Sign in with a verified business account before importing a website.");
    }
    try {
        store().reserve_import(_actor_id());
        raw = collect_website(website);
        view = _draft_view(raw, "Website details imported. Review each field before saving.");
        if os.environ.get("MLOCAL_IMPORT_MODEL", "") {
            try {
                import from services.business_ai { extract_business }
                facts = extract_business(str(raw.get("text", "")));
                view.name = facts.name[:120] or view.name;
                view.cuisine = facts.cuisine[:80] or view.cuisine;
                view.description = facts.description[:1000] or view.description;
                view.address = facts.address[:240] or view.address;
                view.menu_text = facts.menu_text[:4000] or view.menu_text;
                view.ai_used = True;
                view.message = "AI organized the website details. Check the facts and menu prices before saving.";
            } except Exception {
                view.message = "Website details imported. AI was unavailable; review or fill the remaining fields.";
            }
        }
        return view;
    } except ValueError as e {
        return BusinessDraftView(message=str(e));
    } except Exception {
        return BusinessDraftView(message="Could not read this website. Check the address or enter the details manually.");
    }
}

def:protect save_business_draft(name: str, cuisine: str, description: str, address: str,
    website: str, menu_text: str, menu_url: str, image_url: str, confirmed: bool) -> BusinessDraftView {
    if verified_account(_actor_id()).get("kind") != "business" {
        return BusinessDraftView(message="Sign in with a verified business account to edit a business profile.");
    }
    if not confirmed {
        return BusinessDraftView(message="Confirm you may represent this business and use the selected content.");
    }
    try {
        fields = {"name": name.strip(), "cuisine": cuisine, "description": description,
            "address": address.strip(), "website": website, "menu_text": menu_text, "menu_url": menu_url, "image_url": image_url};
        if not store().approval_covers(_actor_id(), fields) {
            fd = _lock();
            try { raw = persist_draft(_actor_id(), fields); }
            finally { _unlock(fd); }
            return _draft_view(raw, "Submitted for review. Once approved, you can publish and manage your offers.");
        }
        raw = activate_business_listing(_actor_id(), fields);
        return _draft_view(raw, "Business profile saved. You can publish offers now.");
    } except ValueError as e {
        return BusinessDraftView(message=str(e));
    }
}
