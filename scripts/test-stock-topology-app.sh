#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
export JAC_BIN
if [[ -n "${JAC_DB_URL:-}" || -n "${JAC_DEV_SOURCE:-}" ]]; then
    echo 'Stock topology proof refuses inherited DB/source override.' >&2
    exit 2
fi
exec timeout --signal=TERM --kill-after=30s 900s bash scripts/python.sh -c \
    'import runpy,sys; sys.path.insert(0,"tests/integration"); runpy.run_path("tests/integration/stock_topology_app_http.py",run_name="__main__")' "$@"
