# Catalog initialization and freshness

`qr_catalog._ensure_seed` stores a versioned `CatalogBootstrap` marker only after the initial catalog and legacy money backfill succeed. Later requests check that marker instead of walking every restaurant, menu item, and offer. Hosted dataset opt-in remains checked on each call so enabling it after bootstrap still works.

Current importers and offer writers initialize cents directly. If a trusted migration introduces legacy raw nodes afterward, increment the bootstrap migration version and run the checks before release. Do not remove offers or claim history to reset the marker.

Authorization still resolves `merchant_owner` live; the marker is not an ownership or session cache. Anonymous session checks do not initialize the catalog. Insights refreshes every two minutes while visible, with manual Refresh and visibility-triggered refresh available.
