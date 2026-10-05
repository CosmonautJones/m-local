"""Idempotent public business activation with private server-owned authority."""
import from services.models { Restaurant, Location, HasLocation }
import from services.promo { _lock, _unlock }
import from services.qr_catalog { _ensure_seed }
import from services.qr_auth { merchant_owner }
import from services.session { _merchant_for_actor }
import from services.onboarding_support { prepare_business_activation, finish_business_activation, persist_draft }


def activate_business_listing(actor: str, fields: dict[str, str]) -> dict[str, str] {
    fd = _lock();
    try {
        # Validate after queued mutations/reviews finish, while further reviews
        # are excluded by the same host lock through graph/private finalization.
        prepared = prepare_business_activation(actor, fields);
        slug = prepared["slug"];
        # Retain the confirmed intent before a graph write. If finalization
        # fails, the owner can reload and continue with these same fields.
        persist_draft(actor, prepared);
        _ensure_seed();
        # Existing server-provisioned merchants retain their current restaurant.
        r = _merchant_for_actor(actor);
        if r is None {
            assigned = merchant_owner(slug);
            if assigned and assigned != actor {
                raise ValueError("This business is assigned to another account. Contact the host.");
            }
            existing = [candidate for candidate in [root.shared -->[?:Restaurant]] if candidate.slug == slug];
            if existing {
                r = existing[0];
                if r.source != "business_signup" {
                    raise ValueError("This business identity is already in use. Contact the host.");
                }
            } else {
                r = Restaurant(slug=slug, name=prepared["name"], source="business_signup");
                root.shared ++> r;
            }
        }
        r.name = prepared["name"];
        r.cuisine = prepared["cuisine"];
        r.blurb = prepared["description"];
        r.image_url = prepared["image_url"];
        r.owner_actor_id = actor;
        locations = [r ->:HasLocation:->];
        location = locations[0] if locations else None;
        if location is None {
            location = Location(address=prepared["address"]);
            r +>:HasLocation():+> location;
        }
        location.address = prepared["address"];
        # Grant private authority only after the shared graph is durable. The
        # reserved slug survives a retry or crash without creating another node.
        # Keep the mutation lock until both stores agree, preventing save order
        # from reversing between the public profile and its private metadata.
        commit();
        saved = finish_business_activation(actor, prepared);
    } finally {
        # ReadOnlyRetry and WriteConflict must reach Jac's abort/replay handler.
        _unlock(fd);
    }
    return saved;
}
