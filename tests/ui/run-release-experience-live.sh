#!/usr/bin/env bash
# Freeze a commit before disposable native/browser acceptance; no shared stores.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
candidate="${1:-$(git -C "$repo" rev-parse HEAD)}"
evidence="${2:-$repo/.jac/release-experience-evidence}"
base_port="${3:-18920}"
if [[ -n "${JAC_DB_URL:-}" || -n "${JAC_DEV_SOURCE:-}" || "$(id -u)" -eq 0 ]]; then
  echo 'Use an unprivileged Linux user without inherited graph/source overrides.' >&2
  exit 2
fi
source "$repo/scripts/runtime.sh"
export JAC_BIN
fixture_root=$(mktemp -d /var/tmp/m-local-browser-runner.XXXXXXXX)
mkdir -m 700 "$fixture_root/source" "$fixture_root/cache" "$fixture_root/node"
git -C "$repo" archive "$candidate" | tar -x -C "$fixture_root/source"
# The harness is explicit additional evidence input when reviewing an older
# candidate. Its copied bytes are hashed separately by the Python fixture.
cp "$repo/tests/ui/release_experience_live.py" "$fixture_root/source/tests/ui/release_experience_live.py"
cp "$repo/tests/ui/release_sample_fixture.jac" "$fixture_root/source/tests/ui/release_sample_fixture.jac"
cd "$fixture_root/source"
export JAC_CACHE_HOME="$fixture_root/cache"
unset PYTHONPATH
"$JAC_BIN" install --no-npm
python="$fixture_root/source/.jac/venv/bin/python"
"$python" -m pip install -r "$repo/tests/ui/browser-requirements.txt"
"$python" -m playwright install chromium
npm install --prefix "$fixture_root/node" --no-audit --no-fund axe-core@4.10.3
browser_packages=$("$python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
export PYTHONPATH="$browser_packages"
exec bash scripts/python.sh -c 'import runpy,sys; script=sys.argv.pop(1); sys.argv[0]=script; runpy.run_path(script,run_name="__main__")' \
  "$fixture_root/source/tests/ui/release_experience_live.py" --source "$fixture_root/source" --source-ref "$candidate" \
  --gateway-repo "$repo" --gateway-ref "$candidate" --evidence "$evidence" --base-port "$base_port" \
  --axe "$fixture_root/node/node_modules/axe-core/axe.min.js"
