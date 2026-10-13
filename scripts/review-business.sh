#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
cd -- "$PROJECT_ROOT"
exec "$JAC_BIN" run --backend python --no-serve scripts/review-business.jac "$@"
