#!/usr/bin/env bash
# Source-only rollback at the unchanged canonical path, with every writer stopped.
# Does not restore or overwrite PostgreSQL, SQLite, keys, identities, or photos.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec python3 "$root/deploy/release/package.py" switch-source "$@"
