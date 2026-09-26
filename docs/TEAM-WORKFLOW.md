# How four engineers and four models work together

## First ten minutes

1. Pick Engineer 1 through 4 using [START-HERE](START-HERE.md). Each human keeps one
   accountable model session. No agent spawns another team or assigns other owners.
2. Read [TEAM-CONTRACT](TEAM-CONTRACT.md) together and accept the scope. Change a
   decision once in that file, rather than differently in four prompts.
3. Engineer 1 records the actual on-site deadline and makes the runtime checkpoint
   the first integration priority. Pick a feature freeze at least 90 minutes before
   the confirmed final deadline; reduce scope sooner if the flow still fails.
4. Each teammate clones separately, creates their assigned branch and pastes the
   prompt at the end of their mission. Public GitHub allows cloning/forks; Travis
   must explicitly add named collaborators for direct pushes to this repository.

WSL Bash, Git Bash or macOS/Linux terminal:

```bash
git clone https://github.com/CosmonautJones/m-local.git
cd m-local
git switch -c feat/01-runtime-release
```

Use exactly one assigned branch: `feat/01-runtime-release`, `feat/02-offer-trust`,
`feat/03-local-context`, or `feat/04-phone-experience`. If a branch already exists,
inspect and continue it instead of recreating or overwriting it. Without write
access, push to your own fork and open a PR to `CosmonautJones/m-local:main`.

## Start concurrently without guessing

Start all four assignments at the same time. Keep one human/model pair per branch
and one owner per production file. The early runtime checkpoint is a shared
dependency, not a requirement to finish Engineer 1's whole mission first.

| Stage | Engineer 1 | Engineer 2 | Engineer 3 | Engineer 4 |
|---|---|---|---|---|
| Runtime checkpoint | Prove version, startup, test invocation and auth hooks | Write lifecycle/identity acceptance cases and inspect graph behavior | Prepare source/fixture records and provenance | Plan loading/error/auth/context states from the contract |
| First integration | Publish runtime/scripts and support owners | Publish core schema/money helper contract | Publish context DTOs and empty-graph helper | Wire against frozen DTOs; keep mocks explicitly test-only |
| Parallel build | Write cross-session/restart checks and integrate small PRs | Implement trusted mutations and tests | Complete upsert, expiry and notice-change behavior | Complete phone flows and recovery |
| Integrated acceptance | Run the actual merged app and record release evidence | Resolve backend failures | Resolve data/context failures | Test iPhone Safari and resolve UI failures |

Try to finish the runtime checkpoint within the first 45 minutes. If it fails,
Engineer 1 supplies the exact failing command and a bounded next probe; the human
team resolves it before multiplying runtime-dependent changes. This is a planning
target, not an assurance about installation time.

No engineer is expected to complete their task without dependencies. Independence
means separate ownership and local tests; integration still has explicit milestones.
Engineers 2 and 3 should expose their small contract commits early, not deliver a
single large final PR. Engineer 4 can use test fixtures until the API exists, but
the final flow must call the real Jac server. Never present mock success as a pass.

### Specific handoffs, not whole-task waits

- Engineer 1 publishes the runtime pin and proved auth hooks; Engineers 2 and 4 can
  then implement their server/client session handling against the same runtime.
- Engineer 2 publishes the core schema and money helper; Engineer 3 can migrate
  importer and seed constructors while the remaining transaction work continues.
- Engineer 3 publishes the context DTO/helper; Engineer 2 can attach context to
  offers while Engineer 3 continues refresh and freshness behavior.
- Engineer 4 builds against these agreed shapes using isolated test fixtures where
  necessary, then verifies against the integrated real server before claiming done.

A handoff names the PR/commit, interface and passing checks. Once the integrator
merges it, dependent owners sync main into their own branches. Models must not
independently invent replacement interfaces or edit another owner's files to
avoid a dependency. Use independent work from the assigned mission while waiting.

### First small deliverables

| Owner / familiar specialization | First useful handoff | Depends on | Must not absorb |
|---|---|---|---|
| 1: platform and integration | Jac pin, run/check/build scripts, Windows/Mac instructions, phone connection path | One teammate runs the clean-clone checklist | Rewriting the product or becoming the sole author of auth |
| 2: backend and offer integrity | Freeze session and offer DTO signatures; prove one student and one merchant using Jac auth; preserve existing public function shapes until callers migrate | Pair briefly with 1 on runtime auth hooks; coordinate UI changes with 4 | Context ingestion, every UI fix, or optional analytics |
| 3: data and local context | One location, one dated access notice, one source/simulation label; freeze the context DTO | Core location IDs from 2; a small shared type commit | Full Ann Arbor aggregation or multiple new feeds |
| 4: frontend and phone experience | One complete browse -> claim -> show-code -> redeem path with loading/error states | Frozen DTOs from 2/3, runtime from 1 | Editing backend files to work around missing endpoints |

Engineer 2's mission is the heaviest: identity, atomic inventory and immutable
terms are distinct problems. Ship a small schema/API checkpoint first, then one
verified lifecycle change per PR. Engineer 1 should pair on the authentication
probe and exercise concurrency over HTTP; this is collaboration, not duplicate
ownership of `services/promo.jac`. Engineer 4 owns UI implementation but all four
humans can help perform phone tests. Engineer 3 can review source labels and help
exercise the final demo after the single context relationship works.

Freeze signatures before large model-generated changes. A frontend fixture is
temporary test data; it is not proof the real endpoint works. Integrate a small
working route early, then sync main after each shared change. Do not wait until
all four missions are finished to run the product together.

The runtime migration requested by Travis is a one-time compatibility exception:
the runtime PR removes retired placement syntax and adds required generic type
annotations in other owners' files. Owners should start from that shared commit
or merge it before adding new changes; it does not transfer ongoing file ownership.

## Small PRs and one integrator

- Engineer 1 owns merges to main. Every other engineer opens PRs and provides evidence.
- Suggested first merges: runtime/scripts -> core schema/money helper -> context
  DTO/helper -> full core/context/UI features as their dependencies pass -> release.
- Review ring: 1 reviews 2; 2 reviews 3; 3 reviews 4; 4 reviews 1. Review contracts
  and behavior, not just generated summaries. Engineer 1 still checks integration.
- Sync from main after each shared-contract merge. Use ordinary merges/rebases only
  on your own branch; never reset shared main or force-push another person's branch.
- Do not regenerate the whole application in JacHammer after manual development
  begins. GitHub main becomes the source of truth; a hosted copy can otherwise drift.

Each PR description includes: user-visible result; owned files changed; exact test
commands and outcomes; screenshots for UI; schema/API changes; known limitations;
whether fixture or live data was used. Secrets and personal test data stay out.

## Lightweight status, every 30-45 minutes

Each owner updates only `docs/status/engineer-N.md` and tells the human team:

```text
Branch / commit:
Now works, with evidence:
Still failing or unverified:
Interface change requested:
Need from another owner:
Next small deliverable:
```

Do not spend the session maintaining a dashboard. A blocker should contain a
reproducer and the specific owner who can resolve it. After 20 minutes of repeated
failure, stop changing unrelated code and bring the evidence to the team.

## Checks that must become real evidence

| Check | Owner | Pass condition |
|---|---|---|
| Clean-clone startup | 1 | Documented pin and commands start the same app on another teammate's machine |
| Role separation | 2 | Guest cannot mutate; student cannot choose merchant identity; merchant A cannot affect B |
| Claim retry / last unit | 2, exercised over HTTP by 1 | Retry returns the original live claim; two distinct students cannot both reserve the last unit |
| Stable claim terms | 2 | Editing an offer does not alter an existing claim's price, conditions or deadline |
| Persistence | 1 | Stop/restart with the same store retains an offer, claim and redemption |
| Notice lifecycle | 3 | Upsert changes one notice; expiry/staleness removes authoritative instructions; other locations are unaffected |
| Phone recovery | 4 | Failed load/claim/save/redeem leaves useful feedback and usable controls; retry does not double-claim |
| Full demo | All, recorded by 1 | Two sessions complete the published offer -> claim -> redemption flow on the integrated commit |

## Scope cuts and release

Cut optional maps, analytics and extra data sources first. Keep one area, one
location per restaurant, one context type and pre-provisioned accounts. Do not cut
truthful labels, role enforcement, stable claim terms or recovery to make a demo
appear finished. If a required check fails at freeze, document the limitation and
demonstrate the verified subset without a pilot-ready claim.

Engineer 1 keeps a release checklist with the exact commit, runtime, source-language
inventory, test results, Baz review evidence, demo video and submission links. Human
teammates confirm event requirements and submit. Agents do not contact people,
purchase services, invite collaborators, accept new permissions or publish a hosted
app without the relevant human authorization.

The user requested these missions and starting prompts. This planning pass does
not launch the four engineering tasks. Each human starts their own selected prompt.
