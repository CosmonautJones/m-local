# Auxiliary PostgreSQL 18 DDL admission

October 16, 2026. This is a prerequisite on the existing disposable auxiliary
adapter, not hosted-startup enablement or deployment acceptance. Official Jac
remains 0.37.23. The inherited PR60-66 integration chain and next functional gate
are recorded in [INTEGRATION-MAP](INTEGRATION-MAP.md).

## Gap and implemented boundary

Matching table/column names and current rows did not establish the adapter's
required uniqueness, CHECK, nullability, default, identity or execution behavior.
The actual selected account/owner/QR/photo paths consume PostgresAuxiliary, so
this guard is on that existing path rather than a detached proof abstraction.

Existing authority admission now reads qualified pg_catalog metadata before its
first application-state query, including the serialization row lock. It admits
only the emitted 15 permanent ordinary heap tables, ordered 65 built-in columns,
66 enforced/validated immediate local constraints, their 17 backing indexes plus
the sends(email,at) index, and one correctly owned/configured by-default review
identity sequence. Exact catalog flags, default btree operator classes, default
collations, CHECK/default deparsing and implicit row/array ownership are checked.
The catalog contract is qualified only for PostgreSQL 18; prior PG 16 evidence
continues to qualify its original heads only.

Constraint/index/sequence names and OIDs are incidental. Sequence start/increment,
limits/cache/cycling and internal ownership are declaration semantics; its
current value is not inspected or reset. The trusted internal DDL grammar is
fully consumed; an unknown future declaration requires an explicit contract
change. Stored defaults/CHECKs/functions are never evaluated for admission.
Catalog inspection uses only pg_catalog in its search path; it restores the owned
application schema only after admission. A review-added operator/function variant
checks that a schema-local equality hook cannot advance the identity counter.
Unexpected relations, dropped/generated/inherited columns, partition/inheritance,
RLS/policies/rules/triggers, schema functions/domains and other namespace objects
are refused. No new business/FK constraints or nullable-column restrictions are
introduced. VERSION 1 and emitted DDL are unchanged.

Selection never initializes, repairs, migrates or replaces state. Existing
initialize adoption uses the same catalog admission before application rows.
Explicit initialize of a genuinely empty owned fixture remains supported; it
checks schema-wide emptiness, emits the existing DDL, validates the catalog, then
inserts its initial version row. An unknown function/view/sequence-only schema
is not empty. Original SQLite/key/photo sources and suspension audit remain
preserved. Error text contains no driver connection details or private records.

## Failing-first qualification and regression witnesses

Acceptance was retained before implementation in the X: evidence directory.
The test-only corrected checkpoint 3f5f661c31a8682fb68a8186563aa057164b4550,
tree af9d1950c89eb8e40b57dfcf050bc652f1b9278a, received existing hosted
[checks 38872683023](https://github.com/CosmonautJones/m-local/actions/runs/38872683023).
Actual PG 18.6/psycopg 3.3.6 ran 55 methods: all 49 prior names and the canonical
renaming/counter positive control passed; five negative DDL methods produced 399
AssertionError events, with zero setup errors/skips. All 20 source inputs and raw
outcome/log hashes match Git. Schema removal, server stop and closed listener/
socket cleanup passed. Independent review confirmed clean behavioral RED.

RED ZIP SHA256: a0011bc642de1dce8838a1bd0bd8cbba0345eae7c2eff32dec066cdb60b93938.
RED receipt SHA256: 512f7b0c581d0bc3aba037ea9bef1ae2bb0648a080500fe91e7d512b10dfedda.
The earlier 70aa checkpoint is retained honestly as mixed behavioral RED plus one
fixture setup error; it is not substituted for the clean checkpoint.

The 55-method source inventory exercises damaged declarations through actual
selected/cached CodeStore, key, owner, QR and photo paths. Independent snapshots
compare rows, catalogs, sequence counters and native identity sentinels after
refusal; local SQLite fallback is forbidden. 47 prior test methods are unchanged.
Two prior late-write rollback methods are strengthened: their synthetic trigger
is installed only after successful admission inside the real transaction,
requires a real PZ001 PostgreSQL write error, and verifies row/catalog rollback.
Thus earlier catalog refusal cannot stand in for the late-failure witness.

Final implementation qualification requires fresh exact-head checks, shared,
native, browser and package workflows (five workflows/eight jobs), all 55 SQL
methods with zero nonpass outcomes and complete cleanup, plus independent source
and retained-evidence review. Final head/results are recorded in the PR and
source-bound receipts; this document makes no unrun GREEN claim. No local Jac/
PostgreSQL tests or services were run; TravOS retains the heavy local test slot.

## Remaining functional and operator gates

Catalog admission assumes quiescent schema ownership. It does not fence a
privileged concurrent DDL writer. Auxiliary serialization does not fence native
writers, make graph/auxiliary transactions atomic, or resolve uncertain commits.
Operator mutation locks, stopped-writer migration, coordinated changed-store
recovery and single-backend routing remain explicit cutover gates.

Native/production guards still reject SQL selection; the owned loopback fixture
restriction remains. SQL driver functional/offline packaging, original-key
selection before native auth/store spawn, actual HTTP photo delivery and upload/
cache failure/restart lifecycle remain the next integrated candidate. Reuse the
existing guarded launcher after singleton/port admission; offline preflight stays
static. One native startup and photo GET/HEAD proof through the gateway, followed
by a complete stop/disposable cache removal/restart and fail-stop variants, takes
priority over further detached proofs. Do not weaken native/media guards merely
to make that fixture run.

Human decisions remain open: research handling #41; public privacy/terms/deletion
or explicit pilot restriction #42; real sender/inbox/bounces/quota; physical iPhone/
Android checks; consenting pilot/approved offer/support; durable hosting/stores,
backups/off-host retrieval/RPO/RTO and one serialized backend. @umich.edu inbox
access includes alumni and is not enrollment/endorsement. JacHammer ephemeral
files/overlapping backends do not meet the governing contract. No merge, live
migration/data change, email, credential creation, permission expansion,
deployment or spending is authorized by this increment.

Catalog references: official PostgreSQL 18 [constraints](https://www.postgresql.org/docs/18/catalog-pg-constraint.html),
[indexes](https://www.postgresql.org/docs/18/catalog-pg-index.html),
[operator classes](https://www.postgresql.org/docs/18/catalog-pg-opclass.html),
[sequences](https://www.postgresql.org/docs/18/catalog-pg-sequence.html) and
[dependencies](https://www.postgresql.org/docs/18/catalog-pg-depend.html).
