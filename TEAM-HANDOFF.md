# M-Local / PromoPusher team handoff

For the four-person build, use [the team mission and starting prompts](docs/START-HERE.md).
That plan follows the source audit and defines work still to be implemented. The
extraction manifest and verification report below describe the original capture;
later documentation and engineering changes are tracked separately in Git history.

## What this repository contains

The application source recovered from Travis's JacHammer project **M-Local** on
September 26, 2026. The generated interface and README still use **PromoPusher**.
This is the team's prototype for time-limited Ann Arbor restaurant offers.

Source project: https://jachammer.ai/project/prj_91a1ccd4ab324e15b8dac8ef0f6e03d7

All 11 application, configuration and documentation files visible in the expanded
project explorer were copied through the browser editor. Every file was copied
twice; both copies and the saved UTF-8 text matched. The original snapshot is commit
`715b4badee054af755beec1b5ab7d3274cd7d6c5`. Clipboard copies used CRLF line endings;
this is an editor-content recovery, not a raw sandbox filesystem export.

`EXTRACTION-MANIFEST.json` records file sizes and SHA-256 hashes. Application code
has not been rewritten during extraction. The follow-up commit adds this handoff,
the manifest, verification evidence and ignore rules for credentials and local files.
The manifest's original `.gitignore` hash refers to the first commit.

The sandbox `.env`, assistant journal/build plan, generated caches and runtime
database were not exported. Demo data is available in `services/seed.jac`.

## Start here

1. Clone `https://github.com/CosmonautJones/m-local.git`.
2. Read `README.md` for setup, the demo walkthrough and architecture.
3. Use the shared **Jac 0.37.23** pin and [runtime instructions](docs/RUNTIME.md).
4. Follow [phone and teammate testing](docs/PHONE-TESTING.md) on Windows/WSL or Mac.

The export originally reported Jac 0.34.20. Travis subsequently authorized the
latest-version migration. Both his local CLI and the project target now use
0.37.23; the separate learning lab remains untouched. JacHammer's hosted version
is controlled by JacHammer. From this checkout in **WSL Bash or Mac Terminal**:

```bash
bash scripts/setup.sh  # first machine setup; see platform prerequisites
bash scripts/dev.sh
```

Open http://localhost:8000/. On the prepared Windows machine, PowerShell can run
`.\scripts\dev.ps1`. No hosted-model credential is needed. Matching uses Jac rules.

## Original extraction verification

- PASS: 11 source files copied twice and matched against local contents (83,434 bytes).
- PASS: referenced local Jac modules are present.
- PASS: bounded credential-pattern scan found no keys. Demo merchant keys are intentional.
- Local execution was outside the extraction step; see the subsequent runtime checkpoint below.

`EXPORT-VERIFICATION.json` remains the historical extraction evidence.

## Subsequent runtime checkpoint (September 26)

The [current verification record](docs/status/engineer-1.md) documents Jac checking,
seven passing core tests in separate stores, a built `.jab`, and local browser
discovery/claim/redemption. It also records the Windows dependency/watch fixes,
MCP guide calls, and limits. Mac and physical-phone checks are still pending.
Do not interpret a local prototype pass as completed authentication or pilot readiness.

## First team work

1. Have each teammate run the shared setup/check/build/core scripts and record
   their platform and commit. The core wrapper isolates its workspace/store;
   do not directly run reset-heavy tests on the shared demo database.
2. Check student discovery, claim, merchant management and redemption end to end.
   Local redemption feedback was observed; physical phone/touch behavior still needs a run.
3. Replace the fixed demo merchant keys and client-supplied student identity before
   accepting real users. Audit ownership, concurrent claims and one-time redemption.
4. Pin compatible dependencies and record startup/test results on a fresh clone.
5. Retain event-time commit history, document generated/template provenance, complete
   the required Baz review and confirm submission requirements with the organizers.

The UI, graph schema and backend rules are in `.jac` source files. A formal
hackathon language-percentage calculation or eligibility review has not been done.

Use feature branches and pull requests so teammates can work without overwriting
one another. No license has been selected; public visibility alone is not an
open-source license grant.
