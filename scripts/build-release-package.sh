#!/usr/bin/env bash
# Creates a sealed engineering artifact only; does not grant launch approval.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
output=${1:?new absolute output directory required}
[[ "$output" == /* && ! -e "$output" && -z "${JAC_DEV_SOURCE:-}" && -z "${JAC_DB_URL:-}" ]] || exit 2
mkdir -m 700 -- "$output"
cd "$root"
source scripts/runtime.sh
[[ -z "$(git status --porcelain --untracked-files=normal)" ]]
"$JAC_BIN" install > "$output/install.txt" 2>&1
bash scripts/build.sh > "$output/build.txt" 2>&1
python3 deploy/release/package.py make-dependencies --source "$root" --output "$output/libraries.tar"
for asset in jac-0.37.23-linux-x86_64 jac-0.37.23-linux-x86_64-jacpython; do
  curl --fail --location --retry 2 --max-time 60 "https://github.com/jaseci-labs/jac/releases/download/v0.37.23/$asset.sha256" -o "$output/$asset.sha256"
done
python3 - "$root" "$output" <<'PY'
import hashlib,json,pathlib,subprocess,sys
root,output=map(pathlib.Path,sys.argv[1:])
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
artifacts=list((root/'dist').glob('*.jab'))
assert len(artifacts)==1
receipt=dict(source_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
    source_tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=root,text=True).strip(),
    artifact_sha256=digest(artifacts[0]),dependency_archive_sha256=digest(output/'libraries.tar'))
(output/'build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
checks={name:(output/asset).read_text().split()[0] for name,asset in
    [('jac','jac-0.37.23-linux-x86_64.sha256'),('jacpython','jac-0.37.23-linux-x86_64-jacpython.sha256')]}
assert all(len(h)==64 for h in checks.values())
(output/'official-checksums.json').write_text(json.dumps(checks,indent=2)+'\n')
(output/'artifact-path.txt').write_text(str(artifacts[0])+'\n')
PY
bash scripts/release-package.sh --output "$output/release" --runtime "$(dirname "$JAC_BIN")" \
  --official-checksums "$output/official-checksums.json" --artifact "$(cat "$output/artifact-path.txt")" \
  --dependency-archive "$output/libraries.tar" --build-receipt "$output/build-receipt.json"
python3 deploy/release/package.py verify --package "$output/release"
cp "$output/release/manifest.json" "$output/package-manifest.json"
tar -czf "$output/offline-package.tar.gz" -C "$output" release
sha256sum "$output/offline-package.tar.gz" > "$output/archive-sha256.txt"
[[ -z "$(git status --porcelain --untracked-files=normal)" ]]
