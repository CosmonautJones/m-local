# Business approval

Public policy: review a business's name and street address before publication.
Offers, descriptions, cuisine, photos, website and menu details are self-service
after approval. A later name or address change requires review; the existing
public profile and offer management remain available while that change waits.

The owner submits the profile, sees that it is awaiting approval, and can check
its status. After approval, **Continue to offers** publishes through the owner's
authenticated app request. The host command records approval in private state;
it does not start the app or mutate a separate CLI graph.

## Review command

Run in the exact app workspace, with its private onboarding directory and
database configuration. Host filesystem/runtime access is the authorization
boundary. `--by` records attribution; it does not authenticate an operator.
The review operation has no public RPC and is excluded from the public gateway.

```sh
bash scripts/review-business.sh list
bash scripts/review-business.sh approve \
  --actor '<actor from list>' \
  --submission '<submission hash from list>' \
  --by 'Operator name' \
  --note 'How business authority and the address were checked'
```

Read the submitted profile and establish authority to represent the named
business at that address before approving. Copy the hash of that reviewed
submission. A concurrent edit invalidates the hash; read and review the new
submission before trying again. Only approved identity changes receive a new
review event. Retrying the same reviewed identity preserves its audit record.

Private `business_reviews` records retain the submitted snapshot, operator,
reason and time. `business_approvals` holds the current reviewed identity.
Review and public activation use the same host mutation lock. Activation checks
the current approval after acquiring it, and holds it through graph commit and
private finalization. A queued request for an older identity cannot overwrite a
newer activation; a review waits for an in-progress activation to finish.
The lock is `mutations.lock` in the configured private onboarding directory.
Configure the same absolute `MLOCAL_ONBOARDING_DIR` and shared volume for the app
and operator command; differing temporary-directory namespaces do not move this
lock. This remains a single-host filesystem lock.
Browser-selected slugs, roles, actor IDs and approval statuses confer no access.
Reserved `business-*` listings require their private approval and activation
even when a configured owner mapping exists. Pre-provisioned demo catalog
merchants use the existing host-managed mapping. The older profile RPC also
rejects name/address changes for those merchants; identity changes require host
review. Routine edits through that RPC update any existing private business draft
without discarding a pending identity submission. Intended fields are retained
before graph mutation. If the graph write fails, the owner can retry those fields;
an unavailable private store prevents the graph write from starting.
An existing malformed or incomplete private draft also blocks routine public
edits and returns an explicit recovery message.

## Rollout and recovery

Back up the graph, private SQLite store and original onboarding key together
before rollout. Run `list` against that deployment's existing private directory
before starting the new API processes. The command first requires a valid
existing key and onboarding database with its account, owner and draft tables
and required columns.
Missing or unrelated state is refused without creating a replacement. It then
constructs `CodeStore` and initializes the current schema, including the approval
identity `body` column.
Quiesce app and operator writers during this pre-start migration, and do not
replace the private database or key while the command runs. These checks do not
authenticate a deployment or prove the original key/database pair: verify the
exact volume and pair against the deployment's backup inventory first.
The request authority path is read-only: it does not migrate an older database
or recreate a missing key. Legacy approvals with no reviewed identity remain
unauthorized after schema migration until the operator reviews the submission.

The resulting list is a private-store inventory, not a complete graph
inventory. Separately inspect the exact deployment's `business_signup` restaurant
nodes and reconcile every slug with a verified private owner, submitted profile
and reviewed identity. Graph-only listings and legacy slug discrepancies remain
hidden; do not infer migration completion from an empty private list.
The list includes older active owners without a private draft
and flags `needs_submission`; ask those owners to sign in and submit their name
and address before reviewing. An empty email indicates an orphaned or wrong-kind
owner record that requires account reconciliation, not automatic approval. Existing empty
or noncanonical whitespace/control-corrupted approval snapshots also require resubmission/review.
Inventory outstanding claims before enabling
this release. Older `active=1` signup records without a reviewed identity are
hidden from new discovery and claims. Their students can still reopen existing
held QRs. Review those owners before rollout so merchant redemption access is
available; preserved QR display alone does not restore merchant authority. Do not
roll out while existing live businesses remain in this migration inventory.
Reading an old active draft without approval displays awaiting review and does
not grant authority or publish a graph mutation.

Approval and activation are separate durable steps. An interruption after
approval leaves the profile ready for the owner to continue. An interruption
after graph commit but before private activation retains the submitted fields
and is recoverable by retrying the same owner save, retaining one business
identity. This is recovery by durable intent, not an atomic transaction across
the graph and private store. Back up graph, identities,
private accounts, approvals/reviews and the onboarding key together.

The current SQLite private store and OS mutation lock remain limited to one
host. This approval implementation does not establish multi-host correctness,
suspension, complete restore, monitoring, operator staffing or public deployment
readiness. Those remain release gates in `RELEASE-ACCEPTANCE.md`.

## Verification

```sh
bash scripts/test.sh onboarding
bash scripts/test.sh core
bash scripts/test-business-approval.sh
```

The HTTP test uses a disposable loopback app, injected local OTP challenges,
the real host approval command, owner activation, private/public boundaries,
ordinary edits, identity re-review, offer publication and restart. It sends no
email. It refuses an inherited `JAC_DB_URL` and leaves its isolated workspace
for diagnosis. GitHub CI runs this same test.
