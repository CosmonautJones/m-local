# Cumulative engineering integration map

Refreshed October 16, 2026, 07:51 UTC. GitHub main is
`b92b92c8387a12e2c55edbb7638c54dfbed78dc2`; all PR60–66 remain open drafts.
This is engineering dependency/evidence ordering, not merge or hosted acceptance.
Current contracts in RELEASE-ACCEPTANCE, RELEASE-GATES, TEAM-CONTRACT and the
hosting/runtime/recovery documents govern. Historical issue checkpoints retain
their original dated scope; their old refs and percentage statements are not
current branch truth.

| Work | Dependency | Frozen head |
| --- | --- | --- |
| [PR60 exact recovery binding](https://github.com/CosmonautJones/m-local/pull/60) | main b92 | `a3b5b1ef2a59d685d006ccf5462fa2cd74c25377` |
| [PR61 offline preflight parity](https://github.com/CosmonautJones/m-local/pull/61) | main b92 | `298b2ed73488050820340a407e2c13b71eff8ced` |
| combined recovery/preflight | PR60 then PR61 cherry-picks | `7a0fd42203a86ad2652e8919c121854acfefa508` |
| [PR62 private research/eligibility](https://github.com/CosmonautJones/m-local/pull/62) | combined7a0 | `936fe26f77154988e19f5ded0e6a1f8b4768a836` |
| [PR63 auxiliary SQL preservation](https://github.com/CosmonautJones/m-local/pull/63) | PR62 | `be8014819293da34316490feb97eae9471ea6989` |
| [PR64 authority parity](https://github.com/CosmonautJones/m-local/pull/64) | PR63 | `454db70d01e84a4cfad73ac177067d1187cb3dd6` |
| [PR65 SQL photo references](https://github.com/CosmonautJones/m-local/pull/65) | PR64 | `d5bf6548e3d6142179607ff546b7df01db512108` |
| [PR66 native-key compatibility](https://github.com/CosmonautJones/m-local/pull/66) | PR65 | `746f5444b46d7cb0554b2da29cf8f8a52ff71fef` |
| strict auxiliary DDL admission, this branch | frozen PR66 | final exact head is recorded in its PR and fresh CI receipts |

Actual cumulative ancestry is b92 →
`84e300f1d88e1ce603df79eb1f5788e54a5308f3` → 7a0 → 936 → be8 → 454 → d5 → 746.
84e300 is the included PR60 cherry-pick with its identical tree; 7a0 includes PR61
with only cherry-pick metadata differences. Original a3/298 are not ancestors of
746. Do not apply PR60/61 again to this cumulative line. Main already includes
PR59/release-finish and the earlier combined integration history; open older PRs
are not an instruction to duplicate their commits.

746 is the reviewed cumulative baseline, including PR60–66 work once. The current
`codex/auxiliary-schema-admission-2026-10-16` branch inherits it and is the next
cumulative candidate. Its final source must receive fresh exact-head checks,
shared-onboarding, native, browser and package qualification. Earlier receipts
qualify only their own source/store/artifact; a new branch or green SQL step is
not a final combined release certificate. Keep every frozen dependency unchanged.

## Next integrated functional gate

After strict DDL admission, prioritize one disposable **actual application startup
and photo HTTP** candidate. Reuse the existing guarded launcher and native/browser
fixtures, with official Jac0.37.23, one owned PG18 database, fixed canonical entry,
one backend and serialized ingress. Online catalog/key admission belongs after
singleton ownership and before native spawn. Offline preflight remains static;
a guard subprocess cannot export signing settings into a later launcher process.

Select the preserved original SQL key before auth/store initialization; verify
original tokens, profiles and roots over real HTTP without replacement issuance.
Make an explicit delivery decision: fresh startup cache using existing
`materialize_photos`, or SQL read-through. A returned ownership URL is not bytes.
The official static route requires files inside its configured assets root;
an external photos-only symlink does not meet that boundary. Verify actual JPEG
GET/HEAD through native HTTP and gateway, then stop all owned processes/sessions,
remove only disposable delivery cache, and repeat after restart. Damaged schema,
key/audit, corrupt initial photos and outage must refuse before serving/fallback.

Live upload, cache invalidation and SQL-write/cache-failure semantics need explicit
acceptance in that same functional integration. Include the optional SQL driver
in its actual functional/offline dependency contract; the isolated test driver is
not packaged application availability. Do not bypass the current native/production
or media guards just to make the fixture run.

Native writer fencing, uncertain native commits, privileged concurrent DDL,
operator mutation locks, stopped-writer migration and coordinated changed-store
recovery remain unresolved. An auxiliary row lock does not make graph/auxiliary
transactions atomic or permit overlapping replacements. Issues34/37/39/40/45
retain live storage/routing/recovery gates. Research handling41 remains separate
from public privacy/deletion42. Human inbox, physical-phone, consenting-pilot and
hosting acceptance remains open. No merge, live migration, deployment or spending
is authorized by this map.
