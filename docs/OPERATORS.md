# M-Local operator responsibilities

Assign named primary and backup operators before hosted rollout. Travis owns
merge, rollout, production-data and spending approval. The coordinator owns
the exact release artifact, test/CI/review binding and unresolved engineering
gates. A hosting operator owns canonical path, durable volumes/database,
restricted edge, secrets, backups, monitoring and approved cutover. A business
review operator follows `BUSINESS-APPROVAL.md` and stops serving before graph
CLI writes under the proposed exclusive topology. Avoid parallel writers.

## Readiness and privacy

Poll the restricted gateway `/healthz`, not an HTML shell or independent native
`home_feed` request. It verifies runtime readiness and a valid guest feed through
the same serialized lane. An empty valid catalog is healthy; a malformed or
failed feed is unavailable. A closed lane makes readiness fail. Do not open
traffic on a page-loading or token-only test.

`MLOCAL_INGRESS_EVENT_LOG=stderr` emits sanitized fixed-category JSON events:
route category/allowlisted RPC, time, HTTP status and failure code. It omits
request body/query, email, token, QR payload, IP and raw upstream exceptions.
Keep native server and SMTP/database diagnostic logs private: these can contain
sensitive runtime information. Never attach them raw to issues or public CI.
Keep release and backup receipts separately; backups include live keys and data.

The existing gateway bounds sockets (96 by default), headers, partial requests,
bodies, queue size (32), queued wait (10 seconds), ordinary upstream completion
(30 seconds), import completion (75 seconds), and readiness (5 seconds). Email
ingress and private per-email/global quotas remain active. A loopback edge with
no reviewed client-IP trust conservatively shares its ingress quota; validate
the actual edge/IP trust and capacity before inviting users. Do not loosen
timeouts or limits to hide a runtime failure.

## Proposed monitoring thresholds

These are a setup/runbook specification; no external alert delivery was installed.
Use the approved host log collector and monitoring endpoint. Verify alert
delivery to both operators with a controlled drill before opening traffic.

| Signal | Initial trigger | Response |
|---|---|---|
| Readiness | Two consecutive failed probes over 30 seconds | Close traffic; inspect backend/gateway and serialization state. |
| `SERIALIZATION_CLOSED`, `UPSTREAM_FAILURE`, `UPSTREAM_DEADLINE` | Any occurrence | Close traffic immediately; establish writer termination and reconcile uncertain mutation before a coordinated restart. |
| Unexpected native 5xx/`UPSTREAM_5XX` | Any mutation failure, or three within five minutes | Preserve protected logs and source SHA; verify persistence/next-request state; do not blind-retry publication/redemption. |
| `QUEUE_FULL`/`QUEUE_DEADLINE` | Five within five minutes | Investigate latency and overload; keep one backend and fail closed; do not add replicas. |
| OTP rate limits | Sustained global saturation or unexpected volume | Check abuse/shared-IP configuration without exposing addresses or disabling quotas. |
| SQLite integrity, key/photo ownership or volume error | Any error | Close onboarding/uploads/serving as appropriate; preserve storage; never regenerate keys or delete accounts. |
| Backup | Missed approved interval, failed checksum or retrieval | Preserve last complete set, block rollout, investigate age and measure RPO. |
| Capacity | Disk below 20% free or unexplained DB/cache growth | Investigate with read-only tools; never clear graph/onboarding/photos to recover space. |

The 15-minute RPO and 30-minute RTO in release planning remain objectives until
scheduled remote backup, retrieval, host preparation, canonical restore,
authenticated checks and cutover have measured evidence. Choose retention and
encrypted off-host destination with Travis; the offline package creates neither.

## Incident and uncertain outcome

1. Close public traffic. Record exact package manifest digest and source SHA,
   symptoms, event times and sanitized operation category. Preserve private logs.
2. Stop the supervising launcher and verify both owned process groups/listeners
   ended. Check for other app, CLI, bootstrap or operator writers. Do not kill
   unrelated processes or delete a lock file to bypass ownership.
3. Reconcile the operation under private authenticated checks: original actor,
   owner and stable offer/publication key; held/redeemed claim IDs, QR and
   snapshots; private state and graph results. An HTTP error or missing
   onboarding row is not proof that an identity or write is absent.
4. Restore service only after runtime/state checks and coordinated restart.
   A failed finalization/cache invariant requires engineering resolution; the
   operator may not override the release evidence file to reopen writes.
5. For source failure with compatible data, use the prepared source rollback.
   For incompatible state, use coordinated isolated recovery and reconciliation.
   Keep accepted post-snapshot claims in the incident plan before any data loss.
6. Record resolution and acceptance test in #33 without private account details.
   Travis approves any live recovery, account remediation or traffic reopening.

## Release drill checklist

Verify final exact-head CI/review and official runtime digests; existing canonical
path and preserved stores; PostgreSQL clients/TLS/roles; backup and retrieval;
stop-before-start with no residual listener; meaningful readiness; native route
denial; security headers and request limits; server-disabled sample paths; original
merchant/student sign-in and isolation; original claim snapshots and QR; exactly-once
redemption; photo ownership/bytes; second restart; actual inbox and devices.
Record owner, source/artifact/runtime digests, scope, commands and results.
Mark local engineering separately from hosted acceptance. Do not call the app
production-ready or grade A while a required acceptance gate remains open.
