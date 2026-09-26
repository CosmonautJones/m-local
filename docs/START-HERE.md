# M-Local: four-engineer hackathon mission

## Yes, these are parallel assignments

**All four engineers can start together. Task numbers identify ownership, not
execution order.** Each person runs their own model in a separate clone and branch.
Engineer 1 establishes the shared runtime while Engineers 2-4 prepare their owned
tests, data and UI states. Once the runtime and small shared interfaces are ready,
all four implement and verify their areas concurrently.

Engineer 1 continues integration and release work throughout; nobody waits for
that entire mission to finish before building. Only dependent changes wait for
their specific interface, and final acceptance uses the merged application.
See the [parallel stages and handoffs](TEAM-WORKFLOW.md#start-concurrently-without-guessing).

**Mission:** Help an Ann Arbor student find an affordable restaurant offer they can
use now, understand how to reach the business, and redeem the exact deal they claimed.
Give the restaurant control over the offer's timing, quantity and terms.

**Why it matters:** Students encounter scattered promotions with unclear conditions.
A small business can publish an offer yet fail to reach people who would use it.
Local access changes can make an otherwise useful recommendation frustrating.
These are the problems we intend to address; user research and business impact
have not yet been established for this prototype.

**Our distinguishing behavior:** Connected, dated local information changes the
student's access explanation. Jac connects the restaurant, location, offer, notice
and claim, rather than leaving the user to reconcile separate pieces of information.

## The demo we are building

1. A merchant publishes an $8 meal offer with two units and a defined time window.
2. A student filters to $8 and offers available now, then reads the actual conditions.
3. The detail screen shows a current, source-labeled access notice for that location.
4. The student claims one unit and receives a QR code, locked-in terms and an expiry.
5. The merchant scans the QR and redeems it once; another redemption cannot consume more inventory.
6. A notice expires or changes. The explanation changes and no longer presents an
   outdated entrance instruction as current.

Use fictional businesses and clearly labeled simulation where we lack confirmed
real participation or data. No fictional offer is redeemable at a real restaurant.

## Four owners, four deliverables

This is a **hybrid specialization split**, not four independent full-stack slices.
In familiar terms: Engineer 1 is platform/integration; 2 is backend; 3 is data and
context; 4 is frontend/mobile web. Each owns a testable outcome as well as files.
All UI remains with Engineer 4, so do not describe the other roles as independent
UI-to-database feature teams. The [handoff table](TEAM-WORKFLOW.md#first-small-deliverables)
identifies what each must deliver early to prevent waiting.

| Engineer | Mission | Owns | Definition of done |
|---|---|---|---|
| 1 | [Runtime, integration and release](superpowers/plans/2026-09-26-01-runtime-release.md) | Toolchain, launch/test scripts, integration checks, release evidence | A teammate can start a clean clone, run checks and reproduce the phone demo |
| 2 | [Trusted offer transactions](superpowers/plans/2026-09-26-02-offer-trust.md) | Core graph, identity enforcement, offers, claims, redemption | Isolated users, preserved claimed terms and verified inventory/lifecycle behavior |
| 3 | [Local context and data](superpowers/plans/2026-09-26-03-local-context.md) | Notice graph, source records, importer and demo fixtures | A sourced or clearly simulated notice updates one location's access explanation |
| 4 | [Phone experience](superpowers/plans/2026-09-26-04-phone-experience.md) | All application UI and client session handling | Student and merchant complete the flow on a phone with clear feedback and recovery |

Each mission ends with a copy-ready model prompt. Choose a human for each row.
Engineer 1 is the integrator, not an additional fifth role. All four work on the
same product through separate branches. Do not have four agents edit `main.jac`.

Read [the shared contract](TEAM-CONTRACT.md) and [the working method](TEAM-WORKFLOW.md)
before starting. These documents define proposed implementation targets, not
features already delivered. The baseline is commit `46ec2d6`.

## What already exists

Seven Jac source files cover a MobUI interface, domain graph, demo data, offer rules
and seven tests. Source extraction was verified. The runtime checkpoint now targets
**Jac 0.37.23**: local startup, seven rule tests and a production `.jab` build have
been executed on Windows/WSL. See [runtime setup](RUNTIME.md),
[phone and teammate checks](PHONE-TESTING.md), and [current evidence](status/engineer-1.md).
Mac execution, physical phone testing and authentication integration remain pending.

Known gaps: demo merchant keys in the client, arbitrary student identity, mutable
terms after claiming, missing failure recovery in write flows, no contextual data
refresh, no proof of restart persistence or concurrent reservations, and expiring
demo records that do not automatically renew. Preserve the original snapshot.

## Impact and evidence

The [free local data guide](research/FREE-DATA-SOURCES.md) ranks City, U-M, transit,
weather and research sources, with actual access results and reuse limits. The
[local impact brief](research/LOCAL-IMPACT-EVIDENCE.md) supplies dated facts for the
pitch. These references support the existing scope; they do not add nine integrations.

The following are **targets**, not results:

| Intended benefit | Small, checkable evidence |
|---|---|
| Less effort to find an affordable offer | Three consenting testers can find a currently valid offer within their stated budget in 60 seconds without coaching |
| Clear merchant control | A tester in the merchant role can publish a correctly bounded offer within two minutes and pause new claims |
| Fewer misleading access instructions | A changed/expired notice changes the explanation for the correct location; unrelated locations remain unchanged |
| A trustworthy exchange | Separate student/merchant sessions complete a claim and one redemption with the original terms; retry and boundary checks pass |

Human teammates can gather voluntary feedback from people at the venue and record
anonymous task outcomes. Models must not contact businesses or other people.
Merchant role-play is not merchant validation. Simulated claims are not real foot
traffic; redemptions alone do not establish increased sales or profit.

## Scope for this build

**Required:** Jac-owned domain behavior; mobile browser flow; authenticated demo
accounts; timed/limited offers; exact claim terms; clear errors; one useful local
context relationship; source/expiry labels; repeatable setup and evidence.

**After required checks pass:** a confirmed-address map link, simple redemption
totals, or one additional context source. Pick at most one.

**Deferred:** full-city aggregation, personalized exam calendars, automatic campaign
generation, notifications, POS/payments, offline claims, native iOS packaging, AR/VR,
garage sales and other peer-to-peer listings. No hosted model is necessary for the
required flow. A graph visualization is optional presentation material.

## Hackathon requirements

The [official A2Tech guide](https://jachacks.org/a2tech-guide/) was checked on
September 26, 2026. It requires meaningful Jac use with at least 40% Jac code,
event-time coding, registered/checked-in teams of at most four, and an in-person
presenter. It calls for Baz review, a public repository, video and written submission.
The guide lists Sunday 9:30 a.m. for the draft and noon for final submission; earlier
Devpost timing conflicted, so the human team must confirm on-site updates. Local
Impact emphasizes a specific local user's problem. Hosting on JacHammer is encouraged.

Engineer 1 maintains submission evidence and the confirmed deadline. Keep honest
labels on generated/template code and simulations. A source-language count is
evidence, not a substitute for the organizer's eligibility decision.

## One-sentence pitch

M-Local connects affordable student meals with the local businesses offering them,
combining limited-time deals with current access information and a dependable
claim-and-redeem process, built in Jac.
