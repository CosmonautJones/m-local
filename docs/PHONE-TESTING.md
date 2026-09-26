# Run it on each computer, then test it on phones

The required product is a mobile web app. iPhone Safari and Android Chrome can
use it without Xcode, Android Studio, an app-store account or native packaging.
Native MobUI packaging remains optional and unverified.

**New team decision:** redemption will use a QR code, not typed letters/numbers.
The running baseline below still has the old entry flow. QR implementation belongs
to Engineers 2/4 under [contract v2](TEAM-CONTRACT.md#approved-qr-decision-2026-09-26).

## Each teammate's setup

| Computer | Shell for Jac | Setup route | Current evidence |
|---|---|---|---|
| Windows | Ubuntu/WSL Bash; PowerShell launcher after setup | `bash scripts/setup.sh`, then `bash scripts/dev.sh` | Executed on Travis's Windows/WSL x86_64 machine |
| Apple Silicon Mac | Terminal / Bash | Same scripts, auto-selecting macOS ARM64 assets | Official assets verified to exist; teammate execution pending |
| Intel Mac | Supported Linux x86_64 VM | Run the Linux setup inside that VM | No native Intel Mac asset in Jac 0.37.23; VM route untested here |

All teammates use **Jac 0.37.23** and the same integrated commit. Follow
[RUNTIME.md](RUNTIME.md), including the branch instruction until the runtime PR
is merged. Windows needs working WSL, not a Windows Python `pip install jaclang`.

Each human records this small check, not a screenshot of a generator's success message:

```text
Human / OS / architecture:
Git commit:
bash scripts/check.sh: exit code
bash scripts/test.sh core: 7 passed, or exact failure
bash scripts/build.sh: artifact path, or exact failure (dev stopped)
bash scripts/dev.sh: page loads and offers appear
Phone/browser: filter -> claim -> redeem result
```

Windows users can run Bash commands through:
`wsl -d Ubuntu --cd <repository-path> --exec bash scripts/check.sh`.
Use `git rev-parse --short HEAD` for the commit. Fix a shared issue once in the
repository and have the others pull it; do not maintain four private setup recipes.

## A phone on the same network

1. Start M-Local normally and verify **http://localhost:8000/** on the computer.
2. Open a second terminal **on the host computer**. For Windows, that means
   **PowerShell, not WSL**. For a Mac, use Terminal. With Node.js 22 or newer:

   ```text
   node scripts/phone-proxy.mjs --lan
   ```

3. The relay prints addresses such as `http://192.168.1.25:8080/`. Pick the
   computer's Wi-Fi address, not a VPN, Docker or WSL virtual adapter.
4. Connect the phone to that same trusted network and open that address in Safari
   or Chrome. **Do not enter localhost on the phone**; that means the phone itself.
5. Keep both terminals running. Stop the relay with Ctrl+C when finished.

The host relay forwards the page, Jac calls and Vite reload connection through
one port. This avoids Windows/WSL IP forwarding setup. It defaults to loopback
without `--lan` and does not change firewall rules. Only enable LAN sharing for
fictional demo data: the current app still uses demo identities/merchant keys.
The relay excludes the framework admin/graph/introspection endpoints; it is
development tooling, not a replacement for Engineer 2's authentication work.

If the phone cannot connect, check that the host URL works first, then check the
chosen Wi-Fi IP and the computer firewall's permission for Node on the intended
network. Venue Wi-Fi may isolate devices even when both show the same network
name. Try a personal hotspot or another trusted network if available. Do not
disable the firewall globally. A public HTTPS tunnel is a separate sharing
decision; none is opened by these scripts.

This HTTP route is enough for current offer browsing/claiming and for displaying
the planned QR. **Live camera scanning on a remote phone requires a secure origin.**
Use a merchant laptop at `localhost` for the first camera test, or a deliberately
configured HTTPS origin for merchant-phone scanning. Camera permission is still
required. See [MDN getUserMedia security requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia#privacy_and_security).
Do not claim the current plain-HTTP LAN relay proves phone-camera scanning.
Loading over LAN does not make offline claims work.

## Five-minute two-device check

Use fictional businesses and different test student IDs on each phone. On the
merchant computer choose the corresponding demo merchant.

1. Phone A filters to a budget and opens a valid offer; terms and access labels fit.
2. Phone A claims it and shows its QR. Merchant scans, checks the terms and confirms.
3. Merchant scans again; the second redemption must be refused.
4. Reload and restart the app with the same store; the redeemed status must remain.
5. Phone B must not be able to impersonate Phone A once the identity mission lands.
   The baseline's name field does **not** satisfy that check.

Engineer 4 records tap behavior, keyboard overlap, errors and rotation in
`docs/phone-validation.md`. Engineer 1 records host/commit/versions. A desktop
390px viewport check is useful but does not count as a physical iPhone Safari run.

## Team verification board

| Check | Travis Windows/WSL | Mac teammate | Windows teammate | Fourth teammate |
|---|---|---|---|---|
| Jac 0.37.23 | Verified | Pending | Pending | Pending |
| Core Jac tests | 7 passed | Pending | Pending | Pending |
| Production bundle | Built `.jab` | Pending | Pending | Pending |
| Browser workflow | Local discovery/claim/redemption exercised | Pending | Pending | Pending |
| Physical phone on LAN | Pending | Pending | Pending | Pending |

Update this table only from an actual run. See the detailed evidence in
[Engineer 1 status](status/engineer-1.md).
