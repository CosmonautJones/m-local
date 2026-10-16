# Application authority proof boundary

This increment exercises existing onboarding and QR authority callers against the
preserved auxiliary SQL fixture. It closes the stale-SQLite authority gap inside
that proof. It does not admit PostgreSQL as a hosted application backend. Official
Jac **0.37.23**, graph/identity handling and all existing release gates remain.
The prior [SQL preservation proof](POSTGRES-AUXILIARY-PROOF.md) is its prerequisite.

## Acceptance recorded before implementation

Acceptance was frozen on October 16, 2026, before implementation on
`codex/authority-backend-parity-2026-10-16`, based on frozen PR63 head
`be8014819293da34316490feb97eae9471ea6989`. Required behavior:

- Actual `store`, `existing_store`, direct owner/status readers, QR consumers and
  first activation use one selected established authority. PostgreSQL approval,
  account kind, owner activation and suspension override contradictory SQLite.
- Unavailable selected authority raises a sanitized `ValueError`; it must never
  masquerade as authoritative owner absence or fall back to SQLite. This protects
  callers that otherwise copy owner absence into graph state.
- Selection neither initializes/imports/migrates SQL nor constructs a SQLite
  store, generates a key or repairs missing audit. Existing keys are required.
- Preserve configured-owner precedence, ordinary catalogue behavior, and approved
  first activation before any owner/status event exists.
- Preserve original/template and separately stale-configured SQLite, key and JPEG
  bytes, plus the synthetic native graph/identity sentinel, after success/refusal.
- Refuse unknown/incomplete/production selection, unavailable schema, incompatible
  version, missing/partial audit, revision mismatch and missing original keys.
  Native startup and media refuse proof mode before filesystem side effects.

The failing-first checkpoint and final exact-head commands, named outcomes,
source digests, dependency versions, independent review and cleanup belong in the
PR and retained receipts. Default-discovery skips are never a SQL pass. Local
full-suite execution is not assigned; existing hosted workflows qualify the head.

## Explicit fixture-only selection

| Setting | Behavior |
| --- | --- |
| `MLOCAL_ONBOARDING_BACKEND` absent or exactly `sqlite` | Existing SQLite behavior; importing the selector does not import the optional PostgreSQL driver. |
| Exactly `postgres-proof` | Require both `MLOCAL_AUXILIARY_TEST_DSN` and `MLOCAL_AUXILIARY_TEST_SCHEMA`; reuse the existing explicitly owned loopback `mlocal_aux_test_*` database/schema guard and already imported state. |
| Empty or any other value | Fail before consulting local private state. |

There is no fallback to `JAC_DB_URL`, environment-selected live databases or a
second deployment backend. Driver `psycopg[binary]==3.3.6` stays isolated to the
proof environment. Initial key/schema admission and later SQL transactions both
sanitize driver failures. Genuine validated absence still returns no owner.

`MLOCAL_ENV=production` refuses this selection even through direct helpers.
The standalone startup/preflight guard refuses every non-SQLite selector even in
development. The existing photo registry, directory, normalization and ownership
paths likewise refuse proof mode: SQL photo storage/cache serving and native key
bootstrap have not been wired into the application. Use only the disposable
runner and synthetic fixtures described in the prerequisite document; this is
not a production configuration example.

Selected-factory operator mutations such as `approve_business` and
`change_business_status` still use `identity_review_lock(self.directory)` and may
create its lock file in the configured private directory. The existing SQL
fixture tests use disposable runtime directories for those mutations. They do
not qualify filesystem-independent operator commands; operator mutation cutover
and native writer coordination remain separate gates. This increment qualifies
the selected factories, authority reads and activation preparation above, not
all application or operator paths. The existing lock is unchanged.

The SQL fixture guard currently validates table/column shape, scalar types,
version and audit consistency. Full DDL constraint/default/identity metadata
conformance is a separate production schema-contract gate. No broad malformed-DDL
or live migration admission is claimed here.

## Remaining release decisions and engineering gates

Before any live cutover, define the production schema/migration contract; stop the
SQLite writer; finish SQL media/cache and native signing-key resolution; qualify
native writer fencing and uncertain commit behavior; and execute changed-store
backup, authenticated restore and restart acceptance for graph/identity, both
auxiliary stores, suspension audit, original keys and photos. Preserve the exact
matching release/recovery artifacts. No deployment or cutover is authorized here.

Hosting provider, durable store/backup ownership and single-backend routing remain
human acceptance decisions. Privacy/terms or an explicit restricted pilot launch,
physical-phone QA, consenting pilot participants, a real approved offer and support
ownership remain open. Exact `@umich.edu` inbox access including alumni is already
approved eligibility; sender/inbox delivery and quota evidence still require host
acceptance. It proves inbox access, not enrollment or U-M endorsement. Browser
checks and SQL compatibility cannot close those human/device/hosting gates.
