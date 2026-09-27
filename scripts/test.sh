#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
suite="${1:-core}"
case "$suite" in
    core|context|all) ;;
    onboarding) python3 -m unittest discover -s tests/onboarding; exit $? ;;
    integration)
        node --test tests/ui/*.test.mjs tests/tooling/*.test.mjs
        accounts="$PROJECT_ROOT/.jac/qr-demo-accounts.json"
        if [[ ! -f "$accounts" ]]; then
            echo 'Integration accounts are missing. Run the local provisioning command first; no fixture success is substituted.' >&2
            exit 2
        fi
        python3 tests/integration/qr_http.py --api "${MLOCAL_API_URL:-http://localhost:8001}" --accounts "$accounts"
        python3 tests/integration/test_admin_approval.py
        exit 0 ;;
    *) echo 'Usage: scripts/test.sh core|context|integration|onboarding|all' >&2; exit 2 ;;
esac
mkdir -p -- "$JAC_CACHE_HOME/test-runs"
test_root="$(mktemp -d "$JAC_CACHE_HOME/test-runs/$suite-XXXXXXXX")"
# Copy only source/configuration. The distinct path gives Jac a separate app store.
while IFS= read -r -d '' source_file; do
    mkdir -p -- "$test_root/$(dirname -- "$source_file")"
    cp -- "$source_file" "$test_root/$source_file"
done < <(find . -type d \( -name .jac -o -name .git -o -name node_modules -o -name .venv \) -prune -o -type f \( -name '*.jac' -o -name '*.py' -o -name '*.pyi' -o -name jac.toml \) -print0)
echo "Isolated test workspace (retained for diagnosis): $test_root"
cd -- "$test_root"
if [[ "$suite" == context ]]; then
    "$JAC_BIN" test services/context.test.jac
else
    "$JAC_BIN" test services/promo.test.jac services/qr.test.jac services/session.test.jac
fi
if [[ "$suite" == all ]]; then
    exit_code=0
    bash "$PROJECT_ROOT/scripts/test.sh" context || exit_code=$?
    bash "$PROJECT_ROOT/scripts/test.sh" integration || exit_code=$?
    exit "$exit_code"
fi
