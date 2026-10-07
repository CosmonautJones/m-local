# M-Local release candidate: BLOCKED

The bounded engineering work is implemented, independently reviewed, pushed and tested on the exact heads below. All applicable functional, native preservation, concurrent/fault, student browser and packaged recovery checks passed. Required CI remains red: the unchanged Jac source-byte criterion is **31.26% against 40%** for the combined candidate. Hosted and human acceptance also remain open. No merge or live deployment was performed; this package does not authorize either.

| Package | Branch / exact SHA | Review |
| --- | --- | --- |
| Refreshed main | main / bb475ca8eb1a96091af7b1356ffc758d31cd05c7 | Preserved |
| Foundation | codex/release-readiness / c581d142a08f733e0ebc0324ff6987a9d12c8f8b | [Draft PR55](https://github.com/CosmonautJones/m-local/pull/55) |
| Hardening | release/native-hardening / 82420879b9e57091b4827c39ed6aa6229cd115c3 | [Draft PR56](https://github.com/CosmonautJones/m-local/pull/56), foundation base |
| Student experience | release/student-experience / 936e205a33aada4b2ad5aa6e430d58033c3d4688 | [Draft PR57](https://github.com/CosmonautJones/m-local/pull/57), foundation base |
| Combined | release/combined-candidate / 2be568a4e1a7fc3bef1a601d78b415ef8d88c99d | Coordinator integration; tree7e7552dd712f22ce7704d4d427df7c9f8aec1ef5 |

Original primary human status/staging/patch and original pilot worktrees are preserved. Bounded builders used disjoint ownership and the coordinator integrated shared files. Council reviews cover security/account preservation, runtime/deployment/recovery and experience/evidence quality; they provide review evidence, not merge authority. Original branches, failed receipts and dropped invite-code/onboarding-only backup approaches remain preserved.

## What changed

Production launch now refuses invalid configuration unsuccessfully before serving children or listeners survive. It checks actual deployment, mounted storage, graph/identity, onboarding SQLite, retained private signing keys, photos, SMTP and sample/demo policy, identifies missing setting names without values and retains usable development behavior. Direct native CLI startup is not the approved production entry point.

Native registration squatting is reproduced on disposable native HTTP and blocked at the intended public ingress. Internal passwordless provisioning remains private. Collisions retain existing native users, roots, keys, SSO/provisioned identities, merchant ownership and held/redeemed claims. Missing onboarding never authorizes deletion or automatic relinking. An auditable operator reconciliation procedure handles existing collisions.

Students browse useful sanitized offers before signup. Claim sign-in retains only the selected public offer ID through verification/reload, rechecks availability and requests explicit confirmation. Server sample policy covers feed/detail/profile/favorite reads and writes, mixed parent/child flags, inherited labels and claim admission, while preserving legitimate saved claims, immutable snapshots and stored favorite marks. Foundation photos, drafts, retry, navigation, account isolation, manual approvals and complete recovery remain intact. Metadata/icons/public links, keyboard and responsive flows, honest states, unobstructed QR and lazy merchant decoding are included.

Bounded first-wave prerequisites cover #38 monitoring preparation, #40 ingress/headers/limits, #43 two-live-hold cap, #46 visible redemption refresh, #47 manifest/icons and #48 keyboard/image-QR recovery, plus #49 lazy scanner delivery. Monitoring events are redacted and do not claim durable COMMIT from a pre-finalization result. Hosted alerts, devices, performance and broad accessibility acceptance remain open. Typed short-code policy and broad screen-module redesign are explicitly deferred; this does not close all21 child issues.

Actual restart diagnosis identified a cold catalog exceeding the five-second health bound. The gateway now performs one full anonymous catalog startup admission through the existing serialized lane under the ordinary30-second bound, with public RPCs closed until acceptance. Periodic health validates native metadata and the strict guest session under the original five-second bound. Native serializer metadata is accepted only as exactly all four known string fields alongside the nine fixed guest values; unknown/partial/malformed or authority-changing fields are refused. Health exposes only readiness. The3/5/30/300 bounds and permanent uncertainty latch remain unchanged. Earlier failed actual proof and the independent mock-only review miss remain disclosed in [REVIEW-READINESS-FOLLOWUP.md](REVIEW-READINESS-FOLLOWUP.md).

Recovery/preflight rejects unsupported PostgreSQL URLs before locking or spawning and prevents inherited libpq service, host-address, option or password-file settings from redirecting an explicit native database URL. No automatic account/database renaming, deletion or remapping occurs. Official native plain-wire PostgreSQL does not prove compatibility with a TLS-required provider; that remains #35's operator/provider gate.

## Exact final verification

| Combined workflow | Exact PUSH run | Conclusion / evidence |
| --- | --- | --- |
| Full checks | [37611016712](https://github.com/CosmonautJones/m-local/actions/runs/37611016712) | Functional jac SUCCESS; required source-share FAILURE31.26% |
| Shared native onboarding | [37611016652](https://github.com/CosmonautJones/m-local/actions/runs/37611016652) | Actual native84 SUCCESS; workflow FAILURE from source-share |
| Native preservation/topology | [37611016746](https://github.com/CosmonautJones/m-local/actions/runs/37611016746) | Actual80 preservation +266 stock-runtime checks/21 faults SUCCESS |
| Actual student browser | [37611016646](https://github.com/CosmonautJones/m-local/actions/runs/37611016646) | All62 checks/14 scenario groups SUCCESS |
| Offline package/recovery | [37611016706](https://github.com/CosmonautJones/m-local/actions/runs/37611016706) | Actual66 authenticated packaged startup/recovery checks SUCCESS |

Official Jac0.37.23 remains pinned and unmodified. Combined source checks;493 core executions/134 expected names; context13; insights12 Python/11 Node/68 Jac; onboarding109; shared-process7; photos7; native business approval/restart; coordinated physical recovery71; monitoring23; deployment-tooling70; production build; Node66; disposable PowerShell deployment safety; and compiled browser162 passed. All applicable steps executed. [combined-functional-2be568a.json](combined-functional-2be568a.json), [test-inventory-2be568a.json](test-inventory-2be568a.json), [monitoring-2be568a.json](monitoring-2be568a.json), [2be-native.json](2be-native.json) and [2be-package.json](2be-package.json) bind original receipts and source inputs.

Hardening exact checks[37610994731](https://github.com/CosmonautJones/m-local/actions/runs/37610994731) pass451 core/124 names, Node63 and compiled130; native[37610994745](https://github.com/CosmonautJones/m-local/actions/runs/37610994745) executes80 preservation checks. Its integrated-runtime and student-browser acceptance steps are conditional skips. Source36.87% fails. Experience exact checks[37611006751](https://github.com/CosmonautJones/m-local/actions/runs/37611006751) pass478 core/131 names, Node66 and compiled162; actual browser[37611006749](https://github.com/CosmonautJones/m-local/actions/runs/37611006749) passes62/62 with1988.63ms redemption update. Source36.43% fails; its native-hardening/topology steps are skips, not additional native proofs. [CI-INVENTORY-2be568a.json](CI-INVENTORY-2be568a.json) records all13 terminal exact-head PUSH outcomes and proof-step skips. Synthetic PR checks never substitute for these results.

The old standalone cf5 browser61/62 failure is preserved, diagnosed and superseded by actual final93662/62; it was not waived as flaky. Historical410 executions/110 names versus380/111 retain every baseline name:32 fewer import repetitions plus2 new executions give net-30. Final foundation comparison has ten additional core definitions, the intentional sanitized-public-policy replacement, one strengthened sample assertion and two retained fixture/claim assertion sets. No unexplained missing assertions were found; lexical inventory is not branch coverage. Main114/114 and the old local113/114 remain separate observations.

## Artifact and hosting package

The recreated local portable archive is363,842,601bytes, SHA256802784f2b264897ce99892b91e78468a29f42af9f7945016f7c040e26fe89513; compiled jab991ed8572c62071a4c9ec37f71b3a044fa2deb0a6fec87f97c3eada76ebb8141 and dependenciese85278d939782cb9a3e7231993a0088bcb51a6418a4f571d171839f0e026dcbe. It is private because full tracked source contains existing research material governed by #41. Only reviewed small evidence projections are published. No database/backup/private key/QR capture/raw log/contact contents are included here.

The first local package drill stopped before fixture startup on WSL EIO. Full430-file manifest traversal later found exactly four changed copied payloads and no extras; retained build inputs and installed official binaries still matched all expected digests. The failed copy was preserved. A new package was created from those verified inputs, flushed, verified and archived. **It has no local authenticated recovery certificate.** The recreated package's actual local drill again failed with filesystem EIO during source installation, before database/mail/server startup; zero checks completed and owned-service cleanup is true. Its [failure projection](local-recovery-2be568a.json) retains the exact manifest and original receipt digest. The final cloud artifact has separate hashes and passed66 authenticated recovery checks; do not substitute its certificate for the local archive. [LOCAL-ARTIFACT-2be568a.json](LOCAL-ARTIFACT-2be568a.json) and [local-package-integrity-2be568a.json](local-package-integrity-2be568a.json) preserve that distinction. The filesystem cause remains unproven.

Read the exact-source [hosting package](https://github.com/CosmonautJones/m-local/blob/2be568a4e1a7fc3bef1a601d78b415ef8d88c99d/docs/RELEASE-HOSTING-PACKAGE.md), [operators](https://github.com/CosmonautJones/m-local/blob/2be568a4e1a7fc3bef1a601d78b415ef8d88c99d/docs/OPERATORS.md), [all-issue gate matrix](https://github.com/CosmonautJones/m-local/blob/2be568a4e1a7fc3bef1a601d78b415ef8d88c99d/docs/RELEASE-GATES.md), [identity reconciliation](https://github.com/CosmonautJones/m-local/blob/2be568a4e1a7fc3bef1a601d78b415ef8d88c99d/docs/IDENTITY-RECONCILIATION.md) and [review protocol](https://github.com/CosmonautJones/m-local/blob/2be568a4e1a7fc3bef1a601d78b415ef8d88c99d/docs/RELEASE-REVIEW-PROTOCOL.md).

Supported bounded topology: one exclusive native backend and one gateway serializing every graph RPC through the complete upstream HTTP response. Startup catalog admission is mandatory in the hosted entry. Uncertainty permanently closes the lane until coordinated recovery. No replica, second gateway, parallel operator/CLI writer, native graph bypass or overlapping rollout is supported. The generic stock fixture deliberately disables warm admission only to retain fifty simultaneous cold-catalog requests; actual hosted-entry, browser and package acceptance are separate mandatory proofs. This does not certify hosted capacity or #39's original two-writer acceptance.

Durable graph/identity PostgreSQL, onboarding SQLite, original native JWT/email keys, photo ownership/JPEGs and the canonical resolved main.jac namespace are preserved together. Cloud recovery verifies original merchant/three students, held/historical redeemed claims and immutable snapshots, wrong-account denial, complete logical SQL restoration to a separate empty private database, every SQLite row/schema, original keys/photos, exactly-once restored redemption and a third restart rejecting spent QR. Existing originals remain intact. Writable-directory tests are not provider durability evidence.

After all gates and explicit approval, approved operators adapt protected paths and run:

```bash
python3 deploy/release/package.py inventory --config /etc/m-local/release.json --output /protected-backups/pre-cutover-inventory.json
# Close ingress, stop every writer and prove configured ports bind-free.
bash scripts/release-backup.sh --package /protected-releases/candidate-package --config /etc/m-local/release.json --output /protected-backups/rc-snapshot --acknowledge-quiesced
python3 deploy/release/package.py verify-recovery --backup /protected-backups/rc-snapshot
bash scripts/release-rollback.sh --package /protected-releases/candidate-package --config /etc/m-local/release.json --acknowledge-quiesced --dry-run
bash scripts/release-rollback.sh --package /protected-releases/candidate-package --config /etc/m-local/release.json --acknowledge-quiesced
python3 scripts/release-preflight.py --package /protected-releases/candidate-package --config /etc/m-local/release.json --evidence /etc/m-local/release-evidence.json
bash scripts/release-run.sh --package /protected-releases/candidate-package --config /etc/m-local/release.json --evidence /etc/m-local/release-evidence.json
curl --fail --silent --show-error http://127.0.0.1:10000/healthz
```

Default launch evidence deliberately refuses startup. Before opening traffic verify original actors/ownership/held+spent claims/photos, sample-off alternate paths and public native-route denial. Required secret names without values, security headers/limits, monitoring and operator duties are in the source package.

For source rollback, close traffic, stop the complete group, prove both ports free and review data compatibility; then:

```bash
bash scripts/release-rollback.sh --package /protected-releases/previous-package --config /etc/m-local/release.json --acknowledge-quiesced --dry-run
bash scripts/release-rollback.sh --package /protected-releases/previous-package --config /etc/m-local/release.json --acknowledge-quiesced
python3 scripts/release-preflight.py --package /protected-releases/previous-package --config /etc/m-local/release.json --evidence /etc/m-local/previous-release-evidence.json
bash scripts/release-run.sh --package /protected-releases/previous-package --config /etc/m-local/release.json --evidence /etc/m-local/previous-release-evidence.json
```

Repeat authenticated smoke checks before reopening. Source rollback retains live stores. Live data restoration requires separate explicit approval and must never overwrite them automatically.

## Remaining gates

| Gate | Owner | Required acceptance |
| --- | --- | --- |
| Unchanged40% Jac source criterion | Maintainers/coordinator; Travis decides substantive follow-up scope | Meaningful supported implementation passing the unchanged full inventory/checks; no padding, exclusions or criterion waiver. Final31.26% remains blocked. |
| Exact rollout artifact | Coordinator and approved operator | Retain/provide a policy-approved artifact with complete manifest verification and an authenticated recovery certificate for that actual artifact. Local rebuilt archive has no such certificate; cloud66 is separately bound. |
| Provider topology/storage/migration | Travis approves; named hosting operator executes | Exclusive protected singleton ingress, supported native DB route, canonical path, mounted full-state replacement/restart survival and original actors/ownership on exact artifact; no overlap/bypass. |
| Mail and monitoring | Named primary/backup operators | Approved sender/headroom, consenting inbox delivery, external uptime/redacted error/SMTP/quota alerts and exercised response. |
| Off-host recovery | Backup operator; Travis approves live work | Encrypted scheduled backup/retention/retrieval and authenticated isolated hosted restore with measured RPO/RTO. |
| Devices/security/accessibility/performance | Named independent testers | Hosted TLS/headers/abuse/native denial; actual phone QR/camera/rotation/offline/expiry/install; screen-reader/zoom; representative Lighthouse/LCP. |
| Privacy/eligibility/retention | Travis and original owners | Approved research retention/publication, privacy/terms/deletion/closure and honest eligibility policy. |
| Manual approvals/pilot/clean setup | Approval operator, consenting participants, independent teammate | Real approval/suspension and useful offers/comprehension/return use; independent docs-only setup. Travis approves outreach. |
| Shared-cache incident | Travis and local runtime operator | Compare independently retained history/backups; current aggregate audit cannot prove prior accounts/graphs unchanged. |
| Explicit deferrals | Travis and original owners | Freeze typed-code security policy before implementation; screen redesign after pilot; human disposition of legacy branches. |

All21 child issues34-54 remain open and hosted acceptance boxes remain unchecked. [#33](https://github.com/CosmonautJones/m-local/issues/33), draft PRs and this immutable evidence checkpoint persist across machines. A GitHub Projects kanban can add owners, dependencies, review and verification states; existing credentials lack read:project, so no board or new access grant was created.

## Invocation incident

An earlier mistaken official jacpython direct-filename invocation started default dev listeners and the shared embedded PostgreSQL cache; the runtime reported two scratch/orphan database reclaims. Only the owned incorrect server group was stopped and its listeners closed; the shared daemon was left untouched. No prior baseline identifies the reclaims or establishes unchanged shared identities/graphs. Independent bounded read-only15-database/138-table aggregate evidence contains no row/identity contents and cannot prove historical preservation. No destructive repair/reset or shared-daemon stop was attempted. Corrected fixture invocations use explicit-c/runpy, private bootstrap caches and override refusal. This review miss remains disclosed separately from unchanged human source/WIP.

**Verdict: BLOCKED.** Completed bounded engineering and real verification are delivered. No merge/deployment approval is requested while required engineering and human gates remain open.
