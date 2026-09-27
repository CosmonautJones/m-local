"""Persistent archive migration for generated demo catalog inventory."""

import from services.models { Restaurant, Offer, Publishes }

node DemoCatalogArchiveMigration {
    has version: int = 2;
}


def archive_excess_demo_catalog() -> int {
    if [root.shared -->[?:DemoCatalogArchiveMigration, version >= 2]] { return 0; }
    kept_businesses = 0;
    archived_count = 0;
    for r in [root.shared -->[?:Restaurant]] {
        generated = r.is_demo and (r.source == "demo-seed" or r.source.startswith("dataset-test:") or r.slug.startswith("sandbox-"));
        if not generated { continue; }
        if r.source == "demo-seed" and r.slug in ["maize-noodle-lab", "arbor-leaf-kitchen"] {
            kept_businesses += 1;
            kept_offers = 0;
            for o in [r ->:Publishes:->] {
                if kept_offers < (1 if r.slug == "maize-noodle-lab" else 2) {
                    kept_offers += 1;
                } else {
                    o.archived = True;
                    archived_count += 1;
                }
            }
        } else {
            r.archived = True;
            for o in [r ->:Publishes:->] {
                o.archived = True;
                archived_count += 1;
            }
        }
    }
    root.shared ++> DemoCatalogArchiveMigration(version=2);
    return archived_count;
}
