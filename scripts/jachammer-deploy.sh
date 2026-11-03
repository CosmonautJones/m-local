#!/usr/bin/env bash
# Deploy the committed source to JacHammer as a preview (default) or to
# production with --prod. Run from WSL/Linux with the jachammer CLI logged in.
# See docs/JACHAMMER-TESTING.md.
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
stage="$(mktemp -d "${TMPDIR:-/tmp}/m-local-jachammer.XXXXXX")"
trap 'rm -rf -- "$stage"' EXIT

# JACHAMMER_OPEN_REGISTRATION=1 leaves native registration open for QA
# provisioning on a preview; it is refused for --prod.
stage_args=()
if [[ "${JACHAMMER_OPEN_REGISTRATION:-}" == 1 ]]; then
    for arg in "$@"; do
        if [[ "$arg" == --prod ]]; then echo "JACHAMMER_OPEN_REGISTRATION is for previews only." >&2; exit 2; fi
    done
    stage_args+=(--open-native-registration)
fi
python3 "$repo/scripts/jachammer-stage.py" "$stage" --source "$repo" "${stage_args[@]}"

# JacHammer's own pre-upload check uses whatever `jac` is first on PATH, which
# may not be the pinned runtime. Check with the pinned one, then skip theirs.
source "$repo/scripts/runtime.sh"
(cd "$stage" && "$JAC_BIN" check main.jac)

cd "$stage"
exec jachammer deploy --skip-check --ready-timeout 900 "$@"
