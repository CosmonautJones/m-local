#!/usr/bin/env bash
# Complete quiesced recovery set. Operator must close ingress and stop every writer.
set -euo pipefail
umask 077
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec python3 "$root/deploy/release/package.py" backup "$@"
