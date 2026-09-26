# Engineer 2 status: trusted offer transactions

Branch: `feat/02-offer-trust`
Runtime used: Jac **0.34.20** (official macOS arm64 release binary, checksum
verified). The unmodified baseline also passes its 7 tests on this version.

## Now works, with evidence

Unit checks: `jac clean --data --force && jac test services/promo.jac services/session.jac`
-> **29 passed**, and 29 passed again on two re-runs against the persisted store.

HTTP checks against a real `jac start` server with real registered accounts
(API-only entry, fresh store): **30/30 passed on three separate runs**. Covered:

| Check | Result |
|---|---|
| Guest `claim_offer`, `redeem_code`, `merchant_portal` | 401 from the runtime |
| Session actor id | Equals the `root_id` returned by `/user/login` |
| Unprovisioned account | Is a student; cannot open a portal |
| Provisioned merchant (env) | Merchant session and own portal; cannot claim |
| Claim retry | Same code, no extra unit |
| Private claims | Other student and guest see no code or claim terms |
| Cross-merchant | Other merchant cannot redeem or edit |
| Stable terms | Offer edited $8 -> $12 after a claim; redemption charges $8.00 |
| Double redemption | Rejected |
| **Last unit, 20 simultaneous students** | Exactly one winner; offer shows sold out |
| 10 simultaneous retries by one student | One code, one unit used |
| Cancel | Releases the unit |
| Restart | Redemption, sold-out stock, edited price and merchant role persist |
| First caller signed in | Seeded catalog still lands in the shared catalog |

The HTTP script is attached to the PR for Engineer 1 (it belongs under
`tests/integration/`, which Engineer 1 owns).

## Contract items delivered

- `services/money.jac`: `money_to_cents(text) -> int` (strict: rejects NaN,
  infinity, negatives, exponents, more than two decimals), plus
  `try_money_to_cents`, `cents_to_dollars`, `money_label`.
- Integer `price_cents` / `regular_price_cents` on Offer and MenuItem. Float
  `price` fields remain as display copies. Records without cents (current
  importer/seed) are backfilled on first request.
- Claim snapshots on Redemption: `offer_title_snapshot`, `price_cents_snapshot`,
  `terms_snapshot`, `eligibility_snapshot`, plus `cancelled_ts` and status
  `cancelled`.
- `Restaurant.owner_actor_id`; `merchant_key` no longer grants anything.
- `services/session.jac`: `SessionView` and server-derived identity.
- New endpoints `current_session()` and `cancel_claim(offer_id)`.
- New view fields: OfferView `price_cents`, `regular_price_cents`, `price_note`,
  `location_id`, `my_title`, `my_price_cents`, `my_terms`, `my_eligibility`;
  ClaimView `title_snapshot`, `price_cents`, `terms`, `eligibility`.
- Lifecycle: exact-deadline expiry (`now >= expires_ts`), idempotent retry,
  cancellation rules, pause keeps existing holds, edits affect future claims only,
  quantity cannot drop below held units, merchants cannot claim.

## Design decisions (please review)

- **Identity = the caller's root id.** Guests run on the shared graph (actor "").
  Mutating endpoints are `def:priv`, so the runtime rejects guests with 401, and
  the helpers recheck the actor anyway.
- **Catalog on `root.shared`.** Nodes a signed-in user creates are private to
  them until granted, which broke cross-user reads (merchant could not see a
  student's claim). Every catalog and claim node is now opened with
  `grant(..., WritePerm)` at creation. Who may read or change what is enforced
  by the checks in `promo.jac`; no endpoint returns raw nodes.
- **Merchant provisioning is server-side only.** Set
  `MLOCAL_MERCHANT_OWNERS="maize-noodle-lab=<root_id>,arbor-leaf-kitchen=<root_id>"`
  in the server's environment. There is no endpoint that assigns a role.
- **Concurrency: single server process only.** Each mutating endpoint holds one
  process-wide lock from its first read until `commit()` has persisted the
  change. Proven with 20 simultaneous requests on one `jac start` process. This
  is **not** safe with multiple workers or replicas; do not claim that.

## Needs from other owners

**Engineer 4 (UI):** `main.jac` must migrate with this PR; it fails `jac check`
until then (lines 194, 229, 238, 241, 261, 273, 279, 327, 342, 354).

- Drop the `student` and `mKey` arguments from every call:
  `list_offers(price, win, diets)`, `get_offer(id, price, win, diets)`,
  `claim_offer(id)`, `merchant_portal()`, `update_profile(name, ...)`,
  `save_offer(offer_id, title, ...)`, `set_offer_status(id, status)`,
  `redeem_code(code)`.
- Remove the `MERCHANTS` key picker; use `current_session()` for role and name.
- Add `current_session` and `cancel_claim` to both import lists.
- Show `my_title` / `my_price_cents` / `my_terms` for an existing claim, and
  `price_note` near prices. Authenticated calls without a login fail with
  "Unauthorized"; send the user to sign in.

**Engineer 3 (data):** no blocker. When convenient:
- Set `price_cents` / `regular_price_cents` in the importer with
  `money_to_cents` (backfill covers it until then).
- Attach imported restaurants to `root.shared` (currently `root`; I re-home them).
- Drop `merchant_key` from seed records. The importer already ignores an
  `owner_actor_id` key (tested).
- `seed_demo` and `import_restaurant` are plain `def`, so they would become
  authenticated API endpoints if the entry module ever imports them. Keep them
  out of `main.jac` imports or rename with a leading underscore.

**Engineer 1 (runtime/release):**
- Jac 0.34.20 works for the server and tests; 0.37.21 is not required.
- Demo accounts: register merchant users, read each `root_id` from
  `/user/login`, restart the server with `MLOCAL_MERCHANT_OWNERS` set.
- Deploy as a single process.

## Still open

- Attach Engineer 3's `access_context` to OfferView once the context DTO/helper
  lands (`location_id` is already populated).
- The JWT/session secret and token expiry are runtime configuration (Engineer 1).
- `jac check` reports warnings, not errors, in `promo.jac`; they are pre-existing
  styles (untyped `any` returns, `tuple`).
