# Local development on Jac 0.37.23

The shared runtime pin is **0.37.23**, the latest stable official release checked
on September 26, 2026. JacHammer is not needed to compile or serve this checkout.
Use the same pin for every team member; do not independently upgrade during the event.

## Start on Travis's prepared Windows machine

From this repository in **PowerShell**:

```powershell
.\scripts\dev.ps1
```

Or, from the repository in **WSL Bash**:

```bash
bash scripts/dev.sh
```

Open **http://localhost:8000/** after the terminal reports Vite and Server ready.
The API uses 127.0.0.1:8001. Keep the terminal running; Ctrl+C stops development.
Use `localhost`, not `127.0.0.1`, for the browser on this Windows/WSL setup:
Jac's Vite child binds an IPv6 wildcard and Windows forwards it differently.
The API host flag does not constrain Vite's bind address in this Jac release.
No public tunnel or Windows firewall/port-forwarding rule is part of this setup.

Edit `.jac` source in your normal Windows editor. `dev.sh` adds a small content-hash
poller on Windows-mounted WSL paths; it emits Linux file-change events without
rewriting source contents. Jac then recompiles and Vite refreshes the browser.
Rebuilds can take tens of seconds on `/mnt/c`; wait for completion before testing.
If multiple saves produce `Sources changed during preparation`, save once more
after compilation settles or restart. Restart when adding/removing modules or
changing dependencies. A checkout inside WSL's Linux filesystem is faster and
uses the ordinary Jac watcher without this bridge.

## New teammate setup

Prerequisites: Windows with Ubuntu/WSL, Linux, or an Apple Silicon Mac; Bash,
curl, and SHA-256 tooling (`sha256sum` on Linux, built-in `shasum` on Mac).
Python 3 is used only for the Windows-save bridge. Internet access is
needed on the first launch for frontend packages and embedded PostgreSQL binaries.

```bash
git clone https://github.com/CosmonautJones/m-local.git
cd m-local
# Check out the runtime PR branch until it is merged.
git checkout feat/01-runtime-release
bash scripts/setup.sh
bash scripts/dev.sh
```

Run the same Bash commands from **Terminal on an Apple Silicon Mac**. On Windows,
run setup inside **Ubuntu/WSL**, not Git Bash. Native Windows binaries are not
included in this release. `uname -m` reports `arm64` on an Apple Silicon Mac;
an Intel Mac reports `x86_64` and needs a supported Linux VM or another host.

`setup.sh` downloads the official Jac executable and its `jacpython` companion,
verifies publisher SHA-256 files, and installs only under
`~/.local/share/m-local/runtimes/0.37.23/`. It does not replace another project's
runtime. It selects official Linux x86_64, Linux ARM64 or macOS ARM64 assets from
the [official release](https://github.com/jaseci-labs/jac/releases/tag/v0.37.23).
Only Windows/WSL x86_64 was executed here; the Mac/Linux ARM paths still need an
actual teammate run. Do not mark all four machines verified from one laptop's result.
The shell installer requires working Linux DNS; the equivalent release downloads
were performed through Windows on Travis's machine because WSL DNS failed.

The underlying command is:

```bash
jac run --dev --host 127.0.0.1 --port 8000
```

Do not use the exported `jac start` instructions or add `--backend python` to the
web-server command. Current Jac ships its own Python runtime and Bun. A separate
Python Jac package or JacHammer subscription is not required by this application.

## Checks and isolated tests

```bash
bash scripts/check.sh
bash scripts/test.sh core
bash scripts/build.sh
```

Stop the dev server before `build.sh`; both commands generate files under `.jac/client`.
The build produces `dist/mobile-starter.jab`, a Jac app bundle containing the web
client and server. A successful build is separate from successfully serving that
artifact. Development uses the source and `dev.sh`, not the bundle.

`check.sh` checks the whole project, including imported modules. Warnings still exist;
passing compilation is not a promise that all generated code is polished.
`test.sh core` copies source/configuration into a fresh path under
`~/.cache/m-local/test-runs/`. Jac derives a separate application store from that
path. Test workspaces and their stores are retained for diagnosis; the live demo
store is not reset. Never run the old `jac clean --data --force` instruction on
your shared demo. `context`, `integration`, and `all` return nonzero until those
team suites exist. `demo.sh` and authenticated account provisioning remain future
integration work, not completed features of this runtime checkpoint.

## Windows-network fallback used on this machine

This is only needed if WSL cannot resolve GitHub/npm while Windows can. Normal
Linux dependency installation is preferable. Do not mix Windows and Linux
native packages without the explicit Linux target below.

1. Let the first `dev.sh` invocation generate `.jac/client/configs/package.json`,
   then stop it if dependency downloads hang.
2. From the repository in **PowerShell**, install Linux-targeted packages:

```powershell
Copy-Item .jac/client/configs/package.json .jac/client/package.json
Push-Location .jac/client
try {
    npm.cmd install --ignore-scripts --os=linux --cpu=x64 --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    npm.cmd ls --depth=0
    if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed' }
} finally { Pop-Location }
$manifestHash = (Get-FileHash .jac/client/configs/package.json -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText((Join-Path $PWD '.jac/client/node_modules/.jac-deps-hash'), $manifestHash)
```

3. In **WSL Bash**, replace npm's Windows shell shim with Vite's Linux entry link:

```bash
ln -sf ../vite/bin/vite.js .jac/client/node_modules/.bin/vite
bash scripts/dev.sh
```

Without step 3, Bun tries to parse the shell wrapper as JavaScript and Vite exits.
Only write the dependency hash after successful installation and validation.
These files are generated and ignored by Git; repeat after dependency changes.
The first production build regenerated the package manifest with current Jac's
type packages. Its first dependency download also hit WSL DNS; applying the same
fallback to that regenerated manifest made the actual `.jab` build pass.

PostgreSQL downloads also require DNS. `runtime.sh` can reuse the already installed
18.6.0 distribution in `~/.cache/jac/pg/dist/linux-amd64-18.6.0` through
`JAC_PG_DIST`. `JAC_CACHE_HOME` defaults to `~/.cache/m-local`, keeping M-Local's
cluster/data separate from the learning lab. On another machine, either let Jac
download its database binaries or explicitly supply a compatible `JAC_PG_DIST`.
The current Jac graph persistence is embedded PostgreSQL, not the old README's SQLite.

## Versions and documentation evidence

| Component | Verified version |
|---|---|
| Project runtime and Travis's user CLI | Jac 0.37.23 |
| Bundled Bun | 1.3.11 |
| Vite | 6.4.3 |
| React / React DOM | 18.3.1 |
| React Native Web | 0.19.13 |
| Embedded PostgreSQL binaries | 18.6.0 |
| Windows npm used for fallback | 10.9.3 |

Linux x86_64 release checksums verified before execution:

```text
jac:       2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad
jacpython: 198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542
```

The compiler's real stdio MCP server was initialized, listed 19 tools, and served
`get_resource` calls for `jac-core-cheatsheet`, `jac-types`, `jac-config`,
`jac-codespaces`, and `jac-arch-wiring`. Teammates can use `jac mcp --transport stdio`
or read the same version-matched guides with `jac guide <name>`.
MCP access is verified; this is not a claim to have memorized all documentation.

The older 0.37.21 learning lab stays pinned and separate. The old user CLI was
backed up as `~/.local/bin/jac-0.37.18`. JacHammer's hosted runtime remains under
JacHammer's control; this change upgrades the local CLI and repository target.

## Migration scope

The user authorized updating the runtimes to latest. Compatibility edits remove
the retired outer `cl` block and duplicate `sv` import, use the extensionless
entry point, and annotate generic dict/tuple/list types required by current Jac.
Unused hosted-model configuration was removed; matching still uses Jac rules.
These small edits cross the source owners' files and must be carried into their
branches. No merchant ownership or reservation rules were redesigned here.

See [runtime verification](status/engineer-1.md) for actual results and gaps.
See [phone and teammate testing](PHONE-TESTING.md) for LAN access and the four-machine checklist.
Real authentication, concurrent-claim guarantees, native mobile builds and a
physical iPhone Safari run remain separate work. Keep fictional offers labeled DEMO.
