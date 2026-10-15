# Exact recovery-package binding increment, October 15, 2026

## Scope and acceptance

Base: `b92b92c8387a12e2c55edbb7638c54dfbed78dc2`, freshly fetched and
confirmed against GitHub main. Branch: `codex/recovery-package-binding-2026-10-15`.
The commit containing this receipt binds the final diff; this receipt does not
certify a built rollout artifact. Official Jac stays pinned at **0.37.23**.

`BACKUP-RECOVERY.md` requires matching source, generated artifacts, dependencies,
canonical entry and complete preserved state. `RELEASE-GATES.md` requires exact
source-bound receipts. Inspection found that `coordinated_backup` recorded
`source_tree` and `package_manifest_sha256`, while `coordinated_restore` ignored
both. A separately valid package from the same source/runtime could substitute
its build or libraries during recovery.

Acceptance for this increment:

1. Reject absent or mismatched tree/package bindings before database selection,
   probing, PostgreSQL restore or private-state restore.
2. Reject different verified artifact/dependency packages even with the same
   source SHA and runtime metadata.
3. Retain the exact original package's restore path and occupied-database gate.
4. Keep complete state handling, launch evidence, approval and runtime unchanged.
5. Obtain independent diff review and publish only a draft engineering PR.

The implementation adds two comparisons to the existing restore guard. It does
not create a new packaging or orchestration system. Existing recovery commands
continue to use the retained original package. An older unbound backup requires
operator-reviewed recovery; its missing evidence must not be manufactured.

## Focused evidence

Executed with Ubuntu system Python 3.14.4, not Jac. Tests use disposable Git
repositories/packages; PostgreSQL commands and recovery receipts are mocked in
the new admission tests. Existing private-state tests exercise real disposable
SQLite backups, keys and photos. No new native Jac or database server was started.

Command (with `MLOCAL_RELEASE_PG_TOOLS` unset):

```bash
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/home/travis/m-local-recovery-bind-1015 \
  python3 -m unittest discover -s tests/tooling -p test_release_package.py -v
```

| Receipt | Actual result | SHA-256 |
| --- | --- | --- |
| Original NTFS-temp baseline | 45 discovered; one file-mode assertion failed, one native drill skipped | `150dc52ea89870b5f2a11f26036930207f62e8a551cd82b7681ecf06184af088` |
| Unchanged Linux-temp baseline | 45 discovered; 44 passed, one native drill skipped; 10.552 seconds | `ec9f1a59c41947afba182c80758637ca4d3461a39b1c876e67574aadba120a90` |
| Failing first, `-k test_restore_` | Four methods; six intended subcase failures, all `ValueError not raised` | `0e976c2c2add9947c8c2c68bebb7f891bfa5aa3f754f1fe15b48dac7cc3dedf4` |
| Final focused suite | 48 discovered; 47 passed, one native drill skipped; 29.469 seconds | `e4af6eceeabe9dd6389abe75ec4477f9cc3b531194f3b29e3a1455a351ac105f` |

`git diff --check` passed. Raw logs and source-file hashes remain at
`X:/Projects/M-Local/increment-20261015/`. The worktree is
`X:/Projects/M-Local/worktrees/recovery-bind-1015`. Linux temporary fixtures use
Ubuntu's POSIX filesystem, whose registered disk location is `X:/WSL/Ubuntu`.
No mount or filesystem-policy change was made to accommodate the first failure.

Independent reviewer `/root/independent_recovery_review` inspected the diff,
retained failures and green receipt and found no actionable correctness or
gate-weakening issue. The reviewer independently replayed four relevant tests:
**4 passed in 0.191 seconds**. Reviewed source-file SHA-256 values:

- `deploy/release/package.py`: `c3efbfa42700b9e6041a0bce2a4d40ce22bf04f6b028139abdb888dd4d91acfd`
- `tests/tooling/test_release_package.py`: `ed2c9d72928e187fb7e6b148e0a89833dfc45e280403aaed5cec2b0182c8bd89`
- `docs/BACKUP-RECOVERY.md`: `7a055924a351d0014e2a4506104812cfc2fecaa9b47a184bb1fc2c1518b1952f`

The reviewer accepted draft-PR scope only. Synthetic package differences prove
manifest substitution is refused; they do not certify reproducible builds or
native application recovery.

## Preserved ownership and prior work

Inspected all four pre-existing registered worktrees; each was clean and remains
preserved: canonical detached `bed4be3d43ec12b949bc2d7799ff14883be3639f`,
release-finish `43be02491e27f04c532137aafff08d400e75723e`, header
`d192dd400df956989f546b8522d97263e5e7662a`, and main integration
`c0a2c5f14dfcdca425fa70569b474f50ebf2b35b`. Human product files were not edited.
Current open PRs #56, #57 and #58 remain drafts; this increment starts at main.

Inspected the existing **Grade patch update** review of the separate Argon
attachments. It reports that they were rejected and not applied because of a
missing `services.mutation_coord` import target and unsafe archive extraction
fallback. Those attachments were reviewed in a separate scratch environment;
they are not a local worktree patch here. No Argon code was applied, repaired,
recreated or silently treated as part of main. Research exclusions, operator
credentials and sender changes remain outside this increment.

## Remaining prerequisites and human decisions

This closes one restore-admission defect. It does not complete hosted acceptance.

- Full exact-head project CI and native authenticated package recovery are still
  required. The explicit native logical-drill skip is not a pass. TravOS owns
  the local heavy-test slot; no full-suite/native rehearsal was started here.
- Build and retain a private exact manifest-bound rollout archive using existing
  `build-release-package.sh`, then run the existing authenticated recovery/restart
  procedure against that exact artifact when the heavy-test slot is available.
  Main's six successful workflows at `b92b92c` certify that base only.
- Offline preflight still checks less than launch: complete build/dependency
  payload, installed-source marker, effective native signing base, ingress mode
  and declared entry are additionally checked by launch. A preflight PASS alone
  must not be described as complete host admission. That separate gap is reported
  here; launch gates were not weakened or refactored.
- Hosting operator must choose and prove durable full-state mounts, protected
  native PostgreSQL route, canonical entry and original keys, exclusive HTTPS
  ingress and one backend/one serialized gateway with stop-before-start rollout.
  Reported JacHammer ephemeral files and overlapping backends do not meet these
  requirements. A remote database TLS requirement is not met by libpq variables
  because official Jac 0.37.23's native driver uses a plain wire connection.
- Preserve complete graph/identity, both SQLite stores including suspension
  status/audit, signing keys and photos. An older provider PostgreSQL dump alone
  does not prove complete recovery or a matching deployed source revision.
- Named operators must demonstrate encrypted off-host retrieval, authenticated
  restoration/restart and measured RPO/RTO, plus monitoring/incident ownership.
- Travis retains decisions on research-contact retention/publication (#41),
  privacy/terms/deletion and student eligibility (#42). Inbox ownership is not
  current-enrollment verification. No research files were removed.
- Consenting real inbox/sender/headroom checks, physical iPhone/Android QR and
  install/performance checks, independent teammate setup, merchant review and
  consenting merchant/student pilot remain human/live acceptance.

No merge, deployment, spending, email, live-data operation, credential creation
or access change was performed. Next action is exact-head CI plus the existing
retained-artifact recovery procedure after the heavy-test slot is released;
provider and human decisions remain independent prerequisites.
