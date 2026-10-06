from pathlib import Path
import json
import os
import stat
import subprocess


def hide_source(path, suffix):
    destination = path.with_name(path.name + suffix)
    original = path.stat()
    assert path.is_absolute() and path.is_dir() and not path.is_symlink() and original.st_uid == 65534 and not destination.exists()
    probe_file = next(file for file in path.rglob('*') if file.is_file() and not file.is_symlink())
    relative_file = str(probe_file.relative_to(path))
    path.rename(destination)
    try:
        os.chown(destination, 0, 0)
        os.chmod(destination, 0o700)
    except BaseException:
        os.chown(destination, original.st_uid, original.st_gid)
        os.chmod(destination, stat.S_IMODE(original.st_mode))
        destination.rename(path)
        raise
    return dict(original=path, alias=destination, uid=original.st_uid, gid=original.st_gid,
        mode=stat.S_IMODE(original.st_mode), device=original.st_dev, inode=original.st_ino, probe_file=relative_file)


def check_sources(hidden):
    assert hidden
    for row in hidden:
        assert not row['original'].exists() and not row['alias'].is_symlink()
        current = row['alias'].stat()
        assert (current.st_uid, current.st_gid, stat.S_IMODE(current.st_mode)) == (0, 0, 0o700)
        assert (current.st_dev, current.st_ino) == (row['device'], row['inode'])


def prove_denied(hidden):
    check_sources(hidden)
    targets = [(str(row['alias']), row['probe_file']) for row in hidden]
    code = '''from pathlib import Path
import errno,json,os
assert os.getuid() == os.getgid() == 65534 and os.getgroups() == []
capabilities = next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('CapEff:'))
assert int(capabilities, 16) == 0
rows = []
for alias, relative in TARGETS:
    for operation in ('directory-list', 'relative-file-read'):
        try:
            list(Path(alias).iterdir()) if operation == 'directory-list' else Path(alias, relative).read_bytes()
        except PermissionError as error:
            assert error.errno == errno.EACCES
            rows.append(dict(alias=alias, operation=operation, errno=error.errno))
        else:
            raise AssertionError('Build source was readable')
print(json.dumps(dict(uid=os.getuid(), gid=os.getgid(), effective_capabilities=capabilities, operations=rows)))
'''.replace('TARGETS', repr(targets))
    process = subprocess.run(['/usr/bin/python3', '-B', '-c', code],
        env=dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8'),
        user=65534, group=65534, extra_groups=[], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=True, timeout=15)
    result = json.loads(process.stdout)
    assert len(result['operations']) == 2 * len(hidden)
    check_sources(hidden)
    return result


def restore_sources(hidden):
    if hidden:
        check_sources(hidden)
    for row in reversed(hidden):
        os.chown(row['alias'], row['uid'], row['gid'])
        os.chmod(row['alias'], row['mode'])
        row['alias'].rename(row['original'])
        restored = row['original'].stat()
        assert (restored.st_uid, restored.st_gid, stat.S_IMODE(restored.st_mode), restored.st_dev, restored.st_ino) == (
            row['uid'], row['gid'], row['mode'], row['device'], row['inode'])
