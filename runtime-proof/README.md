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

`verify-source-handoff-v9.py` checks the exact public source files, sanitized
receipt commitments and required license sidecar against a trusted checkout.
It requires external commit, run and contract-hash bindings and never executes
bundle contents. Synthetic producer/export tests run before native proof.
The producer binds its code to the exact GitHub commit and run, includes the
license sidecar and bootstrap cold hash, and verifies both the private bundle
and the exported copy. CI uploads only that verified directory after success,
retains it for seven days and exposes the contract hash and artifact identity
for a later package gate. Logs, caches and application state stay private.
Actual hosted source/producer/upload acceptance is still pending; synthetic
tests do not establish native proof, package compatibility or adoption.
Failure context retains at most eight known operation labels across chained
errors, including cleanup failures. It omits arbitrary messages and child logs.
Failure diagnostics retain the operation underway, the last scoped command,
whether the source body completed, its error family and finite cleanup actions.
These fields use fixed label lists and never establish acceptance when cleanup
fails; the last command identifies progress and does not imply that it failed.
