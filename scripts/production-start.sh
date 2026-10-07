#!/usr/bin/env bash
# Supported source-server entry: validate preserved state before native auth can
# choose a signing store. The app import guard independently refuses unsafe use.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
bash scripts/python.sh -c 'from services.production_guard import exit_unless_production_ready; exit_unless_production_ready()'
# Source runtime established the canonical project cwd. An explicit .jac file
# triggers stock CLI web-app takeover and discards server flags; project mode
# is the supported invocation for production host/port/no-dev options.
exec "$JAC_BIN" run "$@"
