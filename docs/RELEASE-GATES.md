# Release candidate scope and remaining gates

This classification follows the October 7 release-candidate instruction. Local
fixtures prove engineering behavior only. They do not complete hosted acceptance,
real inbox delivery, physical-device testing, consented pilots, or business policy.
Issue #33 remains the durable coordination record. Independent reviewers provide
findings and evidence; Travis retains merge, deployment, data, outreach and spending
authority. Keep unfinished PRs draft and bind each receipt to its tested source.

| Issue | Classification | Prepared work / remaining acceptance |
| --- | --- | --- |
| #34 storage safeguards | Engineering + live | Fail-closed startup checks, complete storage inventory and preservation package; host must demonstrate mounted durable backing, retained original keys, and restart/replacement survival. |
| #35 representative staging | Live deployment | Prepare isolated deployment tooling; Travis approves the provider, access and deployment. Staging must use the supported topology and real durable services. |
| #36 inbox delivery | Human/live | Local TLS SMTP verifies mechanics. Named operator must verify sender configuration, headroom and delivery to consenting U-M/business inboxes; no real mail is authorized here. |
| #37 hosting reconciliation | Engineering + live | Source/artifact manifests and non-overlapping rollout commands; operator must inventory the existing host and its five hosting commits/data before approved cutover. The public URL alone does not prove its revision. |
| #38 monitoring | Engineering + human/live | Structured redacted gateway events, bounded readiness and operator runbook; choose accountable recipient, configure external uptime/alert delivery, and exercise an incident without spending or outreach here. |
| #39 shared mutation coordination | Engineering blocker for multiple writers | Stock runtime competing-writer regression remains reproducible. A serialized singleton is a bounded launch proposal, subject to final application fault/restart proof. Multiple replicas, rolling overlap, direct backend access and concurrent operator writers remain unsupported. |
| #40 public ingress | Engineering + live | Strict native/admin/graph/docs denial, serialized upstream, body/queue/response bounds, security headers and readiness; verify HTTPS edge, bypass prevention, headers and abuse behavior on the approved public host. |
| #41 research-data privacy | Human policy + bounded audit | Inventory existing contact-research material before publishing a release. Travis must decide retention/removal; do not silently delete human-owned research or represent public availability as consent. |
| #42 privacy/terms/deletion | Human policy, engineering deferred pending policy | Account deletion spans graph, identity, claims, ownership and retention obligations. Do not implement destructive deletion without approved policy and preservation rules. Public release requires approved policy/text or an explicit launch restriction. |
| #43 active hold limit | Engineering | Server cap of two live holds across offers; retries preserve the existing claim, and expiry/cancellation/redemption release slots. Verify native concurrency on the final candidate; existing over-limit accounts retain their claims. |
| #44 merchant verification | Engineering + human operations | Use PR55 manual revision-bound business approval and suspension, with an audit trail. Invite-code approval is a dropped approach. A named operator must accept the runbook and verify real submissions. |
| #45 hosted restart/recovery | Engineering + live | Isolated coordinated recovery and source-only rollback package; a host operator must perform an off-host restore with authenticated preservation checks and measure RPO/RTO. Local cold-copy receipts do not prove host recovery. |
| #46 redeemed feedback | Engineering + device/live | Visible held-claim refresh with account isolation and QR removal/announcement after redemption or expiry; verify real merchant/student interaction and foreground/background behavior on phones. |
| #47 installability | Engineering + device/live | Manifest and authored icons with no private-data service-worker cache; verify actual HTTPS install behavior and icon appearance on iOS/Android. |
| #48 accessibility | Engineering + independent/device acceptance | Keyboard flows and a local QR-image decoding fallback preserve preview and explicit confirmation. A full WCAG 2.2 AA audit remains open; typed short codes require separate security/product policy. |
| #49 mobile performance | Measured live gate | Build and record actual asset sizes; Lighthouse 90 is not implied by unit/browser tests. Measure on representative deployment/device/network. |
| #50 phone QA | Human/device | Named tester records exact revision, host, browser, device, camera denial, rotation, offline/retry, saved claims and redemption. |
| #51 consenting pilot | Human/live | Real offers, consent, comprehension, disputes and return use require Travis-approved outreach; fixtures do not prove merchant value or adoption. |
| #52 independent setup | Human independent check | Package clean-clone instructions and pinned runtime; a second teammate reproduces setup and records results independently. |
| #53 screen-module split | Explicitly deferred | Preserve PR55 design and behavior during release stabilization. A broad screen rewrite is outside this candidate and adds regression risk; reconsider after pilot evidence. |
| #54 old branches | Engineering inspection + human merge decision | Preserve original branches/WIP and selectively port verified work. Old invite-code and onboarding-only backup approaches remain archived on their branches; no automatic merge or deletion. |

## Cross-cutting engineering acceptance

- Run the complete current workflows and focused native/browser regressions on
  the combined candidate, with official Jac 0.37.23 and isolated stores. No check
  run is not a passing check. Keep failures and original receipts.
- Source composition is informational under Travis's current release policy.
  `check-jac-share.py` reports tracked Git blob bytes, including tests and
  operational tooling. Inventory/Git errors still fail the reporting check.
  No padding, exclusions or conversion target replaces correctness, security,
  official-runtime pinning or the required acceptance gates.
- Reconcile test definitions and named outcomes rather than targeting duplicate
  execution counts. The historical 410-to-380 reduction retained every baseline
  name: 32 fewer import-induced repeats plus two executions of one new test.
- Complete independent security/account, runtime/recovery and experience review,
  fix actionable findings, and rerun affected checks at the final head.

## Launch restrictions awaiting approval

The proposal is one backend and one serialized gateway, without overlap during
replacement. Once the gateway exists, every request reaching the backend,
including ongoing readiness, traverses the same serialized lane. Before gateway
creation only, the launcher may poll bounded private `/healthz/ready` metadata
to await native startup; this probe performs no graph RPC and admits no public
traffic. Operators quiesce traffic and stop both processes before offline
operations. An incomplete upstream response closes the lane until both restart.
No regional scaling, two-replica safety, measured capacity or production readiness
claim follows from this proposal. Final stock-runtime evidence and actual host
capabilities determine whether hosting review can proceed.
