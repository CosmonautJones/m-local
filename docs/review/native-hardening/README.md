# Native hardening evidence

This package records isolated engineering checks for the hardening branch based
on release-readiness `c581d142a08f733e0ebc0324ff6987a9d12c8f8b`, preserving the
original untested checkpoint `220f4045136751b6e972a3297542cb9a937a3298`.
The final native receipt records every tested input digest. The coordinator must
bind that manifest to the integrated candidate and run its complete CI gates.

## Changes and independent review resolutions

- Removed all automatic native identity deletion. Missing onboarding state never
  establishes disposability. The original collision refusal and matching pending
  provisioning-marker recovery remain. See
  [the operator reconciliation procedure](../../IDENTITY-RECONCILIATION.md).
- Implemented the missing production startup helper. Invalid production settings
  terminate the real native process with status 78, before it can continue serving
  after a swallowed Jac module-import error. Development remains usable.
- Require an explicit PostgreSQL database, mounted coordinated state, existing
  onboarding/database/signing state, SMTP and deployment policy. Every selected
  storage leaf is checked against its actual backing mount; required files cannot
  escape through symlinks. This addresses the independent durability review.
- Preserve the effective existing `JAC_DATA_PATH` signing state and refuse an
  incompatible signing override. Malformed TOML signing types produce redacted
  setting-name diagnostics rather than a Python traceback.
- Native fixture helpers load only from the sealed tested copy. It verifies both
  official runtime binary hashes and an unchanged input manifest. This addresses
  the independent source-binding review.
- Include the coordinator-approved ingress dependencies from
  `d19c573d0a97a594a5c646f93f152b39a6c50303`. Readiness checks the official native
  `/healthz/ready` JSON contract before the anonymous feed.

## Verification

Run these in WSL Bash with the repository's official pinned runtime wrappers:

```bash
bash scripts/python.sh -m unittest discover -s tests/onboarding -p test_production_guard.py
bash scripts/python.sh -m unittest discover -s tests/onboarding
MLOCAL_HARDENING_DURABLE_BASE=<mounted-disposable-test-volume> \
  bash scripts/test-native-hardening.sh --receipt <receipt-path>
```

- `production-guard-unit.txt`: 22 tests pass, including ephemeral nested mounts,
  escaped required files, incomplete SQLite state, effective signing overrides
  and malformed TOML signing settings.
- `onboarding-unit.txt`: 99 tests pass, including preservation, returning sign-in,
  SQLite challenge concurrency, SMTP and existing onboarding behavior.
- `verification.json` and `native-http.txt`: final actual native-server proof.
  The receipt records status, count, duration, source digests, exact official
  runtime hashes, local TLS SMTP and owned-process cleanup. It reproduces native
  unverified registration, denies inappropriate public native access, preserves
  real pending/redeemed claims, snapshots, root IDs, credentials, preferences,
  merchant ownership and original keys through repeated/concurrent email proofs.
  It also proves invalid/unmounted production process refusal and valid mounted
  production session/catalog readiness.
- `source-seal.json`: final input digest comparison against the branch's working
  source and exact approved ingress dependency bytes.

Official Linux x86_64 v0.37.23 assets, matched to the separately retained public
release checksum files:

| Asset | SHA-256 |
| --- | --- |
| Jac | `2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad` |
| JacPython | `198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542` |

The checksum files were obtained from the official
[v0.37.23 release](https://github.com/jaseci-labs/jac/releases/tag/v0.37.23).

## Preserved failing-first and intermediate receipts

- `failing-first-guard-import.txt`: the original direct import failed because
  `exit_unless_production_ready` did not exist.
- `failing-first-identity.txt`: the unsafe checkpoint attempted eight native user
  deletions in the preservation regression. `passing-identity.txt` records the
  fixed focused suite; the final full onboarding suite includes these tests.
- `failing-first-nested-storage.txt`: the earlier guard accepted nested ephemeral
  storage and required-file escapes. Those cases now fail configuration validation.
- `failing-first-auth-type.txt`: malformed signing TOML exposed an AttributeError;
  the final guard regression covers four malformed shapes with redacted refusal.
- `initial-readiness-fixture-failure.txt`: the first fixture used an incorrect
  `HomeView.offers` expectation. It was corrected to the actual `items` contract
  without increasing readiness timeouts.
- `prior-gateway-checkpoint.*`: an intermediate native proof reached 30 checks
  but the gateway used an incorrect native readiness URL. The ingress owner fixed
  the canonical URL and strict bounded JSON contract before the final rerun.
- `prior-typed-config-checkpoint.*`: the earlier 48-check native pass, preserved
  before the final malformed-signing-configuration fix and fresh native rerun.

Receipts contain source hashes and disposable fixture diagnostics. They do not
include passwords, OTPs, tokens, QR credentials or signing-key values.

## Scope and remaining gates

All state, accounts, PostgreSQL clusters, ports and TLS SMTP deliveries used here
are disposable; the fixture refuses inherited database/runtime overrides. It
preserves failed workspaces privately for diagnosis and removes only its verified
owned successful directories. No live data was changed and no real email was sent.

The mounted local volume proves startup's filesystem contract; provider durability,
remote backup/restore, hosted ingress, actual inbox delivery, physical-device checks
and supported runtime transaction topology remain release acceptance gates. The
fixture expressly sets those acceptance flags to false. SSO and provisioned
identity variants have preservation unit regressions; no live SSO provider journey
was executed. This package does not grant merge or deployment approval.
