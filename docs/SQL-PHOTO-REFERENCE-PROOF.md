# SQL-owned photo reference proof

This bounded increment connects existing uploaded-photo references to the
preserved auxiliary SQL fixture through the actual application helpers. It uses
`PostgresAuxiliary.photo_owned` and the established original signing material.
Official Jac **0.37.23**, public RPC shapes and the SQLite default remain pinned.
The [authority proof](AUTHORITY-BACKEND-PROOF.md) is its prerequisite.

## Acceptance recorded before implementation

Acceptance was frozen at `2026-10-16T06:04:12.162858Z` on
`codex/sql-photo-reference-2026-10-16`, based on reviewed PR64 head
`454db70d01e84a4cfad73ac177067d1187cb3dd6`:

- Real `owned_photo`, `image_reference`, `prepare_business_activation` and
  `finish_business_activation` accept an established SQL-owned image reference
  under the existing explicit disposable `postgres-proof` selection.
- SQL ownership and exact validated JPEG content override stale local ownership
  and bytes. Successful reads require no local photo, SQLite registry, key file
  or private directory. Symlink targets and all original files remain untouched.
- Wrong owners, missing records, invalid URLs, corrupt JPEGs/digests, missing
  original keys, damaged audit, incompatible versions and outages refuse without
  repairing state or consulting local fallback. Messages withhold driver details.
- Unknown, incomplete and production selection refuse. Directory, registry,
  normalization/upload and native startup guards remain in place.
- Repeated real activation preparation/completion retains the SQL image URL,
  canonical owner and approval/status/audit authority without changing preserved
  accounts, approvals, reviews, keys or photos. This helper proof performs no
  native graph commit.
- Default SQLite selection imports no optional SQL driver, including through the
  new internal ownership selector. No new RPC, environment setting or adapter API
  is introduced.

The 39 prior SQL test methods and their setup remain unchanged; six preservation
regressions bring the exact inventory to 45. A passing default-discovery skip is
not SQL evidence. Failing-first and final exact-head receipts, real named test
outcomes and independent review must accompany the PR.

## Meaning of a returned URL

A returned `/static/photos/<32 lowercase hex>.jpg` proves SQL ownership and
validated stored content in this fixture. It does **not** prove that an HTTP
server can deliver that URL. This increment neither writes an upload nor builds,
repairs or serves a static cache. Local photo-directory/registry and normalization
helpers still reject SQL proof selection. Native startup still rejects every
non-SQLite selection, including in development; production remains unavailable.

Selection validates the existing schema/audit and both original signing keys
before calling the adapter's ownership/content check. It never initializes,
imports, migrates or repairs an unavailable selected authority. Valid absence
means denial, never permission to fall through to SQLite. No original JPEG is
recompressed, moved or replaced.

## Reproduction and evidence

Use the existing `checks` workflow on the exact branch head. Its auxiliary step
fetches a distribution through the pinned runtime's public `PgRuntime.fetch_dist`
API into its fresh owned fixture. The requested major, all three executable
versions/SHA-256 values and actual connected server must be PostgreSQL **18**;
resolver fallback or a runner-installed PostgreSQL 16 cannot satisfy the receipt.
`psycopg[binary]==3.3.6` remains isolated to that fixture. The same existing suite
and cleanup gate require 45 distinct successes, no skips and no remaining owned
schemas, listener, socket or server. The receipt binds source SHA/tree/file bytes,
command, dependency identities and actual named callbacks.

Existing PostgreSQL 16 evidence remains evidence only for its recorded earlier
heads. Local full-suite/runtime execution is unassigned while machine commit
headroom is unsafe. Existing hosted workflows supply qualification; no new test
or deployment orchestration layer is added.

## Remaining release gates

The supported topology remains one host, one backend and one serialized gateway,
with no overlapping replacement. The auxiliary SQL lock does not fence native
writers or prove rollout overlap safe. Native writer fencing, uncertain native
commit outcomes and stopped-writer cutover remain explicit unresolved gates.

Before a functional single-PostgreSQL application can be admitted, integrate and
qualify actual upload/static delivery and native signing-key resolution; specify
production schema/DDL/migration admission; and exercise coordinated backup,
authenticated restore and restart across graph/identity, both auxiliary stores,
suspension audit, original signing keys and exact photos. Preserve the matching
release/recovery artifact, including the actual offline payload. Operator paths
that still use a local identity-review lock remain a separate cutover gate.

Hosting/durable-store and backup ownership, single-backend routing, privacy and
retention/deletion approval or explicit restricted-pilot terms, real sender/inbox
delivery and quota evidence, physical-phone QA, consenting participants, a real
approved offer and support ownership remain open under
[release acceptance](RELEASE-ACCEPTANCE.md). Exact `@umich.edu` inbox access,
including alumni, is the approved eligibility policy; it does not establish
current enrollment or U-M endorsement. This engineering proof authorizes no
purchase, credentials, live-data change, deployment, merge or public launch.
