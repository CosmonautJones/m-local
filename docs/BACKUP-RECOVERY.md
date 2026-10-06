# Backup and recovery

The public release recovery gate is still open. A local, quiesced disposable
fixture passed 20 HTTP/state checks on October 4, 2026. Its backup took 0.095
seconds and its recovery took 57.936 seconds. These timings exclude remote
storage, scheduled-backup lag, host provisioning, DNS/TLS and traffic cutover.
They do not establish the proposed 15-minute RPO or 30-minute RTO.

## Preserve the application identity

**Jac 0.37.23 source serving depends on the canonical absolute entry path.**
The runtime's `application_namespace()` in `runtime/prepared.jac` hashes the
entry path into `_jac_app_<hash>`. Persisted graph classes carry that module
name. In the rehearsal, restoring into a different folder preserved JWT sign-in
and the same actor but failed to deserialize restaurants, offers and other graph
classes. The owner became a `business` instead of a `merchant`.

Recovery at the original canonical path passed. Preserve the resolved entry
path, source revision, runtime and deployment layout when recovering a
source-served application on another host. A symlink to a different resolved
path is insufficient. Restore at an alternate path is unsupported until a
separate migration or runtime correction is reviewed and proven. A sealed
bundle's relocation behavior has not been established by this rehearsal.

An anonymous health response or successful sign-in cannot certify recovery.
Keep ingress closed until the authenticated graph checks below pass.

## Backup inventory

Retain one coordinated recovery set:

| Component | Required contents |
|---|---|
| PostgreSQL | Complete application database, including anchors, graph types, native identities, lookup tables, state and outbox tables; required roles/extensions/configuration recorded separately |
| Private onboarding directory | Online SQLite backup of `onboarding.sqlite3`, plus `code.key`; accounts, owners, drafts, submitted reviews, approvals, OTP state and quotas are in this database |
| Photos | All uploaded JPEGs under `assets/photos/`, coordinated with an online backup of private `photo-ownership.sqlite3` in `MLOCAL_ONBOARDING_DIR`; restore both together and verify owner access |
| Native signing state | `.jac/data/jwt_secret` and the configured signing-secret location if it differs |
| Release | Source revision and tree digest, runtime version and distribution digest, dependency/configuration files, generated artifact digest and canonical entry path |
| Deployment | Database selection, persistent volume locations, ingress rules, process/replica configuration and secret references; secret values stay in protected recovery storage |

Do not copy an open SQLite database file as the backup: use its online backup
API or a coordinated checkpoint while writers are stopped. Quiesce all app
writers during this procedure so PostgreSQL and private state represent the
same recovery point. Include every process using the shared onboarding
directory; stopping only one replica does not quiesce the system.

Store encrypted backups away from the application host with restricted access.
Record the snapshot time, completion time, checksums and retention/deletion
owner. Exercise the scheduled job and retrieval procedure; a local dump proves
neither remote durability nor a current recovery point.

The phone source-sync helper now treats `assets/photos/` as persistent
application data: source updates replace other application assets but never
copy or delete the photo directory. A disposable actual read-only POSIX bind
mount retained uploaded bytes through source update and rollback. That proof
used a private-registry sentinel; coordinated recovery of the real ownership
database, photos and graph data remains open. Keep the photo directory on a
durable volume and restore it with the matching ownership database. Uploads
are ignored by Git. Same-store restart does not prove deployment or recovery.

## Recovery procedure

1. Close ingress and stop writers. Preserve the failed deployment and logs for
   investigation. Select a complete recovery set and verify checksums.
2. Provision an isolated recovery host with the recorded runtime and canonical
   resolved source entry path. Restore the matching source and generated
   artifacts. Check dependencies, roles/extensions and private file permissions.
3. Restore the complete PostgreSQL database with matching supported client
   tools. The embedded runtime does not necessarily include `pg_dump` or
   `pg_restore`; prepare official PostgreSQL clients beforehand.
4. Restore the private SQLite backup, HMAC key and native signing key. Point
   `MLOCAL_ONBOARDING_DIR` to the restored durable directory and `JAC_DB_URL`
   to the restored database. Confirm the selected database before startup.
5. Start on loopback behind closed ingress. Run the authenticated acceptance
   gate below, inspect deserialization/quarantine errors, and verify readiness.
   Any failed check leaves traffic closed.
6. Measure recovered snapshot age and elapsed recovery time, including backup
   retrieval and host/traffic preparation. Record the revision, digests,
   canonical path, schema/runtime versions, topology and actual results.
7. Open traffic only after operator acceptance. Recheck the public ingress and
   device flows. Monitor errors and retained state after restart.

Source rollback does not undo database or private-state changes. For an
incompatible migration, restore a coordinated recovery set rather than mixing
an older source with newer state. Reconcile later accepted claims before
discarding post-snapshot data.

## Authenticated acceptance gate

Use protected synthetic acceptance accounts in an isolated recovered deployment.
Do not expose their tokens, QR payloads, email codes or keys in the receipt.

- A known owner authenticates as the same actor with the `merchant` role.
- The reviewed business profile and merchant portal contain the expected
  identity and offer inventory. Private approval and owner bindings agree.
- A student sees the expected held claim and its original QR credential.
- Promised price, terms, eligibility and expiry match the backup snapshot even
  when the current offer has since changed.
- A redeemed claim stays redeemed and refuses another redemption.
- A held fixture claim can be redeemed once through the recovered API.
- Restart the recovered process and verify these states again.
- Repeat isolation/authorization checks at the actual ingress before opening
  it. SMTP delivery, quotas and physical camera checks are separate gates.

The local rehearsal verified held/redeemed state, old price/terms, current
offer price, approval, owner authority, signing keys and one-time redemption.
It did not verify a fresh host, scheduled backup, actual SMTP, cutover or a
post-restore restart. Retained private rehearsal data is not committed or
included in shared evidence.

See [release acceptance](RELEASE-ACCEPTANCE.md) and
[hosting](HOSTING.md) for the remaining deployment gates.
