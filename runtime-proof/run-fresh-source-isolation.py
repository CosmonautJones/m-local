#!/usr/bin/env python3
"""Run the frozen source isolation control in a fresh private mount."""
from pathlib import Path
import hashlib
import json
import os
import re
import stat
import sys


ROOT = Path(__file__).absolute().parents[1]
E_ROOT = Path('/var/tmp/m-local-build-e-drive-v2-01a1050e')
HELPER_RELATIVE = 'runtime-proof/native-inputs/runtime-build-source-isolation-v1.py'
PROBE_RELATIVE = 'runtime-proof/native-inputs/test-runtime-build-source-isolation-v1.py'
HELPER_SHA256 = 'da9af3a768782c6ca9b28134df2b04ab4bac464a434e8ce3e29b69692c96ec9c'
PROBE_SHA256 = '92c9a941a1956928be202b687c43aee3eeb0a71be68816c610ee4adb86b92708'
HELPER_SHA = HELPER_SHA256
PROBE_SHA = PROBE_SHA256
CONTROL_PREFIX = 'm-local-source-isolation-control-v1-'
WORKSPACE_PREFIX = 'source-isolation-control-'
SCOPE = ('Owned test fixtures: readable baseline, root-owned private aliases denied to '
         'UID/GID65534 with zero capabilities, exact directory owner/mode/inode restoration')
LEGACY_HELPER = b"helper = task / 'work/runtime-build-source-isolation.py'"
LEGACY_E_ROOT = b"e_root = Path('/var/tmp/m-local-build-e-drive-01a1050e')"
LEGACY_PUBLIC = b"public = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/runtime-source-isolation-control-v1.json')"
RECEIPT_KEYS = {
    'status', 'scope', 'workspace', 'helper_sha256', 'executed_probe_sha256',
    'readable_baselines_verified', 'denial', 'exact_restoration_verified',
}
DENIAL_KEYS = {'uid', 'gid', 'effective_capabilities', 'operations'}
OPERATION_KEYS = {'alias', 'operation', 'errno'}


def _fail(label):
    raise ValueError(label)


def _sha(raw):
    if type(raw) is not bytes:
        _fail('source isolation input bytes')
    return hashlib.sha256(raw).hexdigest()


def _replace_once(raw, marker, replacement, label):
    if raw.count(marker) != 1:
        _fail(label)
    return raw.replace(marker, replacement)


def adapt_probe(raw, helper_path, storage_root, output_path):
    """Adapt only the three legacy path bindings in the frozen probe."""
    if type(raw) is not bytes or _sha(raw) != PROBE_SHA256:
        _fail('source isolation probe pin')
    helper_path, storage_root, output_path = map(Path, (helper_path, storage_root, output_path))
    if any(not path.is_absolute() or path.resolve() != path for path in
           (helper_path, storage_root, output_path)):
        _fail('source isolation private path')
    adapted = _replace_once(raw, LEGACY_HELPER,
                            b'helper = Path(' + repr(str(helper_path)).encode() + b')',
                            'source isolation helper binding')
    adapted = _replace_once(adapted, LEGACY_E_ROOT,
                            b'e_root = Path(' + repr(str(storage_root)).encode() + b')',
                            'source isolation storage binding')
    adapted = _replace_once(adapted, LEGACY_PUBLIC,
                            b'public = Path(' + repr(str(output_path)).encode() + b')',
                            'source isolation receipt binding')
    adapted = _replace_once(adapted, b'import runpy\n', b'import runpy\nimport signal\n',
                            'source isolation signal import')
    signal_block = (b"def _source_isolation_signal(signum, _frame):\n"
                    b"    raise SystemExit(128 + signum)\n"
                    b"\n"
                    b"for _signum in (signal.SIGTERM, signal.SIGINT):\n"
                    b"    signal.signal(_signum, _source_isolation_signal)\n")
    adapted = _replace_once(adapted, b'os.umask(0o077)\n', signal_block + b'os.umask(0o077)\n',
                            'source isolation signal handler')
    if any(marker in adapted for marker in (LEGACY_HELPER, LEGACY_E_ROOT, LEGACY_PUBLIC)):
        _fail('source isolation legacy binding')
    return adapted


def _read_regular(path, maximum=1024 ** 2):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            info.st_size <= 0 or info.st_size > maximum or path.is_symlink()):
        _fail('source isolation receipt file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        stream = os.fdopen(os.open(path, flags), 'rb')
    except OSError:
        _fail('source isolation receipt open')
    with stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(maximum + 1)
        closed = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_uid', 'st_nlink')
    if (len(raw) != info.st_size or any(getattr(item, field) != getattr(info, field)
            for item in (opened, closed) for field in fields)):
        _fail('source isolation receipt changed')
    return raw


def _private_file(path, expected_sha=None, mode=None):
    path = Path(path)
    info = path.lstat()
    modes = (0o400, 0o600) if mode is None else (mode,)
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_uid != 0 or info.st_mode & 0o777 not in modes):
        _fail('source isolation private file')
    raw = _read_regular(path)
    if expected_sha is not None and _sha(raw) != expected_sha:
        _fail('source isolation private file hash')
    return raw, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode,
                 info.st_uid, info.st_nlink)


def _write_private(path, raw):
    path = Path(path)
    try:
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(path, 0, 0)
        os.chmod(path, 0o400)
    except (OSError, FileExistsError):
        _fail('source isolation private file create')
    _private_file(path, _sha(raw))


def _mount_identity(runner, directory):
    directory = Path(directory)
    e_root = Path(runner.get('E_ROOT', E_ROOT))
    var_tmp = Path('/var/tmp')
    if (not directory.is_absolute() or directory.parent != var_tmp or
            not directory.name.startswith(CONTROL_PREFIX) or
            len(directory.name) != len(CONTROL_PREFIX) + 8 or
            directory.resolve() != directory or directory.is_symlink() or
            not directory.is_mount() or var_tmp.is_symlink() or
            not e_root.is_absolute() or e_root.resolve() != e_root or
            e_root.is_symlink() or not e_root.is_mount()):
        _fail('source isolation mount path')
    root_info, mounted_info = e_root.stat(), directory.stat()
    backing = e_root / directory.name
    if backing.is_symlink() or backing.resolve() != backing or not backing.is_dir():
        _fail('source isolation mount backing')
    backing_info = backing.stat()
    var_info = var_tmp.stat()
    if (any(getattr(item, 'st_uid', None) != 65534 or item.st_mode & 0o777 != 0o700
            for item in (root_info, mounted_info, backing_info)) or
            root_info.st_dev == var_info.st_dev or
            mounted_info.st_dev != root_info.st_dev or
            (mounted_info.st_dev, mounted_info.st_ino) != (backing_info.st_dev, backing_info.st_ino)):
        _fail('source isolation mount identity')
    return e_root


def _validate_private_inputs(path, expected):
    raw, identity = _private_file(path, expected)
    current = Path(path).lstat()
    if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns,
            current.st_mode, current.st_uid, current.st_nlink) != identity:
        _fail('source isolation private input changed')
    return raw


def validate_receipt(raw, storage_root, helper_sha256, probe_sha256):
    """Validate the scrubbed receipt and its exact private workspace binding."""
    if type(raw) is not bytes or _sha(raw) == '':
        _fail('source isolation receipt bytes')
    if (type(helper_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}', helper_sha256) or
            type(probe_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}', probe_sha256)):
        _fail('source isolation receipt hash format')
    try:
        receipt = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('source isolation receipt json')
    if type(receipt) is not dict or set(receipt) != RECEIPT_KEYS:
        _fail('source isolation receipt fields')
    if (receipt['status'] != 'passed' or receipt['scope'] != SCOPE or
            type(receipt['workspace']) is not str or
            receipt['helper_sha256'] != helper_sha256 or
            receipt['executed_probe_sha256'] != probe_sha256 or
            receipt['readable_baselines_verified'] is not True or
            receipt['exact_restoration_verified'] is not True):
        _fail('source isolation receipt binding')
    storage_root = Path(storage_root)
    workspace = Path(receipt['workspace'])
    if (not storage_root.is_absolute() or storage_root.resolve() != storage_root or
            storage_root.is_symlink() or workspace.parent != storage_root or
            not workspace.name.startswith(WORKSPACE_PREFIX) or
            len(workspace.name) != len(WORKSPACE_PREFIX) + 8 or
            re.fullmatch(r'[a-z0-9_]{8}', workspace.name[len(WORKSPACE_PREFIX):]) is None or
            workspace.resolve() != workspace or workspace.is_symlink() or not workspace.is_dir()):
        _fail('source isolation workspace path')
    root_info, workspace_info = storage_root.stat(), workspace.stat()
    if (getattr(workspace_info, 'st_uid', None) != 65534 or
            getattr(workspace_info, 'st_gid', None) != 65534 or workspace_info.st_mode & 0o777 != 0o700 or
            workspace_info.st_dev != root_info.st_dev):
        _fail('source isolation workspace identity')
    denial = receipt['denial']
    if type(denial) is not dict or set(denial) != DENIAL_KEYS:
        _fail('source isolation denial fields')
    if (type(denial['uid']) is not int or denial['uid'] != 65534 or
            type(denial['gid']) is not int or denial['gid'] != 65534 or
            type(denial['effective_capabilities']) is not str or
            re.fullmatch(r'[0-9a-fA-F]{16}', denial['effective_capabilities']) is None or
            int(denial['effective_capabilities'], 16) != 0):
        _fail('source isolation denial identity')
    operations = denial['operations']
    expected = {(str(workspace / 'fork.unavailable'), 'directory-list'),
                (str(workspace / 'fork.unavailable'), 'relative-file-read'),
                (str(workspace / 'stage.unavailable'), 'directory-list'),
                (str(workspace / 'stage.unavailable'), 'relative-file-read')}
    if type(operations) is not list or len(operations) != 4:
        _fail('source isolation denial count')
    actual = set()
    for row in operations:
        if type(row) is not dict or set(row) != OPERATION_KEYS:
            _fail('source isolation denial operation fields')
        if (type(row['alias']) is not str or type(row['operation']) is not str or
                row['operation'] not in {'directory-list', 'relative-file-read'} or
                type(row['errno']) is not int or row['errno'] != 13):
            _fail('source isolation denial operation')
        key = (row['alias'], row['operation'])
        if key in actual or key not in expected:
            _fail('source isolation denial operation identity')
        actual.add(key)
    if actual != expected:
        _fail('source isolation denial operations')
    _private_file(workspace / 'executed-helper.py', helper_sha256, mode=0o600)
    _private_file(workspace / 'executed-probe.py', probe_sha256, mode=0o600)
    return receipt


def run_control(preflight, runner, directory, commit, timeout):
    """Run the frozen control and return private receipt metadata."""
    if type(timeout) is not int or not 0 < timeout <= 75:
        _fail('source isolation timeout')
    e_root = _mount_identity(runner, directory)
    directory = Path(directory)
    if any(path.is_symlink() or path.exists() for path in directory.iterdir()):
        _fail('source isolation pre-existing files')
    helper_raw = preflight['committed_file'](ROOT, commit, HELPER_RELATIVE)
    probe_raw = preflight['committed_file'](ROOT, commit, PROBE_RELATIVE)
    if (type(helper_raw) is not bytes or type(probe_raw) is not bytes or
            _sha(helper_raw) != HELPER_SHA256 or _sha(probe_raw) != PROBE_SHA256):
        _fail('source isolation input pin')
    helper_path, probe_path, output_path = (directory / 'helper.py', directory / 'probe.py',
                                           directory / 'result.json')
    adapted = adapt_probe(probe_raw, helper_path, directory, output_path)
    helper_sha256, probe_sha256 = _sha(helper_raw), _sha(adapted)
    _write_private(helper_path, helper_raw)
    _write_private(probe_path, adapted)
    helper_identity = _private_file(helper_path, helper_sha256)[1]
    probe_identity = _private_file(probe_path, probe_sha256)[1]
    environment = runner['minimal_environment']()
    runner['run_command']('source isolation control',
                          [sys.executable, '-I', '-B', str(probe_path)], cwd=directory,
                          env=environment, timeout=timeout, log=directory / 'control.log')
    _mount_identity(runner, directory)
    _validate_private_inputs(helper_path, helper_sha256)
    _validate_private_inputs(probe_path, probe_sha256)
    if (_private_file(helper_path, helper_sha256)[1] != helper_identity or
            _private_file(probe_path, probe_sha256)[1] != probe_identity):
        _fail('source isolation private input identity')
    if output_path.is_symlink() or not output_path.is_file():
        _fail('source isolation receipt target')
    output_info = output_path.lstat()
    if (not stat.S_ISREG(output_info.st_mode) or output_info.st_nlink != 1 or
            output_info.st_uid != 0 or output_info.st_mode & 0o777 != 0o600):
        _fail('source isolation receipt identity')
    os.chmod(output_path, 0o400)
    receipt_raw = _read_regular(output_path)
    receipt_sha256 = _sha(receipt_raw)
    validated = validate_receipt(receipt_raw, directory, helper_sha256, probe_sha256)
    executed_workspace = Path(validated['workspace'])
    for name in ('executed-helper.py', 'executed-probe.py'):
        path = executed_workspace / name
        expected = helper_sha256 if name == 'executed-helper.py' else probe_sha256
        if path.is_symlink() or not path.is_file():
            _fail('source isolation executed copy')
        os.chmod(path, 0o400)
        copied = _private_file(path, expected, mode=0o400)[0]
        _write_private(directory / name, copied)
    for relative, before in ((HELPER_RELATIVE, helper_raw), (PROBE_RELATIVE, probe_raw)):
        after = preflight['committed_file'](ROOT, commit, relative)
        if type(after) is not bytes or _sha(after) != _sha(before):
            _fail('source isolation root input changed')
    return dict(receipt_path=output_path, receipt_sha256=receipt_sha256,
                helper_sha256=helper_sha256, probe_sha256=probe_sha256,
                status='passed')
