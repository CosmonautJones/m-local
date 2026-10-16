# PostgreSQL auxiliary storage proof

This is a local SQL compatibility proof for storing the onboarding records,
photo ownership and bounded JPEG bytes in one PostgreSQL database. It does not
select a new application backend, change startup defaults, migrate a deployment,
or establish native Jac graph/identity transaction safety. Official Jac
**0.37.23** remains unchanged. The existing release and recovery gates stay in
force.

The proof uses **`psycopg[binary]==3.3.6`** in its isolated test environment
([versioned PyPI release](https://pypi.org/project/psycopg/3.3.6/)).
The bundled wire driver lacks the DB-API and `bytea` operations needed here;
using the supported driver avoids a runtime patch or a new wire protocol. This
choice does not authorize changing the application's dependency defaults.

## Disposable execution boundary

The runner requires both settings explicitly:

- `MLOCAL_AUXILIARY_TEST_DSN`: the owned disposable loopback PostgreSQL database.
  There is no fallback to `JAC_DB_URL` or another application database.
- `MLOCAL_AUXILIARY_TEST_SCHEMA`: a fresh owned schema whose name starts with
  `mlocal_aux_test_`. Only this test schema may be initialized or removed.

The coordinator prepares PostgreSQL, the isolated driver environment and a fresh
existing `TMPDIR` on X-backed Linux storage before running the proof. Synthetic
SQLite originals, keys and JPEGs also stay in that disposable storage. Do not
supply existing user stores, an existing application schema or a public host.

From the isolated worktree in WSL/Linux Bash, with the pinned runtime selected:

```bash
export MLOCAL_AUXILIARY_TEST_DSN="${DISPOSABLE_PG_DSN:?Set the owned loopback test database DSN}"
export MLOCAL_AUXILIARY_TEST_SCHEMA=mlocal_aux_test_unique_run
export TMPDIR="${X_BACKED_TEST_TMPDIR:?Set the fresh existing X-backed Linux scratch directory}"
export MLOCAL_AUXILIARY_DRIVER_SITE="${ISOLATED_DRIVER_SITE:?Set the absolute isolated driver site-packages directory}"
export MLOCAL_AUXILIARY_TEST_FILE="$PWD/tests/integration/test_postgres_auxiliary.py"
"${PINNED_JACPYTHON:?Select the official Jac 0.37.23 jacpython binary}" -c \
  'import os,runpy,sys; sys.path.insert(0,os.environ["MLOCAL_AUXILIARY_DRIVER_SITE"]); runpy.run_path(os.environ["MLOCAL_AUXILIARY_TEST_FILE"],run_name="__main__")'
```

Use the pinned binary's `-c` path with an explicit driver-site insertion. Its
isolated startup ignores `PYTHONPATH`; passing a Python filename through the
wrapper is not the runner for this proof.

Use a unique schema name for each independent run. These are prepared commands,
not a record of execution. Checks use real local SQL transactions and mocked
SMTP; they send no actual email and start no native application server.

## Required proof

| Area | Acceptance |
| --- | --- |
| Preserved originals | Keep both synthetic SQLite stores and all 12 onboarding tables: `codes`, `sends`, `accounts`, `display_names`, `provisioning`, `drafts`, `imports`, `business_owners`, `business_approvals`, `business_reviews`, `business_status`, `business_status_events`. Read back both original HMAC/native signing keys exactly from SQL `BYTEA` and verify an HMAC using the original key. Preserve two distinct JPEGs with their filenames, actors, digests, byte counts and original import timestamps. Original fixture bytes remain unchanged after success and refusal. |
| Import | Import into the owned schema transactionally. Exact replay is idempotent only while the target still matches; refuse replay against a diverged target. Conflicting records, incompatible schema versions and partial suspension/audit state fail without resets or partial replacement. A late injected SQL failure must preserve target rows and sequence state as well as original fixture bytes. |
| Existing behavior | Exercise actual `CodeStore` OTP consumption, quota reservations, failed delivery, provisioning, approvals and suspension revision/command retries using PostgreSQL transactions. A transaction-owned row lock serializes auxiliary mutations; prove blocking by an independent SQL connection rather than an in-process lock. |
| Photos | Metadata and bounded JPEG bytes commit together in the same database. Preserve filenames and owner/digest uniqueness. The proof-internal `photo_save(..., created)` argument is trusted server-clock input; future production RPC wiring must supply `time.time()` itself rather than accepting a browser-selected timestamp. Imported timestamps remain unchanged. Duplicate and lost-success-return retries resolve the existing record. A quota-boundary race cannot overshoot; failure rolls back metadata and bytes together. |
| Disposable cache | Reconstruct static JPEG files from database bytes using only filenames matching `[a-f0-9]{32}\.jpg` and compare their hashes with the originals. Refuse original or other nonempty cache directories before changing bytes or mutation-related file metadata. Cache files are replaceable delivery material, never the durable source of truth. |
| Isolation | Default discovery without a test DSN skips without importing the optional driver. Explicit but incomplete or unsafe configuration is refused. Keep SQL work in the owned disposable database/schema. Use mocked SMTP and synthetic identities; do not use a live store or send email. |

The lost-success-return check simulates losing the caller's successful return
after a committed write. It is not a wire-level acknowledgement fault or proof
of general unknown-commit recovery. SQL key round trips do not switch native Jac
to SQL key retrieval; its signing-key resolution remains unchanged.

Sequence rollback must include the identity generator: PostgreSQL 16 documents
[`ALTER SEQUENCE RESTART`](https://www.postgresql.org/docs/16/sql-altersequence.html)
as transactional, unlike `setval`. JPEG validation must decode pixels as well as
check headers: Pillow's [`verify()`](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.verify)
does not decode image data; reopen and call
[`load()`](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.load)
to detect a truncated payload that header verification accepts.

## Evidence requirements

Acceptance was recorded before implementation on October 16, 2026, for branch
`codex/postgres-auxiliary-proof-2026-10-16`, based on
`936fe26f77154988e19f5ded0e6a1f8b4768a836`.

| Evidence | Required record |
| --- | --- |
| Failing-first runs | Retain the initial unimplemented-module RED run and the independently requested regression RED logs, including failures and cleanup results. |
| Explicit PostgreSQL proof | Run the complete opt-in SQL suite at the committed source head. Bind the command, exit code, named outcomes, counts, driver/server versions and relevant source/test/workflow digests to a receipt. Default-discovery skips are not a SQL pass. |
| Preservation and cleanup | Record unchanged original/template fixture bytes, complete imported state and synthetic native-sentinel isolation, plus removal of owned test schemas and termination of the runner's owned PostgreSQL resources. |
| Independent review | Record the exact reviewed source and evidence, findings, repairs and any independent replay; unresolved findings remain open. |

Current counts and live status belong in the component PR and source-bound run
receipts. Keep the final commit identity there rather than embedding the document's
own containing commit SHA here. Keep DSN values, credentials, keys, source rows
and private paths out of public evidence.

The existing [checks workflow](../.github/workflows/check.yml) includes a dedicated
PostgreSQL auxiliary proof step with an explicit disposable database and driver.
At this proof checkpoint, full candidate workflows have not been dispatched;
their execution awaits coordination with the parent's full-test slot. Adding the
step or passing this focused SQL proof implies no native application, full-suite
or hosted acceptance result.

## Work left before any cutover

A future reviewed migration needs a versioned schema/compatibility guard and
must stop the old SQLite writer before enabling PostgreSQL auxiliary writes.
Old and new writers must not overlap. Preserve the original stores, signing
keys, JPEGs and matching recovery artifacts; do not delete or rewrite them as
part of this proof.

One physical PostgreSQL database does not make separate auxiliary and native
graph transactions atomic. Native effective-writer fencing and uncertain native
commit handling remain open; neither an auxiliary row lock nor a lease/advisory
lock establishes that safety. The stock runtime still requires the accepted
single effective writer and existing release evidence.

Expanded backup automation is deferred. Before adopting the changed store,
define and execute recovery acceptance for its schema, complete auxiliary rows,
photo bytes/associations, original keys and native graph/identity, including
authenticated restore and restart checks. Existing recovery artifacts remain
valid only for their recorded source/store format; this SQL proof does not
certify a new backup format, hosted durability, off-host recovery or rollout.
