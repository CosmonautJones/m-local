#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
export JAC_PRECOMPILE_JOBS="${JAC_PRECOMPILE_JOBS:-2}"
export JAC_PRECOMPILE_RECYCLE_MB="${JAC_PRECOMPILE_RECYCLE_MB:-1024}"
exec "$JAC_BIN" build
