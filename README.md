<p align="center">
  <img src="assets/brand/logo-compact.png" alt="M-Local" width="200">
</p>

<p align="center">
  <strong>Time-limited deals from Ann Arbor's local restaurants, for the U-M community.</strong><br>
  Students find and claim offers. Businesses post them, scan the claim QR at the counter, and see what happened.
</p>

<p align="center">
  <a href="https://mlocal.tail0d5ef8.ts.net/"><strong>Open M-Local</strong></a> ·
  <a href="docs/START-HERE.md">Team start here</a> ·
  <a href="docs/HOSTING.md">Hosting</a> ·
  <a href="docs/RUNTIME.md">Runtime</a>
</p>

---

M-Local (codename **PromoPusher**) is a prototype built in [Jac](https://www.jaseci.org/).
It runs as a mobile-first web app through MobUI and react-native-web. Native iOS and
Android packaging has not been verified.

## What it does

| For students | For businesses |
|---|---|
| Sign in with a U-M email and a 6-digit code. No university password is needed. | Sign up with a business email, import details from the business website, review them, then post offers. |
| Pick tastes once. The **For you** feed puts matching deals first and still shows everything else. | **Manage** offers: publish now or schedule a start time, edit, pause and resume. |
| Filter by maximum price, time and diet from one dropdown. | **Redeem** by scanning the student's claim QR, reviewing the saved terms, then confirming. |
| Claim an offer to get a QR pass that holds one unit for 20 minutes. | **Insights** shows claims, redemptions, returning accounts and redeemed value over 7, 30 or 90 days or a year, with a day-by-day replay and a downloadable recap. |

The interface follows the **M Local App v2** design: navy `#02305C`, maize `#FEC809`,
cream `#F9F6F0`, and the bundled Figtree typeface. See the
[UI refresh notes](docs/UI-REFRESH.md) for what matches the design and what
differs on purpose.

## Screenshots

Captured on 2026-09-27 from the current build with fictional test data
(`tests/ui/refresh_visual.py`, 390 px phone width unless noted).

**Getting started**

<table>
  <tr>
    <td align="center" width="25%"><img src="docs/screenshots/welcome.png" alt="Welcome screen with student and business paths" width="190"><br><sub>Choose a path</sub></td>
    <td align="center" width="25%"><img src="docs/screenshots/email.png" alt="Create account with U-M email" width="190"><br><sub>U-M email sign-up</sub></td>
    <td align="center" width="25%"><img src="docs/screenshots/verify.png" alt="Enter the 6-digit email code" width="190"><br><sub>6-digit code</sub></td>
    <td align="center" width="25%"><img src="docs/screenshots/tastes.png" alt="Pick food, diet and spending tastes" width="190"><br><sub>Pick tastes</sub></td>
  </tr>
</table>

**Students**

<table>
  <tr>
    <td align="center" width="25%"><img src="docs/screenshots/discovery.png" alt="For you feed with a deal card" width="190"><br><sub>For you feed</sub></td>
    <td align="center" width="25%"><img src="docs/screenshots/filters.png" alt="Filter dropdown with price, time and diet" width="190"><br><sub>Filters</sub></td>
    <td align="center" width="25%"><img src="docs/screenshots/offer.png" alt="Offer detail with claim button" width="190"><br><sub>Offer detail</sub></td>
    <td align="center" width="25%"><img src="docs/screenshots/claim.png" alt="Claim pass with QR code and hold countdown" width="190"><br><sub>Claim QR pass</sub></td>
  </tr>
</table>

**Businesses**

<table>
  <tr>
    <td align="center" width="25%"><img src="docs/screenshots/insights.png" alt="Business Insights on a phone" width="190"><br><sub>Insights</sub></td>
    <td align="center" width="25%"><img src="docs/screenshots/merchant.png" alt="Manage offers and restaurant profile" width="190"><br><sub>Manage offers</sub></td>
    <td align="center" width="25%"><img src="docs/screenshots/editor.png" alt="New offer form" width="190"><br><sub>New offer</sub></td>
    <td align="center" width="25%"><img src="docs/screenshots/scanner.png" alt="Scan a student's claim QR" width="190"><br><sub>Scan to redeem</sub></td>
  </tr>
</table>

<p align="center">
  <img src="docs/screenshots/insights-desktop.png" alt="Business Insights at desktop width with metrics and a cumulative redemptions chart" width="820"><br>
  <sub>Business Insights at desktop width (1440 px)</sub>
</p>

## Live app

**Portfolio reviewers:** start with the [project brief](docs/PORTFOLIO.md) for
the team attribution, architecture, demo walkthrough and current hosting limits.

**[Open M-Local](https://mlocal.tail0d5ef8.ts.net/)**, hosted on Travis's laptop.

This is a shared prototype, not an always-on production service. Availability
depends on the laptop. See the dated [release checkpoint](docs/PORTFOLIO.md#release-checkpoint)
before presenting a live demo.

- The host checks `main` every minute. It deploys a new commit after CI passes and
  a rebuild succeeds, and it keeps existing accounts and data.
- Refresh your phone after a deployment.
- Commits on other branches and local edits do not deploy.

[Start and stop, update behavior, and troubleshooting](docs/HOSTING.md)

**Phone demo from your own machine:** on Windows, double-click
**Start Phone Demo.cmd** for an HTTPS link, keep the host awake, and use
**Stop Phone Demo.cmd** to stop sharing. [Phone link setup](docs/PHONE-LINK.md)

## Quick start

From this checkout in **WSL Bash**:

```bash
bash scripts/setup.sh    # first machine setup: installs the pinned Jac runtime
bash scripts/dev.sh      # local web app at http://localhost:8000
```

On Travis's prepared machine, use `.\scripts\dev.ps1` from **PowerShell**.
The development server recompiles `.jac` files as you edit. Demo data seeds itself
the first time an endpoint runs. **Never reset the shared demo database.**

Email delivery needs a configured sender, and AI extraction for business import
is optional. See [email and business signup setup](docs/ONBOARDING.md).

## Checks

```bash
bash scripts/check.sh        # type-check and lint every Jac source
bash scripts/test.sh core    # core, QR and provisioning tests in an isolated store
bash scripts/build.sh        # production build
```

CI (`.github/workflows/check.yml`) runs these plus the insights, onboarding,
deployment-safety and compiled-UI suites on every push and pull request. The
hosted app only deploys a `main` commit that passed.

**Latest local results (2026-09-27, UI refresh branch):**

| Check | Result |
|---|---|
| Type check (`scripts/check.sh`) | Passed |
| Production build (`scripts/build.sh`) | Passed |
| Core, QR and provisioning tests | 194 passed |
| Compiled UI, tooling and insights tests | 113 passed |
| Browser screenshots at 320, 390 and 1440 px | 28 captured, 0 page errors |

These runs used an isolated store and fake server responses. Real email delivery,
physical cameras and physical phones are checked separately.

## Rules the server enforces

- **Sign-in.** Accounts verify an emailed code through Jac's built-in auth. Business
  calls only reach offers and claims that belong to that account's restaurant.
  The app does not verify university enrollment; the business checks the stated ID
  requirement at the counter.
- **Offer windows.** Offers can be claimed only between their start and end, and
  never while paused.
- **Quantity.** `remaining = quantity − redeemed − live claims`. Quantity can't be
  set below the units already held or redeemed.
- **Claim holds.** A claim holds one unit for 20 minutes (`CLAIM_HOLD_MINUTES`) or
  until the offer ends, whichever comes first. An expired hold returns its unit.
- **One claim each.** An account gets one live or redeemed claim per offer. Claiming
  again shows the existing QR, and each QR redeems once.
- **Saved terms.** A claim keeps the price, terms and expiry it was claimed with,
  even if the business edits the offer later.
- **Matching** is deterministic: tastes, budget, time and diet. No external model call.

## Project layout

| Path | Role |
|---|---|
| `main.jac` | App shell, screens and tab bar (MobUI) |
| `theme.jac` | Design tokens and shared styles |
| `client/` | React components: onboarding, filters, QR pass and scanner, offer editor, account, insights |
| `services/models.jac` | Graph schema: restaurants, locations, menu items, offers, claims |
| `services/promo.jac` | Offer and claim rules and the public API |
| `services/qr*.jac` | QR claim payloads, scan preview and redemption |
| `services/foryou.jac`, `services/taste.jac` | Personalized feed and saved tastes |
| `services/onboarding.jac`, `services/business_onboarding.jac` | Email sign-in and business signup |
| `services/analytics.jac` | Business Insights metrics |
| `services/importer.jac` | `import_restaurant(record)`, the single data-import boundary |
| `tests/` | UI, analytics, onboarding and tooling suites |

Graph: `Restaurant -HasLocation-> Location`, `-Serves-> MenuItem`,
`-Publishes-> Offer -Features-> MenuItem`, `Offer -ClaimedAs-> Redemption`.

## Versions

| Component | Version |
|---|---|
| Jac | **0.37.23**, pinned in `jac.toml` and `.jac-version` |
| JavaScript runtime | Bundled Bun 1.3.11 |
| Vite | 6.4.3 |
| react / react-dom | 18.3.1 |
| react-native-web | 0.19.13 |

Data lives in Jac's embedded PostgreSQL graph store. The [runtime guide](docs/RUNTIME.md)
covers installation, data isolation and the Windows network fallback.

## For the team

- [Start here](docs/START-HERE.md): mission, impact goals and engineering assignments
- [Team contract](docs/TEAM-CONTRACT.md) and [parallel workflow](docs/TEAM-WORKFLOW.md): read before implementing
- [Work handoff](docs/WORK-HANDOFF.md): current decisions and context
- [QR redemption](docs/QR-REDEMPTION.md): setup and acceptance checks
- [Business Insights](docs/BUSINESS-INSIGHTS.md): metric definitions, limits and checks
- [Release checklist](docs/RELEASE-CHECKLIST.md)

## Not built yet

Payments, notifications, live routing, garage-sale listings, and automatic business
approval. New community data sources plug in by producing records for
`import_restaurant`.
