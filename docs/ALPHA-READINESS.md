# Real alpha acceptance

The November 15 preview supports supervised testing. It is not yet accepted for
real customer offers. The current task adds source identification, a repeatable
public acceptance check and gateway compatibility for the November operations.
Changes in this branch are not evidence that the hosted preview has changed.

## Use one release check

After staging/deploying a clean reviewed commit, check its actual public origin:

```bash
python3 scripts/check-hosted-alpha.py --url https://YOUR-ALPHA-HOST \
  --expected-revision FULL_COMMIT_SHA
```

For an explicitly named preview only, add `--allow-samples`. This permits sample
offers; it does not waive route denial, headers, identity or healthy responses.
The check makes anonymous read requests and empty native-auth requests to verify
denial. It does not register accounts, request sign-in codes or redeem claims.

`scripts/jachammer-stage.py` now writes `assets/mlocal-build.json`, served at
`/static/assets/mlocal-build.json`, with the
committed source revision, pinned runtime and project version. This is a public
source stamp, not a cryptographic certificate of every installed runtime file.
It contains no host settings or credentials. The existing sealed package
`/version.json` identity contract is separate and unchanged.

## Preview testers without a U-M inbox

Use an inbox the tester controls. On the preview, verify it through the existing
business email-code form, without submitting a business profile. An operator
then adds that authenticated account's ID to the existing `MLOCAL_DEMO_STUDENTS`
list, preserving other test IDs, and applies the reviewed preview configuration.
After refresh, the explicitly listed nonmerchant account acts as a demo student;
ordinary verified business accounts and existing merchant ownership are unchanged.
Use a separate account for the merchant side of the two-phone test.

This tests real email delivery and the student experience with a controlled test
identity. It does not prove delivery to `@umich.edu` or change real-user eligibility.
Keep the override on the preview and remove it before real alpha acceptance;
production startup refuses configured demo-student overrides.

## What still needs hosted acceptance

1. Route all public requests through the restricted gateway; prove no alternate
   origin exposes native auth, graph or admin routes. The stock preview currently
   throttles native registration but does not fully disable it. Deployment on
   JacHammer needs a verified gateway/launch contract; setting environment labels
   alone does not install those protections.
2. Run the public check with the exact deployed commit. Verify onboarding and
   the merchant review link through that same origin. The restricted gateway now
   permits the current compiled client, source stamp, signed review-link RPCs and
   token-protected backup RPC. Backend token checks remain authoritative.
3. Remove QA account overrides and disable samples for real use. Preserve all
   existing identities, signing keys, private stores and photos before cutover.
   Never treat an empty new preview database as a migration of the existing one.
4. Have a consenting U-M inbox and business inbox complete ordinary email-code
   signup/login. Approve a new test business, publish a clearly labeled test
   offer and find it through normal student browsing. Built-in demo restaurants
   are intentionally excluded from hosted discovery and cannot prove that flow.
5. On physical iPhone and Android devices, exercise camera permission, image
   fallback, claim/reload, merchant review/confirmation, duplicate refusal and
   student redeemed feedback. Desktop viewport emulation does not close this.
6. Restore a current hosted backup into an isolated target with matching source,
   canonical entry path, configuration and original signing state. Verify data,
   photos, identity/ownership and authenticated behavior, then stop/restart and
   verify again. A same-machine database round trip is only part of recovery.
7. Name the support and merchant-review operator and prove both approval and
   reversible suspension/reinstatement on the chosen host. The current preview
   can email approval links but cannot run the documented host suspension command.
8. Exercise an account export/deletion and merchant-closure procedure consistent
   with the published privacy page. The November policy promises a response and
   deletion/anonymization within 30 days, but no deletion tool exists. Resolve
   claim/dispute, ownership, photo and audit preservation rules with the owner
   before implementing destructive changes; published text alone is not proof
   those operations can be fulfilled. See [privacy decisions](PRIVACY-DECISIONS.md).

The November 15 recovery drill restored a fresh encrypted hosted snapshot into
an isolated PostgreSQL 18 database: 10 tables, 8,666 rows, 3 private files and 1
photo. Row values, schema objects and file hashes matched; the owned database was
stopped and original backups were unchanged. The snapshot records source
`544fe50deeef85535e30dab7767b68cd6ae0b563`. No recovered application was booted,
so this does not close the authenticated restart or second-machine requirement.
Restore now validates file lengths, names and empty, separate destinations
before changing the database. Keep restore destinations exclusively controlled;
database and filesystem writes are not one atomic transaction.

### Provider acceptance needed

The installed JacScale compiler supports deployment overlays and named-container
merging, but that does not establish which fields JacHammer accepts or how its
public Service is routed. Obtain a generated manifest or provider confirmation
of all of the following before deploying a gateway sidecar:

- A Node gateway container can run with the staged source mounted read-only.
- Every public origin routes to the gateway port, and the native backend port
  remains reachable only by that gateway.
- The original database/private/photo volumes and signing configuration are
  retained, with one application replica and no overlapping old/new writers.
- TLS termination and forwarded-client headers are defined so the gateway's
  secure-ingress and client-rate-limit settings are correct.
- Authorized operators can quiesce the app and perform the documented recovery
  and suspension operations against the actual mounted stores.

The CLI's source upload and accepted rollout overlay are not proof of those
capabilities. If they cannot be supplied, choose a host where the existing
restricted launch contract can be enforced before inviting a real cohort.

## Monitoring and backup operations

The `Hosted alpha monitor` workflow can be run manually with an origin and
revision. Its schedule remains inactive until repository variables
`MLOCAL_ALPHA_URL` and `MLOCAL_ALPHA_REVISION` are set after release acceptance.
Scheduled checks never allow samples. Run a deliberate failing check and confirm
the primary and backup operator receive GitHub Actions failure notifications;
workflow code by itself does not prove alert delivery. GitHub schedules can be
delayed and are not a high-availability monitoring SLA.

The existing daily encrypted backup task depends on the operator being signed
in to Windows. Keep its passphrase and original host signing configuration in
protected recovery storage independent of that computer. A second durable copy
and an independent missed-backup alert still need an operator destination.

The restricted gateway retains its existing 8 MiB response bound and 30-second
ordinary upstream deadline. Large hosted backup documents will be refused; no
unbounded exception was introduced for the token endpoint. Monitor backup
success/size before adding enough photos or history to approach that bound.
An approved private backup transport is required beyond it. The hosted helper's
200 MB photo collection ceiling is not a promise the public gateway can deliver
that much data.

## Decisions that require the owner

- Supply consenting U-M/business test inboxes and relay their verification codes.
- Arrange the physical phone pair and name the support/merchant-review operator.
- Resolve the account-deletion, merchant-closure and retained-claim rules so the
  promised privacy process can be implemented and tested.
- Select primary and backup alert recipients and confirm a failure notification.
- Supply a protected second backup destination/recovery machine, or authorize a
  specific hosting change if the current provider cannot enforce the gateway.
- Accept the exact tested cutover plan and small-cohort limits before inviting
  real merchants/students. Do not weaken a failed check to label the release ready.
