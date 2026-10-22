# Changelog

All notable changes to M-Local are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
`0.1.0` is the first versioned release; earlier work was merged untagged. A
version number does not mean a host is live: nothing listed here has been
deployed or accepted on a live host yet. See the
[gate matrix](docs/RELEASE-GATES.md) and
[acceptance checklist](docs/RELEASE-ACCEPTANCE.md).

## [Unreleased]

## [0.1.0] - 2026-10-21

First versioned release. It contains everything merged to `main` through
[#72](https://github.com/CosmonautJones/m-local/pull/72): the #60-#71 stack
below (merged 2026-10-21), the untagged 2026-10-13 student and merchant
candidate (#55, #59), and the earlier prototype work (#1-#32: Jac runtime and
trusted QR claims, verified email signup and business onboarding, "For you"
tastes and favorites, business Insights sales charts, themed Jac UI, and
laptop/phone demo hosting). Release acceptance is still pending.

### Added
- Build identity: the release gateway serves `/build`, `/version.json` and an
  `X-MLocal-Build` header, so you can tell which verified package a host is
  running ([#69](https://github.com/CosmonautJones/m-local/pull/69),
  [#70](https://github.com/CosmonautJones/m-local/pull/70)).
- Opt-in PostgreSQL proofs showing onboarding, signing keys and photo ownership
  can live in one PostgreSQL database without losing data
  ([#63](https://github.com/CosmonautJones/m-local/pull/63)-[#66](https://github.com/CosmonautJones/m-local/pull/66)).
- A disposable `postgres-local` startup mode for rehearsing a packaged app against
  restored SQL state. It refuses to run in production
  ([#68](https://github.com/CosmonautJones/m-local/pull/68)).
- `psycopg[binary]==3.3.6` is now a pinned app dependency (used only when SQL mode
  is explicitly selected).
- README quick start, how-it-works diagram and hero illustration
  ([#71](https://github.com/CosmonautJones/m-local/pull/71)).

### Changed
- Offline release preflight now uses the same checks as real startup, so it can
  no longer pass a package or configuration that startup would refuse
  ([#61](https://github.com/CosmonautJones/m-local/pull/61)).
- Onboarding, QR and photo helpers use the selected SQL authority when one is
  explicitly chosen, so stale local SQLite data cannot override it
  ([#64](https://github.com/CosmonautJones/m-local/pull/64),
  [#65](https://github.com/CosmonautJones/m-local/pull/65)).
- Access eligibility is documented: anyone who can verify a `@umich.edu` inbox,
  including alumni. This proves inbox access, not enrollment
  ([#62](https://github.com/CosmonautJones/m-local/pull/62)).
- Refreshed the recorded fingerprints of public CA certificate bundles after
  upstream certifi, pip and botocore releases.

### Security
- Coordinated recovery only restores the exact release package it recorded and
  refuses a substituted one ([#60](https://github.com/CosmonautJones/m-local/pull/60)).
- PostgreSQL schemas that were weakened or tampered with are refused before any
  app data is read ([#67](https://github.com/CosmonautJones/m-local/pull/67)).

### Removed
- Contact-research data files are no longer tracked in the public source tree
  (kept privately) and new release packages refuse them
  ([#62](https://github.com/CosmonautJones/m-local/pull/62)). They still exist in
  older Git history.

## 2026-10-13 - Student and merchant release candidate (untagged, included in 0.1.0)

Merged to `main` via [#55](https://github.com/CosmonautJones/m-local/pull/55) and
[#59](https://github.com/CosmonautJones/m-local/pull/59). Hosted and human
acceptance of this candidate was not completed.

### Added
- Students can browse offers before signing in. A selected offer carries through
  email-code sign-in and reload. Claims produce a QR pass with saved terms and
  expiry, and the pass can be recovered later.
- Businesses go through manual approval, then manage profile and offer photos
  (phone upload or website thumbnail), recoverable drafts and safe publication
  retries.
- Operators can suspend and reinstate a merchant, with an audit record of who did
  it, when and why. Suspended merchants are hidden and cannot publish, take new
  claims or redeem. Existing claims keep their original terms.
- Narrow-screen guest header fix (from #58).

### Security
- Native identity hardening and refusal of unsafe startup configuration (from #56).

[Unreleased]: https://github.com/CosmonautJones/m-local/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/CosmonautJones/m-local/releases/tag/v0.1.0
