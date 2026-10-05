#!/usr/bin/env bash
# Diagnostic regression: unchanged Jac 0.37.23 currently fails this invariant.
source "$(dirname -- "${BASH_SOURCE[0]}")/runtime.sh"
candidate="$(mktemp -d /var/tmp/m-local-runtime-proof.XXXXXXXX)"
while IFS= read -r -d '' source_file; do
    mkdir -p -- "$candidate/$(dirname -- "$source_file")"
    cp -- "$source_file" "$candidate/$source_file"
done < <(find . -type d \( -name .jac -o -name .git -o -name node_modules -o -name .venv -o -name dist \) -prune -o -type f \( -name '*.jac' -o -name '*.py' -o -name '*.pyi' -o -name '*.sh' -o -name jac.toml -o -name .jac-version \) -print0)
unset JAC_DB_URL MLOCAL_ONBOARDING_DIR MLOCAL_MERCHANT_OWNERS MLOCAL_DEMO_STUDENTS
cd -- "$candidate"
echo "Retained disposable diagnostic app: $candidate"
bash scripts/python.sh -c 'import runpy; runpy.run_path("tests/runtime/transaction_retry_probe.py",run_name="__main__")'
