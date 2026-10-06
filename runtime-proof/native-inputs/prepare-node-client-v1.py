from pathlib import Path
import hashlib
import json
import tarfile
import urllib.request

assets = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/client-tools')
assets.mkdir(exist_ok=True)
version = '22.16.0'
name = f'node-v{version}-linux-x64.tar.xz'
origin = f'https://nodejs.org/dist/v{version}/'
checks = urllib.request.urlopen(origin + 'SHASUMS256.txt', timeout=30).read()
expected = next(line.split()[0] for line in checks.decode().splitlines() if line.split()[-1] == name)
archive = assets / name
if not archive.exists():
    with urllib.request.urlopen(origin + name, timeout=30) as response, archive.open('xb') as stream:
        while data := response.read(1024 * 1024):
            stream.write(data)
assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
(assets / 'SHASUMS256.txt').write_bytes(checks)
folder = assets / f'node-v{version}-linux-x64'
if not folder.exists():
    with tarfile.open(archive) as tar:
        tar.extractall(assets, filter='data')
assert (folder / 'bin/node').is_file()
print(json.dumps(dict(node_version=version, archive_sha256=expected, tools_directory=str(folder),
    provenance='Exact test-tool version matching the installed Windows Node; archive matches official HTTPS SHA-256 manifest. Not an application dependency or production runtime change.')), flush=True)
