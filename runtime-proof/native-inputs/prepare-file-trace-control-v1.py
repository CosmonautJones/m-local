from pathlib import Path
import hashlib
import json
import os
import subprocess

os.umask(0o077)
origin = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/strace-client-control-v3')
directory = Path('/var/tmp/m-local-kali-file-trace-01a1050e')
assert not directory.exists()
download = json.loads((origin / 'result.json').read_text())
assert download['status'] == 'verified_download'
directory.mkdir(mode=0o700)
root = directory / 'root'
root.mkdir(mode=0o700)
for row in download['packages']:
    archive = origin / row['file']
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == row['sha256']
    assert subprocess.check_output(['dpkg-deb', '-f', str(archive), 'Package'], text=True).strip() == row['package']
    subprocess.run(['dpkg-deb', '-x', str(archive), str(root)], check=True)
binary = root / 'usr/bin/strace'
library = root / 'usr/lib/x86_64-linux-gnu'
env = dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8', LD_LIBRARY_PATH=str(library))
version = subprocess.check_output([str(binary), '--version'], env=env, text=True, stderr=subprocess.STDOUT)
assert 'strace -- version 7.0' in version
ldd = subprocess.check_output(['/usr/bin/ldd', str(binary)], env=env, text=True, stderr=subprocess.STDOUT)
assert 'not found' not in ldd
bindings = {}
for line in ldd.splitlines():
    words = line.split()
    paths = [Path(word) for word in words if word.startswith('/')]
    for path in paths:
        assert path.is_file()
        bindings[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
fixture = directory / 'read-control.txt'
fixture.write_text('Controlled file read\n')
for path in [directory, *directory.rglob('*')]:
    os.chown(path, 65534, 65534, follow_symlinks=False)
calls = 'open,openat,openat2,access,faccessat,faccessat2,newfstatat,stat,lstat,statx,readlink,readlinkat'
trace = directory / 'control.trace'
subprocess.run([str(binary), '-f', '-qq', '-e', 'trace=' + calls, '-o', str(trace), '/usr/bin/python3', '-B', '-c',
                'from pathlib import Path; assert Path(' + repr(str(fixture)) + ').read_text()=="Controlled file read\\n"'],
               env=env, user=65534, group=65534, extra_groups=[], check=True, timeout=20)
assert str(fixture) in trace.read_text()
result = dict(status='passed', scope='Exact official extracted tracing client and controlled file read; no OS installation or global ptrace changes',
              workspace=str(directory), version=version.strip(), binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
              repository_receipt_sha256=hashlib.sha256((origin / 'result.json').read_bytes()).hexdigest(),
              dependency_sha256=bindings, file_syscalls=calls, execve_arguments_traced=False,
              controlled_trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest())
(directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
(directory / 'executed-prepare.py').write_bytes(Path(__file__).read_bytes())
print(json.dumps(result))
