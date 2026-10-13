# Preserve identities when email onboarding collides

The public gateway denies native registration and password login. The native API
is an internal loopback service used by trusted provisioning and operators. A
deployment must not expose that port directly. Existing native, SSO and provisioned
accounts retain their original sign-in, user IDs, graph roots and keys.

An email-code challenge proves inbox access; it does not prove that an existing
native identity, root, preferences, ownership or claims are disposable. Onboarding
therefore refuses an unmanaged collision. It never deletes a user/graph, resets
its root, changes a password, verifies a foreign identity or transfers ownership.
Missing onboarding may indicate a mismatched recovery set. Recovering a matching
pending `mlocal_provision` marker is the sole automatic interrupted-create repair.

## Operator procedure

1. Keep the existing native identity and graph intact. Tell the affected person
   to use the original sign-in or contact the named host operator. Do not create a
   second root with their address. A blocked inbox request must not grant access
   to that native identity.
2. Record a private incident receipt: operator, time, candidate SHA, user ID and
   root ID, identity types/verification state, whether a matching onboarding row
   and pending provisioning marker exist, merchant membership, saved preferences,
   pending/redeemed claim counts, and the recovery-set ID. Never include passwords,
   OTPs, tokens, signing keys or QR credentials. Keep the receipt outside Git.
3. Close public write ingress while investigating a recovery mismatch. Take a
   coordinated backup before an approved remediation. Use the existing
   [recovery procedure](BACKUP-RECOVERY.md), preserving the canonical source path,
   PostgreSQL identity/graph, onboarding database/key, JWT signing state and photos.
   Opening a blank SQLite store is not recovery.
4. Inspect the existing identity through the official `UserManager` in the
   deployment's supported local operator context and its existing database.
   Inspect private onboarding through `existing_store()`, which refuses missing
   keys/database instead of initializing a replacement. Confirm the original
   sign-in and owner/claim evidence with the account holder. No record absence
   classifies an account as abandoned or malicious.
5. If the stores came from different recovery points, restore a matching set into
   an isolated deployment first. Verify the exact original user/root, native
   sign-in, merchant ownership, pending claim terms/credentials and redeemed
   history; then obtain Travis's approval for the proposed live restore. Do not
   synthesize onboarding authority merely from a verified native email flag.
6. If a genuine registration collision remains, require explicit human account
   ownership adjudication. Prepare a root-preserving, narrowly scoped identity
   reconciliation with before/after records and affected-user consent. If address
   reassignment is proposed, prove the current native owner's sign-in/identities
   remain valid and inventory every dependent record. Obtain Travis's approval
   before any live account/data change. There is deliberately no automatic
   delete/recreate, bulk cleanup or public remediation RPC.
7. Run isolated preservation and returning-sign-in tests for that exact procedure,
   obtain independent review, execute only the approved change, and append its
   outcome to the receipt. Open ingress only after authenticated state checks
   pass. Escalate unresolved ownership disputes; do not guess.

## Engineering verification

`bash scripts/test-native-hardening.sh --receipt <private-or-reviewed-receipt>`
uses its own native API, PostgreSQL cluster, mounted disposable state and local
TLS SMTP. Set `MLOCAL_HARDENING_DURABLE_BASE` to an existing mounted directory
reserved for disposable tests, never a live application volume. It reproduces
native unverified registration, creates legitimate pending/redeemed claims and
preferences, simulates a missing private account row in that disposable store,
then submits concurrent email proofs. The same root, original native credentials,
claims/snapshots, ownership and signing keys must survive. It also checks actual
production refusal/readiness and native-route denial at the intended gateway.

Local results do not establish hosted ingress, real inbox delivery, durable
provider storage, remote recovery or official-runtime transaction safety. Those
remain separate release gates.
