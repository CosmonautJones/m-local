#!/usr/bin/env bash
# Source this file; all commands operate on this checkout, regardless of cwd.
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$PROJECT_ROOT"
JAC_VERSION="$(tr -d '\r\n' < .jac-version)"
JAC_BIN="${JAC_BIN:-$HOME/.local/share/m-local/runtimes/$JAC_VERSION/jac}"
if [[ ! -x "$JAC_BIN" ]]; then
    echo "Jac $JAC_VERSION is missing at $JAC_BIN. Run bash scripts/setup.sh or set JAC_BIN. See docs/RUNTIME.md." >&2
    exit 2
fi
actual_version="$("$JAC_BIN" --version)"
read -r version_label version_number version_platform <<< "$actual_version"
if [[ "$version_label" != jac || "$version_number" != "$JAC_VERSION" ]]; then
    echo "Expected Jac $JAC_VERSION; got: $actual_version. Set JAC_BIN to the pinned executable." >&2
    exit 2
fi
export JAC_CACHE_HOME="${JAC_CACHE_HOME:-$HOME/.cache/m-local}"
# Reuse downloaded binaries, never the other application's database directory.
if [[ -z "${JAC_PG_DIST:-}" && -x "$HOME/.cache/jac/pg/dist/linux-amd64-18.6.0/bin/postgres" ]]; then
    export JAC_PG_DIST="$HOME/.cache/jac/pg/dist/linux-amd64-18.6.0"
fi
export PYTHONUNBUFFERED=1
