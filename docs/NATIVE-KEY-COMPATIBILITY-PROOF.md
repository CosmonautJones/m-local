# Preserved native signing-key compatibility proof

This disposable proof exercises a supported Jac **0.37.23** compatibility seam:
original synthetic signing bytes preserved in auxiliary SQL can supply the
existing `JAC_SERVE_AUTH_SECRET` setting without invalidating previously issued
synthetic tokens or changing their persisted identities and roots. The
[SQL photo-reference proof](SQL-PHOTO-REFERENCE-PROOF.md) is its frozen prerequisite.
Application startup still rejects `postgres-proof`. No production code, API,
credential location, startup admission or deployment topology changes here.

## Acceptance recorded before implementation

Acceptance was frozen at `2026-10-16T07:03:08.299626+00:00`, before implementation
on `codex/native-key-compatibility-2026-10-16`, based on PR65 head
`d5bf6548e3d6142179607ff546b7df01db512108`:

- Record the original synthetic key's raw SHA-256 before import. Compare selected
  SQL bytes against that independent anchor; a digest of fetched SQL is insufficient.
- Create actual ordinary synthetic users, verified/unverified email identities,
  profiles and roots through the official `UserManager` and persistent
  `Session`/`PgStore`. Issue baseline tokens with the original-file key source.
- Reuse those exact private tokens in sequential fresh processes: original-file
  verification, SQL-selected verification, repeated SQL verification with a wrong
  effective-secret negative control, and return to the original-file key source.
  Native identities stay in the same explicitly owned PostgreSQL database in all
  phases. No login, refresh, replacement issuance or unknown-user provisioning
  occurs during verification.
- Require official `validate_jwt_token_detail(check_existence=True)`, exact
  user/root/profile/identity verification flags/role/status, identity lookup and
  actual persisted root retrieval. Reject signature tampering and demonstrate
  rejection under a deliberately wrong native effective secret before restoring it.
- Refuse missing/wrong keys, invalid original fingerprints, malformed UTF-8,
  short/empty/placeholder/NUL/embedded CR/LF material, unavailable state and
  unknown/incomplete/production configuration before native settings or stores.
  No fallback signing file or alternate SQLite identity store may appear.
- Preserve raw SQL BYTEA, original/template/stale SQLite stores, suspension audit,
  keys, exact photos and native sentinels. Compare the seeded native public rows
  after every verification and refusal; retain the original token packet unchanged.
- Withhold raw keys, passwords, tokens, connection strings and private requests
  from public output and artifacts. Everything belongs to the disposable fixture.

The original 45 SQL methods and helpers remain unchanged. Four focused methods
bring the inventory to **49**. On the failing-first head
`f5766da29c4bafe038d26b44d85a3bcf35d486da`, hosted run
[38866264201](https://github.com/CosmonautJones/m-local/actions/runs/38866264201)
ran all 49 on actual PostgreSQL **18.6** with `psycopg==3.3.6`: 48 methods passed,
and the new admission method recorded 13 expected failure events, no errors or
skips. All 45 prior methods and the three other new methods passed. Owned schema,
server, listener and socket cleanup passed. This RED concerns the new disposable
harness guard; it is not evidence of a production cutover defect.

## Existing supported seam

The child uses `PostgresAuxiliary.signing_material`, `ServeSettings.load`,
`AuthSettings.resolve_secret`, `configure_identity` and `signing_secret`.
SQL-selected material becomes a validated **nonblank** existing environment
setting before official settings load. The canonical project/entry is fixed, its
fallback key is absent, and every phase uses the same explicit owned loopback
`mlocal_aux_test_*` database. No HTTP server starts. Inherited signing/algorithm,
scratch, alternate database and libpq redirection overrides are removed.

The probe guard requires an independently anchored lowercase SHA-256 and preserves
original raw bytes. Effective text is strict UTF-8 followed by Python Unicode
`strip()`, matching the official file/setting resolver for the tested boundary
whitespace cases. The bounded fixture requires at least 32 effective UTF-8 bytes,
rejects the official placeholder, NUL and embedded CR/LF, and performs no Unicode
normalization, hex/base64 recoding or replacement generation. It refuses ambiguous
embedded line endings instead of defining a new normalization protocol. These are
**proof-harness admission rules**, not an installed application startup guard.

Requests and original token packets use exclusive mode-0600 files inside the
owned fixture; they are never uploaded. Public diagnostics contain only fixed
messages or redacted phase/stage/error-class/line fields. Children have deadlines,
are awaited and checked for process-group survivors, and attempt all public
context/store/pool cleanup operations. The existing workflow stops the whole owned
cluster. Deleting identity rows alone would not establish graph-root cleanup.

## Reproduction and evidence boundary

Run the existing `checks` workflow against the exact candidate head. Its existing
auxiliary step fetches PostgreSQL through the pinned runtime's public tooling into
its owned fixture; requested major, three executable versions/digests and actual
connected server must all establish PostgreSQL **18**. The isolated driver remains
`psycopg[binary]==3.3.6`. A final pass requires 49 distinct named successes, no
skips/failures/errors, exact source bindings and complete cleanup. Default discovery
without an explicitly owned database is not SQL evidence.

Final qualification also uses the existing shared-onboarding, native-hardening,
browser and package workflows on that same frozen head, with independent source
and evidence review. Local runtime/full-suite work remains unassigned while
machine commit headroom is unsafe and TravOS owns the heavy local test slot. No
new orchestration layer is added.

## Remaining release gates

Its acceptance covers only the synthetic compatibility prerequisite. Integrating validated
original-key selection before actual application imports, production secret and
canonical-entry admission, and native HTTP startup are still separate work.
Actual SQL upload/static photo delivery, operator mutation locking, full production
DDL/schema migration admission, and coordinated changed-store backup/restore and
authenticated restart also remain open. Recovery must preserve graph/identity,
both auxiliary stores, suspension audit, original signing keys, exact photos and
the matching retained offline release payload.

One host, one backend and one serialized gateway with no overlapping replacements
remain required. Auxiliary SQL locking does not fence native writers. Native
writer fencing, uncertain native commit outcomes and rollout overlap remain
unresolved. Ephemeral files and overlapping deployment backends cannot satisfy
these storage/topology requirements.

Human gates remain separately open: research readers/retention/history (#41),
public privacy/terms/deletion text or explicit launch restriction (#42), actual
sender/inbox delivery and quota evidence, physical iPhone/Android QA, consenting
pilot participants, a real approved offer/support owner, hosting/durable-store and
backup ownership, and single-backend routing. Exact `@umich.edu` inbox access,
including alumni, is approved eligibility; it proves neither enrollment nor U-M
endorsement. See [release acceptance](RELEASE-ACCEPTANCE.md). This proof authorizes
no deployment, merge, spending, external email, live-data or access change.
