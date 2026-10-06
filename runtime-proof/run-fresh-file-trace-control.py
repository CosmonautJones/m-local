#!/usr/bin/env python3
"""Prepare and verify the private file-trace client controls."""
from pathlib import Path
import hashlib
import json
import os
import re
import stat
import sys
import time
import urllib.parse
import urllib.error
import urllib.request


ROOT = Path(__file__).absolute().parents[1]
E_ROOT = Path('/var/tmp/m-local-build-e-drive-v2-01a1050e')
CONTROL_PREFIX = 'm-local-file-trace-control-v1-'
PREPARE_RELATIVE = 'runtime-proof/native-inputs/prepare-file-trace-control-v1.py'
ENVIRONMENT_RELATIVE = 'runtime-proof/native-inputs/test-file-trace-environment-v1.py'
MANIFEST_RELATIVE = 'runtime-proof/native-inputs/file-trace-download-pins-v1.json'
PREPARE_SHA256 = 'e9624c40e7614d28dfb6aea7aabed097b537aa10ea64a086809550e773cabfa8'
ENVIRONMENT_SHA256 = '65cb7645b36d441846a34242f87658f50e61cee4e4a71b0aca220d0733b51e3c'
MANIFEST_SHA256 = 'e70a83652f580fbf15527633801aeedefa0196917b5128fb47afae8326483a67'
PREPARE_SHA = PREPARE_SHA256
ENVIRONMENT_PROBE_SHA = ENVIRONMENT_SHA256
MANIFEST_SHA = MANIFEST_SHA256
DOWNLOAD_SCOPE = 'Fixed official HTTPS archive bytes; extracted privately with no OS installation or global ptrace changes'
PREPARE_SCOPE = 'Exact official extracted tracing client and controlled file read; no OS installation or global ptrace changes'
ENVIRONMENT_SCOPE = 'Tracing client-only library environment removed from tracee'
FILE_SYSCALLS = 'open,openat,openat2,access,faccessat,faccessat2,newfstatat,stat,lstat,statx,readlink,readlinkat'
MAX_DOWNLOAD_BYTES = 64 * 1024 ** 2
RECEIPT_KEYS = {'status', 'scope', 'workspace', 'version', 'binary_sha256',
                'repository_receipt_sha256', 'dependency_sha256', 'file_syscalls',
                'execve_arguments_traced', 'controlled_trace_sha256'}
ENVIRONMENT_RECEIPT_KEYS = {'status', 'scope', 'workspace', 'trace_sha256',
                            'executed_probe_sha256'}
MANIFEST_KEYS = {'packages', 'repository_index', 'schema', 'scope', 'status'}
PACKAGE_KEYS = {'architecture', 'bytes', 'file', 'package', 'sha256', 'url', 'version'}
INDEX_KEYS = {'bytes', 'sha256', 'url'}
PACKAGE_PINS = {
    'libunwind8': (54024, 'libunwind8_1.8.1-0.4_amd64.deb', '1.8.1-0.4',
                   'aee9cb6fd8e298d52c398eabea640e0a49b198d77c0e6df34e69ed97e255b9b3',
                   'https://kali.download/kali/pool/main/libu/libunwind/libunwind8_1.8.1-0.4_amd64.deb'),
    'strace': (1859716, 'strace_7.0+ds-1_amd64.deb', '7.0+ds-1',
               '3fccef3e6092284d8a065dce98fe6397f9dc1d97a6d81b050135f5ad489bf6f2',
               'https://kali.download/kali/pool/main/s/strace/strace_7.0+ds-1_amd64.deb'),
}
INDEX_PIN = (21574122, '4544587e00a9feb8bfa6e8f82be700718264bff872cdb798dc332ac50dfa759e',
             'https://kali.download/kali/dists/kali-rolling/main/binary-amd64/Packages.gz')


def _fail(label):
    raise ValueError(label)


def _sha(raw):
    if type(raw) is not bytes:
        _fail('file trace bytes')
    return hashlib.sha256(raw).hexdigest()


def _hash_file(path, maximum=MAX_DOWNLOAD_BYTES):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_size <= 0 or info.st_size > maximum):
        _fail('file trace regular file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        stream = os.fdopen(os.open(path, flags), 'rb')
    except OSError:
        _fail('file trace file open')
    digest = hashlib.sha256()
    total = 0
    with stream:
        opened = os.fstat(stream.fileno())
        while True:
            chunk = stream.read(1024 ** 2)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                _fail('file trace file bound')
            digest.update(chunk)
        closed = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_uid', 'st_gid', 'st_nlink')
    if (total != info.st_size or any(getattr(item, field) != getattr(info, field)
            for item in (opened, closed) for field in fields)):
        _fail('file trace file changed')
    return digest.hexdigest(), total, (info.st_dev, info.st_ino, info.st_size,
                                      info.st_mtime_ns, info.st_mode, info.st_uid,
                                      info.st_gid, info.st_nlink)


def _read_file(path, maximum=MAX_DOWNLOAD_BYTES):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_size <= 0 or info.st_size > maximum):
        _fail('file trace read regular file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        stream = os.fdopen(os.open(path, flags), 'rb')
    except OSError:
        _fail('file trace read open')
    with stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(maximum + 1)
        closed = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_uid', 'st_gid', 'st_nlink')
    if (len(raw) != info.st_size or any(getattr(item, field) != getattr(info, field)
            for item in (opened, closed) for field in fields)):
        _fail('file trace read changed')
    return raw


def _private_file(path, expected=None, mode=None):
    path = Path(path)
    info = path.lstat()
    modes = (0o400, 0o600) if mode is None else (mode,)
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_uid != 0 or info.st_mode & 0o777 not in modes):
        _fail('file trace private file')
    raw = _read_file(path)
    if expected is not None and _sha(raw) != expected:
        _fail('file trace private hash')
    identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_mode, info.st_uid, getattr(info, 'st_gid', None), info.st_nlink)
    return raw, identity


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
        _fail('file trace private create')
    _private_file(path, _sha(raw), mode=0o400)


def _create_private_log(path):
    path = Path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        os.close(descriptor)
        os.chown(path, 0, 0)
        os.chmod(path, 0o600)
    except OSError:
        _fail('file trace private log create')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or
            info.st_nlink != 1 or info.st_mode & 0o777 != 0o600 or info.st_size != 0):
        _fail('file trace private log identity')


def _mkdir_owned(path):
    path = Path(path)
    if path.exists() or path.is_symlink():
        _fail('file trace pre-existing directory')
    try:
        path.mkdir(mode=0o700)
        os.chown(path, 65534, 65534)
        os.chmod(path, 0o700)
    except OSError:
        _fail('file trace directory create')
    return path


def _replace_once(raw, marker, replacement, label):
    if raw.count(marker) != 1:
        _fail(label)
    return raw.replace(marker, replacement)


def _private_path(*paths):
    values = tuple(map(Path, paths))
    if any(not path.is_absolute() or path.resolve() != path for path in values):
        _fail('file trace private path')
    return values


def adapt_prepare(raw, origin, directory):
    if type(raw) is not bytes or _sha(raw) != PREPARE_SHA256:
        _fail('prepare pin')
    origin, directory = _private_path(origin, directory)
    adapted = _replace_once(raw,
        b"origin = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/strace-client-control-v3')",
        b'origin = Path(' + repr(str(origin)).encode() + b')', 'prepare origin binding')
    adapted = _replace_once(adapted,
        b"directory = Path('/var/tmp/m-local-kali-file-trace-01a1050e')",
        b'directory = Path(' + repr(str(directory)).encode() + b')', 'prepare directory binding')
    if (b'/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/strace-client-control-v3' in adapted or
            b'/var/tmp/m-local-kali-file-trace-01a1050e' in adapted):
        _fail('prepare legacy binding')
    return adapted


def adapt_environment_probe(raw, tools, environment_parent):
    if type(raw) is not bytes or _sha(raw) != ENVIRONMENT_SHA256:
        _fail('environment probe pin')
    tools, environment_parent = _private_path(tools, environment_parent)
    adapted = _replace_once(raw,
        b"root = Path('/var/tmp/m-local-kali-file-trace-01a1050e')",
        b'root = Path(' + repr(str(tools)).encode() + b')', 'environment root binding')
    adapted = _replace_once(adapted,
        b"directory = Path(tempfile.mkdtemp(prefix='m-local-trace-environment-control-', dir='/var/tmp'))",
        b'directory = Path(tempfile.mkdtemp(prefix=\'m-local-trace-environment-control-\', dir=' +
        repr(str(environment_parent)).encode() + b'))', 'environment directory binding')
    if (b'/var/tmp/m-local-kali-file-trace-01a1050e' in adapted or
            b"dir='/var/tmp'" in adapted):
        _fail('environment legacy binding')
    return adapted


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
        _fail('file trace mount path')
    root_info, mounted_info = e_root.stat(), directory.stat()
    backing = e_root / directory.name
    if backing.is_symlink() or backing.resolve() != backing or not backing.is_dir():
        _fail('file trace mount backing')
    backing_info, var_info = backing.stat(), var_tmp.stat()
    if (any(getattr(item, 'st_uid', None) != 65534 or item.st_mode & 0o777 != 0o700
            for item in (root_info, mounted_info, backing_info)) or
            root_info.st_dev == var_info.st_dev or mounted_info.st_dev != root_info.st_dev or
            (mounted_info.st_dev, mounted_info.st_ino) != (backing_info.st_dev, backing_info.st_ino)):
        _fail('file trace mount identity')
    return e_root, (mounted_info.st_dev, mounted_info.st_ino, mounted_info.st_uid,
                    mounted_info.st_gid, mounted_info.st_mode & 0o777)


def _safe_environment(runner):
    environment = dict(runner['minimal_environment']())
    forbidden = {'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'http_proxy',
                 'https_proxy', 'all_proxy', 'no_proxy', 'FTP_PROXY', 'ftp_proxy',
                 'GITHUB_TOKEN', 'GH_TOKEN',
                 'ACTIONS_RUNTIME_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'RUNNER_TOKEN',
                 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AZURE_CLIENT_SECRET',
                 'AWS_SESSION_TOKEN', 'NPM_TOKEN', 'PIP_INDEX_URL', 'PIP_EXTRA_INDEX_URL',
                 'AZURE_DEVOPS_EXT_PAT', 'DOCKER_AUTH_CONFIG', 'NETRC'}
    for key in list(environment):
        upper = key.upper()
        if (key in forbidden or upper.endswith('_PROXY') or
                any(word in upper for word in ('TOKEN', 'PASSWORD', 'PASSWD', 'SECRET',
                                               'CREDENTIAL', 'AUTH'))):
            environment.pop(key, None)
    return environment


def _download_url(url):
    if type(url) is not str:
        _fail('file trace download URL')
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'kali.download' or
            parsed.username is not None or parsed.password is not None or
            parsed.query or parsed.fragment or parsed.port is not None):
        _fail('file trace download URL')


class _PinnedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        _download_url(newurl)
        return super().redirect_request(request, file, code, message, headers, newurl)


def _download(url, destination, expected_bytes, expected_sha256, deadline):
    _download_url(url)
    if type(expected_bytes) is not int or expected_bytes <= 0 or expected_bytes > MAX_DOWNLOAD_BYTES:
        _fail('file trace download size')
    if type(expected_sha256) is not str or re.fullmatch(r'[0-9a-f]{64}', expected_sha256) is None:
        _fail('file trace download hash')
    if destination.exists() or destination.is_symlink():
        _fail('file trace download overwrite')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedRedirectHandler())
    request = urllib.request.Request(url, headers={'User-Agent': 'm-local-file-trace-control/1'})
    try:
        response = opener.open(request, timeout=min(25, _remaining(deadline)))
    except (OSError, urllib.error.URLError):
        _fail('file trace download unavailable')
    try:
        with response:
            _download_url(response.geturl())
            status = getattr(response, 'status', None)
            if status is not None and status != 200:
                _fail('file trace download status')
            content_length = getattr(getattr(response, 'headers', None), 'get', lambda *_: None)('Content-Length')
            if content_length is not None and content_length != str(expected_bytes):
                _fail('file trace download length')
            digest, total = hashlib.sha256(), 0
            reader = getattr(response, 'read1', None)
            if not callable(reader):
                _fail('file trace download read1')
            with destination.open('xb') as stream:
                while True:
                    _remaining(deadline)
                    chunk = reader(min(1024 ** 2, expected_bytes + 1 - total))
                    _remaining(deadline)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > expected_bytes:
                        _fail('file trace download bound')
                    digest.update(chunk)
                    stream.write(chunk)
                _remaining(deadline)
                stream.flush()
                os.fsync(stream.fileno())
    except (OSError, urllib.error.URLError):
        _fail('file trace download read')
    if total != expected_bytes or digest.hexdigest() != expected_sha256:
        _fail('file trace download digest')
    os.chown(destination, 0, 0)
    os.chmod(destination, 0o400)
    _private_file(destination, expected_sha256, mode=0o400)


def _validate_manifest(raw):
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('file trace manifest JSON')
    if type(manifest) is not dict or set(manifest) != MANIFEST_KEYS or manifest['schema'] != 'm-local-file-trace-download-pins-v1' or manifest['status'] != 'declared_before_extraction' or manifest['scope'] != DOWNLOAD_SCOPE:
        _fail('file trace manifest schema')
    packages = manifest['packages']
    if type(packages) is not list or len(packages) != 2:
        _fail('file trace manifest packages')
    for row in packages:
        if type(row) is not dict or set(row) != PACKAGE_KEYS:
            _fail('file trace package schema')
        if (row['package'] not in {'strace', 'libunwind8'} or row['architecture'] != 'amd64' or
                type(row['bytes']) is not int or row['bytes'] <= 0 or
                type(row['file']) is not str or Path(row['file']).name != row['file'] or
                type(row['version']) is not str or type(row['url']) is not str or
                re.fullmatch(r'[0-9a-f]{64}', row['sha256']) is None):
            _fail('file trace package binding')
        expected = PACKAGE_PINS[row['package']]
        if (row['bytes'], row['file'], row['version'], row['sha256'], row['url']) != expected:
            _fail('file trace package pin')
        parsed = urllib.parse.urlparse(row['url'])
        if (parsed.scheme != 'https' or parsed.hostname != 'kali.download' or
                parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or
                parsed.port is not None or Path(parsed.path).name != row['file']):
            _fail('file trace package URL')
    if {row['package'] for row in packages} != {'strace', 'libunwind8'}:
        _fail('file trace package identity')
    index = manifest['repository_index']
    if (type(index) is not dict or set(index) != INDEX_KEYS or type(index['bytes']) is not int or
            index['bytes'] <= 0 or type(index['url']) is not str or
            re.fullmatch(r'[0-9a-f]{64}', index['sha256']) is None):
        _fail('file trace index schema')
    if (index['bytes'], index['sha256'], index['url']) != INDEX_PIN:
        _fail('file trace index pin')
    parsed = urllib.parse.urlparse(index['url'])
    if (parsed.scheme != 'https' or parsed.hostname != 'kali.download' or parsed.username is not None or
            parsed.password is not None or parsed.query or parsed.fragment or parsed.port is not None):
        _fail('file trace index URL')
    return manifest


def _remaining(deadline):
    value = int(deadline - time.monotonic())
    if value <= 0:
        _fail('file trace deadline')
    return value


def _validate_download_receipt(raw, manifest, origin, expected_sha):
    try:
        receipt = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('file trace download receipt JSON')
    if (type(receipt) is not dict or set(receipt) != {'status', 'scope', 'packages', 'repository_index'} or
            receipt['status'] != 'verified_download' or receipt['scope'] != DOWNLOAD_SCOPE or
            receipt['packages'] != manifest['packages'] or receipt['repository_index'] != manifest['repository_index'] or
            _sha(raw) != expected_sha):
        _fail('file trace download receipt binding')
    for row in manifest['packages']:
        path = origin / row['file']
        actual, size, _ = _hash_file(path)
        if size != row['bytes'] or actual != row['sha256']:
            _fail('file trace downloaded package binding')
    return receipt


def _validate_prepare_receipt(raw, tools, origin_sha):
    try:
        receipt = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('file trace prepare receipt JSON')
    if (type(receipt) is not dict or set(receipt) != RECEIPT_KEYS or receipt['status'] != 'passed' or
            receipt['scope'] != PREPARE_SCOPE or receipt['workspace'] != str(tools) or
            type(receipt['version']) is not str or 'strace -- version 7.0' not in receipt['version'] or
            type(receipt['binary_sha256']) is not str or re.fullmatch(r'[0-9a-f]{64}', receipt['binary_sha256']) is None or
            receipt['repository_receipt_sha256'] != origin_sha or receipt['file_syscalls'] != FILE_SYSCALLS or
            receipt['execve_arguments_traced'] is not False or
            type(receipt['controlled_trace_sha256']) is not str or
            re.fullmatch(r'[0-9a-f]{64}', receipt['controlled_trace_sha256']) is None):
        _fail('file trace prepare receipt binding')
    dependencies = receipt['dependency_sha256']
    if type(dependencies) is not dict or not dependencies:
        _fail('file trace dependency receipt')
    binary = tools / 'root/usr/bin/strace'
    actual, _, _ = _hash_file(binary, 1024 ** 3)
    if actual != receipt['binary_sha256']:
        _fail('file trace client binary binding')
    for name, expected in dependencies.items():
        path = Path(name)
        if (not path.is_absolute() or path.is_symlink() or type(expected) is not str or
                re.fullmatch(r'[0-9a-f]{64}', expected) is None):
            _fail('file trace dependency path')
        actual, _, _ = _hash_file(path, 1024 ** 3)
        if actual != expected:
            _fail('file trace dependency hash')
    trace = tools / 'control.trace'
    trace_raw = _read_file(trace, 64 * 1024 ** 2)
    if (_sha(trace_raw) != receipt['controlled_trace_sha256'] or
            str(tools / 'read-control.txt') not in trace_raw.decode('utf-8', 'replace') or
            b'execve(' in trace_raw or b'execveat(' in trace_raw):
        _fail('file trace controlled trace binding')
    return receipt, trace


def _validate_environment_receipt(raw, workspace, environment_sha):
    try:
        receipt = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('file trace environment receipt JSON')
    if (type(receipt) is not dict or set(receipt) != ENVIRONMENT_RECEIPT_KEYS or
            receipt['status'] != 'passed' or receipt['scope'] != ENVIRONMENT_SCOPE or
            receipt['workspace'] != str(workspace) or type(receipt['trace_sha256']) is not str or
            re.fullmatch(r'[0-9a-f]{64}', receipt['trace_sha256']) is None or
            receipt['executed_probe_sha256'] != environment_sha):
        _fail('file trace environment receipt binding')
    trace_raw = _read_file(workspace / 'file.trace', 64 * 1024 ** 2)
    if _sha(trace_raw) != receipt['trace_sha256']:
        _fail('file trace environment trace binding')
    return receipt, trace_raw


def _copy_executed(control, source, name, expected):
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        _fail('file trace executed script')
    os.chmod(source, 0o400)
    raw, _ = _private_file(source, expected, mode=0o400)
    _write_private(control / name, raw)


def run_control(preflight, runner, fresh_owned_mounted_directory, commit, timeout):
    """Download the pinned tracing client and prove the two frozen controls."""
    if type(timeout) is not int or not 0 < timeout <= 180:
        _fail('file trace timeout')
    deadline = time.monotonic() + timeout
    mount_identity = _mount_identity(runner, fresh_owned_mounted_directory)[1]
    control = Path(fresh_owned_mounted_directory)
    if any(path.is_symlink() or path.exists() for path in control.iterdir()):
        _fail('file trace pre-existing files')
    helper_raw = preflight['committed_file'](ROOT, commit, PREPARE_RELATIVE)
    environment_raw = preflight['committed_file'](ROOT, commit, ENVIRONMENT_RELATIVE)
    manifest_raw = preflight['committed_file'](ROOT, commit, MANIFEST_RELATIVE)
    if (_sha(helper_raw) != PREPARE_SHA256 or _sha(environment_raw) != ENVIRONMENT_SHA256 or
            _sha(manifest_raw) != MANIFEST_SHA256):
        _fail('file trace input pin')
    manifest = _validate_manifest(manifest_raw)
    downloads = _mkdir_owned(control / 'downloads')
    environment_parent = _mkdir_owned(control / 'environment')
    tools = control / 'tools'
    prepare_path, environment_path, manifest_path = control / 'prepare.py', control / 'environment-probe.py', control / 'file-trace-download-pins-v1.json'
    prepare_input_path = control / 'prepare-input.py'
    environment_input_path = control / 'environment-probe-input.py'
    adapted_prepare = adapt_prepare(helper_raw, downloads, tools)
    adapted_environment = adapt_environment_probe(environment_raw, tools, environment_parent)
    _write_private(prepare_input_path, helper_raw)
    _write_private(environment_input_path, environment_raw)
    _write_private(prepare_path, adapted_prepare)
    _write_private(environment_path, adapted_environment)
    _write_private(manifest_path, manifest_raw)
    staged_identities = {
        prepare_input_path: _private_file(prepare_input_path, PREPARE_SHA256, mode=0o400)[1],
        environment_input_path: _private_file(environment_input_path, ENVIRONMENT_SHA256, mode=0o400)[1],
        prepare_path: _private_file(prepare_path, _sha(adapted_prepare), mode=0o400)[1],
        environment_path: _private_file(environment_path, _sha(adapted_environment), mode=0o400)[1],
        manifest_path: _private_file(manifest_path, MANIFEST_SHA256, mode=0o400)[1],
    }
    for row in manifest['packages']:
        _download(row['url'], downloads / row['file'], row['bytes'], row['sha256'], deadline)
    origin_receipt = dict(status='verified_download', scope=DOWNLOAD_SCOPE,
                          packages=manifest['packages'], repository_index=manifest['repository_index'])
    origin_raw = json.dumps(origin_receipt, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    _write_private(downloads / 'result.json', origin_raw)
    origin_sha = _sha(origin_raw)
    _validate_download_receipt(origin_raw, manifest, downloads, origin_sha)
    environment = _safe_environment(runner)
    prepare_log, environment_log = control / 'prepare.log', control / 'environment.log'
    _create_private_log(prepare_log)
    _create_private_log(environment_log)
    runner['run_command']('file trace prepare', [sys.executable, '-I', '-B', str(prepare_path)],
                          cwd=control, env=environment, timeout=_remaining(deadline),
                          log=prepare_log)
    if _mount_identity(runner, control)[1] != mount_identity:
        _fail('file trace mount changed')
    _private_file(prepare_log, mode=0o600)
    tools_result = tools / 'result.json'
    if tools.is_symlink() or not tools.is_dir() or tools_result.is_symlink() or not tools_result.is_file():
        _fail('file trace prepare output')
    tools_info, control_info = tools.stat(), control.stat()
    if (tools_info.st_uid != 65534 or tools_info.st_gid != 65534 or tools_info.st_mode & 0o777 != 0o700 or
            tools_info.st_dev != control_info.st_dev):
        _fail('file trace prepare workspace')
    os.chmod(tools_result, 0o400)
    prepare_receipt_raw, prepare_receipt_identity = _private_file(tools_result, mode=0o400)
    prepare_receipt, trace_raw = _validate_prepare_receipt(prepare_receipt_raw, tools, origin_sha)
    _copy_executed(control, tools / 'executed-prepare.py', 'executed-prepare.py', _sha(adapted_prepare))
    environment_workspace = None
    runner['run_command']('file trace environment', [sys.executable, '-I', '-B', str(environment_path)],
                          cwd=control, env=environment, timeout=_remaining(deadline),
                          log=environment_log)
    if _mount_identity(runner, control)[1] != mount_identity:
        _fail('file trace mount changed')
    _private_file(environment_log, mode=0o600)
    candidates = [path for path in environment_parent.iterdir()
                  if path.is_dir() and not path.is_symlink() and
                  path.name.startswith('m-local-trace-environment-control-')]
    if len(candidates) != 1 or len(list(environment_parent.iterdir())) != 1:
        _fail('file trace environment workspace')
    environment_workspace = candidates[0]
    if (len(environment_workspace.name) != len('m-local-trace-environment-control-') + 8 or
            re.fullmatch(r'[a-z0-9_]{8}', environment_workspace.name[-8:]) is None):
        _fail('file trace environment workspace name')
    workspace_info, control_info = environment_workspace.stat(), control.stat()
    if (workspace_info.st_uid != 65534 or workspace_info.st_gid != 65534 or
            workspace_info.st_mode & 0o777 != 0o700 or workspace_info.st_dev != control_info.st_dev):
        _fail('file trace environment workspace identity')
    environment_result = environment_workspace / 'result.json'
    if environment_result.is_symlink() or not environment_result.is_file():
        _fail('file trace environment output')
    os.chmod(environment_result, 0o400)
    environment_receipt_raw, environment_receipt_identity = _private_file(environment_result, mode=0o400)
    environment_receipt, _ = _validate_environment_receipt(environment_receipt_raw, environment_workspace,
                                                            _sha(adapted_environment))
    _copy_executed(control, environment_workspace / 'executed-probe.py',
                    'executed-environment-probe.py', _sha(adapted_environment))
    prepare_receipt_after, prepare_receipt_identity_after = _private_file(tools_result, mode=0o400)
    if (prepare_receipt_after != prepare_receipt_raw or
            prepare_receipt_identity_after != prepare_receipt_identity):
        _fail('file trace prepare receipt changed')
    _validate_prepare_receipt(prepare_receipt_raw, tools, origin_sha)
    environment_receipt_after, environment_receipt_identity_after = _private_file(environment_result, mode=0o400)
    if (environment_receipt_after != environment_receipt_raw or
            environment_receipt_identity_after != environment_receipt_identity):
        _fail('file trace environment receipt changed')
    _validate_environment_receipt(environment_receipt_raw, environment_workspace,
                                  _sha(adapted_environment))
    _private_file(control / 'executed-prepare.py', _sha(adapted_prepare), mode=0o400)
    _private_file(control / 'executed-environment-probe.py', _sha(adapted_environment), mode=0o400)
    staged_hashes = {prepare_input_path: PREPARE_SHA256, environment_input_path: ENVIRONMENT_SHA256,
                     prepare_path: _sha(adapted_prepare), environment_path: _sha(adapted_environment),
                     manifest_path: MANIFEST_SHA256}
    for path, identity in staged_identities.items():
        if _private_file(path, staged_hashes[path], mode=0o400)[1] != identity:
            _fail('file trace staged input identity')
    _private_file(prepare_path, _sha(adapted_prepare), mode=0o400)
    _private_file(environment_path, _sha(adapted_environment), mode=0o400)
    _private_file(manifest_path, MANIFEST_SHA256, mode=0o400)
    _validate_download_receipt(origin_raw, manifest, downloads, origin_sha)
    for relative, before in ((PREPARE_RELATIVE, helper_raw),
                             (ENVIRONMENT_RELATIVE, environment_raw),
                             (MANIFEST_RELATIVE, manifest_raw)):
        after = preflight['committed_file'](ROOT, commit, relative)
        if type(after) is not bytes or _sha(after) != _sha(before):
            _fail('file trace root input changed')
    if _mount_identity(runner, control)[1] != mount_identity:
        _fail('file trace mount changed')
    os.chmod(tools / 'control.trace', 0o400)
    os.chmod(environment_workspace / 'file.trace', 0o400)
    if _mount_identity(runner, control)[1] != mount_identity:
        _fail('file trace mount changed')
    _remaining(deadline)
    return dict(status='passed', trace_tools_directory=tools,
                environment_control_directory=environment_workspace,
                tracing_client_receipt_path=tools_result,
                tracing_client_receipt_sha256=_sha(prepare_receipt_raw),
                tracee_environment_receipt_path=environment_result,
                tracee_environment_receipt_sha256=_sha(environment_receipt_raw),
                client_binary_sha256=prepare_receipt['binary_sha256'],
                executed_prepare_sha256=_sha(adapted_prepare),
                executed_environment_probe_sha256=_sha(adapted_environment))
