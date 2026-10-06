# Email and business onboarding

Signed-out visitors always see the same welcome screen with **Find local deals**
and **List my business**. Choosing either opens its email form. **Back** returns
to both choices, and the compact **Account type** selector can also switch forms.
Logout returns to this welcome screen. Previously saved path choices are ignored.
Valid authenticated sessions still restore automatically; the server account's
role determines the available screens and permissions. App content stays hidden
until the session is authenticated.

Students/community members enter their uniqname beside a fixed `@umich.edu`.
The server constructs the address. Business owners enter their full work email.
A six-digit email code creates an account or resumes its existing Jac session.
No university password is collected. Email verification proves inbox access,
not current enrollment or official U-M endorsement.

**Create an account** asks for your name and email. **Sign in**
switches to returning sign-in, which only needs your email. The server checks
account existence after successful email verification. Returning sign-in never
overwrites your saved name or changes your account type.

Public sign-in uses email codes only. Demo/password sign-in controls and the
public `/user/login` route have been removed. Internal provisioning tools still
work against the loopback API for isolated tests. Existing data is preserved.
Seeded sample offers are hidden from public browsing; new business offers appear
normally. The feed shows an empty state when no real offers have been published.

The sign-in form has one primary action per phase. Signup/sign-in is a small text
link; account type is a selector rather than another full-width button. After a
code is requested, these controls disappear, leaving verification, resend, and
change-email actions. Duplicate account headings and explanatory paragraphs have
been removed. Business setup still follows successful verification.

Signed-in members can open **Account** to edit their display name, cancel unsaved
changes, and view their email and access status. Email and account type are not
editable profile fields. Demo accounts may save a name without gaining verified
email status. Profile reads and writes use `get_account_profile` and
`save_account_profile(display_name)` under the authenticated Jac root.

## Turn on email delivery

No sender is configured by default. Until one is configured the form reports
that email sign-in is unavailable; it does not pretend to send a code.

### Fastest test setup without a domain

Use a dedicated Gmail account for this small team test. Your real `@umich.edu`
accounts are recipients; you do not need university SMTP access or SSO approval.

1. [Create a Google account](https://accounts.google.com/signup) with a Gmail address.
2. Enable **2-Step Verification** on that account, then create an
   [app password](https://myaccount.google.com/apppasswords) named **M-Local**.
   Google requires you to complete its account/security steps. See Google's
   [app-password instructions](https://support.google.com/accounts/answer/185833).
3. From the checkout that actually hosts the phone demo, run in **PowerShell**:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure-email.ps1 -Provider gmail
```

Enter the dedicated Gmail address and app password at the hidden prompt.
Do not paste the app password into chat, a command argument, or a Git file.
The helper uses `smtp.gmail.com:465` with TLS, checks authentication without
sending mail, and only then saves `.jac/onboarding.env`. It preserves other
settings in that file. The Gmail sender and login address are the same account.
This does not use your normal Google password or a university password.

The equivalent command in **WSL Bash** is:

```bash
python3 scripts/configure-email.py --provider gmail
```

4. Restart the app. For the phone demo, use **M-Local - Stop Phone Demo**, then
   **M-Local - Start Phone Demo**. The new tunnel has a new phone link.
5. Open that link, enter a real U-M uniqname, receive and enter the six-digit
   code, then sign out and sign in with a fresh code. Check spam folders too.

To check saved credentials without sending email, run the PowerShell helper
with `-Check`, or `python3 scripts/configure-email.py --check` in WSL.
Authentication success does not prove inbox delivery or verify the sender's
authorization at every provider. Complete the real code test before announcing
email signup as ready.

If **App passwords** is missing, confirm the correct dedicated account and
2-Step Verification. Google may withhold the option for some account/security
configurations; do not weaken account security to bypass that restriction.
A domain-backed sender is the alternative. Personal Gmail also has
[sending limits](https://support.google.com/mail/answer/22839) and may reject or
filter mail. Move to a transactional provider before a wider launch.

### Domain-backed sender or another SMTP provider

For example, [Resend SMTP](https://resend.com/docs/send-with-smtp) uses host
`smtp.resend.com`, port `587` with STARTTLS, username `resend`, and an API key as
the password. The setup helper defaults to 587; the host's WSL runtime completed
an encrypted handshake on that port, while port 465 timed out on the test network.
You must own and verify a sending domain; `umich.edu` and `gmail.com` cannot be
verified by the team. Use the helper with `-Provider resend` or `-Provider custom`
(WSL: `--provider resend` or `--provider custom`). A provider account/domain and
credentials still have to be supplied by the team; none were created here.

For manual setup, `.env.example` documents `MLOCAL_SMTP_HOST`, `MLOCAL_SMTP_PORT`,
`MLOCAL_SMTP_USERNAME`, `MLOCAL_SMTP_PASSWORD`, and `MLOCAL_SMTP_FROM`. Edit the
ignored `.jac/onboarding.env` locally using shell-quoted values. `scripts/dev.sh`
loads it on startup; other launchers must source it before starting Jac. The phone
demo launcher does this. Port 465 uses TLS immediately; other ports must support
STARTTLS. Unencrypted delivery is not supported. Keep the file under your local
user's filesystem permissions and never expose it through the web server.

## Business creation and optional AI

After business email verification, the review card is open. A reload of a
verified business account that does not yet have a restaurant opens that same
card, without a separate Business profile toggle. Paste a public `https://`
homepage or type details manually. Import reads at most the homepage and one
same-site menu HTML page; PDF menus remain links. JavaScript-only sites may
require manual entry. It reads structured business data, metadata, text, menu
URLs and photo candidates. Website photos appear as selectable thumbnails,
with a preview of the selected photo. Owners can also upload, replace or remove
a phone photo. Selecting a website photo imports an owned copy; uploads and
imports are normalized to JPEG with metadata removed. Uploaded photos live in
`assets/photos/`, with ownership recorded privately in the onboarding directory.
Preserve both together during deployment and recovery. Physical Safari/HEIC
compatibility remains an open device check; export a JPG if the browser cannot
open a HEIC photo.

To additionally organize site text with Jac's real `by llm()` implementation,
set `MLOCAL_IMPORT_MODEL` and its provider credential in the same private env
file, run `jac install` with the pinned runtime, then restart. For example, `MLOCAL_IMPORT_MODEL='gpt-4o-mini'` with
`OPENAI_API_KEY`. This sends bounded public website text to that provider.
No model call occurs when `MLOCAL_IMPORT_MODEL` is empty. Metadata import and
manual editing continue if AI is unavailable. No model has authority to publish,
assign roles, fetch arbitrary URLs, or perform actions from website instructions.

Review facts and prices, choose a business photo and correct the menu link, confirm representation and
content rights, and choose **Submit for review**. The profile stays private until
the host approves business authority, name and address. **Check approval** refreshes
the status; **Continue to offers** then publishes through the owner's authenticated
request and opens offer management. See [Business approval](BUSINESS-APPROVAL.md)
for the local review command and migration inventory. Email verification and the
representation confirmation remain required. This public policy replaces the
instant activation enabled for team testing on September 27.

Previously pending applications retain their saved fields. Explicitly save the
profile to activate it; simply opening it does not publish anything. If the
profile cannot load, retry before editing so an empty form cannot overwrite it.
If saving succeeds but refreshing the session fails, **Open offer management**
retries the session refresh without submitting a second profile write.
Student accounts cannot use business draft or website import endpoints.

The server generates an actor-specific restaurant slug and records ownership in
the private onboarding store. Repeated saves update the same restaurant and
preserve its offers. Two businesses with identical names still have separate
owners. Existing `MLOCAL_MERCHANT_OWNERS` provisioning takes precedence and
continues to support demo merchants. Clients cannot submit an owner or restaurant
ID to the activation endpoint. The saved image URL is public profile media:
students see it on the deal, offer detail and public business page, and the
merchant sees it beside the restaurant name. Each offer can have its own photo.
An empty photo is valid; views provide a fallback.

Business owners use **Manage** to create offers and **Edit business details** to
open the account's business form. Name and address changes return to review;
routine edits remain self-service. The existing public identity and offer
management stay available while a proposed identity change waits. Host-configured
legacy merchants cannot change name/address through the older profile RPC.
**New offer** opens a form with explicit **Publish offer** action;
a future Ann Arbor start time schedules the offer. **Save changes** edits that
same offer. Paused offers remain paused, and existing claims retain their
promised price, terms and deadline. There is no server-side draft for the offer
form. New-offer drafts recover locally on refresh for the same business account
on that browser. Cancel, successful publication and sign-out clear the draft.
The owner-scoped publication key prevents equivalent retries from creating a
second offer. Rejected writes preserve the entered values and never report success.
Money supports at most two decimals, quantity is 1 to 10,000, and expiry must
be in the future. Times use Ann Arbor's Eastern timezone, including validation
of daylight-saving gaps and repeated hours.

## Existing demos and deployment

Before updating an already-provisioned demo, run in its actual runtime directory:

```bash
python3 scripts/enable-demo-students.py --state-dir .jac
source .jac/qr-demo.env
```

This appends explicit student root IDs from the existing private account file.
It never changes accounts, passwords, claims or merchant ownership. New provisioning
already writes this allowlist. Restart the server with that environment. Generic
runtime accounts cannot claim offers until verified or explicitly provisioned.

Only expose the compiled app and exact application RPCs through public ingress.
Add `request_email_code`, `verify_email_code`, `get_business_draft`,
`import_business_website`, `upload_business_photo`, `import_business_photo`,
`save_business_draft`, `get_business_profile`, `get_account_profile`, and
`save_account_profile` to the phone gateway allowlist.
Keep `/user/register`, arbitrary RPCs, graph/admin endpoints and private files
blocked. Apply `scripts/onboarding-ingress.mjs` using a trusted client IP from
your reverse proxy (never arbitrary `X-Forwarded-For` from a browser).

Private OTP/account/draft/business-ownership state is in `.jac/onboarding/`, or an absolute
`MLOCAL_ONBOARDING_DIR`. Preserve it together with the Jac identity database.
It contains personal data and a mode-0600 HMAC key; do not commit or expose it.
SQLite transactions serialize verification across processes on one host. This
implementation is for a single host, not independent replicas. A recovery journal
finishes interrupted account provisioning without taking over foreign accounts.

Codes expire after 10 minutes, have five guesses, are single-use, and are HMAC
digests at rest. Sending has a 60-second cooldown, five sends/address/hour, and
global spending caps. Ingress adds per-client limits. Drafts are read/saved only
under the authenticated request's actor. Website requests validate all DNS answers,
pin the chosen public IP while checking TLS for the hostname, bound response sizes,
and obey robots restrictions. The model sees source text as untrusted data.

## Verification commands

```bash
bash scripts/test.sh onboarding
bash scripts/python.sh -m unittest discover -s tests/integration -p test_onboarding_shared.py
bash scripts/check.sh
bash scripts/test.sh core
bash scripts/build.sh
node --test tests/ui/*.test.mjs tests/tooling/*.test.mjs
# Requires the existing jsdom test runtime and a compiled .jac/client/dist:
MLOCAL_UI_TEST_MODULES=/path/to/ui-test-runtime/node_modules node --test tests/ui/browser/*.test.mjs
```

`test_onboarding_shared.py` uses separate Linux processes against a fresh shared
local directory. It checks cold key/schema creation, single-use consumption,
resend and hourly sending budgets, and account/draft visibility after replacing
a process. A separate-directory negative control demonstrates why copying state
does not share new writes. Sender callbacks are disposable sinks: the fixture
does not prove SMTP, native HTTP/session behavior, or independent-host replication.
All seven checks passed in [CI at 634eb70](https://github.com/CosmonautJones/m-local/actions/runs/37415914169)
with no skips. The full run also passed the existing approval, recovery, build and
compiled UI checks; independent-host and actual inbox delivery gates remain open.

`bash scripts/test-shared-onboarding.sh` adds a disposable Linux proof with two
native Jac APIs, one private graph database and a common onboarding directory.
It delivers codes through a local TLS SMTP sink, then checks cross-API sign-in,
single-use codes, shared sending budgets, business approval/activation and draft
visibility after replacing an idle crashed API. The dedicated workflow runs this
fixture. Its [first native run](https://github.com/CosmonautJones/m-local/actions/runs/37419329648)
passed sign-in, approval and cross-API writes, then failed during replacement
startup. A small Linux socket reproduction showed the port probe rejected a
recently closed connection; it now uses address reuse, matching the existing
recovery verifier. The corrected full journey is pending execution.
The sink accepts only explicitly
allowed fictional recipients and never forwards email. This does not establish
real inbox delivery, public ingress, independent-host replication, cold seed
deduplication, browser capacity or safety during an in-flight crash.

`tests/integration/onboarding_http.py` exercises actual Jac identities/sessions
using locally injected test challenges. Run it only in a disposable workspace
named `onboarding-check`, with a local server at port 8240. It sends no email and
does not prove real inbox receipt. Real model extraction and physical phone
behavior need separate checks with configured services/devices.

`tests/integration/account_posts_http.py` checks account name edits, returning
sign-in, legacy pending-profile activation, separate business ownership, merchant
profile edits, self-service publication and claim redemption. It uses the same
isolated workspace name and port, requires local
demo provisioning plus a restart with `.jac/qr-demo.env`, and saves its private
receipt under `.jac/`. Restart and rerun with `--verify-restart` to verify
persistence. It sends no email and never runs against the shared phone demo.

### Implementation checkpoint

Verified on Windows/WSL with Jac 0.37.23: 26 Python onboarding/security/setup/migration
tests, 22 existing core Jac tests, one typed MockLLM extraction test, 18 compiled
browser tests, and 12 QR/scan/proxy tests. `jac check` and the sealed application
build passed (the existing project still emits warnings). The isolated HTTP test
proved actual runtime account/session creation, OTP replay rejection, student
claims, denied business claims, per-account draft isolation and denied anonymous
access. It did not send real mail, call a paid model, or test a physical phone.

### Live email checkpoint (September 26, 2026)

Resend is configured privately on the phone-demo host using a verified sending
domain and encrypted SMTP on port 587. A real U-M verification message showed
**Delivered** in Resend, its recipient supplied the code, and the live application
created an **Email verified** session that survived a page refresh. Travis then
confirmed successful login with two real U-M accounts. Addresses, codes, API keys,
and private account state are excluded from this record and from Git.

The repository remains unconfigured for fresh clones until a host runs sender
setup. This checkpoint proves live email signup; it does not certify physical
camera scanning or hosted AI extraction. Business approval was removed in the
September 27 self-service increment described above.
