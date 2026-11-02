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

The repository's `jac.toml` is unchanged. `scripts/jachammer-stage.py` writes
the JacHammer-specific settings into a staged copy at deploy time; see its
docstring and `tests/tooling/test_jachammer_stage.py`.

## What testers can do

**Students** (anyone who can receive mail at an `@umich.edu` address):

1. Open the test link on a phone.
2. Browse and filter offers without signing in.
3. Claim an offer: enter the U-M email, type the emailed code, and get a QR pass.
4. Reload or come back later and find the saved pass.

**Merchants.** Self-service business approval needs the host command in
[BUSINESS-APPROVAL.md](BUSINESS-APPROVAL.md), and JacHammer has no shell into
the app pod, so new businesses stay at "awaiting approval" on this host. To test
the merchant side, attach a tester to one of the fictional sample restaurants:

1. The tester signs in once as a business with their own email.
2. They send their account ID. On a computer, open the test site signed in,
   open the browser's developer tools, Network tab, reload, select the
   `current_session` request and copy `actor_id` from its response.
3. The operator maps a sample restaurant to that ID and redeploys:
   `jachammer env add 'MLOCAL_MERCHANT_OWNERS={"arbor-leaf-kitchen":"<actor id>"}' --name M-Local-Main`
   then `jachammer redeploy`.
4. The tester now manages that sample restaurant: post an offer, then scan a
   student's QR and confirm the one-time redemption.

Each actor ID can own only one restaurant; give each merchant tester a
different sample slug.

## What to record

For each run, note the tester, phone and browser, and the result of: guest
browse and filters, email code delivery (time to arrive, spam folder),
claim and QR display, reload and saved pass, merchant scan and confirm, a second
scan being refused, and camera-denied behavior. These feed issues #36 (inbox
delivery), #46 (redeemed moment) and #50 (phone QA).

## Known gaps on this host

- **Native registration is reachable.** Jac's built-in `/user/register` and
  `/user/login` answer through JacHammer's gateway. An account made that way
  cannot claim (claims need a verified `@umich.edu` account) or act as a
  merchant, but it should be closed before a public launch by running the
  repository's restricted gateway in front of the app (issue #40).
- **No self-service business approval** (see above).
- **Rate limits** use the app's own per-email limits only; the repository's
  per-IP gateway limits are not in front of this host.
- **Backups** of JacHammer's volumes and PostgreSQL are not yet confirmed with
  the provider (issue #45). Treat test data as disposable.
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
deploy or `jachammer redeploy`.
