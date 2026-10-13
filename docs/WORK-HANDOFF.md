# M-Local: ChatGPT Work coordinator handoff

Travis requested this transfer on 2026-09-26 and explicitly chose **ChatGPT Work**.
He wants an efficient agentic workflow supporting a four-human JacHacks team.

## Current integration instruction (October 13, 2026)

Finish the existing combined release and selective header fix; do not restart
the app or overwrite human work. Main remains `bb475ca` at the start of this
task. Clean local integration `c0a2c5f` has the same tree as header `d192dd4` and
preserves PR55 history. Its complete final-head qualification is still required.
Use the current release gates, business approval, hosting package and runtime
transaction contracts over older checkpoints below. Conditional merge authority
now covers normal reviewed engineering PRs after complete tests and independent
review; public deployment, credentials, real email, live data and contact remain
excluded. Confirm no main updater can deploy before merging.

JacHammer's provider confirmed a free preservation hold until October 16 at
23:59 EDT and supplied a PostgreSQL 18 custom dump. That older deployed source
revision is unknown; the provider dump does not certify the release candidate's
complete SQLite/key/photo backup. Provider correspondence stays with the parent.

## Product and current decisions

Help Ann Arbor students find affordable, time-limited restaurant offers, understand
current access conditions, claim the promised terms and redeem once. Give local
restaurants control over timing, stock and terms. A Jac knowledge graph connects
restaurants, locations, offers, access notices and claims. Keep the scope to one
useful context relationship before expanding into a community aggregator.

**The team has decided to use QR codes instead of typed letters/numbers.** The
runtime branch now contains student QR display, merchant scanning, authenticated
preview/confirmation endpoints and local account provisioning. Read
`docs/QR-REDEMPTION.md` and the newest section of `docs/status/engineer-1.md` for
actual checks and remaining database/device gates. The original checkpoint below
is historical six-character-code evidence. API/ownership rules remain in
`docs/TEAM-CONTRACT.md` v2 with the frozen QR wire contract.
Mixed Windows/Mac computers and iPhone/Android browsers are required test targets.

## Start from the real code

- Repository: https://github.com/CosmonautJones/m-local
- Runtime branch: `feat/01-runtime-release`; use its PR/commit, not stale main.
- Original captured source: `715b4badee054af755beec1b5ab7d3274cd7d6c5`.
- Current runtime work began at `c64b9d82739e3d9664c15325065bc7defd180122`.
- Read `AGENTS.md`, `docs/RUNTIME.md`, `docs/status/engineer-1.md`,
  `docs/PHONE-TESTING.md`, `docs/TEAM-CONTRACT.md`, `docs/TEAM-WORKFLOW.md`, then
  the specific owner mission under `docs/superpowers/plans/`.
- The cloud task must clone/fetch the public repository. Do not assume it can
  access Travis's Windows files, cached runtime, running localhost app or Obsidian vault.

Local origin, when working on Travis's machine:
`C:\Users\Travesty\Documents\Codex\2026-09-23\hey-fellow-travelers\work\m-local`.
Jac is pinned at **0.37.23**. The CLI's bundled guides and real stdio MCP were used
for migration. `jac mcp --transport stdio` exposes the version-matched tools.
Use `jac guide jac-core-cheatsheet` and `jac guide jac-types` before editing Jac.

## What was actually proved

Windows/WSL: source compilation, seven core rule tests in isolated stores,
production `.jab` build, PowerShell launcher, actual browser discovery/filtering,
claim/redemption, and redeemed state retained across app restart. A separate core
test run did not erase the demo claim. A Windows-save bridge triggered real Jac
recompilation. The phone relay served the real app through localhost:8080 with
Vite connected; two relay tests passed. See the status file for detailed limits.

Mac execution and physical phone/touch tests are not done. Some automated mouse
activations failed while keyboard Enter reached the same MobUI controls. Treat
that as an automation observation until a person tests taps. Authentication,
concurrent last-unit safety, stable claimed terms, context integration and QR
rendering/scanning are still work. No hosted model, business contact, deployment
or public tunnel was used. The build artifact was built, not release-served.

Commands: `bash scripts/setup.sh`, `bash scripts/dev.sh`,
`bash scripts/check.sh`, `bash scripts/test.sh core`, `bash scripts/build.sh`.
Stop dev before building. Windows setup uses WSL; Apple Silicon Mac assets exist
but need teammate execution. Intel Mac has no native asset in this Jac release.

## Agent workflow and ownership

The roles are a hybrid, not four independent vertical slices:
1. Platform/runtime/integration: scripts, configuration, cross-layer proof.
2. Backend: identity, graph schema, trusted offers/claims/redemption.
3. Data: importer, fixtures, source labels and one location-specific notice.
4. Frontend: all phone UI, client session handling, QR display/scanning.

Travis's agent coordinator may use bounded subagents. Preserve the human ownership
table; other humans may have local work that is not pushed yet. Start with small
read-only reviews/reproduction in parallel, not four agents rewriting the app.
One coordinator owns integration and the shared contract. Use file-disjoint workers
and an independent verifier; workers return diffs plus commands/results. No worker
merges, deploys, contacts people or makes external spending decisions.

Check open PRs and branch state before dispatch. If a production lane is already
claimed by a human, coordinate with Travis before taking it over. Continue runtime
verification, test design or read-only QR/API review while a lane decision is pending.
The latest agentic request supersedes blanket no-subagent wording in older prompts
for Travis's coordinator, not the other humans' ongoing ownership.

## First bounded increment

1. Review/reproduce the runtime PR in the new environment; report actual errors.
2. Freeze QR credential and DTO details with the backend/frontend owners. A QR
   encodes an opaque durable claim credential; Jac still enforces merchant ownership,
   expiry and single use. Do not merely QR-encode a predictable ID and call it secure.
3. Add QR display and merchant scanning in the assigned lanes, with server-resolved
   terms, explicit confirmation, denied-camera recovery and duplicate-scan handling.
4. Test student phone display -> merchant laptop localhost scanner first. A remote
   merchant phone camera needs HTTPS; the current HTTP LAN relay does not prove it.
   See PHONE-TESTING.md for sources and the network decision boundary.
5. Obtain a real Mac run and physical iPhone/Android flow. Record commit, OS, browser,
   commands and results. Do not declare an all-machine pass from one host.

Keep the hackathon rule/evidence notes and original provenance. The team guide
records a meaningful-Jac threshold and required Baz review; humans must confirm
the event deadline/rules on site. Do not turn old learning code into claimed
event-time implementation. No real-business contact, spending, public deployment
or new hosted-model credentials without the relevant human authorization.
