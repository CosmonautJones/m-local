from pathlib import Path
import hashlib
import json
import os
import subprocess

os.umask(0o077)
control = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/pg-client-control-v1')
metadata = json.loads((control / 'result.json').read_text())
directory = Path('/var/tmp/m-local-kali-pg-client-01a1050e')
assert not directory.exists()
directory.mkdir(mode=0o700)
root = directory / 'root'
for row in metadata['packages']:
    package = control / row['file']
    assert package.parent == control and package.suffix == '.deb'
    assert package.stat().st_size == row['bytes'] and hashlib.sha256(package.read_bytes()).hexdigest() == row['sha256']
    subprocess.run(['dpkg-deb', '--extract', str(package), str(root)], check=True)
for path in [directory, *directory.rglob('*')]:
    os.chown(path, 65534, 65534, follow_symlinks=False)
env = dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8',
    LD_LIBRARY_PATH=str(root / 'usr/lib/x86_64-linux-gnu'))
result = dict(status='passed', scope='Extracted hash-verified official client tools only; no system package or database changes',
    workspace=str(directory), package_index_sha256=metadata['index_sha256'], package_version=metadata['version'], tools=[])
for name in ('psql', 'pg_dump', 'pg_restore'):
    path = root / 'usr/lib/postgresql/18/bin' / name
    assert path.is_file() and not path.is_symlink()
    linked = subprocess.check_output(['ldd', str(path)], env=env, text=True, stderr=subprocess.STDOUT)
    assert 'not found' not in linked
    version = subprocess.check_output([str(path), '--version'], env=env, text=True).strip()
    assert '(PostgreSQL) 18.6 ' in version
    result['tools'].append(dict(name=name, version=version, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
(directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
os.chown(directory / 'result.json', 65534, 65534)
print(json.dumps(result))
