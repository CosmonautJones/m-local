"""Shared catalog bootstrap and compatibility backfill; server helper only."""

import from services.models { Restaurant, Serves, Publishes }
import from services.seed { seed_demo }
import from services.money { money_to_cents }
import from services.qr_auth { merchant_owner }
import from services.hosted_dataset { ensure_hosted_dataset, hosted_dataset_enabled, HostedDatasetLoaded }
import from services.catalog_events { catalog_changed, seed_verified, mark_seeded }

node CatalogBootstrap {
    has version: int = 1;
    def __jac_access__ -> AccessLevel { return AccessLevel.READ; }
}

"""Bootstrap one catalog regardless of which authenticated root asks first.

The importer remains in its owner lane: it creates under the current root.
Only initial bootstrap bridges those app-owned nodes into the public commons.
Serializable request replay prevents two bootstraps publishing duplicate catalogs.
"""
def _ensure_seed {
    # Only cache completion of the migration, never identity or inventory.
    # Current import/write paths populate cents themselves. Bump the version
    # when a future release needs another compatibility migration.
    # Every read path calls this. Once a request has seen a complete seed, later
    # requests in this process skip the graph check until the next catalog write.
    key = jid(root.shared) + ("|hosted" if hosted_dataset_enabled() else "");
    if seed_verified(key) { return; }
    if [root.shared -->[?:CatalogBootstrap, version == 1]] {
        complete = not hosted_dataset_enabled() or bool([root.shared -->[?:HostedDatasetLoaded]]);
        ensure_hosted_dataset();
        # Only a check that wrote nothing is remembered; a write may still roll back.
        if complete { mark_seeded(key); }
        return;
    }
    if not [root.shared -->[?:Restaurant]] {
        previous = [jid(r) for r in [root -->[?:Restaurant]]];
        seed_demo();
        for r in [root -->[?:Restaurant]] {
            if jid(r) not in previous {
                for o in [r ->:Publishes:->] { o.qr_ready = True; }
            }
            if jid(root) != jid(root.shared) {
                root.shared ++> r;
            }
        }
    }
    ensure_hosted_dataset();
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
    root.shared ++> CatalogBootstrap();
    # Seeding writes outside the mutation lock; rebuild the read snapshot.
    catalog_changed();
}
