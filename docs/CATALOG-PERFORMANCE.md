# Catalog initialization and freshness

`qr_catalog._ensure_seed` stores a versioned `CatalogBootstrap` marker only after the initial catalog and legacy money backfill succeed. Later requests check that marker instead of walking every restaurant, menu item, and offer. Hosted dataset opt-in remains checked on each call so enabling it after bootstrap still works.

Current importers and offer writers initialize cents directly. If a trusted migration introduces legacy raw nodes afterward, increment the bootstrap migration version and run the checks before release. Do not remove offers or claim history to reset the marker.

Authorization still resolves `merchant_owner` live; the marker is not an ownership or session cache. Anonymous session checks do not initialize the catalog. Insights refreshes every two minutes while visible, with manual Refresh and visibility-triggered refresh available.

## Read snapshot (`services/catalog.jac`)

Feed, list, detail, favorites and taste-history reads used to walk the graph
place by place: offers, location, every access notice, menu and stock were
separate round trips for each restaurant. With the 346-offer hosted sample
catalog that was thousands of queries and about 2.6 s of server time per feed
load, so one serialized backend topped out near 20 feed loads a minute.

The catalog module now keeps an in-process snapshot of the **public** catalog
(restaurants, first location, menu labels and categories, offers, public stock
reservations and access notices), built with one batched query per
relationship. Reads assemble views from it with the same `build_view` that live
graph reads use (`promo._view` copies the live nodes and calls it), so there is
one definition of what an offer looks like.

- **Private claims stay private.** `actor_claims(actor)` reads one account's own
  claims with one chained query under that account's access rights and is only
  returned to that account. Nothing private enters the shared snapshot.
- **Writes stay live.** Claims, cancellations, redemptions, hold limits and
  publication read and write the graph under the mutation lock. The cache never
  decides stock or authorization. Listing visibility and merchant suspension
  are still evaluated per request.
- **Invalidation.** `promo._unlock` marks the catalog changed after every locked
  write. Claim, cancel and redeem instead refresh only that offer's stock and the
  claimant's own claims. Seeding marks the catalog changed too. Snapshots also
  expire after 10 minutes (claims index after
  120 s) as a safety net for writes outside the lock, such as seeding.
- **Lookups by id.** `_find_offer` resolves an offer with `jobj` instead of
  scanning every restaurant, and still returns only offers published by a
  shared-catalog restaurant. The hold limit counts the caller's claims with one
  chained query instead of one per offer.
- **Tests.** `scripts/test.sh` sets `MLOCAL_CATALOG_CACHE=off` because in-process
  tests write the graph directly; every read then rebuilds through the same code.
  `services/catalog.test.jac` and the cached-read tests in `promo.test.jac` turn
  reuse on to cover invalidation and to compare every cached view with the live
  graph view.
- **Topology.** The snapshot belongs to one process, which matches the supported
  single serialized backend. A second replica would show displays up to the max
  age stale; it would not change claim correctness, but multiple writers remain
  unsupported for the reasons in `RUNTIME-TRANSACTION-RISK.md`.
