#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
export JAC_BIN
if [[ -n "${JAC_DB_URL:-}" || -n "${JAC_DEV_SOURCE:-}" ]]; then
    echo 'Shared onboarding proof requires its own graph database and pinned runtime.' >&2
    exit 2
fi
if [[ "$(id -u)" -eq 0 ]]; then
    echo 'Shared onboarding proof must run as an unprivileged Linux user.' >&2
    exit 2
fi
exec timeout --signal=TERM --kill-after=30s 1200s bash scripts/python.sh -c \
    'import runpy,sys; sys.path.insert(0,"tests/integration"); runpy.run_path("tests/integration/shared_onboarding_http.py",run_name="__main__")'
