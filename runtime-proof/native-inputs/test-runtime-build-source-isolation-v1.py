from pathlib import Path
import hashlib
import json
import os
import runpy
import stat
import subprocess
import tempfile

os.umask(0o077)
task = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
helper = task / 'work/runtime-build-source-isolation.py'
isolation = runpy.run_path(str(helper))
e_root = Path('/var/tmp/m-local-build-e-drive-01a1050e')
directory = Path(tempfile.mkdtemp(prefix='source-isolation-control-', dir=str(e_root)))
os.chown(directory, 65534, 65534)
hidden = []
original = []
result = dict(status='running', scope='Owned test fixtures: readable baseline, root-owned private aliases denied to UID/GID65534 with zero capabilities, exact directory owner/mode/inode restoration',
    workspace=str(directory), helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),
    executed_probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
try:
    for name, mode in (('fork', 0o700), ('stage', 0o755)):
        path = directory / name
        path.mkdir(mode=mode)
        os.chmod(path, mode)
        (path / 'fixture.py').write_text('print("fixture")\n')
        os.chown(path, 65534, 65534)
        os.chown(path / 'fixture.py', 65534, 65534)
        original.append((path, path.stat(), (path / 'fixture.py').read_bytes()))
        subprocess.run(['/usr/bin/python3', '-B', '-c', 'from pathlib import Path; assert Path(' + repr(str(path / 'fixture.py')) + ').read_bytes()'],
            user=65534, group=65534, extra_groups=[], check=True, timeout=15,
            env=dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8'))
        hidden.append(isolation['hide_source'](path, '.unavailable'))
    result['readable_baselines_verified'] = True
    result['denial'] = isolation['prove_denied'](hidden)
finally:
    isolation['restore_sources'](hidden)
    for path, before, content in original:
        after = path.stat()
        assert (after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode), after.st_ino, after.st_dev) == (
            before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode), before.st_ino, before.st_dev)
        assert (path / 'fixture.py').read_bytes() == content
    result['exact_restoration_verified'] = True
result['status'] = 'passed'
(directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
(directory / 'executed-probe.py').write_bytes(Path(__file__).read_bytes())
(directory / 'executed-helper.py').write_bytes(helper.read_bytes())
public = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/runtime-source-isolation-control-v1.json')
assert not public.exists()
public.write_bytes((directory / 'result.json').read_bytes())
print(json.dumps(result))
