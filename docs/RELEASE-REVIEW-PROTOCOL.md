# Persistent release coordination and review

GitHub issues and PRs are the cross-machine source of truth. Issue #33 links the
foundation, two component PRs, combined candidate, exact-head CI, immutable
receipts and remaining gates. A GitHub Projects kanban view can organize these
same issues when existing account permissions permit it; no separate hosted app,
new access grant or paid service is required for persistent coordination.

Use Backlog, Ready, Owned, Review, Verification, Blocked and Ready for merge.
Ready requires a bounded acceptance test and dependency. Owned records one
coordinator, a branch/base SHA, file boundaries and the current agent. A worker
must inspect staged and unstaged differences before editing. Human-owned WIP and
old approaches remain preserved. Shared integration files have one writer.

Implementation and review are separate. Independent reviewers inspect security
and account preservation, runtime and recovery, and product and accessibility.
Review records the exact diff and evidence scope; council advice grants no merge
authority. A found defect is reproduced, fixed, independently rereviewed, and
retested where affected. Changed source invalidates an older whole-candidate
receipt even when a narrower component proof remains useful.

Verification requires actual CI on every final pushed component and combined
SHA, complete applicable checks, source binding, real native HTTP and browser
proofs, and terminal results. A skipped or absent required check is not success.
A red source-share job keeps the unchanged release criterion open even when
functional jobs pass. Keep unfinished work draft and link failures as well as
passing receipts. Live inbox, host, device, recovery and pilot gates stay open
until their own acceptance is recorded.

The coordinator integrates PR55's manual approval and coordinated recovery
foundation, the hardening component, and the selectively ported experience.
Component PRs target `codex/release-readiness`. The combined candidate is the
release acceptance unit. Travis explicitly approves merging, deployment, live
account/data changes, outreach and spending after a concrete package is ready.
Do not auto-merge from a council vote, local tests or a kanban state.
