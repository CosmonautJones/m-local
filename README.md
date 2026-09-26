# PromoPusher (prototype)

**Hackathon team: [start here](docs/START-HERE.md).** The mission, impact goals,
four engineering assignments and copy-ready model prompts are documented there.
Read the [shared contract](docs/TEAM-CONTRACT.md) and
[parallel workflow](docs/TEAM-WORKFLOW.md) before implementing. These are planned
changes; see the [verified local runtime](docs/RUNTIME.md) and
[current results](docs/status/engineer-1.md) before implementing.

Mobile-friendly Ann Arbor app connecting students with time-limited restaurant offers.
The Jac source runs locally as a web app using MobUI/react-native-web.
Native iOS/Android packaging has not been verified.

**Team decision:** the next redemption flow uses QR scanning instead of typed
letters/numbers. That work is specified in [contract v2](docs/TEAM-CONTRACT.md)
and the [ChatGPT Work handoff](docs/WORK-HANDOFF.md); the current running baseline
still uses the legacy code-entry flow described in the walkthrough below.

## Versions (recorded 2026-09-26)

| Component | Version |
|---|---|
| Jac | **0.37.23**, pinned in `jac.toml` and `.jac-version` |
| JavaScript runtime | Bundled Bun 1.3.11 |
| Vite | 6.4.3 |
| react / react-dom | 18.3.1 |
| react-native-web | 0.19.13 |

Persistence uses Jac's embedded PostgreSQL graph store. The [runtime guide](docs/RUNTIME.md)
covers installation, data isolation and the Windows-network fallback.

## Setup

From this checkout in **WSL Bash**:

```bash
bash scripts/setup.sh       # first machine setup; installs the pinned Jac runtime
bash scripts/dev.sh         # http://localhost:8000
```

On Travis's prepared machine, use `.\scripts\dev.ps1` from **PowerShell**.
Edit `.jac` files locally and let the development server recompile them.
Demo data seeds itself when an endpoint first runs. Do not reset shared demo data.
JacHammer is not required to build or run this checkout.

## Layout

| File | Role |
|---|---|
| `services/models.jac` | Graph schema: Restaurant, Location, MenuItem, Offer, Redemption + edges |
| `services/promo.jac` | Business rules and `def:pub` API (all enforcement is here) |
| `services/importer.jac` | `import_restaurant(record)`: the single data-import boundary |
| `services/seed.jac` | Three fictional "(Demo)" businesses and labeled demo offers |
| `services/promo.test.jac` | Rule checks |
| `theme.jac` | Design tokens and StyleSheet |
| `main.jac` | Entire MobUI interface (4 screens + tab bar) |

Graph: `Restaurant -HasLocation-> Location`, `-Serves-> MenuItem`, `-Publishes-> Offer -Features-> MenuItem`, `Offer -ClaimedAs-> Redemption`.

## Rules (server-enforced)

- **Roles.** Students identify by name/ID; merchants by a per-restaurant merchant key
  (`noodle-demo`, `leaf-demo`, `dough-demo`). Every merchant call resolves the key to one
  restaurant and only touches offers/claims reachable from it. This is a prototype
  stand-in for real accounts.
- **Expiration.** Offers claimable only between start and end and when not paused.
- **Quantity.** `remaining = quantity - redeemed - live claims`. Quantity cannot be edited
  below units already held.
- **Claim expiration.** A claim holds one unit for **20 minutes** (`CLAIM_HOLD_MINUTES`) or
  until the offer ends, whichever is sooner. An unredeemed claim past that time becomes
  `expired`, its unit returns to availability, and its code can no longer be redeemed.
- **Duplicates.** One live or redeemed claim per student per offer; each code redeems once.
- **Matching** is deterministic (budget, time window, dietary tags). No external model call.
  The details screen explains each factor in plain language.

## Demo walkthrough

1. **Offers** tab: five demo offers (one paused offer is hidden). Tap "Under $5", "Right now"
   or "vegan" to filter.
2. Open "Harvest bowl for $8": read "Why this matches you", terms, eligibility and location.
   Diag Dough and Noodle Lab show dated entrance/construction notes.
3. Tap **Claim this offer**: a 6-character code appears and availability drops by one.
   Claiming again is refused.
4. **Redeem** tab: choose "Arbor Leaf", enter the code, tap **Redeem code**. Redeeming it
   again is refused; choosing "Noodle Lab" and entering the same code is refused.
5. **Manage** tab: edit the profile (entrance note + date), create a new offer, edit one,
   pause/resume. Paused offers disappear from discovery.

## Checks

```bash
bash scripts/check.sh
bash scripts/test.sh core
```

Seven core rule tests pass in an isolated test workspace. They cover idempotent seeding,
merchant isolation (redeem + edit), expired and
not-started offers, exhausted quantity, abandoned-claim release, repeated redemption, paused
offers, filters and match explanations. This does not prove concurrent HTTP safety or
real authentication. See the verification record for browser/restart evidence.

## Deferred

Payments, notifications, live routing, external data ingestion, garage-sale listings and
real authentication. New community sources plug in by producing records for
`import_restaurant`.
