<p align="center">
  <img src="assets/brand/logo-compact.png" alt="M-Local" width="200">
</p>

# M-Local

M-Local is a team-built prototype connecting Ann Arbor students with time-limited
local restaurant offers. Students discover an offer, claim saved terms and present
a QR pass; the merchant previews and confirms one-time redemption.

Built by **Travis Jones, Rohan Maxa, Manthan Patil and Adam Jiang**. See
[team attribution](docs/PORTFOLIO.md#team-and-attribution) and the
[ownership contract](docs/TEAM-CONTRACT.md).

[Illustrative demo](docs/demo/m-local-demo.mp4) ·
[Connected-photo review](docs/UI-PHOTO-REVIEW.md) ·
[Runtime setup](docs/RUNTIME.md) ·
[Release tracking](https://github.com/CosmonautJones/m-local/issues/33)

## Release status

`main` contains the merged engineering release candidate: the PR #55/#59
student and merchant release plus the October 15-18 hardening stack
(PRs #60-#70: exact-package recovery binding, offline preflight parity,
private research handling, single-PostgreSQL auxiliary proofs, disposable SQL
startup and immutable build identity). Every workflow passes on `main`.
**Live rollout remains unapproved.** An existing hosted app must not be assumed
to contain the repository's latest changes; compare its `/version.json` build
identity before relying on it. See the
[release tracking record](https://github.com/CosmonautJones/m-local/issues/33).

| Component | Review |
| --- | --- |
| Manual approval, connected photos and recovery foundation | [PR #55](https://github.com/CosmonautJones/m-local/pull/55) |
| Native hardening, student experience, header fix and merchant suspension | [PR #59](https://github.com/CosmonautJones/m-local/pull/59) (includes #56-#58) |
| Recovery binding, preflight parity, private research and build identity | [PR #70](https://github.com/CosmonautJones/m-local/pull/70) (includes #60-#62, #69) |
| PostgreSQL auxiliary proofs and disposable integrated SQL startup | [PR #68](https://github.com/CosmonautJones/m-local/pull/68) (includes #63-#67) |

Earlier immutable handoffs (for example the
[combined candidate handoff](https://github.com/CosmonautJones/m-local/blob/7b5344f62176dc3edf7c6a54720e4274daff6931/docs/review/release-rc-bed4be3/HANDOFF.md))
preserve historical receipts. Source composition is
[informational](docs/RELEASE-SOURCE-POLICY.md); every later source head needs
its own checks.

Remaining gates include research access, retention and historical publication,
provider durability and existing-user migration, an approved rollout artifact,
current-candidate inbox delivery, off-host recovery, monitoring, phones/cameras
and human acceptance.
Follow the [gate matrix](docs/RELEASE-GATES.md)
and [acceptance checklist](docs/RELEASE-ACCEPTANCE.md). Local fixtures and a
reachable homepage do not complete hosted acceptance.

Travis approved private retention of contact research on October 16. `main` no
longer tracks research payloads (they were preserved privately first) and new
release packages refuse them. Prior public Git history still contains them until
separately addressed; older archives containing research must remain
private. Readers, retention and history handling remain open in
[privacy decisions](docs/PRIVACY-DECISIONS.md).

## Candidate behavior

| Students | Businesses |
| --- | --- |
| Browse before signup; filter by price, time and diet. | Verify a business email, import or enter details, and submit for manual approval. |
| Sign in with an emailed code when claiming; retain the selected offer through verification and reload. | Manage connected profile/offer photos, drafts, publication retries and bounded offer windows. |
| Recheck availability before confirming; receive a QR pass with saved terms and expiry. | Preview the claim QR and explicitly confirm one-time redemption. |
| See clear empty, loading, sold-out, expired and error states. | Inspect recorded claims and redemptions with honest sample labels. |

The server owns authorization, inventory, expiry and redemption. A hold lasts up
to 20 minutes or the offer end, whichever comes first. The combined candidate
limits each student to two live holds while preserving existing claims. Repeat
requests retain the original claim; saved price and terms do not change when an
offer is edited.

Host-authorized merchant suspension hides public offers and blocks new claims,
publication and redemption. Existing claims stay visible with support guidance
and keep their original expiry and terms. Only an attributed, revision-checked
reinstatement resumes service; routine business edits cannot clear suspension.
See the [operator commands](docs/BUSINESS-APPROVAL.md#reversible-suspension-and-reinstatement).

M-Local access is available to people who can verify access to their `@umich.edu`
inbox, including alumni. Verification proves inbox access, not current enrollment
or official U-M endorsement. Businesses check any stated offer eligibility at the
counter. Sample offers are fictional and cannot be redeemed at a real business.
Server sample policy applies across public feed, detail and favorite paths while
preserving legitimate saved claims.

## Demo

The [accepted 50-second, 1080p demo](docs/demo/README.md) uses fictional businesses
and illustrative activity. It predates the connected-photo revision; review
[current photo screens](docs/UI-PHOTO-REVIEW.md) separately. It does not establish
real merchant participation, live hosting, inbox delivery or physical-device
acceptance. The current media privacy review still has audio and QR contents
unverified.

## Screenshots

These are historical browser captures from **September 27, 2026**, with fictional
test data, predating the connected-photo candidate. They do not establish current
host behavior or physical-device acceptance. Other preserved captures remain
in [docs/screenshots](docs/screenshots).

| Discovery | Offer detail | Claim pass | Business insights |
| --- | --- | --- | --- |
| ![Historical offer feed](docs/screenshots/discovery.png) | ![Historical offer detail](docs/screenshots/offer.png) | ![Historical claim pass](docs/screenshots/claim.png) | ![Historical business insights](docs/screenshots/insights.png) |

## Local development

Run from the repository in **WSL Bash**, with pinned official Jac **0.37.23**:

```bash
bash scripts/setup.sh
bash scripts/dev.sh
```

The development app listens at `http://localhost:8000`. Use the runtime wrappers
in [RUNTIME.md](docs/RUNTIME.md); preserve existing stores and human work.
Never reset a shared demo or production database. Email setup and optional website
extraction are described in [ONBOARDING.md](docs/ONBOARDING.md).

## Verification

```bash
bash scripts/check.sh
bash scripts/test.sh core
bash scripts/test.sh context
bash scripts/test.sh insights
bash scripts/test.sh onboarding
bash scripts/build.sh
```

Complete checks are defined in [check.yml](.github/workflows/check.yml) and
[shared-onboarding-proof.yml](.github/workflows/shared-onboarding-proof.yml),
with additional native, browser and packaged-recovery workflows on the component
and combined branches. They include photo ownership, manual business approval,
coordinated recovery, deployment safety, Node and compiled-browser checks.
Required proofs must execute at the final source SHA; absent or skipped proof
steps are not passing evidence.

At the historical `2be568a` checkpoint, the functional job passed **493 core executions across
134 expected names, 66 Node tests and 162 compiled-browser tests**.
[Actual browser proof](https://github.com/CosmonautJones/m-local/actions/runs/37611016646)
passed 62 checks;
[native preservation/topology proof](https://github.com/CosmonautJones/m-local/actions/runs/37611016746)
passed 80 preservation checks and 266 runtime checks with 21 faults;
[cloud package recovery](https://github.com/CosmonautJones/m-local/actions/runs/37611016706)
passed 66 authenticated checks for its separate artifact. These receipts do not
certify a later source or the recreated local archive, which still lacks its own
authenticated recovery certificate.

## Architecture and hosting

Jac owns the connected graph, offer/claim lifecycle and application shell.
Python supports onboarding, email, photo normalization, production validation and
recovery tooling. JavaScript supports browser components and the restricted
gateway. Use the suitable language for each task; source percentage imposes no
language-conversion target.

The supported combined topology is **one exclusive backend and one serialized
gateway**, with no overlapping rollout, extra graph writer or public native-route
bypass. Complete upstream responses stay in the serialized lane. This is bounded
safety evidence, not a multiple-replica or measured-capacity claim.

Graph/identity storage, onboarding SQLite, original signing keys and photo
ownership/files must be preserved together on durable storage.
The [hosting package](docs/RELEASE-HOSTING-PACKAGE.md)
contains secret names, preflight, backup, isolated restore, rollout, smoke checks
and source rollback. Travis must explicitly approve deployment and live data
work.

The existing [JacHammer address](https://mlocal.jachammer.app/) is a historical
host reference. Its deployed candidate revision, durability and readiness are
unverified here. Do not invite real account onboarding from this README.

## Team references

- [Work handoff](docs/WORK-HANDOFF.md)
- [Team contract](docs/TEAM-CONTRACT.md) and [parallel workflow](docs/TEAM-WORKFLOW.md)
- [QR redemption](docs/QR-REDEMPTION.md)
- [Business insights](docs/BUSINESS-INSIGHTS.md)
- [Persistent coordination and independent review](docs/RELEASE-REVIEW-PROTOCOL.md)

Payments, POS integration, automatic business approval and native iOS/Android
packaging remain outside this candidate.
