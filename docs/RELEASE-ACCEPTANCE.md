# Public U-M / Ann Arbor release acceptance

This release candidate starts at `bb475ca`. Travis requested an A for product,
production readiness, and scaling, with agreement from independent reviewers,
and work held at the final review / PR boundary. Passing this document is not a
substitute for running its checks against the actual candidate and deployment.

Baseline independent reviews on October 4, 2026: product B+, production/security
C−, scaling D. None approved A. Reviewer feedback and measured results must be
retained; unfinished or unavailable evidence remains an open gate.

## Product

- Student setup, returning sign-in, preferences, filters, claim, reload, and saved
  QR retrieval work without a dead end at 320/390px in both themes.
- Business manual/import setup, image review, approval, publishing, scheduling,
  editing, pausing, insights, and redemption have one obvious primary action.
- Business imagery appears consistently in setup, feed, offer, and profile, with
  accessible alt text and a useful fallback when the image fails.
- Exactly one appearance control remains throughout navigation. Keyboard, focus,
  camera-denied recovery, rotation, and offline/retry behavior are checked.
- New-offer drafts recover on refresh for the same business account. Cancel,
  successful publication, and sign-out clear the local draft. A lost response,
  equivalent formatting, or API restart cannot create a second offer; a changed
  payload directs the owner to edit the original offer from Manage.
- Real iPhone Safari and Android Chrome QR display/camera flows cover review,
  explicit confirmation, repeated scan refusal, and saved state after restart.
  Evidence names the revision, host, device, browser, scenario, and result.

## Production and trust

- Reconcile JacHammer's five hosting commits with the tested candidate without
  overwriting them. Prove the public artifact's exact revision and current UI.
- Account, identity/session, owner, draft, OTP/key, offer, and claim state survive
  replacement of either app instance. Independent replicas share durable state.
- Restore the complete application into an isolated deployment and verify users,
  ownership, saved prices/terms, pending claims, and redeemed status. Measure RPO
  and RTO; proposed regional targets are 15 minutes and 30 minutes respectively.
  See `BACKUP-RECOVERY.md` for the confirmed canonical-path constraint and the
  authenticated gate required before traffic opens.
- Public ingress blocks native registration/login, admin/graph/docs routes,
  bounds request bodies, enforces abuse limits, and sets browser security headers.
- Verify account/merchant isolation, expiry, wrong-owner denial, private QR
  handling, and failure behavior on the exact public ingress.
- **Confirmed policy:** approve a business once before public visibility, then
  let it manage offers. Name/address changes require another review; routine
  profile edits remain self-service. Operator approval/suspension must be authenticated or
  local-only, auditable, and unavailable through client parameters.
  See `BUSINESS-APPROVAL.md` for the submitted-revision check and rollout.
- Student eligibility policy is pending Travis's answer. U-M inbox ownership
  must not be described as verified current enrollment.
- Email headroom, failures/bounces, sender configuration, and U-M delivery are
  checked. No SMTP credentials, code values, or QR credentials enter logs.
- Uptime/error/latency monitoring, alerts, support, privacy/retention/deletion,
  suspension, incident response, and rollback have an accountable operator and
  an exercised procedure. No outreach or spending is implied by this checklist.
- Run a consenting merchant/student pilot and record usable real offers,
  publishing/redemption comprehension, disputes, and return use. Fixture data
  and generated analytics do not prove adoption or merchant value.

## Scaling benchmark

Reviewers propose this concrete regional envelope: two Jac app instances, one
shared Postgres database, one trusted ingress, 30 merchants, 120 active offers,
500 accounts, and 250 concurrent browser clients. It is a benchmark target,
not measured capacity. Scale the target if launch requirements exceed it.

- Sustain 20 requests/second for 15 minutes across feed, session, profile, and
  offer reads: p95 ≤1s, p99 ≤2.5s, HTTP errors <0.5%.
- Exercise 50 simultaneous claim/redemption attempts across both instances:
  mutation p95 ≤2s, p99 ≤5s; exactly one winner for a one-unit offer and exactly
  one successful redemption of a claim.
- Concurrent cold starts do not duplicate seeds, businesses, owners, or accounts.
  OTP consumption and sending quotas apply across instances.
- Crash/restart, disconnect, and retry cases preserve invariants and recover.
  Unknown COMMIT outcomes return an explicit uncertain result without automatic
  body replay; offer publication reconciles through its owner-scoped create key.
  A lease expiring or an advisory connection disappearing must not permit a
  stale mutation to commit outside coordination.
  See `RUNTIME-TRANSACTION-RISK.md` for the pinned-runtime retry issue.
- Merchant analytics stays within the read target with 365 days and at least
  10,000 historical claims. Publish latency, errors, lock waits, memory, database
  connections, dataset size, topology, and test duration with the results.

## Independent final review

Reviewers must inspect the final diff and evidence independently. A gate is open
when proof is missing, indirect, stale, or scoped more narrowly than its claim.
Do not mark the goal complete, request a PR, or call the whole release A until
all reviewers agree and all required evidence is current. Publication remains
at Travis's requested final review boundary.
