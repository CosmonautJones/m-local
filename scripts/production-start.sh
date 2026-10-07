#!/usr/bin/env bash
# Supported source-server entry: validate preserved state before native auth can
# choose a signing store. The app import guard independently refuses unsafe use.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
bash scripts/python.sh -c 'from services.production_guard import exit_unless_production_ready; exit_unless_production_ready()'
exec "$JAC_BIN" run "$PROJECT_ROOT/main.jac" "$@"
