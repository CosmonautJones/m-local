# Isolated runtime verification

This branch prepares disposable hosted verification for the M-local release.
It does not adopt a runtime, deploy the application or establish capacity by
itself. The application stays pinned to official Jac 0.37.23.

`inputs/public-source-manifest.json` binds the reviewed proof sources, patches
and 17 modified Jac implementation files. These are the actual files the fresh
fork must byte-match before compile, bootstrap and matrix execution.
`inputs/v7-adapter-manifest.json` binds the four new finite source adapters.
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
