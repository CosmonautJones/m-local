#!/usr/bin/env bash
# Real approval/HTTP/restart proof in a retained disposable app, without SMTP.
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
if [[ -n "${JAC_DB_URL:-}" ]]; then
    echo 'This test requires an isolated embedded database; unset JAC_DB_URL.' >&2
    exit 2
fi
bash scripts/python.sh -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",8252)); s.close()'
candidate="$(mktemp -d /var/tmp/m-local-release-approval.XXXXXXXX)"
tar --exclude=.git --exclude=.jac --exclude=node_modules --exclude=.venv --exclude=dist --exclude='.env*' -cf - . | tar -xf - -C "$candidate"
cd -- "$candidate"
source scripts/runtime.sh
export MLOCAL_ONBOARDING_DIR="$candidate/.jac/onboarding"
export MLOCAL_DEMO_MODE=0 MLOCAL_MERCHANT_OWNERS='{}' MLOCAL_DEMO_STUDENTS='[]'
server_pid=''
stop_server() {
    if [[ -n "$server_pid" ]]; then
        kill -TERM "$server_pid" 2>/dev/null || true
        for _ in {1..10}; do
            kill -0 "$server_pid" 2>/dev/null || break
            sleep 1
        done
        kill -KILL "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
        server_pid=''
    fi
}
trap stop_server EXIT
"$JAC_BIN" install > install.log 2>&1
start_server() {
    "$JAC_BIN" run --no-dev --no-client --host 127.0.0.1 --port 8252 < /dev/null > server.log 2>&1 &
    server_pid=$!
    for _ in {1..180}; do
        if ! kill -0 "$server_pid" 2>/dev/null; then
            echo "Test server failed; retained logs: $candidate" >&2
            tail -n 20 server.log >&2
            return 1
        fi
        if curl --silent --fail --max-time 2 -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8252/function/current_session > /dev/null; then return; fi
        sleep 1
    done
    echo "Test server did not become ready; retained logs: $candidate" >&2
    return 1
}
start_server
bash scripts/python.sh -c 'import runpy,sys; sys.path.insert(0,"tests/integration"); runpy.run_path("tests/integration/business_approval_http.py",run_name="__main__")'
stop_server
start_server
bash scripts/python.sh -c 'import runpy,sys; sys.path.insert(0,"tests/integration"); sys.argv=["business_approval_http.py","--verify-restart"]; runpy.run_path("tests/integration/business_approval_http.py",run_name="__main__")'
echo "Approval and restart checks passed. Retained disposable workspace: $candidate"
