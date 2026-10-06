# Runtime Verification

## Selected runtime

- Jac: `0.37.23`
- Verified platforms: macOS arm64 (historical); Linux x86_64 on WSL/Kali (controlled October 4 checks)
- Pin: `.jac-version`
- Runtime location: `~/.local/share/m-local/runtimes/0.37.23/jac`
- Client build: Bun 1.3.11, Vite 6.4.3, React 18.3.1, react-native-web 0.19.13
- Persistence/runtime support: Jac embedded PostgreSQL on the runtime branch

The runtime was installed by `bash scripts/setup.sh`. Both the `jac` and
`jacpython` release assets were checksum-verified. The repository scripts reject
a missing or mismatched Jac binary.

Host Python 3 is a prerequisite for project tooling and cache path checks.
`scripts/setup.sh` verifies it before downloading anything. The bundled
`jacpython` is used separately for fixtures that import Jac services.

Keep `JAC_CACHE_HOME` outside the application checkout. `scripts/runtime.sh`
rejects paths inside the checkout, including relative paths and symlinks into
it. A controlled comparison with identical application/dependency inputs and
the same sealed runtime passed with a sibling cache in 42.09 seconds; placing
the cache under the app root exceeded a 120-second guard. Imported runtime
modules under the project root can enter whole-app dependency analysis.

`scripts/build.sh` defaults Jac's sealing step to two precompile workers and
recycles workers at 1,024 MiB. Set the existing `JAC_PRECOMPILE_JOBS` and
`JAC_PRECOMPILE_RECYCLE_MB` variables if a build host needs different limits.

## Commands verified

```bash
bash scripts/setup.sh
bash scripts/check.sh
bash scripts/test.sh core
bash scripts/build.sh
MLOCAL_PORT=8127 bash scripts/demo.sh
bash scripts/test.sh integration
bash scripts/test.sh all
```

Historical macOS results:

- `check.sh`: pass.
- `test.sh core`: 3 passed, 2 skipped.
- `build.sh`: pass; produced `dist/mobile-starter.jab`.
- `demo.sh`: pass; isolated server returned HTTP 200 on port 8127.
- UI/tooling integration checks: 11 passed.
- `test.sh integration`: intentionally nonzero when `.jac/qr-demo-accounts.json` is absent.
- `test.sh all`: intentionally nonzero because context tests and provisioned QR HTTP tests are not available in this checkout.

`dev.sh` uses `jac run --dev --host 127.0.0.1 --port 8000` for Jac 0.37.23.
`demo.sh` uses a temporary copied workspace and a dedicated `MLOCAL_PORT`.

### October 4 Linux verification

The current application snapshot (`9ef18320b7d10f8cfdba5ee6b8700f4706d41931998e1175ccacdeebcf740412`)
passed the canonical source check, 451 core tests, 75 onboarding/operator tests,
12 analytics tests, 62 native insights checks, 11 insights JavaScript checks,
126 compiled UI checks, 13 UI unit checks, 18 JavaScript tooling checks and the
sealed build on official Jac 0.37.23. Python tooling ran 12 tests: 11 passed
and the case-insensitive-filesystem check was skipped on Linux ext4. That
remaining canonical case-alias test then passed separately on E: NTFS through
WSL DrvFS, using a fixture Jac version responder.

The sealed artifact is 4,424,686 bytes, SHA-256
`ece36e69f5cee0b7fc0a39449a9917b7a3fcbef371be1c43d731c10f5d2d5f93`.
The build used two precompile workers and 1,024 MiB recycling; measured peak
process-group RSS was 3,908,220 KiB. This is one host's build result.

An isolated fictional local preview also passed 23 authenticated HTTP QR checks
and 11 role, claim, redemption and same-state restart checks. These include
last-unit claim/redemption races, denied wrong-account access and repeat
redemption after restart. SMTP is disabled in this preview. It provides no
real inbox, physical camera, multi-process, derivative-runtime or sustained
capacity proof. Evidence is retained as `operator-store-native-v1`,
`application-native-v1`, `client-native-v1`, `case-insensitive-cache-v1` and
`local-paired-preview-v3` in the task's separate outputs; private account files
are excluded. Earlier preview receipts remain as historical snapshots.

### Strict isolated backend coverage

For application source `71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42`,
the [strict backend receipt](review/backend-coverage-v35/verification.json)
records 451 core tests and 62 Jac insights tests passing with no skips, plus
12 Python and 11 JavaScript insights tests.

Graph suites install the declared Python dependencies in their fresh workspace
with `jac install --no-npm` and enable `JAC_TEST_STRICT=1`. This prevents missing
imports, including Pillow, from silently skipping a test file. Fresh installs
need network access. Unset `JAC_DB_URL` when running these suites: an external
URL overrides Jac's per-case scratch database isolation, so the harness refuses
it before creating test or PostgreSQL state. Integration tests retain their
separate documented server and account setup.

## Authentication and integration gates

The Jac runtime authentication API is documented in the bundled
`jac-sv-auth` guide: register with `identities` and `credential`, then login
with `identity` and `credential`; authenticated functions receive the caller's
root implicitly. `scripts/provision-demo.py` creates private local accounts and
a server-only merchant ownership map without printing credentials.

Not yet verified here:

- compatibility and capacity of the proposed derivative runtime;
- real public U-M inbox delivery on the current deployed revision;
- physical iPhone/Android camera flow and secure-origin camera behavior;
- a separate teammate clean-clone run;
- Baz review, event deadline confirmation, and deployment authorization.

No public write-enabled pilot is authorized by this document.

Python tests that import Jac services must use the pinned companion interpreter:
`bash scripts/test.sh onboarding` or `bash scripts/python.sh tests/integration/onboarding_http.py`.
The latter fixture requires its documented isolated local server and store; it must not target production.
Plain system Python does not register Jac imports. `scripts/setup.sh` installs both executables together.
