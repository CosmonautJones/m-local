#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
version="$(tr -d '\r\n' < .jac-version)"
case "$(uname -s)/$(uname -m)" in
    Linux/x86_64) platform=linux-x86_64 ;;
    Linux/aarch64|Linux/arm64) platform=linux-aarch64 ;;
    Darwin/arm64) platform=macos-aarch64 ;;
    *) echo "No matching Jac $version release asset for this OS/architecture. Windows: use WSL. Intel Mac: use a supported Linux VM or a teammate host; see docs/RUNTIME.md." >&2; exit 2 ;;
esac
destination="$HOME/.local/share/m-local/runtimes/$version"
mkdir -p -- "$destination"
download_dir="$(mktemp -d)"
trap 'rm -rf -- "$download_dir"' EXIT
for suffix in '' '-jacpython'; do
    asset="jac-$version-$platform$suffix"
    curl --fail --location --retry 2 "https://github.com/jaseci-labs/jac/releases/download/v$version/$asset" -o "$download_dir/$asset"
    curl --fail --location --retry 2 "https://github.com/jaseci-labs/jac/releases/download/v$version/$asset.sha256" -o "$download_dir/$asset.sha256"
    expected="$(awk '{print $1}' "$download_dir/$asset.sha256")"
    if command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "$download_dir/$asset" | awk '{print $1}')"
    else
        actual="$(shasum -a 256 "$download_dir/$asset" | awk '{print $1}')"
    fi
    [[ "$actual" == "$expected" ]] || { echo "Checksum mismatch: $asset" >&2; exit 1; }
    echo "Checksum verified: $asset"
    target=jac
    [[ -z "$suffix" ]] || target=jacpython
    install -m 755 -- "$download_dir/$asset" "$destination/$target"
done
"$destination/jac" --version
echo 'Runtime installed. Next: bash scripts/dev.sh (first launch downloads app dependencies).'
