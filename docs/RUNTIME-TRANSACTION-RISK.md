# Jac 0.37.23 transaction retry risk

Independent scaling review found a conflict between the documented request
replay model and the pinned runtime's internal commit recovery. A disposable
PostgreSQL diagnostic reproduced the stale overwrite on October 4, 2026. This
is not a completed two-app or two-host fault-injection result. It remains an open
release gate; neither a PostgreSQL advisory lock nor a graph fence has been
adopted as a claimed fix.

Relevant runtime sources are `server/impl/session.impl.jac`,
`server/impl/server.impl.jac`, and `data/impl/store.impl.jac` in Jac 0.37.23.

- `_flush_locked()` updates `_version_seen` after each successful upsert,
  before the surrounding database transaction commits.
- `Session.commit()` catches SQLSTATE `40001`, `40P01`, `55P03`, and `08006`
  and may retry the flush five times through `_recover_conflict()`.
- `_recover_conflict()` rolls back and re-dirties changed anchors, retaining
  those advanced expected versions. It does not rerun business reads.
- A direct `WriteConflict` escapes to `_run_function_with_occ()` and gets a
  complete request replay. The internal SQLSTATE recovery path can instead
  reapply stale writes after another transaction has committed.

A singleton graph fence would participate in ordinary version conflicts, but
can inherit this stale-flush behavior. Lazy creation also does not establish
uniqueness: two replicas can create different UUID anchors with the same key.
A separate advisory-lock connection can disappear before a graph commit; a
transaction can also reconnect after losing a lock on its original connection.
Lock acquisition alone therefore does not establish the required invariant.

The supported `[serve] on_conflict`, `conflict_max_attempts`, and
`conflict_backoff_ms` settings control the outer request loop. They do not
disable the internal commit retry. `JAC_DB_RO_UNITS=0` disables the read-only
tier, not commit recovery. Reviewed server-extension hooks expose validation,
registration and worker lifecycle; none provides a supported session/store or
commit-policy replacement.

## Observed diagnostic

The pinned `Session` and `PgStore` performed real PostgreSQL writes. A test-only
store wrapper rolled back immediately after the first flush, let a separate
`jacpython` process commit a competing update, and raised `PgWireError` with
SQLSTATE `40001`. Permission admission was stubbed because this diagnostic tests
transaction behavior, not authentication. It used a newly created cluster under
`/var/tmp/m-local-runtime-conflict-*`; its processes were stopped afterward.

The initial record had version 0. The competitor committed version 1. The
original `Session.commit()` attempted twice without replaying business reads,
then persisted its stale value at version 2, overwriting the competitor. The
invariant assertion failed as expected. This establishes a concrete runtime
defect; it does not establish capacity or that every public request encounters it.

The official v0.37.23 source tag resolves to
`58cb97eb75cdff8b5ee78f4094ca2be16376601c`. Its Session sources match the installed
payload byte for byte. A separate local runtime checkout has been prepared for
a reviewable correction. The shared installed runtime and app pin remain intact.

Abort also needs verification: a successful flush updates its cached hash before
COMMIT, so `_evict_uncommitted()` can retain a failed transaction's mutated
anchor. Request replay must invalidate failed writes and business reads,
then reload roots/current data rather than reuse the abandoned objects.

The next proof must cover two actual app processes sharing a database with
independent host locks, competing one-unit claims/redemptions, cold-start
uniqueness, `40001`, connection loss and an unknown COMMIT result. Required
results are one winner, no duplicate redemption, bounded retries and convergence
after restart. A reviewable pinned-runtime fix must route served transaction
conflicts to complete request replay, including nested server calls; unknown
commit outcomes additionally require idempotent application behavior.

Do not patch the shared installed runtime or monkeypatch private session fields
as an unreviewed production workaround. Keep any runtime fork, its exact source
revision, build and fault-injection evidence reviewable with the release.

## Earlier isolated correction checkpoint

A separate v0.37.23 source checkout now retains original expected versions
until COMMIT, invalidates touched request reads and failed writes on abort,
refreshes evicted root pointers, and routes internal conflicts in an active
served call to complete body replay. Snapshot/unit close failures abort and
rethrow; rollback failure still clears abandoned cache state and effects.
The installed runtime and application pin remain unchanged.

Latest diagnostics passed four SQLSTATE/unknown-acknowledgement cases, three
transaction boundary cases, three lifecycle failure cases, and nine real
`ExecutionManager` replay cases. The latter include clean edges, roots on
replay and the next request, internal `has`/batch/read-barrier failures,
noncompeting writes derived from changed reads, and nested `run_request`
read attribution. These use disposable PostgreSQL and test-only permission
admission. They do not constitute two-API, packaged-runtime, authorization,
idempotency or load proof. Independent targeted source review found no new
defect in these passing cases; the overall release gate remains open.

The app also passed compiler/lint, 67 onboarding tests, 432 core tests, a sealed
build and 120 compiled UI tests with the isolated source override. Real HTTP
then exposed a missing `read_ids` initializer in `JScaleExecutionContext`, whose
custom initializer skips inherited field defaults. Adding that initializer
closed the observed HTTP 500; 28 approval and four restart checks passed in the
rerun. The candidate now changes four runtime files. This is source-override
compatibility evidence, not an installed or deployed runtime release.

## Query conflicts and uncertain commits

An authenticated two-API run of the sealed derivative reproduced HTTP 500 when
different owners published simultaneously: a raw `40001` escaped from a graph
query before `Session.commit()`. The next source candidate adds a server-boundary
catch around the body and unit finalization. It examines wrapped exceptions;
`40001`, `40P01`, and `55P03` enter the existing bounded full-request replay.

`08006` now aborts and returns `commit_uncertain` / HTTP 503 without body replay.
It is also removed from Session's internal retry set. The database may already
have committed, so callers must reconcile the result. M-Local new-offer publishes
use an owner-scoped key and canonical payload digest; repeating that key returns
the original offer, while different details require an explicit edit.

Seventeen served diagnostics pass, including raw/wrapped queries, five-attempt
exhaustion, nonretryable errors, and accepted COMMIT acknowledgement loss with
one body execution. A real native-auth two-API source-override run passes 32
checks: concurrent same/different payloads, separate owners, one-unit claims,
redemption, discarded HTTP response, and restarts. These are local correctness
checks with separate private-state copies, not cross-host replication or load
capacity. A separate test-only acknowledgement-loss hook also passes 37 native
HTTP checks, including actual `COMMIT_UNCERTAIN` / 503 and publish-key
reconciliation through the other API without duplication. The new runtime
changes five files. Its sealed package now passes 85 native HTTP checks with
the fork and build-stage source paths unavailable throughout the run. The exact
binary SHA256 is
`233fff51248d9f18ed023e8b3b050070c414f2fc0ddc45c08c0cc6d9a7d1d1fa`;
the runtime patch SHA256 is
`6c9dc855c84e322aeec45a9d23f2f7fc12320861d06a536ebc1b1fd7a100305a`.
Five changed payload files were byte-matched before hiding the source paths.
Fifty concurrent claims produced one winner, and fifty redemption attempts
produced one success. Restart, lost-response retry, separate-owner keys,
canonical formatting and actual post-COMMIT acknowledgement loss passed.
One intentional HTTP 503 reconciled to the original offer; no unexpected 5xx
or traceback occurred. All owned API processes and PostgreSQL were stopped.
Private identity state was cloned once before the second API started; it was
not replicated. This closes the tested packaged correctness failure, not
public capacity, production deployment or cross-host private-state durability.
The prior four-file package and its
08006-as-WriteConflict receipts are historical evidence, not this candidate.

Errors before the execution manager and failures after a streaming response has
returned remain outside this catch. The installed runtime and app pin stay
unchanged; adoption and deployment remain release gates.

## Earlier cold compiler compatibility failure

The 85-check binary above did not complete a cold whole-app compiler check.
Its packaging recipe also used an older Python payload. A fresh official-runtime
control passed the same app input in 56.23 seconds at about 1.4 GiB RSS.

A corrected sealed build byte-matched all 1,247 official Python payload files
and bundled dependencies, with the same five-file patch and no fork-path
references. Its binary SHA256 is
`ec4184a61dcd3b1c194d9e05a9066f553c818638191b548739239b1e0fdb53be`.
Its whole-app check still hit the 18 GiB resource guard after 713.18 seconds.
The owned process was stopped; onboarding, core, build, UI, HTTP and capacity
checks were not run by that failed runner. The older HTTP receipt does not certify it.

Bounded checks of individual source files passed on both binaries, including
the main file, offer editor and runtime context constructor. Those checks read
imports as interfaces and do not establish whole-program compatibility. An
unmodified stock-source package control subsequently passed. A later controlled
cache-placement comparison isolated the compiler failure's operational cause;
see below. Runtime adoption, capacity certification and release acceptance
remain open.

## Fresh exact-package compatibility and HTTP evidence

The same `ec4184` binary and five-file patch passed fresh installed serial and
default compiler controls, then a separate fresh canonical project suite:
`scripts/check.sh` in 41.03 seconds, 67 onboarding tests, 442 core tests, a sealed
build and 126 compiled UI tests. No application or runtime source changes were
made between the failed workspace check and these successful controls. Raw
application/config inputs match; the production source digest is
`1881533faeccb9a7a7384b484699a38cb1eb5835d439b07be68a401d4a5d94e4`.
The earlier 713-second / 18 GiB failure is retained; the later cache-placement
control below explains the operational difference.

Reduced whole-import probes omitted explicit dependency installation and
normalized the entry file to LF. The original unmodified entry also passed that
setup, so those probes do not identify a rendering or tracker defect. The later
installed controls and canonical suite use the original raw application input.

A fresh exact-binary native HTTP run also passed 85 checks with both the runtime
fork and build-stage paths hidden. Fifty simultaneous last-unit claims and fifty
redemption attempts each produced one winner. Equivalent publish retries,
changed-payload refusal, owner-scoped keys, discarded responses and restarts
passed. A test-only hook discarded one acknowledgement after a real accepted
COMMIT: one intentional `COMMIT_UNCERTAIN` / 503 reconciled through the other API
to the original offer without duplication. Owned API processes stopped and the
hidden paths were restored. No source override was active.

This closes the tested local packaged compatibility and correctness gates. It
does not establish production capacity, hosting durability, public ingress,
SMTP headroom or physical-device behavior. Private stores were cloned once;
cross-host state remains unproven. The installed runtime and application pin
are unchanged. Runtime adoption and release acceptance remain open.

## Cache placement and subsequent application changes

With the same `ec4184` binary and byte-identical entry/config/dependency inputs,
a cache inside the app root exceeded a 120-second guard at 3.3 GiB RSS. A fresh
sibling cache passed in 42.09 seconds at 1.4 GiB. An independent external-cache
canonical repeat also passed in 43.03 seconds. Project dependency analysis can
include imported runtime modules inside the project root; its path exclusions
do not exclude an arbitrary `cache` directory. This is not evidence that every
cached file is compiled. `scripts/runtime.sh` now requires an external cache.

The compatibility/85-check HTTP receipts above bind to source digest `1881533`.
Subsequent application changes bucket analytics once per day, filter feed/offer
claim queries by actor before graph hydration, and cap accepted HTTP connections
at 96 per API process. Fresh compatibility, HTTP and capacity receipts are
required before applying the older verification to those changes.

## Capacity failure and connection budget

The first measured 20-request/second run with 500 accounts, 30 businesses,
120 live offers and 10,000 historical claims failed. PostgreSQL reported
`53300` connection exhaustion and APIs returned HTTP 500; the statistics sampler
also lost its connection. The resource guard did not trigger. The run did not
complete 15 minutes and cannot establish client latency percentiles. Partial
server logs include responses as slow as 72.57 seconds.

The runtime's PostgreSQL limit is 256 connections. Its default pool cap bounds
idle connections, not active work. `[serve.limits].max_connections = 96` admits
at most 192 HTTP handlers across two single-worker APIs; their two default idle
pools can retain another 32 connections, leaving approximately 32 for operations.
Saturated handlers receive HTTP 503 with `Retry-After: 1` before opening a graph
context. Idle keepalive sockets count toward the cap. Budget every worker and
API instance against the actual database limit before changing production
topology. Backpressure prevents overload from becoming database exhaustion;
it does not prove the capacity target.
