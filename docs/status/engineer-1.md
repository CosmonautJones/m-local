# Engineer 1 status: local runtime checkpoint

Date: 2026-09-26. Branch: `feat/01-runtime-release`.
Base: `c64b9d82739e3d9664c15325065bc7defd180122`.
This is the runtime checkpoint, **not completion of the full integration mission**.

## Verified on Travis's Windows/Ubuntu WSL x86_64 machine

| Check | Result |
|---|---|
| Official release | Latest stable `v0.37.23`; Linux executable and companion matched publisher SHA-256 files |
| Local CLI/project pin | Both 0.37.23; previous user CLI backed up; independent 0.37.21 lab unchanged |
| Real Jac MCP | Initialized stdio server; 19 tools listed; five bundled guide resources fetched via `tools/call` |
| Whole-program check | `bash scripts/check.sh`: exit 0; compiler warnings remain |
| Core rule tests | `bash scripts/test.sh core`: 7 passed; repeated in a second distinct workspace/store |
| Paths containing spaces | Copied source/scripts into `path with spaces`; core wrapper returned 7 passed |
| Missing runtime / missing integration suite | Clear diagnostic and exit 2 in both cases |
| Production build | `bash scripts/build.sh`: exit 0; `dist/mobile-starter.jab`, 874733 bytes on this run; 5/5 server modules compiled |
| PowerShell launch | `.\scripts\dev.ps1`: Jac API at 127.0.0.1:8001 and Vite at localhost:8000; actual page opened |
| Browser | Five visible demo offers; $5 filter reduced to latte/slice; offer details loaded from Jac |
| Claim and redeem | Fictional $3 latte claim generated a six-character code; stock 25 -> 24; Arbor Leaf redeemed it with visible charge/feedback |
| Store isolation and restart | Separate core test run did not remove the claim; stopping/restarting the dev server retained its REDEEMED status |
| Windows edit loop | Changed heading to `LOCAL JAC EDIT CHECK`, observed browser update, restored it. The content-hash bridge also triggered recompilation of a temporary callback diagnostic, then that diagnostic was removed |
| Phone relay | Two Node tests pass: app body forwarding/admin rejection/Vite entry, and actionable stopped-upstream response. Real browser loads the Jac app and persisted redemption through localhost:8080; Vite websocket connected |
| Mobile viewport | DOM viewport 390 x 844, document scrollWidth 390; this is not a physical Safari test |

Browser automation's mouse activation did not reliably trigger some MobUI
Pressable controls. Keyboard Enter did trigger the same controls and actual Jac
requests. Do not report a confirmed touch defect from this observation; test on
the physical phone. Temporary Jac instrumentation was removed before the build.

## Failures that informed the setup

- The exported entry point/placement syntax and unparameterized generic types
  failed current Jac checks. A bounded compatibility migration fixed those errors.
- WSL DNS could not resolve GitHub/npm; Windows fetched official assets and
  installed Linux-targeted frontend dependencies. Current Jac regenerates its
  manifest for production; the fallback was repeated for that manifest.
- Windows npm generated a shell launcher for Vite. Bun failed while parsing that
  shell script. Replacing only the generated launcher with Vite's Linux symlink
  let Jac start the frontend normally.
- Windows saves were invisible to Linux inotify. A content-hash poller emits Linux
  modification events, without rewriting saved source bytes. Rapid changes during
  compilation once produced `Sources changed during preparation`; stable retry
  recovered. Rebuilds on the mounted Windows drive can take tens of seconds.
- A PowerShell `wslpath` call lost Windows path separators through shell parsing.
  The launcher now uses `wsl --cd <Windows path> --exec bash ...` directly.
- The initial phone relay blocked Vite's `index.html?html-proxy` entry module.
  The added regression assertion failed 403 vs 200, then passed after allowing
  that exact asset. The real page subsequently rendered through the relay.

Local raw evidence remains ignored under `.jac/evidence/`: `build.log`,
`script-check-all.log`, `script-core-tests*.log`, `path-spaces-test.log`,
`browser-flow.log`, `dev-script.log`, `windows-npm-launcher-failure.log`,
`phone-relay-tests.log` and `local-redemption.png`. Runtime/MCP downloads and the
first isolated test workspace are outside the repo in sibling `m-local-runtime`.
Do not commit local graph data, generated secrets, node_modules or compiler caches.

## Still unverified or unfinished

- Real Mac teammate execution and clean-clone bootstrap on every team computer.
- Physical iPhone/Android testing on the intended network; LAN sharing is an
  explicit `--lan` command, not an automatically opened public tunnel.
- Running the produced `.jab` as a release server (the build itself passed).
- Real identity/ownership, two authenticated roots sharing a catalog, concurrent
  last-unit HTTP claims, retry guarantees and immutable claimed terms.
- Context/integration suites, fresh authenticated `demo.sh`, CI, Baz review,
  competition eligibility review and deployment. `test.sh all` must not appear green.

## Decisions and next handoffs

- The user's latest-version request authorizes the small cross-owner compatibility
  edits; carry them into the other branches. It does not authorize redesigning
  their domain/UI implementation in this checkpoint.
- The roles are a hybrid platform/backend/data/frontend split. Keep file ownership,
  publish small DTO/auth contracts early, and pair Engineers 1/2 on the auth probe.
- Have one Mac teammate and another Windows teammate run [the checklist](../PHONE-TESTING.md).
  Engineer 4 then records a real phone flow, including tap behavior. Engineer 2
  should deliver the first auth/offer interface checkpoint before large UI rewrites.
