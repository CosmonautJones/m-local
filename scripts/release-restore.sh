#!/usr/bin/env bash
# Restore only into an empty isolated database and empty private-state targets.
# Canonical entry/source/runtime must match; never drops a serving database.
set -euo pipefail
umask 077
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec python3 "$root/deploy/release/package.py" restore "$@"
