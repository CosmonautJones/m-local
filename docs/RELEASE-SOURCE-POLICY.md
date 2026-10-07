# Informational source-composition policy

Travis retired the Jac percentage requirement for the M-Local release candidate
on October 7, 2026. Source composition is evidence, not a release percentage target.
Use the suitable language for each task; do not convert working code, pad Jac or
exclude safety tooling and tests to manipulate the report.

`scripts/check-jac-share.py` reports tracked Git blob bytes at the selected
revision. It keeps the existing extension mapping and `.d.ts` exclusion, includes
tests and operational scripts, and emits the language totals, total source bytes,
Jac percentage and `policy: "informational"`. Inventory/Git errors still exit
unsuccessfully. Both workflow callers retain the report without a minimum share.

Correctness, authorization and account preservation, official Jac **0.37.23**,
runtime/concurrency safety, complete applicable tests, independent review,
recovery and hosted/human acceptance remain required. This decision does not
change the application runtime or historical hackathon eligibility decisions.

Historical below-threshold CI runs and immutable receipts remain unchanged.
Updated source requires completed checks at its new exact head; an old functional
pass does not certify a new commit, and missing/skipped required proof is not green.
Issue #33 and the PRs bind the current heads and remaining gates.
