# Engineer 2 status: trusted offer transactions

Branch: `feat/02-offer-trust` (includes Engineer 1's `feat/01-runtime-release`;
merge that PR first, then this one).
Runtime: Jac **0.37.23**, the team pin. Contract: **v2 (QR redemption)**.

## Now works, with evidence

- `bash scripts/test.sh core` (Engineer 1's isolated-store runner): **31 passed**.
- `jac test services/session.jac`: **2 passed**. `scripts/test.sh` does not run
  this file yet; see "Needs from Engineer 1".
- HTTP checks against a real `jac run --serve` server with real registered
  accounts: **37/37 passed on every run**. That is 5 runs with the default
  worker count (several processes) and 1 run with `--workers 1`, the last two
  against a fresh clone of this exact branch.

| HTTP check | Result |
|---|---|
| Guest `claim_offer`, `preview_claim`, `redeem_claim`, `merchant_portal` | 401 from the runtime |
| Session actor id | Equals the `root_id` returned by `/user/login` |
| Unprovisioned account | Student only; no portal |
| Provisioned merchant | Merchant session and own portal; cannot claim |
| Claim | Returns a `mlocal:v1:` QR payload (42 characters) |
| Retry | Same claim id and QR payload, no extra unit |
| Private claims | Other student and guest see no QR, claim id or claim terms |
| Other merchant | Cannot preview, redeem ("different restaurant") or edit |
| Student with a QR | Cannot redeem |
| Malformed or URL payload | Rejected |
| Stable terms | Offer edited after the claim; preview and redemption use the claimed price |
| Double redemption | Rejected |
| **5 simultaneous scans of one QR** | Redeemed exactly once |
| **20 simultaneous students, last unit** | Exactly one winner; offer shows sold out |
| 10 simultaneous retries by one student | One claim, one unit |
| Cancel | Releases the unit |
| Restart | Redemption, sold-out stock, edited price and merchant role persist |
| First caller signed in | Seeded catalog still lands in the shared catalog |

The HTTP script and its API-only entry file are attached to the PR for
Engineer 1 (they belong under `tests/integration/`, which Engineer 1 owns).

## Core API (produced for Engineer 4)

```text
current_session() -> SessionView                                   :pub
list_offers(max_price="", window="any", diets="") -> list[OfferView] :pub
get_offer(offer_id, max_price="", window="any", diets="") -> OfferView | None  :pub
offer_defaults() -> list[str]                                      :pub
claim_offer(offer_id) -> ActionResult                              :protect
cancel_claim(offer_id) -> ActionResult                             :protect
merchant_portal() -> MerchantView                                  :protect
update_profile(name, cuisine, blurb, address, neighborhood, entrance_note, note_date) -> MerchantView  :protect
save_offer(offer_id, title, description, price, regular_price, start_local, end_local,
           quantity, eligibility, terms, dietary, menu_item) -> ActionResult   :protect
set_offer_status(offer_id, status) -> ActionResult                 :protect
preview_claim(qr_payload) -> ClaimCheck                            :protect
redeem_claim(qr_payload) -> ActionResult                           :protect
```

- `ActionResult`: `ok`, `message`, `claim_id`, `qr_payload`. For `save_offer`,
  `claim_id` carries the saved offer's id.
- `OfferView` adds `price_cents`, `regular_price_cents`, `price_note`,
  `location_id`, `my_claim_id`, `my_qr_payload`, `my_status`, `my_expires`,
  `my_title`, `my_price_cents`, `my_terms`, `my_eligibility`. `my_code` is gone.
- `ClaimView` has `claim_id` (replaces `code`), `title_snapshot`,
  `price_cents`, `terms`, `eligibility`.
- `ClaimCheck` (new, for the scan screen): `ok`, `message`, `claim_id`,
  `status`, `restaurant`, `title_snapshot`, `price_cents`, `terms`,
  `eligibility`, `expires_label`.
- `SessionView`: `authenticated`, `actor_id`, `role` (guest, student,
  merchant), `restaurant_id`, `display_name`, `is_demo`.

### QR payload format (frozen as v1)

`mlocal:v1:` followed by 32 URL-safe base64 characters (192 random bits).
It is not a URL, so phones will not try to open it, and it carries no student
data, merchant key or price. Treat it as opaque: render it as a QR, and send
exactly what the scanner read to `preview_claim`, then `redeem_claim`.
Surrounding whitespace is tolerated.

Suggested scan flow: on detection, stop scanning and call `preview_claim`
once. Show `ClaimCheck` (title, price, terms, eligibility). Only an explicit
"Confirm" tap calls `redeem_claim`. Repeat taps are safe: the second is
rejected as already redeemed.

## Design decisions (please review)

- **Identity = the caller's root id.** Guests run on the shared graph (actor "").
  Mutations are `def:protect`, so the runtime returns 401 for guests, and the
  helpers recheck the actor anyway. Plain defs are private in 0.37 and never served.
- **Catalog on `root.shared`.** Nodes a signed-in user creates are private until
  granted, which hid students' claims from merchants. Catalog and claim nodes
  are opened with `grant(..., AccessLevel.WRITE)` at creation. Who may read or
  change what is enforced in `promo.jac`; no endpoint returns raw nodes.
- **Merchant provisioning is server-side only.** Set
  `MLOCAL_MERCHANT_OWNERS="maize-noodle-lab=<root_id>,arbor-leaf-kitchen=<root_id>"`
  in the server's environment. No endpoint assigns a role.
- **Concurrency.** 0.37 serves with several worker processes on Postgres. Each
  mutation takes an exclusive OS file lock, calls `commit()` to start a fresh
  transaction (so it sees the previous holder's writes), and commits again
  before unlocking. Proven with simultaneous requests under the default worker
  count. This covers **one machine** only; several machines would need a
  shared lock. Do not claim multi-machine safety.

## Needs from other owners

**Engineer 4 (UI):** `main.jac` must migrate before this reaches a demo. It
currently fails `jac check` with 17 errors, all API migration:
9 x too many arguments, 5 x `my_code`, 2 x `ClaimView.code`, 1 follow-on.

- Drop the `student` and `mKey` arguments from every call.
- Remove the `MERCHANTS` key picker; use `current_session()` for role and name.
- Replace code display and entry with QR: show `my_qr_payload` as a QR, and
  build the scan -> `preview_claim` -> confirm -> `redeem_claim` flow.
- Show `my_title` / `my_price_cents` / `my_terms` for an existing claim, and
  `price_note` near prices.
- A `:protect` call without a login fails with "Unauthorized"; send the user to sign in.

**Engineer 3 (data):** no blocker. When convenient:
- Set `price_cents` / `regular_price_cents` in the importer with
  `money_to_cents` (a backfill covers it until then).
- Attach imported restaurants to `root.shared` (currently `root`; I re-home them).
- Drop `merchant_key` from seed records. The importer ignores an
  `owner_actor_id` key (tested).

**Engineer 1 (runtime/release):**
- Add `services/session.jac` to `scripts/test.sh` (`jac test services/session.jac`).
- Adopt the HTTP check under `tests/integration/`.
- Demo accounts: register merchant users, read each `root_id` from
  `/user/login`, restart the server with `MLOCAL_MERCHANT_OWNERS` set.
- Deploy on a single machine.
- `jac clean --data` does not reset the shared embedded Postgres. Isolated
  stores need a distinct project path, as `scripts/test.sh` already does.

## Still open

- Attach Engineer 3's `access_context` to `OfferView` once the context
  DTO/helper lands (`location_id` is already populated).
- JWT/session secret and token expiry are runtime configuration (Engineer 1).
