# Isolated runtime verification

This branch prepares disposable hosted verification for the M-local release.
It does not adopt a runtime, deploy the application or establish capacity by
itself. The application stays pinned to official Jac 0.37.23.

`inputs/public-source-manifest.json` binds the reviewed proof sources, patches
and 17 modified Jac implementation files. These are the actual files the fresh
fork must byte-match before compile, bootstrap and matrix execution.
`inputs/v9-adapter-manifest.json` binds the current adapters and their frozen
v8 predecessors. The v9 matrix persists the source-only email scope already
declared on stdout, so the strict receipt verifier can accept the saved result.
The thin v9 adapters and verifier hash-check their v8 predecessors before
applying exactly counted substitutions. All prior validation remains active.
The v8 matrix binds the frozen loader to the fresh fork after checking its
original hash; every implementation and module containment assertion remains.
The original v3 sources, v7/v8 adapters, manifests and v8 verifier remain unchanged.
No historical caches, accounts, graph state, private photos or logs are inputs.
The input directory preserves its original bytes in Git, including line endings
and patch context whitespace; its manifests verify the staged blobs before push.

The Jac implementation sources derive from public
[`jaseci-labs/jac` at 58cb97e](https://github.com/jaseci-labs/jac/tree/58cb97eb75cdff8b5ee78f4094ca2be16376601c),
with the recorded runtime patch applied. The original copyright and MIT
permission notice is preserved in [JAC-LICENSE.txt](JAC-LICENSE.txt).

`public-download-pins.json` declares exact public runtime and embedded
PostgreSQL download bytes and hashes before execution. The downloader uses
private fresh output paths and validates every redirect and content identity.
Official cache, Python/dependencies and native shim/typeshed inputs must be
materialized freshly on the runner and retained there.

The source runner must preserve the cold compiler rejection/correction proof,
53-check bootstrap gate and 10+2 matrix. Package assembly, strict compatibility,
native HTTP, sustained capacity and independent acceptance are later gates.
Only a privacy-reviewed fresh proof handoff may cross to a later package job.

`runtime-direct-use-inputs-v1.json` declares the complete 17-file runtime patch
scope before assembly: 348,363 Jac bytes, with an explicit denominator and
exclusions. Package input CI checks this predeclared runtime scope, replacing
its inherited whole-Git language check, and exercises the offline boundaries.
The application's whole-Git language gate remains unchanged. The operational
proof branch's complete Git language share is not a runtime acceptance claim.
The declaration does not claim that assembly ran.
The package preflight binds this declaration as its thirteenth consumer input.
`check-runtime-direct-use.py --expected-commit <reviewed-commit>` also checks
all declared source files against their actual committed bytes.
Fresh-fork checks require the exact base, unstaged patch and changed-file set.
Unexpected untracked or ignored inputs are rejected; official shim and typeshed
additions require their original hashes and exact typeshed inventory.
Assembly inventory bindings require the hash from the executed v7 recipe's
result. They remain insufficient without the frozen independent verifier and
fresh loader/catalog evidence. `run-fresh-package.py` now connects the checks
to a fresh fork, the frozen recipe and its independent verifier. It is prepared
and has not established native package acceptance.

The package parent requires a fresh root-provisioned Ubuntu 24.04 host with
systemd, cgroup v2, at least four available CPUs and 16 GiB of raw MemTotal.
It preserves the fresh 64 GiB storage proof and the recipe's 7/8 GiB memory,
zero-swap and 4,200-second assembly limits. It authenticates the successful
source job, then excludes repository credentials from worker environments.
The bundled Python interpreter and official extracted cache are verified
before patched compiler imports. After assembly, three classifier controls
run on a disposable copy; the original stage stays unchanged. The immutable
independent verifier then checks the packed bytes, inventories and catalog.
The parent binds those actual outputs before reporting direct use observed.
Its offline tests establish rejection behavior, not a native build or capacity.

`verify-source-handoff-v9.py` checks the exact public source files, sanitized
receipt commitments and required license sidecar against a trusted checkout.
It requires external commit, run and contract-hash bindings and never executes
bundle contents. Synthetic producer/export tests run before native proof.
The producer binds its code to the exact GitHub commit and run, includes the
license sidecar and bootstrap cold hash, and verifies both the private bundle
and the exported copy. CI uploads only that verified directory after success,
retains it for seven days and exposes the contract hash and artifact identity
for a later package gate. Logs, caches and application state stay private.
Earlier source run [37477834755](https://github.com/CosmonautJones/m-local/actions/runs/37477834755)
completed successfully at commit `990c7b33c920e6a93431d34a01df7b8c87c432ba`.
Its authenticated archive and 38 physical files passed independent verification,
including the 36-member contract and all 34 public source bindings. This proves
that source handoff, not package compatibility, capacity or runtime adoption.
Current package defaults use source run
[37532312763](https://github.com/CosmonautJones/m-local/actions/runs/37532312763)
at commit `82d2789dcbbfea32d3362ee4008104b7e52b193a`, as recorded in
[fresh package execution plan](FRESH-PACKAGE.md). Keep each source run paired with
its exact commit; the earlier run does not substitute for these current inputs.
Failure context retains at most eight known operation labels across chained
errors, including cleanup failures. It omits arbitrary messages and child logs.
Failure diagnostics retain the operation underway, the last scoped command,
whether the source body completed, its error family and finite cleanup actions.
These fields use fixed label lists and never establish acceptance when cleanup
fails; the last command identifies progress and does not imply that it failed.
