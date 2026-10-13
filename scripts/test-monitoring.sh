#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
export JAC_BIN
if [[ -n "${JAC_DB_URL:-}" || -n "${JAC_DEV_SOURCE:-}" || "$(id -u)" -eq 0 ]]; then
    echo 'Monitoring proof requires an unprivileged user, official runtime and its own disposable database.' >&2
    exit 2
fi
receipt=${1:-.jac/release-native/monitoring.json}
mkdir -p -- "$(dirname -- "$receipt")"
exec timeout --signal=TERM --kill-after=30s 900s bash scripts/python.sh -c \
    'import runpy,sys;sys.path.insert(0,"tests/integration");runpy.run_path("tests/integration/release_monitoring_http.py",run_name="__main__")' \
    --receipt "$receipt"
