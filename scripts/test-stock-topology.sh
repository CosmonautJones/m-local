#!/usr/bin/env bash
# Regression diagnostic; preserves original runtime binaries and private evidence.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
export JAC_BIN
if [[ -n "${JAC_DB_URL:-}" || -n "${JAC_DEV_SOURCE:-}" ]]; then
    echo 'Stock topology proof refuses inherited database/source override.' >&2
    exit 2
fi
exec timeout --signal=TERM --kill-after=30s 480s bash scripts/python.sh -c \
    'import runpy,sys; sys.path.insert(0,"tests/integration"); runpy.run_path("tests/integration/stock_topology_http.py",run_name="__main__")' "$@"
