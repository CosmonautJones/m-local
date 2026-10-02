#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
suite="${1:-core}"
case "$suite" in
    core|context|insights|all) ;;
    onboarding) bash scripts/python.sh -m unittest discover -s tests/onboarding; exit $? ;;
    integration)
        node --test tests/ui/*.test.mjs tests/tooling/*.test.mjs
        accounts="$PROJECT_ROOT/.jac/qr-demo-accounts.json"
        if [[ ! -f "$accounts" ]]; then
            echo 'Integration accounts are missing. Run the local provisioning command first; no fixture success is substituted.' >&2
            exit 2
        fi
        python3 tests/integration/qr_http.py --api "${MLOCAL_API_URL:-http://localhost:8001}" --accounts "$accounts"
        exit 0 ;;
    *) echo 'Usage: scripts/test.sh core|context|insights|integration|onboarding|all' >&2; exit 2 ;;
esac
if [[ "$suite" == insights ]]; then
    python3 -m unittest discover -s tests/analytics -p test_analytics.py
    node --test tests/analytics/insights.test.mjs
fi
mkdir -p -- "$JAC_CACHE_HOME/test-runs"
test_root="$(mktemp -d "$JAC_CACHE_HOME/test-runs/$suite-XXXXXXXX")"
# Copy only source/configuration. The distinct path gives Jac a separate app store.
while IFS= read -r -d '' source_file; do
    mkdir -p -- "$test_root/$(dirname -- "$source_file")"
    cp -- "$source_file" "$test_root/$source_file"
done < <(find . -type d \( -name .jac -o -name .git -o -name node_modules -o -name .venv \) -prune -o -type f \( -name '*.jac' -o -name '*.py' -o -name '*.pyi' -o -name jac.toml \) -print0)
echo "Isolated test workspace (retained for diagnosis): $test_root"
# Seeded catalog tests read fixture rows. Production leaves this unset.
export MLOCAL_DEMO_MODE=1
cd -- "$test_root"
if [[ "$suite" == context ]]; then
    "$JAC_BIN" test services/context.test.jac
elif [[ "$suite" == insights ]]; then
    "$JAC_BIN" test tests/analytics/backend_tests.jac
else
    "$JAC_BIN" test services/promo.test.jac services/qr.test.jac services/session.test.jac services/business_onboarding.test.jac \
        services/taste.test.jac services/taste_sandbox.test.jac services/foryou.test.jac \
        services/nearby.test.jac services/business_profile.test.jac services/hosted_dataset.test.jac services/dataset_activity.test.jac
fi
if [[ "$suite" == all ]]; then
    exit_code=0
    bash "$PROJECT_ROOT/scripts/test.sh" context || exit_code=$?
    bash "$PROJECT_ROOT/scripts/test.sh" integration || exit_code=$?
    exit "$exit_code"
fi
