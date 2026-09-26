#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
bridge_pid=''
cleanup() {
    [[ -z "$bridge_pid" ]] || kill "$bridge_pid" 2>/dev/null || true
}
trap cleanup EXIT
if [[ "$PROJECT_ROOT" == /mnt/* ]] && [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
    python3 scripts/watch-wsl.py "$PROJECT_ROOT" &
    bridge_pid=$!
fi
echo "M-Local / Jac $JAC_VERSION: open http://localhost:8000/ after Server ready. Ctrl+C stops."
"$JAC_BIN" run --dev --host 127.0.0.1 --port 8000
