# Offline release preflight parity checkpoint — 2026-10-15

This is a bounded engineering increment from main
`b92b92c8387a12e2c55edbb7638c54dfbed78dc2` on
`codex/offline-preflight-parity-2026-10-15`. It is independent of draft PR60;
PR60 remains frozen at `a3b5b1ef2a59d685d006ccf5462fa2cd74c25377`.
It does not incorporate or duplicate PR60's coordinated-restore binding change.
All new worktrees, source, disposable stores and evidence are on X:, including
Ubuntu's X:-backed ext4 disk. Existing writers and Argon state remain preserved.

## Acceptance and concrete gap

Acceptance was recorded before coding from AGENTS, WORK-HANDOFF, TEAM-CONTRACT,
RELEASE-ACCEPTANCE, RELEASE-GATES and RELEASE-HOSTING-PACKAGE. Main's offline
preflight could return PASS for incomplete runtime/build/dependency packages,
missing installed markers, source drift, incompatible native-data bases or
canonical project entries, restricted-edge settings and production guard
failures. This was demonstrated with real CLI invocations and disposable
synthetic packages; their small runtime shims are test fixtures, not evidence of
official-runtime or host qualification.

The change shares two existing launcher blocks: static startup admission and
the bounded packaged production guard. Launch retains lock, free-port check,
final guard and serving-child ordering. The existing gateway's exact
`MLOCAL_TRUSTED_HTTPS_EDGE=1` rule now fails earlier in common admission.
The effective production overrides are identical for both commands. Guard
errors expose setting names only; raw subprocess output and secret/path values
remain private. Guard bytecode writes are disabled without changing the
runtime's supported `-c` invocation.

Preflight has no serving, readiness, lock, port-bind or network-connection path.
The existing guard opens SQLite read-only and creates/removes temporary
writability probes in existing directories; runtime interpreter bootstrap may
initialize local caches. These operations do not establish a provider's durable
backing, backups, public ingress, real mail or host qualification. Default or
missing approval/runtime/host evidence continues to block.

## Observed local checks

- Unchanged baseline: 45 discovered,44 passed,1 explicit native PostgreSQL skip.
- Definitive failing-first v2:7 methods,19 false-PASS assertion failures, before
  any production edit. Original first red log is also retained; one of its 18
  failures was a diagnostic mismatch and was corrected before v2. Marker absence
  and installed-source drift were split so each independently failed first.
- Initial green run: 52 discovered,50 passed,1 skip,1 assertion failure caused
  by an unmounted fixture's signing-secret expectation. The unchanged guard
  could not accept the key's storage, so it did not reach dependent secret
  comparison. That assertion moved to the existing actual mounted native
  package fixture; the guard was not changed or mocked to pass.
- Final full lightweight tooling suite: 86 discovered,83 passed,3 skips (explicit
  native PostgreSQL opt-in and two Windows junction regressions).
- Final production guard suite: 24 passed, including rejection of
  writable but unmounted state. No local heavy/native full suite was started.

The existing CI package fixture now requires both mismatched-secret preflight
refusal with value redaction and successful preflight on its real disposable
mount. Both must preserve original complete private-state/key/photo inventory
and keep backend/gateway ports closed, followed by unchanged authenticated
startup/restore/restart assertions. Those new mounted outcomes are pending CI
at this checkpoint; they are not claimed as local passes.

## Source and retained evidence

- `deploy/release/package.py`: SHA256 `bf016138e38c1c78ec14f1c235411fc66e4ebbffdad6765b869ac5e5313b5832`
- `tests/tooling/test_release_package.py`: SHA256 `3271e0ae0bb7e03c0fbcb7fb2d00c384658911c3e95e5edd9ed87f44f37eb084`
- `tests/integration/release_package_http.py`: SHA256 `2e45418639c16dfd8ef36bfeb505d57444da0c0af335c855b692bc96b89c1cc2`
- `docs/RELEASE-HOSTING-PACKAGE.md`: SHA256 `e99b6eb967a97d695dd3f36b72417fcc400d5ea15a8826a28f17ec9e951e172e`

Local evidence root: `X:/Projects/M-Local/preflight-20261015`.
`ACCEPTANCE-BEFORE-CODE.md`, `source-audit-and-test-matrix.md`, all original
red/green logs, `INITIAL-GREEN-FIXTURE-CORRECTION.md` and
`light-check-results.json` are retained there. Tooling log SHA256
`690ca7f3f536dd1a71e46d4cfc15bb808eaf6352f0f733c9438281b04b2dfb95`;
guard log SHA256
`6ef293f30938b9d1e055070cd784cb13fce7b7527a5c990ba4093a1c3d3173c5`.
Definitive red log SHA256
`a4510c9c12d092a0332fd9924037b2f8b8900d2873b930572988b64ae564bd1b`.

Independent final code/evidence review and required exact-head CI must complete
before qualification. The draft PR and external terminal evidence will record
those results without rewriting this commit-time checkpoint.

## Unclosed release gates

No merge, deployment, purchase, real email, live-data operation, operational
credential or access change is authorized here. Official Jac 0.37.23 stays pinned.
Actual hosting inventory/JacHammer reconciliation, complete durable stores and
original keys/photos, supported singleton topology without rollout overlap,
public ingress/TLS, off-host retrieval and measured RPO/RTO remain unproved.
Human research/privacy/retention/deletion/eligibility policy, named operators,
real inbox/device/accessibility/performance evidence, independent human setup
and consenting pilot gates remain open. Dynamic startup readiness and actual
host acceptance are not replaced by this local preflight.
