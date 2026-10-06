#!/usr/bin/env bash
set -euo pipefail

# Bounded local recovery rehearsal. The Python fixture retains its private
# workspace and performs all process/database cleanup in finally blocks.
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
export JAC_BIN

if [[ -n "${JAC_DB_URL:-}" ]]; then
    echo 'Recovery rehearsal requires its private embedded PostgreSQL; unset JAC_DB_URL.' >&2
    exit 2
fi

if [[ "$(id -u)" -eq 0 ]]; then
    echo 'Recovery rehearsal must run as the unprivileged workspace user.' >&2
    exit 2
fi

# Python handles TERM and stops every owned process/private PostgreSQL cluster;
# a final KILL after this bound can only leave the retained private diagnosis state.
bash scripts/python.sh -c 'import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("127.0.0.1", 8252)); s.close()'

exec timeout --signal=TERM --kill-after=30s 1200s \
    env -u JAC_DB_URL bash scripts/python.sh tests/integration/recovery_http.py
