# JacHammer test environment

A hosted test copy of M-Local on JacHammer, for the team and a few invited
testers. It is **not** the public launch: it runs in the app's normal
(non-production) mode with fictional sample offers turned on, and the remaining
launch gates in [RELEASE-GATES.md](RELEASE-GATES.md) still apply.

Do not share the link publicly. It sends real verification emails through the
project's Resend sender.

## What is set up

| Area | How |
| --- | --- |
| Hosting | JacHammer project **M-Local-Main** (Builder plan), preview deployment. |
| Runtime | Official Jac 0.37.23, the repository pin. JacHammer ships the same binary (sha256 `2c3c6976…d9c6ad`). |
| One writer | One app replica, no autoscaler, one request thread, and a rollout that stops the old pod before starting the new one. |
| Graph | JacHammer's PostgreSQL 18 on its own persistent volume. |
| Accounts, email-code key, approvals | `MLOCAL_ONBOARDING_DIR=/srv/m-local/onboarding` on the `mlocal-state` persistent volume. |
| Uploaded photos | `assets/photos` on the `mlocal-photos` persistent volume. |
| Sign-in tokens | Fixed `JAC_SERVE_AUTH_SECRET` project variable, so deploys do not sign everyone out. |
| Sample offers | `MLOCAL_SHOW_SAMPLES=1`. Every sample is labeled fictional and cannot be redeemed at a real business. |
| Email | Existing Resend settings (`MLOCAL_SMTP_*`). |

Verified on 2026-11-02 against the preview deployment:

- JacHammer rendered one app replica, no app autoscaler, and both persistent
  volumes (`mlocal-state`, `mlocal-photos`) bound to AWS EBS and attached to
  the app pod; the rollout scaled the old pod down rather than running two.
- The welcome page, `current_session` and `home_feed` (346 labeled sample
  offers) respond.
- A throwaway native test account's sign-in token and graph identity survived
  a full `jachammer redeploy` (same actor, still authenticated). That account
  has the `unverified` role and cannot claim.
- Not yet exercised on this host: real email-code delivery, claim/QR,
  redemption, photo upload, and onboarding-store survival across a restart.
  Those are the first things for testers to try.

The repository's `jac.toml` is unchanged. `scripts/jachammer-stage.py` writes
the JacHammer-specific settings into a staged copy at deploy time; see its
docstring and `tests/tooling/test_jachammer_stage.py`.

## What testers can do

**Students** (anyone who can receive mail at an `@umich.edu` address):

1. Open the test link on a phone.
2. Browse and filter offers without signing in.
3. Claim an offer: enter the U-M email, type the emailed code, and get a QR pass.
4. Reload or come back later and find the saved pass.

**Merchants.** A business that signs up is approved from the emailed review
link (see Known gaps and [BUSINESS-APPROVAL.md](BUSINESS-APPROVAL.md)). To test
the merchant side without a real business, attach a tester to one of the
sample restaurants:

1. The tester signs in once as a business with their own email.
2. They send their account ID. On a computer, open the test site signed in,
   open the browser's developer tools, Network tab, reload, select the
   `current_session` request and copy `actor_id` from its response.
3. The operator maps a sample restaurant to that ID and redeploys:
   `jachammer env add 'MLOCAL_MERCHANT_OWNERS={"arbor-leaf-kitchen":"<actor id>"}' --name M-Local-Main`
   then `bash scripts/jachammer-deploy.sh`.
4. The tester now manages that sample restaurant: post an offer, then scan a
   student's QR and confirm the one-time redemption.

Each actor ID can own only one restaurant; give each merchant tester a
different sample slug.

## QA accounts and simulated usage

`scripts/qa-hosted.py` creates QA accounts on the test host and replays
realistic use, without email:

```bash
python3 scripts/qa-hosted.py provision --url https://m-local-preview-prjc0b.jachammer.app
# set the two printed variables on the host, then bash scripts/jachammer-deploy.sh
python3 scripts/qa-hosted.py run --url https://m-local-preview-prjc0b.jachammer.app --minutes 10
```

`provision` registers 8 QA students and 3 QA merchants (one per sample
restaurant) with `example.test` addresses and stores their credentials in
`~/.mlocal-qa/accounts.json` (mode 0600, outside the repository). QA students
claim through `MLOCAL_DEMO_STUDENTS`; QA merchants own the sample restaurants
through `MLOCAL_MERCHANT_OWNERS`. Both are demo settings the production guard
refuses, so remove them before any production deploy.

`run` checks roles, guest browsing and filters, claim/QR/one-time redemption,
wrong-merchant and forged-QR refusal, the two-hold limit, a six-way race for a
one-unit offer, duplicate publish, pause/resume, access control, and tastes and
favorites. It then runs mixed traffic (every QA student browsing, opening
offers, favoriting, claiming and cancelling with 2–8 s think time, while the
merchants scan and redeem) and writes a JSON report with per-call latency next
to the credentials file. It refuses non-preview hosts unless `--allow-host` is
given.

### QA results, 2026-11-02 (preview, 8 QA students, 3 QA merchants)

Scenario checks: **60/60 passed** on the hosted preview (roles, browse and
filters, claim/QR/one-time redemption, wrong-merchant and forged-QR refusal,
two-hold limit, six-way last-unit race with exactly one winner, duplicate
publish, pause/resume, access control, tastes and favorites). A phone-size
browser pass covered the welcome screen, guest feed, taste picker, personalized
feed, offer detail, claim and QR pass, saved pass after reload, cancel, and the
merchant offers and Insights screens.

Mixed traffic, no errors in any run:

| Students | Minutes | Feed p50 / p95 | Offer detail p50 / p95 | Feed loads |
| --- | --- | --- | --- | --- |
| 4 | 5 | 6.1 s / 9.5 s | 4.2 s / 9.2 s | 80 |
| 8 | 5 | 12.8 s / 18.7 s | 11.1 s / 17.3 s | 85 |

Findings:

1. **Feed capacity** (addressed in `233f238`, see below). `home_feed` cost about 2.6 s of server time with the
   346-offer sample catalog (a $3-filtered `list_offers` still takes 2.9 s,
   so it is computation, not payload size). With one request thread, the host
   completes roughly 17–20 feed loads a minute in total, and the feed screen
   refreshes every 30 s while open, so about ten people with the feed open
   saturate it. Everything else (claims, redemptions, merchant actions) is
   ~0.2 s when it is not queued behind feed loads (#49).
2. **Sold-out offers rank first** (fixed in `233f238`). `services/taste.jac` treated
   `remaining <= 3` as "Almost gone", which includes 0, so sold-out offers get
   that badge next to "Sold out" and a ranking boost to the top of the feed.
3. **Serialization conflicts surface as HTTP 500.** With the default thread
   pool (local rehearsal), a `toggle_favorite` hit PostgreSQL `40001` and the
   client received HTTP 500 with the raw database error text. Not seen with the
   hosted one-thread setting; relevant before raising concurrency (#39).
4. **"Fictional businesses" label is inaccurate** (fixed: the header now says
   "invented deals, not real promotions"). The hosted sample catalog
   (`data/simulation/places.json`) uses real Ann Arbor places, including chains
   and a U-M dining hall, with invented deals. Offers are tagged "Sample" and
   offer pages say to confirm real offers with the business, but the feed
   header says "fictional businesses" (and only for demo accounts).
5. **Accessibility.** Taste chips showed selection by color only (#48). They
   are now checkboxes with a checked state; the feed filters were already
   native radio buttons and checkboxes.
6. **Minor copy** (fixed). A cancelled claim no longer shows "Hold expires …";
   offers ending more than 18 hours out name the day, and spans of two days or
   more read "13d 13h left".

Not covered by automation: email-code delivery, camera scanning on real
phones, photo upload.

### Performance after the catalog snapshot, 2026-11-03 (preview, `233f238`)

Same hosted preview, same 346-offer sample catalog, same QA tool and traffic
model (each simulated student acts every 2–8 s, much busier than a real user,
who loads the feed every 30 s while it is open). Compression was also turned on
(`JAC_SERVE_COMPRESSION=true`), taking the feed from 552 KB to 58 KB on the wire.

| Students | Feed p50 / p95 | Detail p50 / p95 | Claim p50 | Feed loads in 5 min | Errors |
| --- | --- | --- | --- | --- | --- |
| 8, before | 12.8 s / 18.7 s | 11.1 s / 17.3 s | 7.7 s | 85 | 0 |
| 8, after | 0.25 s / 0.41 s | 0.12 s / 0.19 s | 0.16 s | 450 | 0 |
| 32, after | 0.27 s / 0.66 s | 0.14 s / 0.36 s | 0.17 s | 1,763 | 0 |

Scenario checks: 84/84 passed (the four extra role checks are the added QA
students). The 32-student run completed about 3,550 requests in five minutes
(about 12 per second) on the single serialized backend. Latency now comes from
the network and the stress pattern, not the catalog walk; single feed loads
from a home connection take 85–150 ms.

One browser load right after the 32-student run got HTTP 500 from JacHammer's
gateway with a DNS lookup error (`Name or service not known`) for the app's
internal service name. It did not recur in eight immediate retries or the UI
refresh, and no request failed during the runs. Watch for it in the provider's
gateway logs before a public launch.

### Capacity of the single backend, 2026-11-03

A read-only probe (guest `home_feed`, gzip, no think time) against the preview
at `e1cfa37` found the ceiling of the one-thread backend: about 22.5 feeds a
second. Latency stayed flat up to 4 concurrent callers and queued beyond 8
(16 callers: p50 0.69 s), with no errors. Profiling the same request showed
about two thirds of the time spent turning the 298-deal response into JSON,
and most of the rest in per-place ownership and suspension checks that opened
the private store several times per place.

Changes after that measurement:

- **Feed paging.** The phone asks for 40 ranked deals and shows "Show more
  deals"; the caller's live holds are always included. `home_feed` with no
  `limit` still returns everything (QA tool, tests). Locally the paged feed is
  8.6 KB compressed instead of 77 KB and takes less than half the time. It also
  renders 40 cards on a phone instead of 300 (#49).
- **Views only for returned deals.** Ranking uses the snapshot directly; full
  offer views are built for the page only.
- **One private-store read per request** for ownership and suspension across
  all places (`place_access`, `merchant_owners`), instead of up to three per
  place. Still read live on every request; nothing about suspension is cached.
  `current_session` uses the same batch lookup.
- **Seed check once per process.** Every read path ran the catalog bootstrap
  query; it now runs once and again after any catalog write.

Measured on the preview after the change (`777db54`, same probe):

| Callers at once | Feed loads/s, before | p50, before | Feed loads/s, paged | p50, paged |
| --- | --- | --- | --- | --- |
| 1 | 5.1 | 176 ms | 7.9 | 113 ms |
| 4 | 19.7 | 187 ms | 28.4 | 122 ms |
| 16 | 22.8 (ceiling) | 688 ms | 95.3 (not yet a ceiling) | 154 ms |

The paged feed is 8.6 KB compressed instead of 58 KB. At 16 callers the time
is mostly network round trip, so the true ceiling was not reached. One request
in the 8-caller step took 60 s (no error); it did not recur and looks like the
provider's gateway, which runs its own autoscaler and logged metric errors
during the deploy.

The QA run on the same build (32 students, 5 minutes, full unpaged feeds as the
QA tool requests them) passed every scenario check; the access-control check
now confirms native registration is refused (`CHALLENGE_REQUIRED`). Traffic:
1,787 feeds (p50 258 ms, p95 412 ms), 1,069 offer pages (p50 125 ms), 403 claim
attempts (p50 156 ms), 202 cancels, 161 favorites, zero server or network errors.

## What to record

For each run, note the tester, phone and browser, and the result of: guest
browse and filters, email code delivery (time to arrive, spam folder),
claim and QR display, reload and saved pass, merchant scan and confirm, a second
scan being refused, and camera-denied behavior. These feed issues #36 (inbox
delivery), #46 (redeemed moment) and #50 (phone QA).

## Known gaps on this host

- **Native registration is throttled, not removed.** JacHammer's gateway
  cannot refuse a route and Jac always mounts `/user/register` and
  `/user/login`. The deploy staging sets `[serve.auth]` to require a
  proof-of-work challenge and allow one registration attempt an hour (behind
  the gateway that is effectively one an hour in total). M-Local never uses
  native registration: accounts come from the email-code flow inside the
  server. An account made natively cannot claim or act as a merchant. Provisioning
  more QA accounts needs `JACHAMMER_OPEN_REGISTRATION=1 bash
  scripts/jachammer-deploy.sh` (refused with `--prod`). Running the repository's
  restricted gateway in front of the app would close it fully (#40).
- **Business approval by email.** With `MLOCAL_OPERATOR_EMAIL` and
  `MLOCAL_PUBLIC_URL` set, each new business submission emails the operator an
  approve link ([BUSINESS-APPROVAL.md](BUSINESS-APPROVAL.md)). Suspension still
  needs the host command, which JacHammer cannot run.
- **Backups are pulled to the operator's PC** once a day
  ([HOSTED-BACKUPS.md](HOSTED-BACKUPS.md)); JacHammer's own backups remain
  unconfirmed (#45).
- **Sign-in email limits.** `MLOCAL_MAIL_DAILY_CAP` / `MLOCAL_MAIL_HOURLY_CAP`
  (defaults 300 and 60) cap codes for the whole site. Resend's free plan stops at
  100 emails a day, so the preview sets 90 a day; raise both after upgrading the
  Resend plan. Sessions last 30 days on this host, so a student needs about one
  code a month.
- **Rate limits** use the app's own per-email limits only; the repository's
  per-IP gateway limits are not in front of this host.
- **Package format.** JacHammer requires PyPI pins under `[dependencies.pypi]`,
  which pinned 0.37.23 does not read. Pillow still installs with the runtime;
  psycopg does not, which only matters for the opt-in SQL proof modes.

## Deploying

From WSL with the `jachammer` CLI logged in, on a clean checkout of the branch
to deploy:

```bash
bash scripts/jachammer-deploy.sh          # preview (the test environment)
bash scripts/jachammer-deploy.sh --prod   # production; launch gates first
```

The script stages tracked files only (never local stores or keys), omits
`docs/` and `tests/` to stay under JacHammer's ~10MB upload cap, type-checks
with the pinned runtime, then deploys. JacHammer's own pre-upload check is
skipped because it uses whatever `jac` is first on `PATH`.

A deploy takes about 20 minutes. `jachammer env add` changes apply on the next
deploy: run `bash scripts/jachammer-deploy.sh` again. Do not use
`jachammer redeploy --name M-Local-Main`: on 2026-11-03 that created a second,
separate preview (`m-local-main-preview-…`, with its own empty database)
instead of updating the app, because the project name differs from the app
name `m-local`.
