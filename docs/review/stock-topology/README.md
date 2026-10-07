# Official Jac topology diagnostics, October 7, 2026

These receipts distinguish the known stock runtime defect from the proposed
exclusive, serialized deployment. They do not mark hosted acceptance complete.

## Evidence

| Receipt | Result | Scope |
|---|---|---|
| `competing-writer.json` | **Expected invariant failure** | Real disposable PostgreSQL, stock Session/PgStore, a separate competing writer, a test-only rollback/40001 wrapper and stubbed write admission. The competitor committed version 1; internal retry overwrote it with stale version 2. Abort retained the stale cached value. This is a transaction diagnostic, not native HTTP or production authentication evidence. |
| `native-fault.json` | Six bounded native HTTP fault cases pass | Minimal test-owned persistent node, stock native server and authorization, independent PgStore observer. 57P01 rollback returns 500, 40001 and 08006 rollback return bounded 409, accepted COMMIT acknowledgement loss returns 200 with durable version 2. Process death before COMMIT preserves the original row; process death after COMMIT preserves the new row. Both lose the HTTP response and converge after restart. |
| `serialized-app.json` | 20 full-app correctness assertions pass | Source snapshot at `bae94549120647ddf3cff1be161c5989e83a4dc0` plus its recorded input manifest. One native API and one experimental serialized gateway, queue capacity 64 and ten-second queue wait. Fifty simultaneous cold feeds, taste writes, favorite toggles, same-key publications, distinct-student last-unit claims and redemptions. Independent PostgreSQL reads confirm uniqueness and durable state; backend and gateway restart preserves results. This predates the gateway slow-reader fix. |

The native acknowledgement wrapper is imported only by the disposable minimal
entry. It wraps **PgStore.commit only**, performs real database rollback or commit,
then raises a test-only PgWireError. Actual process-death cases call `os._exit`
inside the owned serving process before or after the real COMMIT. Installed runtime
files are not edited, and no source override is enabled. Replaying a faulted
`probe_write` deliberately arms the same fault again, so rollback 40001/08006
cases test bounded exhaustion rather than eventual retry success. This fixture
does not demonstrate a false-success path through `Session.unit_exit`.

The full-app race fixture uses newly provisioned native identities and explicitly
configured fictional demo membership. No real inbox is contacted. Those private
tokens and QR payloads remain inside the mode-0700 disposable workspace and are
excluded from the receipts. It does not prove passwordless admission or mail
capacity. Separate hardening and onboarding fixtures cover those paths.

Original failed fixture attempts and the earlier four-case receipt are retained.
`fixture-import-failure.json`, `fixture-rebind-failure.json`, and
`fixture-error-envelope-failure.json` are **fixture setup/parser failures**, not
runtime safety failures. The corrected fixture handles error envelopes with null
data, checks a distinct private PostgreSQL port, and preserves case results before
attempting restart. All recorded owned API/gateway process groups and private
PostgreSQL instances were stopped; the private directories remain for inspection.

## Runtime identity

The installed Linux x86_64 binaries match the official v0.37.23 published checksums:

- `jac`: `2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad`
- `jacpython`: `198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542`

Published checksum sources: [jac](https://github.com/jaseci-labs/jac/releases/download/v0.37.23/jac-0.37.23-linux-x86_64.sha256)
and [jacpython](https://github.com/jaseci-labs/jac/releases/download/v0.37.23/jac-0.37.23-linux-x86_64-jacpython.sha256).
Each receipt binds the binary hashes and the exact fixture/application inputs.
The runtime's extracted payload is verified during its normal bootstrap. Both
`jac-core-cheatsheet` and `jac-types` were read before the test-only Jac entry/node
were written.

## Commands, WSL Bash

```bash
# Regression diagnostic: nonzero is expected on the stock competing-writer bug.
bash scripts/test-runtime-transaction.sh

# Minimal native transaction/acknowledgement/process-death proof.
bash scripts/test-stock-topology.sh --evidence docs/review/stock-topology/native-fault.json

# Actual app and gateway simultaneous correctness proof.
bash scripts/test-stock-topology-app.sh

# Final integration proof also exercises the two-active-hold policy.
bash scripts/test-stock-topology-app.sh --require-hold-cap
```

Preserve existing receipts before rerunning. These scripts refuse inherited
`JAC_DB_URL`/`JAC_DEV_SOURCE`, create private databases under `/var/tmp`, scrub mail
credentials, and stop only their owned processes. Ports 18880/18881 must be free;
never kill an unrelated listener to make them available.

## Remaining topology gate

The ordinary serialized app races and minimal native faults pass. An exclusive
single-backend launch still needs a receipt on the final integrated source,
including the fixed gateway and new hold cap. It also needs fault injection on
actual M-Local publication/claim paths, complete native 5xx followed by clean
readback, and accepted-COMMIT/lost-response reconciliation using the application
publication key. Minimal-node fault proof does not close those application gates.
The current verdict is **not hosting certified**.

A candidate constrained topology must have one public gateway serialization
lane, one private backend, and no bypass ingress. Every upstream request,
including readiness and reads, must stay in that lane through the full upstream
response. Multiple gateways, API replicas, direct native access, concurrent
operator mutations and overlapping old/new backends would reintroduce competing
transactions. They are excluded. A release replacement must quiesce admission,
stop the old gateway and backend, then start the replacement; stock Jac has no
proven safe rolling overlap here. An uncertain upstream completion requires the
documented closed gateway and backend-plus-gateway restart/reconciliation path.

The stock competing-writer defect remains an official-runtime blocker to scaling.
Its resolution is an upstream, reviewable fix with packaged native HTTP/fault
proof: preserve expected versions until COMMIT, discard failed writes and reads,
and replay the full request rather than internally flushing stale business state.
Do not adopt the historical local fork or modify the installed runtime silently.
