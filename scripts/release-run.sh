#!/usr/bin/env bash
# Deliberate foreground runner. No auto-update, replicas, or raw public backend.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec python3 "$root/deploy/release/package.py" run "$@"
