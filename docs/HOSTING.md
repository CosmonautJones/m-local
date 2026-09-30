# M-Local hosting

## Shared hosting status

Verified September 29, 2026. The JacHammer app is at
**https://m-local-main-prjc0b.jachammer.app/**. Its application, gateway and
PostgreSQL passed readiness checks with three healthy pods and zero restarts.
This host runs independently of Travis's laptop.

All visitors connect to the same backend and persistent PostgreSQL graph store.
Publishing an offer updates the shared catalog. Shared storage does not mean
shared access: account profiles, business ownership and claim credentials must
remain protected by server-side authorization. Anonymous claim and merchant
requests returned 401; the guest feed exposed no private QR credentials.
Complete hosted account-isolation tests are still pending.

| Area | Verified status / remaining work |
|---|---|
| Web app and backend | Public HTTPS welcome, student email form, session and catalog responses work. |
| Shared graph database | PostgreSQL has persistent storage. Application-level restart and backup/restore acceptance remains open. |
| Email and ownership records | Separate SQLite database plus signing key currently sit in ephemeral app storage. Move both to durable storage before onboarding real users. A single-instance persistent-disk configuration passed compiler dry-run; it is not deployed. |
| Email sender | Configured sender is `mlocal@travisjohnjones.com` through Resend. An earlier Gmail sender was not confirmed. Actual email delivery still needs a controlled recipient test. Never commit SMTP credentials. |
| Registration protection | JacHammer exposes native registration/login handlers. Restore the equivalent of the laptop gateway's restrictions before broad onboarding. |
| Source and release status | The dashboard reports healthy production while deployment history remains `in_flight`. Reconcile the deployed revision before the next rollout; do not submit duplicate jobs to clear a stale status. |
| Custom domain | `mlocal.dev` is not connected. Ownership/DNS access and HTTPS verification are pending. No domain purchase is authorized. |

Next engineering steps: preserve existing onboarding data, deploy durable storage
and registration protection, verify separate student/merchant email flows and
one-time redemption, prove restart/restore behavior, then attach the domain.
Merging these findings does **not** deploy those fixes or complete acceptance.
GitHub imports source; they do not migrate laptop/sandbox databases or secrets.
Keep the team branches and existing stores intact.

## Stable laptop hosting with updates from main

**Team URL: https://mlocal.tail0d5ef8.ts.net/**

The laptop runs the app, backend, and database. Tailscale Funnel provides public
HTTPS on the existing Free plan. Phones only need a browser, including on cellular
data. Keep the laptop awake, plugged in, and online. No paid hosting was created.

## Daily use

- `Start Stable Phone Demo.cmd`: start hosting and check main every 60 seconds.
- `Stop Stable Phone Demo.cmd`: stop this session and its owned backend.
- Push or merge changes into main, wait for checks and deployment, then refresh
  each phone. Local edits and commits on other branches do not deploy.

Keep the launcher window open. It prevents idle sleep without changing permanent
power settings. Public access can take about a minute to recover after restart;
the launcher waits for HTTPS readiness before displaying the link.

## How updates work

The latest push run of `.github/workflows/check.yml` must pass for the exact main
commit. The updater archives that revision into a temporary Linux directory,
installs dependencies, and runs Jac check and a production build while the old app
stays online. Existing compiler warnings do not fail Jac check.

After preflight succeeds, it stops the backend, switches the dedicated deployment
checkout, and starts the app in the same native runtime directory. The app briefly
becomes unavailable during restart. The gateway and public address stay in place;
accounts and stored data are retained.

Failed checks/builds keep the current version. Failed startup attempts to restore
and restart the previous source. Failed revisions are skipped until a new commit
or explicit redeploy. This restores source, not database/schema changes; coordinate
incompatible schema changes before merging.

Uncommitted changes in the deployment checkout suspend updates. Network operations
time out after 60 seconds and retry on the next poll. Preparation is limited to
nine minutes and removes its temporary workspace.

## Configuration and troubleshooting

Ignored `.jac/stable-link/config.json` selects `AppCheckout`, a separate clean
checkout reserved for deployment. Travis's setup reuses the existing phone-link
checkout and its database/SMTP settings. Hosting helpers stay in hosted-app.
Develop in the normal project checkout and push to main, not in the deployment
checkout.

Application frontend/backend and data/resource directories update automatically.
Gateway and launcher changes require a deliberate update/restart of the helper
checkout; they do not replace themselves while running.

Read `.jac/stable-link/deployment.json` for active commit, last check time, failed
revision and status. Candidate and app logs are in the same ignored directory.
Review logs before sharing them; never share private account/configuration files.

`/healthz` checks both runtime readiness and an anonymous `home_feed` response
within five seconds. A missing, failing, or malformed feed returns HTTP 503 with
`{"ready":false}`; a valid empty catalog is healthy. The page reports an invalid
feed as a connection error, rather than the "Offers are on their way" empty state.
The visible offers page refreshes every 30 seconds, on returning to the tab or
regaining connectivity, and when **Refresh offers** is pressed. This recovers
from a brief outage; it does not eliminate downtime during a backend restart or
loss of the laptop's internet connection.

From **PowerShell** in the helper checkout:

```powershell
.\scripts\stable-demo.ps1                 # normal start and main updates
.\scripts\stable-demo.ps1 -RedeployCurrent # retry/rebuild the current main
.\scripts\stable-demo.ps1 -NoAutoUpdate    # keep current app version
```

Stop an existing hosting launcher before changing startup options.

## Testing with several people

Everyone opens the same public URL and signs in with their own email address.
Student accounts use their own U-M inbox; business testers use distinct business
emails. A verified business can save its company profile and publish immediately.
All devices share the published catalog, while account profiles, preferences,
company ownership and claim credentials belong to each account. Unsaved form
edits stay in that browser page. Refresh offers shows another tester's new post;
the active offers page also refreshes automatically.

On one computer, use separate browser profiles or private browser sessions for
different people. Ordinary tabs in the same browser profile share login storage;
two tabs are not two independent accounts. Signing into the same email on two
devices intentionally opens the same account. Additional private windows may
share a private session, depending on the browser; separate profiles are the
clearest choice for manual tests.

The gateway permits twelve email-code requests per minute and thirty per hour
per trusted client IP, allowing four people behind one Wi-Fi connection to join
together. Per-email limits remain one send per minute and five per hour, with
five guesses per challenge. The entire app keeps its sixty-email/hour and
three-hundred-email/day sending limits. Gateway-limited requests return HTTP 429
with Retry-After; waiting or using an already signed-in session is appropriate.

Do not start a separate backend/database for each visitor. The host owns the
persistent database; each visitor needs only a browser and an independent login.

## Persistent state

Never remove or relocate these during code updates:

- The app checkout's private `.jac/onboarding.env` and demo-account files.
- `~/.local/share/m-local/phone-demos/<checkout-key>/`, including its private
  `.jac` data, account/role configuration, and recorded running revision.
- Jac's PostgreSQL store under `~/.cache/m-local/pg/`.
- `~/.local/state/m-local/tailscale/`, containing identity, certificates and
  Funnel configuration. Replacing or renaming the device can change the URL.

Tailscale 1.102.4 was installed without administrator rights inside WSL from its
official checksum-verified archive. A new machine needs setup-stable-link.sh, the
running app and stable-link service, then stable-link login and publish. Sign-in
and Funnel enablement must be completed for that account.

## Verification

For repeatable multi-user acceptance, use the existing disposable
`onboarding-check` fixture described in [onboarding](ONBOARDING.md), with the
backend on 8240. In a second **Bash/WSL** terminal in that fixture, start the real
gateway on loopback only:

```bash
node --input-type=module -e 'import {createShareProxy} from "./scripts/phone-share-proxy.mjs"; createShareProxy({upstreamHost:"127.0.0.1",upstreamPort:8240,trustCloudflare:false,healthCheck:true}).listen(8241,"127.0.0.1")'
```

From another **Bash/WSL** terminal in the same fixture:

```bash
bash scripts/python.sh tests/integration/multi_user_http.py --api http://127.0.0.1:8241
# After restarting the same disposable backend without replacing its store:
bash scripts/python.sh tests/integration/multi_user_http.py --api http://127.0.0.1:8241 --verify-restart
```

The HTTP test injects four local verification challenges and saves a private
`.jac/multi-user-check.json` receipt. It checks concurrent account/company edits,
shared publication, owner-only management, private QR access and exactly-once
claim/redemption. It sends no email and rejects nonlocal API addresses.
`tests/ui/live_multi_user.py --workspace <path-to-onboarding-check>` then uses
Python Playwright with installed Chromium to keep four independent browser
contexts open at 390px. It checks separate drafts, shared posts, account edits
and logout isolation. Run this from an environment that can reach loopback
8241; on Windows the workspace can be the fixture's WSL UNC path. Do not point
either test at the public host. Physical-device testing remains separate.

Public browser offers and distinct student/merchant sessions were verified.
Private admin/schema/raw signup routes returned 403. Deployment tests use real
disposable Git repositories to verify CI rejection, dirty-checkout protection,
bounded subprocesses and source rollback. Source-sync tests preserve private data.

On September 27, a real preflight/build/backend replacement completed at main
`ffa9878`. Three login tokens issued before deployment still authenticated as the
same student/merchant identities afterward; existing offer IDs were unchanged.
The 20 gateway/UI tests, deployment safety tests, and two source-sync tests passed.
The UI tests use the runtime-installed React/QR libraries under WSL; a bare Windows
test run without those built dependencies cannot run the QR roundtrip test.

New email delivery and physical phone-camera scanning remain acceptance checks.
Funnel is a free beta service with bandwidth limits and depends on the laptop's
connection.

References: [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel),
[same URL across restarts](https://tailscale.com/docs/use-cases/application-testing/share-local-dev-server-with-internet).

## JacHammer production network binding

Keep the local `[serve] host = "127.0.0.1"` default for laptop operation. For
JacHammer production, set the project environment variable:

```text
JAC_SERVE_HOST=0.0.0.0
```

Jac 0.37.23's generated Kubernetes command uses `jac run --serve main.jac`
without a host override. Its health probes connect to the pod IP, so a
loopback-only listener cannot pass those probes. Verified on a disposable
source snapshot: default binding was `127.0.0.1:18200`; with the override it
was `0.0.0.0:18200`, and `/healthz/ready` returned HTTP 200 with `ready:true`.
Environment changes require redeployment. This is a startup prerequisite,
not proof that a hosted deployment is healthy.

For diagnostics, JacHammer's served CLI 0.2.0 (prod@1d9f65a, September 28)
compiles with its tested Jac 0.36.1 runtime but not with 0.37.23. Run that CLI
with a separate compatible runtime; keep this app pinned to 0.37.23. The CLI
commands `ls --deployments`, `inspect --prod`, and `logs --prod` expose more
information than the dashboard's generic exit-code message. Pass
`--name M-Local-Main` explicitly for diagnostic commands. Never print or commit
the stored CLI token.
