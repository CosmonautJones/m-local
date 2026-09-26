# Engineer 4: Phone Experience Implementation Plan

**Approved update:** QR redemption replaces typed letters/numbers. Follow
TEAM-CONTRACT v2: render the server's QR payload, scan on the merchant screen,
show the resolved terms, and require confirmation. Handle camera denial and
duplicate detections. Coordinate the payload/API with Engineer 2 and secure-origin
phone testing with Engineer 1. Legacy code-entry wording below is superseded.

> **For agentic workers:** Four human engineers run their own models. Implement
> only this mission. Use `superpowers:executing-plans` if available; otherwise use
> the inspect, failing-test, implementation, verification loop. Do not spawn agents
> or replace another engineer's backend implementation.

**Goal:** Let a student and merchant complete the whole exchange on a phone without
coaching, ambiguous terms, silent failures or controls stuck in a loading state.

**Architecture:** Retain the MobUI interface and its current four views. Own every
change to main.jac/theme.jac. Consume the shared authenticated API and contextual
DTOs, keeping source facts, availability and confirmed actions server-owned.

**Tech stack:** Jac MobUI, the pinned runtime's session helpers, browser/UI testing.

**Spec:** [Mission](../../START-HERE.md), [contract](../../TEAM-CONTRACT.md),
[workflow](../../TEAM-WORKFLOW.md).

## Global constraints

- Branch: `feat/04-phone-experience`; keep application logic in Jac.
- Mobile browser and actual iPhone Safari first; native packaging is deferred.
- No fake success or model-generated facts in the real application flow.
- No public write-enabled pilot without verified identity/ownership.
- No real business contacts, spending, secret commits or unapproved deployment.

## Files and ownership

Modify `main.jac`, `theme.jac`. Create `client/session.cl.jac`,
`tests/ui/phone-flow.spec.ts` (or the same cases in the team's already-supported
browser test format), `docs/phone-validation.md`, and `docs/status/engineer-4.md`.
Do not edit server modules, schema, fixtures or runtime configuration. Ask Engineer
1 before adding a test dependency. Keep JSX in the entry module until the selected
compiler's MobUI module restrictions have been verified; avoid a speculative rewrite.

## Interfaces

Consume the exact core API, SessionView, claim snapshots and AccessContextView in
TEAM-CONTRACT. Produce the client session adapter's signIn/signOut/loadSession
functions using Engineer 1's proved runtime helpers. Engineer 2 remains the identity
authority. Do not store or submit a client-selected role/student ID as authorization.

## Review focus

1. Rejected request: busy state always clears and the user gets a useful next action.
2. Out-of-order filter responses: an old response cannot replace the latest selection.
3. Offer changes after claiming: show the claim's snapshot, not newly edited terms.
4. Expired/unconfirmed context: no stale entrance instruction appears authoritative.
5. Phone keyboard, long text and session switching: actions remain reachable and private state clears.

## Work sequence

### 1. Make the existing screens reliable

- [ ] Read current main.jac/theme.jac and the shared API contract. Record each current
  async handler and its loading/error/empty/success states before changing it.
- [ ] Add browser cases `claim_failure_recovers`, `redeem_failure_recovers`,
  `offer_save_failure_recovers`, and `profile_save_failure_recovers`. Simulate an
  actual rejected request; assert an error, cleared busy state and enabled retry.
- [ ] Add try/catch/finally or the verified Jac equivalent around every async UI
  operation. Preserve user input on failure. Never show success before server confirmation.
- [ ] Add `latest_filter_response_wins`; delay an earlier response and verify it cannot
  overwrite results for the later selected budget/diet/time. Handle missing offers
  with a usable return path rather than a permanent loading screen.
- [ ] Reproduce the reported missing redemption feedback in a real browser. Use the
  actual result to fix it; the current source already contains a message component.

### 2. Integrate authenticated roles and exact claims

- [ ] Replace the public merchant-key picker and arbitrary student-ID field with
  session-aware sign-in/out. Use provisioned demo accounts; label demo content.
  Guests can browse, and claiming prompts sign-in. Merchant screens are role-gated
  for usability, while the server independently enforces permission.
- [ ] Add `signout_clears_private_state` and `student_cannot_show_merchant_controls`.
  On account changes, clear previous claim codes, merchant data and in-flight results.
- [ ] Migrate server calls to the key-free/identity-free signatures. Temporary fixtures
  belong only in UI tests; the final application must call the real Jac server.
- [ ] Display snapshot price, title, terms, eligibility and the claim deadline for
  an existing hold, including after an offer edit. Provide cancellation and its
  confirmed outcome according to the server contract. A retry must show the same code.
- [ ] Keep merchant creation practical: readable labels, numeric prices/quantity,
  clear Ann Arbor timezone, field validation, visible saved state and pause controls.
  No new menu-management or merchant-registration subsystem in this slice.

### 3. Make local context legible and verify the phone flow

- [ ] Render access_context with summary, source/publisher, checked time, validity
  and a demo label when applicable. A needs_recheck notice must clearly say it is
  unconfirmed/outdated and must not recommend a specific unverified entrance.
- [ ] Add `context_change_updates_detail` and `stale_context_has_no_definitive_route`.
  Legacy free-text notes are unverified merchant notes unless the new context record
  independently supports them. Do not label offer availability as actual opening hours.
- [ ] Add `claim_snapshot_survives_offer_edit` and the two-session full flow to UI
  acceptance. Use Engineer 1's isolated fixture server and Engineer 2's real API.
- [ ] Run `./scripts/check.sh`, relevant UI tests and `./scripts/test.sh all` once
  the integrated backend exists. Record blocked cases rather than simulating passes.
- [ ] Test real iPhone Safari with the human owner: sign-in, filters, keyboard/form
  entry, claim code, cancellation, redemption and an interrupted network request.
  Browser device emulation alone is not proof of physical Safari behavior.
- [ ] Record viewport/OS, commit, tested actions, screenshots and remaining issues in
  docs/phone-validation.md. Ensure large text and narrow width keep actions reachable.
- [ ] Commit focused UI changes and open your PR. Send backend failures to Engineer 2
  and source/context failures to Engineer 3 instead of patching their modules.

## Done when

The complete flow works against the real server in separate roles, actual phone
checks are recorded, requests recover from failure, private state clears between
users, and claim/context wording matches the facts. Do not replace evidence with
screenshots of static or mocked states.

## Starting prompt

```text
You are Engineer 4, phone experience owner for M-Local.
Repository: https://github.com/CosmonautJones/m-local
Read AGENTS.md, docs/START-HERE.md, docs/TEAM-CONTRACT.md,
docs/TEAM-WORKFLOW.md, and your plan:
docs/superpowers/plans/2026-09-26-04-phone-experience.md.
Implement only this mission on feat/04-phone-experience in my own clone.
Own main.jac, theme.jac, client/session.cl.jac, UI checks and phone-validation
notes. Do not edit server files, graph schemas, seed data or runtime configuration.
Preserve the existing MobUI app and improve the complete student/merchant flow.
First fix asynchronous recovery and reproduce the redemption-feedback issue.
Then consume the agreed authenticated API, remove demo-key/arbitrary-ID controls,
show immutable claim terms and cancellation, and display Engineer 3's sourced
context with truthful current/stale/demo states. Use Engineer 1's verified auth
helpers and runtime. Guard against stale requests and account-switch data leaks.
Use fixtures only in tests, never as pretend application success. Verify narrow
screens, keyboards and real iPhone Safari with my help when device input is needed.
No framework rewrite, native packaging, new backend, contacts, spending, deployment
or extra agents. End with commit/PR, exact checks, screenshots, real-device versus
emulated results, remaining issues, and docs/status/engineer-4.md.
```
