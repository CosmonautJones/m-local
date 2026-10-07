# Release hosting engineering package

**Status: BLOCKED for hosted writes.** This package prepares a reviewable Linux
deployment. It does not certify the proposed topology, change Jac 0.37.23,
deploy to JacHammer, migrate live accounts, or complete hosted acceptance.
The final source SHA, tree, official runtime digests and build digest are in
the generated `manifest.json`; the execution ledger and #33 link the exact CI
and independent review receipts. Do not substitute a historical runtime fork.

## Proposed launch topology and constraints

One Linux host, one application instance, one native Jac backend on loopback,
one restricted gateway, and one explicit trusted HTTPS edge. Every graph RPC,
including readiness/feed probes, passes through the gateway's single lane.
The lane holds its slot until the complete upstream response finishes. A
downstream disconnect does not release it. An uncertain upstream failure or
deadline permanently closes the lane until coordinated operator recovery.

This eliminates some concurrent writers; it does **not** establish that stock
Jac acknowledges only durable commits. Official-runtime commit failure,
unknown outcome, cache, concurrency and restart receipts must pass before
launch. See `RUNTIME-TRANSACTION-RISK.md` and the candidate's topology receipt.
An unsuccessful invariant remains a hosting blocker even if ordinary tests
and CI pass. Never change the evidence template to waive that failure.

Only the gateway may reach the backend over the public request path. Restrict
native `/user/register`, `/user/login`, graph, docs and admin routes at ingress;
internal passwordless provisioning still calls the private native backend.
Restrict database credentials/network access to this instance and backup
operators. No parallel CLI graph writers, operator reviews, replicas, second
gateway, rolling replacement, blue/green overlap, scheduled seed job or
independent readiness RPC may bypass the lane. Stop serving before operating
on the graph. Locking in the launcher prevents other package operations on the
same durable root; it does not stop an unrelated process or another host.

Generic `restricted-edge` and Funnel bind the gateway to loopback. `render`
binds the gateway publicly only after the provider proves that its edge is the
exclusive ingress and the native port is inaccessible. Production `direct`
mode refuses to start. The explicit `MLOCAL_TRUSTED_HTTPS_EDGE=1` setting is an
operator assertion, not a discovery of TLS or network policy. JacHammer's
actual canonical entry path, one-replica policy, gateway/sidecar routing,
private backend, stop-before-start behavior and persistent mounts are still
provider capability gates. Do not run its existing live-deploy command as a
substitute for these checks.

## Persistent inventory and migration

Use a dedicated, real writable Linux volume; a writable folder or overlay
container layer is insufficient. Keep these components together:

| State | Location and preservation requirement |
|---|---|
| Complete native identity and graph | Explicit durable PostgreSQL `JAC_DB_URL`; retain database, roles, extensions and configuration. Never reset it during update. |
| Email, accounts, business owners, approvals, drafts, challenges and quotas | `MLOCAL_ONBOARDING_DIR/onboarding.sqlite3`, outside source on the durable volume. |
| Email code signing | The existing 32-byte `code.key` in that directory; never silently regenerate it. |
| Photo ownership | Matching `photo-ownership.sqlite3` in the same private directory. |
| Native JWT signing | Existing canonical app `.jac/data/jwt_secret`, or the original effective `<JAC_DATA_PATH>/.jac/data/jwt_secret`; preserve the configured base, resulting location and original effective key. |
| Uploaded photos | Existing canonical app `assets/photos/`; restore with ownership and graph associations. |
| Application identity | The **resolved absolute `main.jac` path**, source SHA, runtime, dependencies and layout. |

The example `/srv/m-local/app/main.jac` is for a new host specification, not
permission to relocate an existing source-served application. Official Jac
hashes this resolved path into persisted graph class namespaces. A different
path can keep sign-in working while graph ownership fails. Determine and retain
the deployed canonical path before migration. A symlink is not a migration.
Provision/mount the whole durable layout so canonical native state and photos
are inside the real durable root; do not use data symlinks.
If the current host uses `JAC_DATA_PATH`, preserve that original **base** setting.
Official Jac appends `.jac/data` to it. Record the resulting existing directory
`<JAC_DATA_PATH>/.jac/data` in optional `native_data_dir` and its existing
`jwt_secret` in `native_signing_file`. Do not set `JAC_DATA_PATH` to that resulting
signing directory: Jac would append `.jac/data` again.
The launcher refuses a base with leading/trailing whitespace instead of
validating a trimmed path while sending a different raw path to the runtime.
Keep the same explicit environment setting. The launcher rejects a path mismatch;
it never chooses a new signing store. Any `JAC_SERVE_AUTH_SECRET` or configured
serve-auth secret must match the preserved original effective key, as verified
by the production guard. Secret values remain outside the JSON/package.

Before cutover, capture the protected `inventory` receipt, native actor IDs,
merchant/restaurant bindings, submitted and approved business states, held
and redeemed claims, immutable snapshots and original QR credentials, photo
associations/bytes, both SQLite inventories and key digests. Keep private
identities and tokens out of Git and public logs. Restore into empty isolated
storage and compare these identities again before any traffic. A missing
onboarding row never authorizes deleting an existing native user or graph.
Follow the hardening branch's collision remediation procedure where ownership
requires an operator; do not automate destructive reconciliation.

## Create and verify the offline artifact

Run in **WSL/Linux Bash**, using the pinned repository wrappers for build and
tests. Commit the final reviewed candidate first; dirty sources are refused.
Use a fresh output directory outside source. This command performs no hosting.

```bash
source scripts/runtime.sh
bash scripts/check.sh
bash scripts/build.sh
# Select the actual .jab produced by the pinned build; never guess its path.
find . -name '*.jab' -not -path './.git/*'
```

After the exact build, create the installed-library archive from its tested
workspace (use its native Linux staging path if applicable):

```bash
python3 deploy/release/package.py make-dependencies --source /absolute/tested/workspace \
  --output /var/tmp/m-local-tested-libraries.tar
sha256sum /var/tmp/m-local-tested-libraries.tar
```

This includes only tested Python libraries, npm modules and generated client
metadata. It rejects private state, unsafe links and archive traversal. Generated
compiler caches carrying a source namespace are not copied. Source switching
creates local virtualenv metadata using the exact packaged bundled CPython with
`--without-pip`, then installs the tested libraries without overwriting
`.jac/data`; this operation performs no dependency downloads. Copying a build
workspace's absolute interpreter links is deliberately avoided. Archive generation does not prove that a different source
or platform was tested; its build receipt must bind the same tested candidate.

The coordinator records `build-receipt.json` with `source_sha`, `source_tree`,
`artifact_sha256` and `dependency_archive_sha256` from that exact build. Record the official release-asset
checksums for both `jac` and `jacpython` in `official-checksums.json` using
their official v0.37.23 `.sha256` receipts. A version label alone does not prove
that the executable is unmodified. Package creation verifies both checksums.
The source archive contains tracked files only, refuses tracked private data,
and excludes ignored live stores. The declared dependency files and built
artifact and complete installed-library archive are digested; platform and
installed dependency/runtime provenance remain part of the CI/build receipt.
Launch refuses an incomplete package lacking runtime, libraries or build.

```bash
bash scripts/release-package.sh --output /var/tmp/m-local-rc-package \
  --runtime "$(dirname -- "$JAC_BIN")" \
  --official-checksums /var/tmp/official-checksums.json \
  --artifact /absolute/path/to/the-tested-build.jab \
  --dependency-archive /var/tmp/m-local-tested-libraries.tar \
  --build-receipt /var/tmp/build-receipt.json
python3 deploy/release/package.py verify --package /var/tmp/m-local-rc-package
sha256sum /var/tmp/m-local-rc-package/manifest.json
```

The package retains source for the proven canonical-path serving mode. A
`.jab` is included and bound as build evidence; relocated bundle serving has
not been certified. The manifest records source SHA/tree/file inventory,
official binary digests, artifact digest and dependency declarations. Any
modified/missing/injected package file fails verification. Do not publish the
private recovery set with this public engineering artifact.

The backend starts with official `jac run --no-dev --host 127.0.0.1 --port
BACKEND_PORT` from the recorded canonical app directory. The launcher requires
`[project] entry-point = "main"` before acquiring its lock or starting children.
Do not insert a positional filename before those flags: official 0.37.23 treats
the following options as script arguments, allowing default development startup.
Meaningful native readiness at the configured port and absence of default
development listeners/children must be verified on the actual packaged candidate.

## Configuration and preflight

Copy `deploy/release/config.example.json` into a protected operator directory
and replace paths with the actual recorded canonical layout. Never put secret
values into that JSON. Required external secret/configuration names are:

```text
JAC_DB_URL
MLOCAL_SMTP_HOST MLOCAL_SMTP_PORT MLOCAL_SMTP_FROM
MLOCAL_SMTP_USERNAME MLOCAL_SMTP_PASSWORD
MLOCAL_ONBOARDING_DIR MLOCAL_DURABLE_ROOT
MLOCAL_ENV=production
MLOCAL_PUBLIC_INGRESS=restricted
MLOCAL_DEPLOYMENT_TOPOLOGY=single-instance-serialized
MLOCAL_APP_REPLICAS=1
MLOCAL_SHOW_SAMPLES=false
MLOCAL_DEMO_MODE=false MLOCAL_DEMO_COMPANIES=0
MLOCAL_DEMO_STUDENTS=[] MLOCAL_HOSTED_DATASET=false
MLOCAL_INGRESS=restricted-edge
MLOCAL_TRUSTED_HTTPS_EDGE=1
MLOCAL_INGRESS_EVENT_LOG=stderr
```

Do not enable import-model credentials as a hosting prerequisite; paid model
calls remain a separate approval. Use the real production guard rather than
folder-writability alone. Retain keys and private state before it runs. The
launcher runs the guard before spawning serving children, and the onboarding
import enforces the actual native-process refusal path again.

```bash
python3 scripts/release-preflight.py \
  --package /var/tmp/m-local-rc-package \
  --config /etc/m-local/release.json --evidence /etc/m-local/release-evidence.json
```

The evidence file begins from `deploy/release/evidence.example.json` and must
reference the independently reviewed exact-candidate official-runtime cases,
canonical host/storage/network constraints and Travis's explicit rollout
approval. The default template blocks launch. Preflight reads state and never
contacts a deployment API. Passing local preflight does not prove remote
PostgreSQL durability, off-host backup retrieval, provider policy or actual
TLS/SMTP/device acceptance.

## Backup, isolated restore and acceptance

Supply official, compatible `pg_dump`, `pg_restore` and `psql` clients. The
embedded Jac distribution is not a substitute. Record client/server versions,
required roles/extensions and provider TLS settings separately in protected
operator records. Configure PostgreSQL SSL using `PGSSLMODE`/`PGSSLROOTCERT`.
The tool passes credentials in process environment, never command arguments
or public receipts. PostgreSQL is selected only by explicit URLs.

Close ingress and stop **all** app and CLI/private-store writers. Verify
termination, including other hosts. The package obtains the exclusive local
deployment lock and refuses an active package launcher. Quiescence is required
so graph, approval, signing and media state share one recovery point.

```bash
python3 deploy/release/package.py inventory --config /etc/m-local/release.json \
  --output /protected-backups/pre-cutover-inventory.json
bash scripts/release-backup.sh --package /var/tmp/m-local-rc-package \
  --config /etc/m-local/release.json --output /protected-backups/rc-snapshot \
  --acknowledge-quiesced
python3 deploy/release/package.py verify-recovery --backup /protected-backups/rc-snapshot
```

This creates a private logical PostgreSQL dump, online SQLite backups,
original HMAC/JWT keys, photo ownership and JPEG bytes, plus checksums and
source/runtime/canonical-path binding. An incomplete set has no valid final
receipt. Encrypt it and transfer it off-host using the approved operator
storage mechanism. Record completion, retention owner and retrieval evidence;
neither a local file nor checksum establishes the 15-minute RPO/30-minute RTO.

For an isolated recovery host, restore the original canonical entry path and
matching source/runtime. Provision an **empty separate** PostgreSQL database;
set `MLOCAL_RECOVERY_DB_URL` privately. Restore paths must be empty; existing
private identities, keys, photos and application tables are refused.

```bash
bash scripts/release-restore.sh --package /var/tmp/m-local-rc-package \
  --config /etc/m-local/recovery.json --backup /protected-backups/rc-snapshot \
  --acknowledge-quiesced
# Point the isolated instance's JAC_DB_URL to the restored database afterward.
# Keep public traffic closed throughout authenticated acceptance.
```

Use the authenticated gate in `BACKUP-RECOVERY.md`: same merchant/student
actors and keys, business approval and ownership, held/redeemed IDs and
snapshots, original QR, exactly-once redemption, photo bytes/ownership, other
account isolation, then another restart and readback. Run
`bash scripts/test-recovery.sh` for the existing disposable native rehearsal;
its matching-runtime cold-copy scope remains distinct from logical dump,
fresh-host, off-host, scheduled-backup and public cutover acceptance. Bind the
new candidate receipts separately; preserve the old receipts.

The package tooling's separate native drill uses official Ubuntu PostgreSQL
16.15 clients/server extracted into private disposable Linux storage. It proves
logical dump and empty-database restore of synthetic identity, graph and outbox
tables, both SQLite stores, original keys, photo bytes and source binding; original
components remain preserved. It also proves offline metadata creation using the
official Jac bundled CPython, followed by `ensure_venv` retaining the restored
library. This is procedure evidence, not authenticated Jac application recovery,
runtime transaction safety, remote durability or hosted acceptance. Run it with
`MLOCAL_RELEASE_PG_TOOLS` pointing to the extracted official tools root:

```bash
python3 -m unittest discover -s tests/tooling -p test_release_package.py
```

Independent review also required, and the regressions verify: refusing a live
listener even after the local lock is free; never labeling a backup with an
uninstalled proposed package; redacting malformed PostgreSQL port inputs; and
writing private inventory receipts exclusively without overwriting prior evidence.

## Prepared rollout and source rollback commands

These commands are prepared for an approved operator; **do not execute against
the current public host without Travis's explicit approval and resolved gates**.
Retain the previous complete package before switching source. Use a reserved
clean runtime layout, never a human's active development checkout.

```bash
# 1. Close edge traffic; stop the old supervised service; prove no owned child
#    or backend listener remains; take/verify the coordinated backup above.
# 2. Dry-run and switch source while every writer remains stopped.
bash scripts/release-rollback.sh --package /var/tmp/m-local-rc-package \
  --config /etc/m-local/release.json --acknowledge-quiesced --dry-run
bash scripts/release-rollback.sh --package /var/tmp/m-local-rc-package \
  --config /etc/m-local/release.json --acknowledge-quiesced
# 3. Run local preflight; start privately in the foreground or reviewed systemd unit.
python3 scripts/release-preflight.py --package /var/tmp/m-local-rc-package \
  --config /etc/m-local/release.json --evidence /etc/m-local/release-evidence.json
bash scripts/release-run.sh --package /var/tmp/m-local-rc-package \
  --config /etc/m-local/release.json --evidence /etc/m-local/release-evidence.json
# 4. In a second private terminal, verify meaningful readiness.
curl --fail --silent --show-error http://127.0.0.1:10000/healthz
# 5. Complete authenticated preservation/public-denial smoke checks, then
#    operator opens the approved HTTPS edge and checks the actual public URL.
```

The launcher stops **both owned process groups** when backend/gateway exits,
startup readiness fails, or the operator sends TERM/INT. It never auto-restarts
an uncertain queue outcome. Stop it and prove termination before rollback:

```bash
# Traffic closed and new launcher stopped. Data/schema compatibility reviewed.
bash scripts/release-rollback.sh --package /protected-releases/previous-package \
  --config /etc/m-local/release.json --acknowledge-quiesced --dry-run
bash scripts/release-rollback.sh --package /protected-releases/previous-package \
  --config /etc/m-local/release.json --acknowledge-quiesced
# Use the previous package's matching approved evidence, then repeat preflight,
# private startup, authenticated preservation and edge smoke checks.
```

Source rollback preserves `.jac` signing state, onboarding storage and photos;
it does not undo database/private-state migrations. For an incompatible schema,
keep traffic closed and use a reviewed coordinated recovery set on isolated
storage. Do not discard post-snapshot accepted claims without reconciliation.

## Remaining gates and owners

| Gate | Owner | Required acceptance |
|---|---|---|
| Stock Jac finalization/uncertain outcome/cache safety | Runtime reviewer and coordinator | Exact official binary/native fault receipt; failed invariant blocks hosted writes. |
| Final artifact, component/combined CI and independent review | Coordinator | Exact final SHAs, terminal CI, resolved findings and source bindings. |
| Canonical existing host, network, one-instance replacement and durable mounts | Hosting operator | Actual provider capability/read-only inventory, followed by approved disposable rollout proof. |
| Existing-user migration and complete recovery | Hosting/operator reviewer | Same identities/keys/ownership/claim/media state on restored host, restart, off-host retrieval and measured RPO/RTO. |
| Public TLS, deny paths, request limits, sample invisibility, authenticated isolation | Hosting/security reviewer | Actual intended ingress checks after approved rollout. |
| SMTP/inbox, business approval, physical phone QR/device usability | Travis and designated testers | Controlled real inbox and device receipts; no local test substitutes. |
| Traffic opening/merge/deploy/spending | Travis | Specific explicit approval for the prepared action. |

Monitoring and response ownership are in `OPERATORS.md`. No alert service,
provider, new access grant, DNS change, paid resource or business communication
has been configured by these offline tools.
