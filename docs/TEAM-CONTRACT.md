# Shared implementation contract v2: QR redemption

This is the target agreed by the task split, not a description of the current code.
Engineer 1 coordinates changes; Engineer 2 owns core API/schema decisions; Engineer
3 owns context types; Engineer 4 consumes both. An owner proposes a changed signature
in their PR and informs the humans affected before callers are changed.

## Ownership

| Owner | Allowed production files |
|---|---|
| 1 | `jac.toml`, dependency lock/version files, `README.md`, `AGENTS.md`, `TEAM-HANDOFF.md`, `.gitignore`, `scripts/**`, `.github/workflows/**`, `tests/integration/**`, release/runtime docs |
| 2 | `services/models.jac`, `services/promo.jac`, `services/promo.test.jac`, new `services/session.jac`, `services/session.test.jac`, `services/money.jac` |
| 3 | `services/importer.jac`, `services/seed.jac`, new `services/context_models.jac`, `services/context.jac`, `services/context.test.jac`, `data/**`, `docs/data/**` |
| 4 | `main.jac`, `theme.jac`, new `client/session.cl.jac`, `tests/ui/**`, `docs/phone-validation.md` |

Each engineer may update their own mission checklist and `docs/status/engineer-N.md`.
Engineer 1 owns shared planning documents after this handoff. No one rewrites the
extraction manifest or baseline verification to pretend new code matches the export.
If a fix belongs to another owner's file, send the human owner the failing case and
proposed change. Do not silently expand the edit scope.

## Runtime and interface checkpoint

Engineer 1 first publishes a verified runtime pin and exact commands in
`docs/RUNTIME.md`. Start by reproducing the generated 0.34.20 environment in isolation;
do not overwrite another project runtime. If unavailable, select one supported
version and coordinate a bounded migration with the source owners. Test the actual
MobUI app and built-in authentication hooks before declaring compatibility.

Runtime checkpoint update (2026-09-26): Travis authorized upgrading to latest.
The selected pin is **0.37.23**; local startup, core tests and a production build
are verified in `docs/RUNTIME.md`. Use that pin rather than repeating the original
0.34.20 experiment. Authentication hooks and Mac/physical-phone execution are
still separate unverified gates, detailed in `docs/status/engineer-1.md`.

The generated `jac start` instructions are version-specific. Do not give every
engineer a different runtime or let each model independently upgrade dependencies.
Until the checkpoint, engineers can inspect code and prepare fixtures, tests and UI
states; runtime-dependent implementation waits for the selected toolchain.

Engineer 1 also proves the installed runtime's client sign-in/sign-out helpers,
server principal access, and shared/private graph behavior with two local accounts.
Record the exact exports and imports in `docs/RUNTIME.md`. Use built-in supported
authentication; do not invent bearer-token protocols to bypass an unknown runtime.

## Core API: Engineer 2 produces, Engineer 4 consumes

These signatures describe the public Jac functions after the identity migration.
Remove caller-supplied merchant keys and student identity from the interface.
Existing tests and callers must migrate together. All unlisted DTO fields remain
compatible with the baseline until both owners agree otherwise.

```text
current_session() -> SessionView
list_offers(max_price: str = "", window: str = "any", diets: str = "") -> list[OfferView]
get_offer(offer_id: str, max_price: str = "", window: str = "any", diets: str = "") -> OfferView | None
claim_offer(offer_id: str) -> ActionResult
cancel_claim(offer_id: str) -> ActionResult
merchant_portal() -> MerchantView
update_profile(name: str, cuisine: str, blurb: str, address: str, neighborhood: str,
               entrance_note: str, note_date: str) -> MerchantView
save_offer(offer_id: str, title: str, description: str, price: str,
           regular_price: str, start_local: str, end_local: str, quantity: str,
           eligibility: str, terms: str, dietary: str, menu_item: str) -> ActionResult
set_offer_status(offer_id: str, status: str) -> ActionResult
redeem_claim(qr_payload: str) -> ActionResult
offer_defaults() -> list[str]
```

`SessionView`: `authenticated: bool`, `actor_id: str`, `role: str` (guest, student,
merchant), `restaurant_id: str`, `display_name: str`, `is_demo: bool`.
The server supplies all identity and ownership fields. Guest browsing returns no
personal claim credentials. A student cannot become a merchant by submitting a role or ID.
`ActionResult` supplies `ok: bool`, `message: str`, `claim_id: str`, `qr_payload: str`.
Engineer 2 coordinates the DTO migration with Engineer 4. Current `code` and
`my_code` fields are legacy implementation details, not the approved user flow.

## Approved QR decision (2026-09-26)

The team explicitly chose **QR codes instead of displaying and typing letters and
numbers**. This decision is approved; it is not yet implemented in the runtime PR.

- Student claims an offer and sees a scannable QR plus human-readable offer terms
  and expiry. Engineer 4 owns rendering, camera scanner and success/error states.
- Engineer 2 supplies a versioned, high-entropy opaque redemption credential bound
  to a durable claim. It contains no student PII, merchant key or authoritative
  price. Public browsing and other students must not receive another claim's payload.
- Merchant scans, sees the server-resolved offer/terms, and confirms redemption.
  Repeated camera detections must not issue uncontrolled mutation requests.
- Jac validates the authenticated merchant's ownership, expiry and unredeemed state
  atomically. Encoding an ID in QR is not authentication or single-use enforcement.
- An idempotent claim retry returns the same live claim and QR payload. Expired,
  cancelled, malformed, wrong-merchant and already-redeemed payloads are rejected.
- Freeze `qr_payload`'s version/format in Engineer 2's small interface PR before
  frontend rendering/scanning is wired. No external URL in a scanned QR is opened
  automatically. No manual-code UX should silently be reintroduced.
- Engineer 1 supplies the phone/secure-origin test path. A student can display QR
  over the current LAN preview; in-browser camera scanning on a remote phone needs
  HTTPS. A merchant laptop at localhost is the simplest initial camera test host.
  Verify real iPhone Safari and Android support; do not assume BarcodeDetector exists.

This supersedes code-entry language in older plans. Preserve historical numeric-code
test evidence as historical evidence, not as proof the QR implementation is done.

Engineer 2 adds `owner_actor_id: str` to Restaurant for one-owner membership in this
slice. Only trusted local account provisioning assigns it; record imports and public
profile edits cannot set it. The current `merchant_key` field is retired from access
control. Engineer 3 removes those keys from new committed seed records.

Engineer 4 supplies the client adapter `client/session.cl.jac`:
`signIn(email: str, password: str) -> SessionView`, `signOut() -> None`, and
`loadSession() -> SessionView`. It delegates credential/session handling to the
runtime-supported client helpers proved by Engineer 1. `loadSession` calls the
server's `current_session`. Never log passwords or tokens. Self-service registration
is deferred; use distinct pre-provisioned demo accounts with privately shared
credentials and server-owned restaurant membership.

All clients must see the same intended public offer catalog while private claims
and merchant writes stay owner-scoped. Do not assume Jac's `root` means a global
shared graph after authentication is added; prove this with two sessions.

## Price and claim contract

Engineer 2 adds authoritative integer `price_cents` and `regular_price_cents` fields
to Offer/MenuItem. `services/money.jac` provides
`money_to_cents(text: str) -> int`, accepting nonnegative decimal amounts with at
most two fractional digits and rejecting invalid/non-finite input. The API keeps
the existing dollar-string inputs and display-only numeric dollar DTO fields.
Engineer 3 uses the same converter when importing demo/source records.

Add these fields to `Redemption`: `offer_title_snapshot: str`,
`price_cents_snapshot: int`, `terms_snapshot: str`, `eligibility_snapshot: str`.
The existing `expires_ts` is the immutable claim deadline. Add corresponding
`my_title`, `my_price_cents`, `my_terms`, `my_eligibility` to `OfferView` for the
current user's claim. Add `title_snapshot`, `price_cents`, `terms`, `eligibility`
to `ClaimView`. Unclaimed views use empty/default claim fields.

- Offer claimability is `start_ts <= now < end_ts`, active and with stock remaining.
- A hold lasts `min(now + 20 minutes, original offer end)`; at the deadline it expires.
- Retry while an identical actor/offer hold is live returns success with the same
  QR payload and consumes no additional unit. A redeemed offer cannot be claimed again
  by the same actor in this build.
- Cancellation releases a live hold once. Repeated cancellation is harmless;
  cancellation after redemption is rejected. A cancelled/expired hold can be
  replaced by a new claim only while the offer remains claimable.
- Pausing stops new claims. Existing holds retain their original price, terms and
  deadline. Editing offer price, text or end time affects future claims only.
- Quantity cannot fall below active holds plus redeemed units. Confirm the last
  unit using simultaneous HTTP requests, not only sequential helper calls.
- Prefer a supported atomic storage operation. If the runtime only supports a
  verified single-worker serialized mutation path, enforce that deployment limit
  and prove the durable write occurs within it. Do not claim multi-worker safety.
- Eligibility wording is shown; the merchant checks the stated ID condition at
  redemption. Do not claim automatic verification of university enrollment.
- Listed prices exclude tax unless a merchant explicitly includes it. Display
  that limitation; no payment or tax calculation is performed.

## Context API: Engineer 3 produces, Engineer 2 attaches, Engineer 4 displays

Create `ContextNotice` and an `Affects` edge to the existing Location node in
`services/context_models.jac`. Keep these separate from Engineer 2's model file.
Notice identity is `(source_id, external_id)`, with a source version and retained
original/normalized source evidence. Required data: summary, publisher, source URL
(empty only for explicitly simulated fixtures), checked timestamp, validity start
and end, affected location ID, `is_demo`, and optional confirmed entrance instruction.

```text
get_access_context(location_id: str, now_ts: float) -> AccessContextView
```

This is an internal server helper, not a public endpoint accepting a client clock.
`AccessContextView`: `state: str` (current, needs_recheck, none),
`notices: list[AccessNoticeView]`.
`AccessNoticeView`: `id: str`, `summary: str`, `publisher: str`, `source_url: str`,
`checked_at: float`, `valid_from: float`, `valid_until: float`, `state: str`
(current or needs_recheck), `is_demo: bool`, `entrance_instruction: str`.

Engineer 2 adds `location_id: str` and `access_context: AccessContextView` to
OfferView, calling the helper from `_view` with the server clock. One restaurant
has one location for this slice; every offer resolves to that explicit location ID.
Multiple business locations are deferred rather than silently choosing among them.

Engineer 3 publishes these DTOs/helper in a small first PR before completing the
source adapter. The initial helper may return `none` for an empty notice graph;
it must not manufacture current notices. This breaks the dependency cycle between
the core API and context work.

For this build, a notice is current only when `valid_from <= now < valid_until`
and its checked timestamp is no more than 24 hours old and not in the future.
Expired, stale, missing-date or unconfirmed records show `needs_recheck` and cannot
supply a definitive entrance instruction. Empty context means no known notice,
not proof of unobstructed access. A road closure is not evidence of a closed
pedestrian entrance. Only explicit confirmation supports an alternate entrance.

Use a reviewed JSON adapter and an idempotent upsert: a changed version replaces
the same notice, without duplicates; a failed refresh retains the previous record
and its original checked timestamp. No model-invented facts. Live scraping is not
required. Label simulated records and do not link a real notice to a fictional
business as if that association had been verified.

## Stable team commands: Engineer 1 implements

From a cloned repository in WSL Bash (or Bash on a supported teammate machine):

```bash
./scripts/dev.sh
./scripts/check.sh
./scripts/test.sh core
./scripts/test.sh context
./scripts/test.sh integration
./scripts/test.sh all
./scripts/demo.sh
```

Current runtime checkpoint implements dev/check/build and the core test wrapper.
Run `bash scripts/build.sh` with dev stopped to build the `.jab`. Context/integration
and all deliberately return nonzero while downstream suites are missing; demo.sh
is still pending. The API binds to loopback; current Jac's Vite child binds all WSL
interfaces and is reached through `localhost:8000` on Windows. See RUNTIME.md.
Test commands create isolated disposable stores and return nonzero on
failure. `demo.sh` launches a fresh, clearly labeled fixture store without deleting
existing data. Separate invocations must not collide in store or port. Runtime
pinning and client build commands live behind these wrappers, not in four sets of
contradictory instructions. Phone/network exposure is a deliberate integration step.

## Release boundary

No public write-enabled pilot without verified identity/ownership. If that gate
fails, demonstrate locally with explicit limitations and do not call it pilot-ready.
Do not silently replace authentication with the existing merchant-key selector.
No new service spending, live business contacts, secrets in Git, or deployment from
an individual feature branch. The team chooses hosting after the integrated checks.
