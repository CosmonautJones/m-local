"""Shared catalog bootstrap and compatibility backfill; server helper only."""

import from services.models { Restaurant, Serves, Publishes }
import from services.seed { seed_demo }
import from services.money { money_to_cents }
import from services.qr_auth { merchant_owner }

"""Bootstrap one catalog regardless of which authenticated root asks first.

The importer remains in its owner lane: it creates under the current root.
Only initial bootstrap bridges those app-owned nodes into the public commons.
Serializable request replay prevents two bootstraps publishing duplicate catalogs.
"""
def _ensure_seed {
    # seed_demo imports only missing fictional slugs, so run it even when a
    # partial or real shared catalog already exists.
    previous = [jid(r) for r in [root -->[?:Restaurant]]];
    seed_demo();
    for r in [root -->[?:Restaurant]] {
        if jid(r) not in previous {
            for o in [r ->:Publishes:->] { o.qr_ready = True; }
        }
        if jid(root) != jid(root.shared) and not [root.shared -->[?:Restaurant, slug == r.slug]] {
            root.shared ++> r;
        }
    }
    # Compatibility backfill for the unchanged importer and old durable catalog.
    # Once populated, cents are authoritative; float fields are display-only.
    for r in [root.shared -->[?:Restaurant]] {
        configured = merchant_owner(r.slug);
        if r.owner_actor_id != configured {
            r.owner_actor_id = configured;
        }
        for m in [r ->:Serves:->] {
            if m.price_cents < 0 { m.price_cents = money_to_cents(str(m.price)); }
        }
        for o in [r ->:Publishes:->] {
            if o.price_cents < 0 { o.price_cents = money_to_cents(str(o.price)); }
            if o.regular_price_cents < 0 {
                o.regular_price_cents = money_to_cents(str(o.regular_price));
            }
        }
    }
}
