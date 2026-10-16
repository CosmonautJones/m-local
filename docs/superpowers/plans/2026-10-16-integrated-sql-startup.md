# Integrated SQL Startup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove canonical disposable SQL application startup, original identities and photo delivery/restart through the existing guarded package launcher.

**Architecture:** Keep the launcher and its existing native child slot. A bootstrap running in the restored app venv validates established SQL state and an exact/fresh cache, exports the preserved key in-process and execs official Jac. Existing singleton/gateway lifecycle and production refusals remain intact.

**Tech Stack:** Official Jac 0.37.23, Python stdlib, psycopg binary 3.3.6, official PG18, existing Node gateway and GitHub workflows.

**Spec:** `docs/INTEGRATED-SQL-STARTUP.md`

## Global Constraints

- Official Jac 0.37.23 stays pinned; one backend and serialized gateway, no overlap.
- No production SQL admission, implicit import, initialization, replacement or fallback.
- Preserve graph/identity, both SQLite stores including suspension audit, both keys and original photos.
- All deliberate local files/evidence on X:; no local heavy services/tests while TravOS owns the slot.
- No spending, deployment, merge, live data/credential/permission changes or external messages.

## Review Focus

- Ambient production/driver/native redirect settings cannot escape explicit disposable admission.
- Conflicting effective signing keys must refuse before native auth initializes.
- A partial cache from a failed publication cannot be repaired or served silently.
- Original tokens must reach root-backed profiles and ownership, not merely decode.
- Exact tar replay, matching PG18 clients and clean process termination bound the result.

---

### Task 1: Failing actual restored application proof

**Files:** `tests/integration/release_package_http.py`, new `tests/integration/sql_startup_http.py`, `.github/workflows/release-package-proof.yml`.

**Interfaces:** Fixture adds a normal restored-venv driver assertion before PG services; SQL phase consumes original fixture tokens/state after the unchanged 104 legacy checks. Workflow supplies a safely re-extracted exact archive and existing mount.

- [ ] Add driver/bootstrap and actual-launch behavior assertions, plus every required refusal in spec 6–8.
- [ ] Run existing hosted package workflow; verify clean missing-normal-driver assertion (RED1).
- [ ] Pin ordinary `psycopg[binary]==3.3.6` in `jac.toml`; run again and verify actual SQL launch refusal at the absent mode (RED2), with all old assertions preserved.
- [ ] Commit separate test/config checkpoints with immutable hosted evidence.

### Task 2: Minimal startup admission

**Files:** `deploy/release/package.py`, `services/onboarding_backend.py`, `services/production_guard.py`, `services/postgres_auxiliary.py`; focused `tests/tooling` only if needed.

**Interfaces:** `validate_launch_inputs(..., disposable_sql=False)` remains static; `launch(..., disposable_sql=False)` preserves its process ownership. `bootstrap_native(argv)` in onboarding backend validates normal driver, SQL keys/catalog and cache before `os.execve`. `PostgresAuxiliary.validate_photo_cache(cache_dir, preserved_registry=None)` verifies exact existing cache without writes; `materialize_photos(cache_dir, preserved_registry=None)` retains its existing fresh-cache behavior. Actual bootstrap always supplies the preserved original registry and compares all imported metadata before any cache write; optional defaults retain older adapter callers only.

- [ ] Implement CLI admission and full static safeguards for explicit owned disposable context; all other modes retain refusals.
- [ ] Add in-process original-key bootstrap in the existing native child slot, sanitize injection/redirect settings, then exec official Jac unchanged.
- [ ] Validate the mandatory original registry and every imported SQL photo metadata row (including owner drift with empty cache); validate exact nonempty cache or materialize empty cache; refuse invalid/partial state and uploads.
- [ ] Run hosted actual startup/HTTP/restart/refusal proof to GREEN, inspect unchanged originals and cleanup receipts; fix real failures without relaxing assertions.
- [ ] Commit minimal runtime changes.

### Task 3: Exact-head qualification and review

**Files:** `docs/INTEGRATED-SQL-STARTUP.md`, relevant release handoff/status, X: evidence only.

**Interfaces:** Final immutable head consumes all previous proof receipts. Independent reviewer reads cumulative diff from frozen PR67 plus source-bound hosted evidence.

- [ ] Obtain independent source and runtime review and resolve material findings with failing-first checks.
- [ ] Run all five existing workflows/eight jobs at the frozen final SHA; preserve raw logs, artifact inventories and portable checksums on X:.
- [ ] Verify no-spend payload retention feasibility; if unverified, record that blocker without uploading the large payload.
- [ ] Prepare and attach reviewed draft PR; report exact branch/SHA, limits, remaining human gates and next action.
