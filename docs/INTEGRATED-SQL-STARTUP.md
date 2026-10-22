# Integrated disposable SQL startup acceptance

This increment extends frozen PR67 (`3ebacd0538161b986bc62f242d7aed2cd40ed20a`).
The governing contracts are AGENTS.md, TEAM-CONTRACT.md v2,
RELEASE-ACCEPTANCE.md, RELEASE-GATES.md and WORK-HANDOFF.md.
It closes an application-startup rehearsal gap, not hosted-pilot acceptance.

## Scope and authority

- Official Jac 0.37.23 stays pinned. One Linux host, one backend, one serialized
  gateway; stop all writers before replacement. No overlapping deployment.
- Use the existing package launcher and PostgreSQL auxiliary adapter. No new
  supervisor, native token protocol, startup importer, schema initializer or
  fallback database. No Jac product API changes are planned.
- `postgres-proof` remains authority-only and refuses native startup.
  `sqlite` remains the default application backend.
- New `postgres-local` is explicitly disposable: the package `run`/`preflight`
  command requires `--disposable-sql`, caller `MLOCAL_ENV=disposable`, fixture-only
  evidence and an owned private temporary fixture root. A production request
  cannot be silently downgraded. Production SQL rollout stays blocked.
- All deliberate local files/worktrees/evidence use X:. Keep frozen prior heads,
  Argon WIP and other writers unchanged. Hosted disposable checks use existing
  workflows; TravOS retains the local heavy-test slot.
- No deployment, merge, purchase, live migration, credentials, permission change
  or external messages. Branch pushes and draft PR preparation are authorized.

## Required evidence

1. Restore the complete exact-source archive offline, then test that extraction
   using the actual `bash scripts/release-run.sh` entry point. Preserve the
   previous 104 package assertions and 55 auxiliary tests without weaker gates.
2. The restored application's ordinary `.jac/venv/bin/python` imports pinned
   `psycopg[binary]==3.3.6` from its own library tree. No injected driver site.
   Resolve official PG18 tools once and bind server/client versions and hashes.
3. Before serving, reuse the existing native child process slot to validate
   the selected established SQL catalog, suspension audit, both original keys
   and photo bytes. Require the preserved original SQLite photo registry as a
   read-only anchor: every imported filename, owner, digest, byte count and
   creation time must remain present unchanged in SQL before cache publication;
   extra valid SQL photos are allowed. Missing or malformed registry refuses.
   Select the original SQL native key before exec of the
   official Jac binary. Native and auxiliary URLs must exactly identify the
   same owned loopback `mlocal_aux_test_*` database; the schema is owned too.
4. Preserve synthetic original graph identities, root-backed profiles/merchant
   ownership and existing tokens across actual SQL startup and repeated restart.
   Exercise SQL draft/QR authority through actual authenticated HTTP calls.
5. Materialize imported original JPEGs into the ordinary configured static asset
   directory. Native and gateway GET return exact bytes; HEAD returns 200,
   matching Content-Length and no body. A normal restart admits only an exact
   complete cache. After full stop, discard only the fixture-owned cache and
   prove reconstruction and another authenticated restart.
6. Missing/wrong config, mismatched native/aux database, missing actual app
   driver, missing/incompatible schema/audit, wrong/missing keys, missing/corrupt
   photos, changed imported photo metadata and startup SQL outage refuse before
   either serving listener exists.
   Preserve SQL, original SQLite stores, keys and photos; never fall back.
7. Unknown, corrupt or partial nonempty cache refuses unchanged. Cache write
   failure may leave a partial cache but cannot serve; subsequent startup
   refuses it without repair. Original photo storage and SQL remain unchanged.
8. Upload is explicitly unavailable in this configuration: HTTP reports
   `ok=False` without SQL/SQLite/cache mutation. Existing SQLite uploads remain
   covered by the preceding package proof.
9. Offline preflight stays static and network-free. It cannot certify online
   catalog/key/photo admission, native serving or durable hosting.
10. Independent final source and hosted-runtime evidence review, then all five
    existing workflows/eight jobs succeed at the exact final branch SHA.
    Retain portable archive checksum/replay receipts. Retain the large tested
    payload on X: only where no-spend delivery capacity is established.

## Limits and human decisions

This is not changed-store SQL recovery, an operator-run host rehearsal, an
external HTTPS deployment, or a durability/RPO/RTO claim. Native writer fencing,
unknown COMMIT outcomes and overlapping replacement remain open. Guest readiness
and cached public JPEGs after an ongoing SQL outage are not certified by this
startup-only increment. Cache publication is per-file, not atomic as a set.

Issue 41 already chooses private research retention. Historical exposure and
copies, authorized readers, integration and retention procedure remain open;
public privacy/terms/deletion or access restriction is separately unresolved.
Real SMTP inbox delivery/headroom, physical phones, consenting pilot outcomes,
host/provider volume durability, off-host recovery and accountable operations
remain human acceptance gates. Exact @umich.edu inbox access includes alumni;
it does not prove enrollment or U-M endorsement.
