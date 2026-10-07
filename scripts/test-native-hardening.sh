#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
export JAC_BIN
if [[ -z "${MLOCAL_HARDENING_DURABLE_BASE:-}" ]]; then
    echo 'Set MLOCAL_HARDENING_DURABLE_BASE to an existing mounted disposable-state base; no live state volume.' >&2
    exit 2
fi
if [[ -n "${JAC_DB_URL:-}" || -n "${JAC_DEV_SOURCE:-}" || "$(id -u)" -eq 0 ]]; then
    echo 'Native hardening requires an unprivileged Linux user, official runtime and its own disposable database.' >&2
    exit 2
fi
exec timeout --signal=TERM --kill-after=30s 1500s bash scripts/python.sh -c \
    'import runpy,sys;sys.path.insert(0,"tests/integration");runpy.run_path("tests/integration/native_hardening_http.py",run_name="__main__")' \
    --durable-base "$MLOCAL_HARDENING_DURABLE_BASE" "$@"
