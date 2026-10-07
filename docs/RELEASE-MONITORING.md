# Release monitoring hooks

Set `MLOCAL_DOMAIN_EVENT_LOG=stderr` to enable server-only operational events.
Other values disable them. This setting contains no secret. Configure the
gateway's separate `MLOCAL_INGRESS_EVENT_LOG=stderr` for route, authorization,
upstream and serialization events. Neither setting installs an external
collector, uptime monitor or alert destination.

The domain event schema is deliberately small:

| Code | Operation | Meaning |
|---|---|---|
| `OPERATION_FAILED` | `email_request`, `claim`, `redeem` | The application returned `ok=False`, including a friendly HTTP-200 failure. |
| `SMTP_DELIVERY_FAILED` | `email_delivery` | The local sender raised; the challenge remains unusable and the friendly failure is unchanged. |
| `MAIL_QUOTA_NEAR` | `email_request` | Reserved attempts reach 80% of the existing hourly or daily limit. |
| `MAIL_QUOTA_REACHED` | `email_request` | Existing hourly/daily quota blocks a new send. |

Every event has only `kind=mlocal_domain_event`, numeric `time`, fixed
`operation` and fixed `code`. Quota events add `hourly_attempts`, `hourly_limit`,
`daily_attempts`, `daily_limit`, bounded at the current limits of 60 and 300.
Counts are attempted/reserved sends, including failed delivery, rather than
successful inbox delivery. The hook reuses counts already read by the existing
SQLite quota transaction; it adds no graph query or new admission rule.

No event accepts an email, name, actor, offer/claim ID, QR, token, code, request
body, message, URL or exception text. Success is silent. Unknown operations,
non-Boolean outcomes and invalid quota counts are silent. Logging exceptions
are swallowed so a broken sink cannot change authorization, quota admission,
challenge cleanup, claim/redemption behavior or the original friendly result.
Protected claim/redemption result hooks run after the existing mutation unlock;
they run before the runtime's final response/transaction finalization and do not
alter that path. These are failed application-result events, not durable-COMMIT
receipts. Runtime replay may repeat an attempted-operation event; use separate
gateway/fault/independent database readback evidence to establish durable state.

Use a private, bounded host log collector and test redaction before rollout.
Raw native/SMTP/database diagnostics remain private; collect only these fixed
events into public engineering receipts. A domain failure reports the attempted
operation and does not establish whether an uncertain transaction committed.
On upstream uncertainty, follow `OPERATORS.md` and stop/reconcile both processes
rather than replaying a claim, publication or redemption.

Before opening traffic, name primary/backup hosting and mail operators, choose
an approved external uptime/alert destination, and exercise receipt by both.
Alert on repeated SMTP delivery failures and quota-near/reached events while
preserving private inbox details. Record the chosen window, threshold and actual
delivery; the original issue #38 monitoring acceptance remains open until that
hosted drill succeeds. Real inbox placement, sender authentication and measured
latency remain #36 acceptance. No real email or new service spending is implied.

Verify locally with official pinned Jac 0.37.23:

```bash
bash scripts/test.sh onboarding
bash scripts/test.sh core
bash scripts/check.sh
bash scripts/python.sh -c 'import runpy,sys; sys.path.insert(0,"tests/integration"); runpy.run_path("tests/integration/release_monitoring_http.py",run_name="__main__")' --receipt /absolute/fresh/monitoring.json
```

The HTTP proof creates disposable private stores and local TLS SMTP, checks
actual HTTP-200 failure events and mail headroom, and stops its own server and
PostgreSQL. It does not deploy, contact external inboxes or certify hosted alerts.
