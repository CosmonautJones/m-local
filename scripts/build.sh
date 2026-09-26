#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
exec "$JAC_BIN" build
