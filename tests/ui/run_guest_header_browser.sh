#!/usr/bin/env bash
# Compile an allowlisted snapshot and render synthetic guest UI; never serve Jac.
set -euo pipefail
umask 077

[[ "$(uname -s)/$(uname -m)" == Linux/x86_64 && "$(id -u)" -ne 0 ]] || {
  echo 'Use an unprivileged Linux x86_64 user.' >&2; exit 2;
}
[[ -z "${JAC_DB_URL:-}" && -z "${JAC_DATA_PATH:-}" && -z "${JAC_DEV_SOURCE:-}" && -z "${JACPATH:-}" ]] || {
  echo 'Remove inherited database and Jac source overrides.' >&2; exit 2;
}
repo=${1:?source checkout required}
evidence=${2:?new absolute evidence directory required}
expected_head=${3:?exact source commit required}
base_sha=${4:-}
[[ "$repo" == /* && "$evidence" == /* && ! -e "$evidence" && "$expected_head" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ -z "$base_sha" || "$base_sha" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ -n "${HOME:-}" && -n "${PATH:-}" ]] || exit 2
repo=$(realpath -e -- "$repo")
evidence=$(realpath -m -- "$evidence")
[[ -d "$repo" && ! -e "$evidence" ]] || exit 2
case "$evidence/" in "$repo/"*) echo 'Evidence must be outside the checkout.' >&2; exit 2 ;; esac
task_root=$(mktemp -d /var/tmp/m-local-guest-header.XXXXXXXX)
mkdir -m 700 -- "$task_root/app" "$task_root/toolchain" "$task_root/tools" "$task_root/proof-binding" "$task_root/cache" "$task_root/config" "$task_root/data" "$task_root/state" "$task_root/tmp" "$task_root/unused-pg-dist"

# Preserve the user's real HOME. All configurable tool/cache locations are private.
env -i HOME="$HOME" PATH="$task_root/toolchain/bun/bin:$PATH" USER="$(id -un)" LOGNAME="$(id -un)" \
  LANG=C.UTF-8 LC_ALL=C.UTF-8 TMPDIR="$task_root/tmp" TMP="$task_root/tmp" TEMP="$task_root/tmp" \
  XDG_CACHE_HOME="$task_root/cache" XDG_CONFIG_HOME="$task_root/config" XDG_DATA_HOME="$task_root/data" XDG_STATE_HOME="$task_root/state" \
  CURL_HOME="$task_root/config" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_ATTR_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 GIT_NO_LAZY_FETCH=1 \
  JAC_BIN="$task_root/toolchain/jac" JAC_CACHE_HOME="$task_root/cache/jac" JAC_PG_DIST="$task_root/unused-pg-dist" \
  JAC_PRECOMPILE_JOBS=2 JAC_PRECOMPILE_RECYCLE_MB=1024 JAC_NO_DEV_SOURCE=1 MLOCAL_ENV=development \
  UV_NO_CONFIG=1 UV_CACHE_DIR="$task_root/cache/uv" UV_PYTHON_INSTALL_DIR="$task_root/toolchain/uv-python" UV_TOOL_DIR="$task_root/toolchain/uv-tools" \
  PIP_CONFIG_FILE=/dev/null PIP_CACHE_DIR="$task_root/cache/pip" PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1 \
  PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
  npm_config_cache="$task_root/cache/npm" npm_config_userconfig="$task_root/config/npmrc" npm_config_globalconfig="$task_root/config/npm-globalrc" npm_config_prefix="$task_root/toolchain/npm" \
  BUN_INSTALL="$task_root/toolchain/bun" BUN_INSTALL_CACHE_DIR="$task_root/cache/bun" BUN_TMPDIR="$task_root/tmp" \
  PLAYWRIGHT_BROWSERS_PATH="$task_root/cache/browsers" \
  PROOF_RUN_ID="${GITHUB_RUN_ID:-}" PROOF_RUN_ATTEMPT="${GITHUB_RUN_ATTEMPT:-}" PROOF_REPOSITORY="${GITHUB_REPOSITORY:-}" \
  PROOF_HEAD_REPOSITORY="${PR_HEAD_REPOSITORY:-}" PROOF_WORKFLOW_SHA="${PROOF_WORKFLOW_SHA:-}" PROOF_WORKFLOW_REF="${PROOF_WORKFLOW_REF:-}" PROOF_EVENT_SHA="${GITHUB_SHA:-}" \
  bash --noprofile --norc -euo pipefail -s -- "$repo" "$evidence" "$expected_head" "$base_sha" "$task_root" <<'RUNNER'
repo=$1 evidence=$2 expected_head=$3 base_sha=$4 task_root=$5
app="$task_root/app"
binding="$task_root/proof-binding/compile-source-binding.json"
touch "$npm_config_userconfig" "$npm_config_globalconfig"

# The snapshot contains no data, research, photos, environment files or Git state.
cat > "$task_root/tools/bind_source.py" <<'PY'
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

mode, repo_arg, app_arg, evidence_arg, expected, base = sys.argv[1:]
repo, app, evidence = map(lambda value: Path(value).resolve(), (repo_arg, app_arg, evidence_arg))
binding_path = evidence / "compile-source-binding.json"
if app.is_relative_to(repo) or evidence.is_relative_to(repo) or evidence.is_relative_to(app):
    raise SystemExit("Snapshot and evidence must be outside the checkout and separate.")

def git(*args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(repo), *args])

head = git("rev-parse", "--verify", "HEAD").decode().strip()
tree = git("rev-parse", "--verify", "HEAD^{tree}").decode().strip()
if head != expected or Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() != repo:
    raise SystemExit("Checkout differs from the requested exact source.")

roots = {".jac-version", "jac.toml", "main.jac", "theme.jac"}
wrappers = {f"scripts/{name}.sh" for name in ("runtime", "check", "build", "python")}
producers = {"tests/ui/guest_header_browser.py", "tests/ui/run_guest_header_browser.sh", ".github/workflows/guest-header-proof.yml"}
required = roots | wrappers | producers | {"assets/manifest.webmanifest"}
extensions = (".jac", ".py", ".pyi", ".jsx", ".mjs", ".js", ".ts", ".tsx", ".css", ".json")

def selected(name):
    return name in required or name.startswith("assets/brand/") or (
        name.startswith(("client/", "services/")) and name.endswith(extensions))

def safe_file(root, name):
    parts = Path(name).parts
    if any(part in {".git", ".jac", ".venv", "node_modules", "research", "photos"} or part.startswith(".env")
           or part.endswith((".pem", ".p12", ".key")) for part in parts):
        raise SystemExit("Disallowed path in source allowlist.")
    path = root / name
    if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.resolve().is_relative_to(root) or not path.is_file():
        raise SystemExit("Allowlisted source must be a contained regular file.")
    return path

inputs = {}
research_blobs = set()
research_count = 0
for item in git("ls-tree", "-rz", "--full-tree", "HEAD").split(b"\0"):
    if not item:
        continue
    metadata, raw_name = item.split(b"\t", 1)
    name = raw_name.decode("utf-8")
    file_mode, kind, oid = metadata.decode().split()
    if name.startswith("data/research/") and kind == "blob":
        research_count += 1
        research_blobs.add(oid)
    if not selected(name):
        continue
    if kind != "blob" or file_mode not in {"100644", "100755"}:
        raise SystemExit("Source allowlist contains a symlink or unsupported entry.")
    path = safe_file(repo, name)
    raw = path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != oid:
        raise SystemExit("Raw checkout bytes differ from HEAD blobs; use an exact LF source snapshot.")
    inputs[name] = {"git_blob_sha1": oid, "sha256": hashlib.sha256(raw).hexdigest()}
    if mode == "before":
        target = app / name if name not in producers else app.parent / "tools" / Path(name).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(0o600)
    elif name not in producers and hashlib.sha256(safe_file(app, name).read_bytes()).hexdigest() != inputs[name]["sha256"]:
        raise SystemExit("Snapshot source changed during proof.")
    elif name in producers and hashlib.sha256((app.parent / "tools" / Path(name).name).read_bytes()).hexdigest() != inputs[name]["sha256"]:
        raise SystemExit("Proof producer changed during proof.")

# Metadata-only enumeration of objects already present; no cat-file blob reads
# and no lazy fetch. This wrapper is for a fresh, sparse partial CI checkout.
local_objects = set(git("cat-file", "--batch-all-objects", "--batch-check=%(objectname)").decode().splitlines())
research_present = len(research_blobs & local_objects)
if research_present:
    raise SystemExit("Research payload objects are already present; use a fresh sparse CI checkout.")

if not required.issubset(inputs) or not any(name.startswith("client/") for name in inputs) or not any(name.startswith("services/") for name in inputs):
    raise SystemExit("Required source or proof producer is absent from HEAD.")
if mode != "before":
    observed = {name for name in roots if (app / name).is_file()}
    for path in app.iterdir():
        if path.is_file() and path.name.endswith(extensions) and path.name not in roots | {"package.json", "package-lock.json"}:
            raise SystemExit("Unexpected root source file appeared during proof.")
    for directory in ("client", "services", "assets/brand", "scripts"):
        for path in (app / directory).rglob("*"):
            name = path.relative_to(app).as_posix()
            if path.is_symlink():
                raise SystemExit("Snapshot source gained a symlink during proof.")
            if path.is_file():
                safe_file(app, name)
                observed.add(name)
    if (app / "assets/manifest.webmanifest").is_file():
        observed.add("assets/manifest.webmanifest")
    if observed != set(inputs) - producers or (app / "data").exists() or (app / "assets/photos").exists():
        raise SystemExit("Snapshot source-path allowlist changed during proof.")
if (app / ".jac-version").read_text().strip() != "0.37.23":
    raise SystemExit("Candidate Jac pin differs from 0.37.23.")
if mode == "before":
    record = {"schema": 1, "source_commit": head, "source_tree": tree, "base_commit": base or None,
              "inputs": inputs, "compiled_files_sha256": {}, "inputs_unchanged_after": False,
              "research_payloads": {"excluded_file_count": research_count, "local_payload_objects_present": research_present},
              "producer_run": {"repository": os.environ.get("PROOF_REPOSITORY") or None,
                               "head_repository": os.environ.get("PROOF_HEAD_REPOSITORY") or None,
                               "run_id": os.environ.get("PROOF_RUN_ID") or None,
                               "attempt": os.environ.get("PROOF_RUN_ATTEMPT") or None,
                               "workflow_sha": os.environ.get("PROOF_WORKFLOW_SHA") or None,
                               "workflow_ref": os.environ.get("PROOF_WORKFLOW_REF") or None,
                               "event_sha": os.environ.get("PROOF_EVENT_SHA") or None},
              "official_runtime_sha256": {
                  "jac": "2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad",
                  "jacpython": "198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542"}}
else:
    record = json.loads(binding_path.read_text())
    if record["source_commit"] != head or record["source_tree"] != tree or record["inputs"] != inputs:
        raise SystemExit("Source binding changed during proof.")
    if record["research_payloads"] != {"excluded_file_count": research_count, "local_payload_objects_present": research_present}:
        raise SystemExit("Research exclusion metadata changed during proof.")

def compiled_files():
    result = {}
    for directory in (app / ".jac/client/dist",):
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if path.is_symlink() or not path.resolve().is_relative_to(app):
                    raise SystemExit("Compiled output must stay inside the snapshot.")
                if path.is_file():
                    result[path.relative_to(app).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result

if mode == "compiled" or (mode == "after" and record["compiled_files_sha256"]):
    for name, digest in record["official_runtime_sha256"].items():
        if hashlib.sha256((app.parent / "toolchain" / name).read_bytes()).hexdigest() != digest:
            raise SystemExit("Official runtime bytes changed during proof.")

if mode == "compiled":
    compiled = compiled_files()
    if not compiled or not any(Path(name).name.startswith("client.") and name.endswith(".js") for name in compiled):
        raise SystemExit("Compiled client output is absent.")
    record["compiled_files_sha256"] = compiled
elif mode == "after":
    if record["compiled_files_sha256"] and compiled_files() != record["compiled_files_sha256"]:
        raise SystemExit("Compiled output changed during browser proof.")
    record["inputs_unchanged_after"] = True
elif mode != "before":
    raise SystemExit("Unknown binding stage.")
binding_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
PY

bind_source() { python3 "$task_root/tools/bind_source.py" "$1" "$repo" "$app" "$task_root/proof-binding" "$expected_head" "$base_sha"; }
finish() {
  result=$?
  trap - EXIT
  if [[ -f "$binding" ]]; then bind_source after || result=1; fi
  if [[ -e "$app/.jac/data" || -n "$(find "$JAC_PG_DIST" -mindepth 1 -print -quit)" ]]; then
    echo 'Compile-only proof unexpectedly created native state.' >&2
    result=1
  fi
  if [[ -f "$binding" ]]; then
    mkdir -p -m 700 -- "$evidence"
    cp -- "$binding" "$evidence/compile-source-binding.json" || result=1
  fi
  python3 - "$evidence" "$result" <<'PY' || result=1
import hashlib
import json
import sys
from pathlib import Path
evidence, result = Path(sys.argv[1]), int(sys.argv[2])
receipt_path = evidence / "receipt.json"
if receipt_path.is_file():
    receipt = json.loads(receipt_path.read_text())
    receipt["wrapper_status"] = "passed" if result == 0 else "failed"
    receipt["wrapper_exit_code"] = result
    if result:
        receipt["status"] = "failed"
        receipt["passing_claim"] = False
    binding_path = evidence / "compile-source-binding.json"
    if binding_path.is_file():
        binding = json.loads(binding_path.read_text())
        receipt["compile_binding"] = {"file": binding_path.name, "sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
                                      "source_commit": binding["source_commit"], "source_tree": binding["source_tree"],
                                      "compiled_files_sha256": binding["compiled_files_sha256"]}
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
PY
  echo "Retained private workspace: $task_root"
  echo "Evidence directory: $evidence"
  exit "$result"
}
trap finish EXIT
bind_source before
[[ "$(node --version)" == v22.* ]] || { echo 'Node 22 is required.' >&2; exit 2; }

# Official v0.37.23 Linux x86_64 asset SHA256 values from the published release.
# https://github.com/jaseci-labs/jac/releases/tag/v0.37.23
for entry in \
  'jac|jac-0.37.23-linux-x86_64|2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad' \
  'jacpython|jac-0.37.23-linux-x86_64-jacpython|198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542'; do
  IFS='|' read -r target asset digest <<< "$entry"
  curl -q --fail --location --retry 2 --connect-timeout 20 --max-time 180 --proto '=https' --tlsv1.2 \
    "https://github.com/jaseci-labs/jac/releases/download/v0.37.23/$asset" -o "$task_root/toolchain/$target"
  printf '%s  %s\n' "$digest" "$task_root/toolchain/$target" | sha256sum --check --status
  chmod 700 "$task_root/toolchain/$target"
done
cd -- "$app"
source scripts/runtime.sh
"$JAC_BIN" install --no-npm
bash scripts/check.sh
bash scripts/build.sh
[[ ! -e "$app/.jac/data" && -z "$(find "$JAC_PG_DIST" -mindepth 1 -print -quit)" ]] || {
  echo 'Compile-only proof unexpectedly created native state.' >&2; exit 1;
}
bind_source compiled

# Normal Python drives the synthetic browser fixture; it does not import Jac.
python3 -m venv "$task_root/toolchain/browser-venv"
browser_python="$task_root/toolchain/browser-venv/bin/python"
"$browser_python" -m pip install playwright==1.56.0
"$browser_python" -m playwright install chromium
"$browser_python" "$task_root/tools/guest_header_browser.py" \
  --app-root "$app" --evidence "$evidence" --source-commit "$expected_head"
bind_source after
"$browser_python" - "$evidence" "$binding" <<'PY'
import json
import sys
from pathlib import Path
evidence = Path(sys.argv[1])
binding = json.loads(Path(sys.argv[2]).read_text())
receipt_path = evidence / "receipt.json"
receipt = json.loads(receipt_path.read_text())
if (receipt.get("status") != "passed" or receipt.get("passing_claim") is not True
        or receipt.get("source_commit") != binding["source_commit"]
        or binding.get("inputs_unchanged_after") is not True):
    raise SystemExit("Browser verdict or exact-source verification did not pass.")
PY
RUNNER
