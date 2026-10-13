# Release test inventory and historical discovery counts

The saved baseline log has 410 executions and 110 reported names. The earlier
experience log has 380 executions and 111 names. Every baseline name appears in
the experience log. There are 32 fewer repeated executions and two added
executions: the net change is 30. No evidence supports a claim that 31 tests
silently disappeared.

The earlier business-profile change removed an unnecessary production import of
`foryou`; its transitively discovered tests accounted for 14 foryou, 14 taste and
four sandbox repetitions. One new test definition was executed twice. Production
import decoupling is appropriate; adding duplicate discoveries would not restore
coverage. Definitions, retained assertions, fixtures and individual outcomes are
the meaningful comparison.

The refreshed PR55 foundation declares 124 expected core cases; the integrated
experience declares 134. Ten new cases cover sample visibility/favorites,
claim admission and existing-claim preservation. One former test title,
`anonymous direct calls are rejected before catalog access`, is deliberately
replaced by `anonymous business lookup exposes the sanitized public projection
only`: authorized guest browsing now succeeds, while five assertions verify
public-only fields, no ownership/merchant key, no private claim/QR, and safe
invalid lookup. Restoring blanket guest rejection would contradict the intended
feature. This is an explicit policy replacement, not an undisclosed lost case.

Three retained bodies changed: sample-parent/child hiding tightens its assertions
from ten to eleven; the hosted catalog uses an isolated real-loader input while
retaining three assertions; the saved-claim filter fixture uses local noon and
retains all eight expiry/ownership assertions. Body hashes, lexical assertion
locations, exact foundation/candidate SHAs and individual outcomes are retained
in the coordinator's comparison receipt and CI inventory. Fresh integrated core
execution is 493 passed/134 distinct expected cases; repeated imports remain
recorded separately. These counts are not branch-coverage percentages.

The current core runner records verbose named outcomes plus an isolated input
manifest before and after execution, exact candidate SHA, runner digest, runtime
identity, exit status and log digest. `scripts/test-inventory.py` compares the
declared core definitions to those actual outcomes and refuses missing, failed,
unmapped, ambiguous or differently bound results. Jac reports quoted titles in
direct runs and sanitized identifier aliases for imported tests; both map to one
logical definition. The report retains reported labels and repeated execution
counts separately. Lexical assertion tokens are an inventory, not semantic
assertion or branch coverage. The optional paid business-AI suite is excluded
from core expectations and is not silently counted as passed.

```bash
bash scripts/test.sh core
python3 scripts/test-inventory.py \
  --core-log .jac/release-core-outcomes.log \
  --binding .jac/release-core-binding.json \
  --output .jac/release-test-inventory.json
```

The exact final expected inventory and outcomes are retained by the checks
workflow artifact and the candidate evidence ledger. Final counts follow the
tested definitions, rather than a historical execution target.

Main's successful 114/114 compiled-browser CI and the old local 113/114 late-night
observation are separate evidence. There is no retained stack proving the cause
of that old failure. A current backend expiry fixture crossed Ann Arbor midnight;
its deterministic noon fixture preserves the expiry assertions. Current compiled
and native browser failures must still be reproduced and fixed. They are never
waived by an old flake note.
