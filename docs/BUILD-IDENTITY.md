# Build identity

The release gateway serves a readable build page at `/build` and a read-only
JSON response at `/version.json`. GET and HEAD are supported. Every gateway
response also carries `X-MLocal-Build`, containing the full build ID or `unknown`.
These responses use `Cache-Control: no-store` and the existing security headers.
The build routes perform no backend RPC and do not change `/healthz` readiness.

The supported release launcher verifies the sealed package inventory, embedded
artifact receipt and installed canonical source using the existing release gates.
Before starting either child, it replaces any inherited `MLOCAL_BUILD_IDENTITY`
with one public allowlisted snapshot. The hosted gateway normalizes and freezes
that snapshot for its process lifetime. Changing the package requires a new
approved launch; changing request headers, cookies or query strings cannot change
this response.

## Compare a retained package with a running gateway

After an independently approved rollout through the release launcher:

1. Retain the exact admitted package and its existing acceptance evidence.
2. Calculate SHA256 of the package's inner `manifest.json`, for example
   `sha256sum /path/to/retained-package/manifest.json` on the operator's Linux host.
3. Read `https://<approved-host>/version.json` or open `/build` on that same host.
4. Require `status: "known"`, compare the full `build_id` to that digest, and
   compare `source_sha`, `source_tree`, `artifact_sha256` and
   `dependency_archive_sha256` with that retained package's manifest. A missing
   dependency archive is represented by JSON null.
5. Assess readiness and rollout acceptance separately. An unknown or mismatching
   identity cannot establish which admitted package that host launched.

The build ID is the exact **inner manifest digest**, not the outer tar digest or
the candidate implementation commit. This avoids a circular artifact digest. Two
separately packaged manifests can have different build IDs even for the same source
revision. Retain the package rather than reconstructing its ID from a checkout.

The JSON schema has exactly these fields:

```json
{"schema":1,"status":"unknown","build_id":null,"source_sha":null,"source_tree":null,"artifact_sha256":null,"dependency_archive_sha256":null,"serving_mode":null,"verification":null}
```

For a verified artifact package, status is `known`, the hashes are lowercase hex,
`serving_mode` is `source-at-fixed-canonical-entry`, and `verification` is
`launch-snapshot`. The dependency archive hash may be null for a package without
that archive; the production launcher still requires the complete existing
runtime, build and dependency package before admitting a launch.

## Meaning and limits

This is package provenance checked at startup under the trusted release launcher.
The gateway accepts a schema-valid snapshot from its host environment; that input
is trusted operator configuration, not a signature or independent attestation.
Manually setting an environment SHA or snapshot does not establish provenance.

The current launcher runs canonical source with the pinned Jac 0.37.23 runtime.
The artifact digest identifies the **packaged JAB**. A consistent build receipt
does not prove test qualification or that those JAB bytes are served to clients.
The snapshot does not continuously inspect files and does not certify current
readiness, live database state, every browser asset or freedom from host changes.

Missing metadata in raw/development gateway startup yields `unknown` with null
hashes. There is no runtime Git, `GITHUB_SHA`, branch, bundle-name or URL fallback.
Dirty installed source remains a launch refusal through the existing inventory
gate. Invalid supplied snapshot metadata refuses gateway creation with a fixed
redacted diagnostic. Package labels inconsistent with the sealed files or receipt
also refuse verification. A source-only package can be inspected as unknown; it
cannot satisfy the existing complete-package launch gate.

Only the fixed public fields above are exposed. No canonical paths, complete
manifest, environment, runtime stack version, branch name, credentials, graph or
identity contents, SQLite/suspension audit contents, signing keys, photos or private
store digests are included.

This feature does not deploy itself or identify an existing host retroactively.
Public checks on 2026-10-18 found no revision metadata on the JacHammer landing
response. Its live source SHA remains unverified. Deployment topology, privacy,
inbox, real-phone pilot checks and hosting approval retain their existing gates;
see [the work handoff](WORK-HANDOFF.md) and [the team contract](TEAM-CONTRACT.md).
