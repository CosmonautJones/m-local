#!/usr/bin/env bash
# All release tools run in WSL/Linux Bash. This performs no deployment.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec python3 "$root/deploy/release/package.py" create --source "$root" "$@"
