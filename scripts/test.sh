#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
suite="${1:-core}"
case "$suite" in
    core|all) ;;
    context|integration)
        echo "$suite suite is not implemented yet; see the team missions." >&2
        exit 2 ;;
    *) echo 'Usage: scripts/test.sh core|context|integration|all' >&2; exit 2 ;;
esac
mkdir -p -- "$JAC_CACHE_HOME/test-runs"
test_root="$(mktemp -d "$JAC_CACHE_HOME/test-runs/core-XXXXXXXX")"
# Copy only source/configuration. The distinct path gives Jac a separate app store.
while IFS= read -r -d '' source_file; do
    mkdir -p -- "$test_root/$(dirname -- "$source_file")"
    cp -- "$source_file" "$test_root/$source_file"
done < <(find . -type d \( -name .jac -o -name .git -o -name node_modules -o -name .venv \) -prune -o -type f \( -name '*.jac' -o -name jac.toml \) -print0)
echo "Isolated test workspace (retained for diagnosis): $test_root"
cd -- "$test_root"
"$JAC_BIN" test services/promo.jac
if [[ "$suite" == all ]]; then
    echo 'Core completed; context and integration suites are not implemented. All is NOT passing.' >&2
    exit 2
fi
