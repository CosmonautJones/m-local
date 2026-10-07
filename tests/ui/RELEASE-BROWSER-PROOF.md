This fixture is verification infrastructure. Its complete acceptance run has
**not yet passed**. The implementation at `b4bc6d0` passed source/build checks,
145 compiled browser tests,16 UI node tests and189 focused Jac executions.
Those synthetic checks do not substitute for this native proof.

Run in unprivileged WSL Bash or Ubuntu with the official pinned Jac0.37.23
wrappers, Node/npm, OpenSSL and Chromium's Linux system libraries:

```bash
bash scripts/setup.sh
bash tests/ui/run-release-experience-live.sh <candidate-sha> <absolute-new-evidence-directory> 18920
```

The runner archives the requested commit, installs application dependencies in
the private snapshot, installs pinned Playwright1.56.0 and axe-core4.10.3 in
disposable directories, and uses actual native HTTP plus the committed strict
gateway. It never deploys, sends real email, resets shared stores or changes the
source checkout. `--source`, `--source-ref` and `--gateway-ref` allow an explicitly
bound combined candidate. `source_ref` is informational; the receipt binds the
actual copied application/helper/gateway bytes independently with SHA256.

The allowlisted local TLS SMTP fixture verifies sign-in, selected public-offer
intent, reload and availability changes. Real browser checks include guest
feed/profile/detail,320/390px layout and keyboard focus, axe WCAG A/AA,44px
controls, local QR image preview/explicit confirmation, held-claim refresh,
manifest/icons and CSP. After quiescing owned writers, the same isolated app
restarts with samples explicitly disabled while demo/hosted flags are enabled.
HTTP checks cover sample parents with unmarked children, marked child offers,
feeds, direct detail/claim, public profiles and favorite reads/writes.

Private credentials and QR images remain in the mode0700 disposable workspace;
review screenshots are taken before sign-in. Preserve each evidence directory.
An exception is a failed proof even if earlier individual assertions passed.
The receipt's `phase` and completed check list explain partial progress.

Observed partial native receipt: `live-v4` passed three guest/profile assertions,
then the helper's stale Back locator failed. The locator was corrected to the
existing `Back to offer` control. Earlier fixture dependency-path isolation was
also corrected. WSL intermittently returns `Wsl/Service/0x8007274c`; a fresh
combined run is pending.44px/axe and later account/QR/sample assertions are not
certified. No timeout, authority rule or acceptance criterion was weakened.
