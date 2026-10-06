#!/usr/bin/env python3
"""Prepare and verify the private PostgreSQL client prerequisite."""
from pathlib import Path
import hashlib
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).absolute().parents[1]
E_ROOT = Path('/var/tmp/m-local-build-e-drive-v2-01a1050e')
CONTROL_PREFIX = 'm-local-pg-client-control-v1-'
EXTRACTOR_RELATIVE = 'runtime-proof/native-inputs/extract-pg-client-v1.py'
MANIFEST_RELATIVE = 'runtime-proof/native-inputs/pg-client-download-pins-v1.json'
EXTRACTOR_SHA256 = '613690e6b45348e64d736c400b2273e6ff386cb3426c20e64da3aa5467f44e4d'
MANIFEST_SHA256 = '81d93240ca340937197838f2f942e269b78a47ec39cf15d2390c0c07c9ad63a2'
EXTRACTOR_SHA = EXTRACTOR_SHA256
MANIFEST_SHA = MANIFEST_SHA256
DOWNLOAD_SCOPE = 'Fixed official PGDG HTTPS archive bytes; extracted privately with no OS installation or database changes'
FROZEN_SCOPE = 'Extracted hash-verified official client tools only; no system package or database changes'
BINDING_SCOPE = 'Hash-bound private PostgreSQL client binaries, dependencies, versions, and dropped-privilege probes'
MAX_DOWNLOAD_BYTES = 64 * 1024 ** 2
PACKAGE_KEYS = {'architecture', 'bytes', 'file', 'package', 'sha256', 'url', 'version'}
MANIFEST_KEYS = {'packages', 'repository_documentation', 'repository_index', 'schema', 'scope', 'status', 'version'}
FROZEN_KEYS = {'status', 'scope', 'workspace', 'package_index_sha256', 'package_version', 'tools'}
FROZEN_TOOL_KEYS = {'name', 'version', 'sha256'}
PROBE_KEYS = {'status', 'workspace', 'uid', 'gid', 'supplementary_groups', 'tools'}
PROBE_TOOL_KEYS = {'name', 'version'}
FILE_NAMES = ('psql', 'pg_dump', 'pg_restore')
PACKAGE_PINS = {
    'libpq5': (264072, 'libpq5_18.6-1.pgdg24.04+2_amd64.deb', '18.6-1.pgdg24.04+2',
               'b487c5ed2ceb9244c6a9d6ae65818ed6707c3c44a2e14488394ae4194c52c53b',
               'https://apt.postgresql.org/pub/repos/apt/pool/main/p/postgresql-18/libpq5_18.6-1.pgdg24.04+2_amd64.deb'),
    'postgresql-client-18': (2114236, 'postgresql-client-18_18.6-1.pgdg24.04+2_amd64.deb', '18.6-1.pgdg24.04+2',
                             'b9d10d99a73bf7aa375be2fe36626c40499cfdf553d0ad174674a88a1b256b43',
                             'https://apt.postgresql.org/pub/repos/apt/pool/main/p/postgresql-18/postgresql-client-18_18.6-1.pgdg24.04+2_amd64.deb'),
}
INDEX_PIN = (1193489, '76f88d168136f48e7375f4af4f78abc04969aee357633f622ece00aca04521dd',
             'https://apt.postgresql.org/pub/repos/apt/dists/noble-pgdg/main/binary-amd64/Packages.gz')
REPOSITORY_DOCUMENTATION = 'https://www.postgresql.org/download/linux/ubuntu/'
VERSION_PROBE_SOURCE = b'''from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

os.umask(0o077)
root = Path(sys.argv[1])
output = Path(sys.argv[2])
tools = [Path(value) for value in sys.argv[3:]]
os.setgroups([])
os.setgid(65534)
os.setuid(65534)
assert os.getuid() == 65534 and os.getgid() == 65534 and os.getgroups() == []
env = dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8',
           LD_LIBRARY_PATH=str(root / 'root/usr/lib/x86_64-linux-gnu'))
rows = []
for path in tools:
    assert path.parent == root / 'root/usr/lib/postgresql/18/bin'
    version = subprocess.check_output([str(path), '--version'], env=env, text=True,
                                      stderr=subprocess.STDOUT).strip()
    assert '(PostgreSQL) 18.6 ' in version
    rows.append(dict(name=path.name, version=version))
result = dict(status='passed', workspace=str(root), uid=os.getuid(), gid=os.getgid(),
              supplementary_groups=os.getgroups(), tools=rows)
output.write_text(json.dumps(result, sort_keys=True) + chr(10))
print(json.dumps(result))
'''


def _fail(label):
    raise ValueError(label)


def _sha(raw):
    if type(raw) is not bytes:
        _fail('pg client bytes')
    return hashlib.sha256(raw).hexdigest()


def _hash_file(path, maximum=MAX_DOWNLOAD_BYTES):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_size <= 0 or info.st_size > maximum):
        _fail('pg client regular file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        stream = os.fdopen(os.open(path, flags), 'rb')
    except OSError:
        _fail('pg client file open')
    digest, total = hashlib.sha256(), 0
    with stream:
        opened = os.fstat(stream.fileno())
        while True:
            chunk = stream.read(1024 ** 2)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                _fail('pg client file bound')
            digest.update(chunk)
        closed = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_uid', 'st_gid', 'st_nlink')
    if (total != info.st_size or any(getattr(item, field) != getattr(info, field)
            for item in (opened, closed) for field in fields)):
        _fail('pg client file changed')
    return digest.hexdigest(), total, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                                      info.st_mode, info.st_uid, info.st_gid, info.st_nlink)


def _read_file(path, maximum=MAX_DOWNLOAD_BYTES):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_size <= 0 or info.st_size > maximum):
        _fail('pg client read regular file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        stream = os.fdopen(os.open(path, flags), 'rb')
    except OSError:
        _fail('pg client read open')
    with stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(maximum + 1)
        closed = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_uid', 'st_gid', 'st_nlink')
    if (len(raw) != info.st_size or any(getattr(item, field) != getattr(info, field)
            for item in (opened, closed) for field in fields)):
        _fail('pg client read changed')
    return raw


def _private_file(path, expected=None, mode=None):
    path = Path(path)
    info = path.lstat()
    modes = (0o400, 0o600) if mode is None else (mode,)
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o777 not in modes):
        _fail('pg client private file')
    raw = _read_file(path)
    if expected is not None and _sha(raw) != expected:
        _fail('pg client private hash')
    identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode,
                info.st_uid, info.st_gid, info.st_nlink)
    return raw, identity


def _write_private(path, raw, mode=0o400):
    path = Path(path)
    try:
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(path, 0, 0)
        os.chmod(path, mode)
    except OSError:
        _fail('pg client private create')
    _private_file(path, _sha(raw), mode=mode)


def _create_private_log(path):
    path = Path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        os.close(descriptor)
        os.chown(path, 0, 0)
        os.chmod(path, 0o600)
    except OSError:
        _fail('pg client private log create')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or
            info.st_mode & 0o777 != 0o600 or info.st_nlink != 1 or info.st_size != 0):
        _fail('pg client private log identity')


def _mkdir_owned(path):
    path = Path(path)
    if path.exists() or path.is_symlink():
        _fail('pg client pre-existing directory')
    try:
        path.mkdir(mode=0o700)
        os.chown(path, 65534, 65534)
        os.chmod(path, 0o700)
    except OSError:
        _fail('pg client directory create')
    return path


def _private_path(*paths):
    values = tuple(map(Path, paths))
    if any(not path.is_absolute() or path.resolve() != path for path in values):
        _fail('pg client private path')
    return values


def _dropped_file(path, label):
    digest, _, identity = _hash_file(path)
    if (identity[4] & 0o777 != 0o600 or identity[5] != 65534 or
            identity[6] != 65534 or identity[7] != 1):
        _fail(label)
    return digest, identity


def _replace_once(raw, marker, replacement, label):
    if raw.count(marker) != 1:
        _fail(label)
    return raw.replace(marker, replacement)


def adapt_extractor(raw, origin, directory):
    if type(raw) is not bytes or _sha(raw) != EXTRACTOR_SHA256:
        _fail('pg client extractor pin')
    origin, directory = _private_path(origin, directory)
    adapted = _replace_once(raw,
        b"control = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/pg-client-control-v1')",
        b'control = Path(' + repr(str(origin)).encode() + b')', 'pg client control binding')
    adapted = _replace_once(adapted,
        b"directory = Path('/var/tmp/m-local-kali-pg-client-01a1050e')",
        b'directory = Path(' + repr(str(directory)).encode() + b')', 'pg client tools binding')
    if (b'/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/pg-client-control-v1' in adapted or
            b'/var/tmp/m-local-kali-pg-client-01a1050e' in adapted):
        _fail('pg client legacy binding')
    return adapted


def _mount_identity(runner, directory):
    directory = Path(directory)
    e_root = Path(runner.get('E_ROOT', E_ROOT))
    var_tmp = Path('/var/tmp')
    if (not directory.is_absolute() or directory.parent != var_tmp or
            not directory.name.startswith(CONTROL_PREFIX) or len(directory.name) != len(CONTROL_PREFIX) + 8 or
            directory.resolve() != directory or directory.is_symlink() or not directory.is_mount() or
            var_tmp.is_symlink() or not e_root.is_absolute() or e_root.resolve() != e_root or
            e_root.is_symlink() or not e_root.is_mount()):
        _fail('pg client mount path')
    root_info, mounted_info = e_root.stat(), directory.stat()
    backing = e_root / directory.name
    if backing.is_symlink() or backing.resolve() != backing or not backing.is_dir():
        _fail('pg client mount backing')
    backing_info, var_info = backing.stat(), var_tmp.stat()
    if (any(item.st_uid != 65534 or item.st_gid != 65534 or item.st_mode & 0o777 != 0o700
            for item in (root_info, mounted_info, backing_info)) or root_info.st_dev == var_info.st_dev or
            mounted_info.st_dev != root_info.st_dev or
            (mounted_info.st_dev, mounted_info.st_ino) != (backing_info.st_dev, backing_info.st_ino)):
        _fail('pg client mount identity')
    return e_root, (mounted_info.st_dev, mounted_info.st_ino, mounted_info.st_uid,
                    mounted_info.st_gid, mounted_info.st_mode & 0o777)


def _safe_environment(runner):
    environment = dict(runner['minimal_environment']())
    for key in list(environment):
        upper = key.upper()
        if (upper.endswith('_PROXY') or any(word in upper for word in
                ('TOKEN', 'PASSWORD', 'PASSWD', 'SECRET', 'CREDENTIAL', 'AUTH')) or
                key in {'PIP_INDEX_URL', 'PIP_EXTRA_INDEX_URL', 'NETRC'}):
            environment.pop(key, None)
    return environment


def _download_url(url):
    if type(url) is not str:
        _fail('pg client download URL')
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'apt.postgresql.org' or
            parsed.username is not None or parsed.password is not None or parsed.query or
            parsed.fragment or parsed.port is not None):
        _fail('pg client download URL')


class _PinnedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        _download_url(newurl)
        return super().redirect_request(request, file, code, message, headers, newurl)


def _remaining(deadline):
    value = int(deadline - time.monotonic())
    if value <= 0:
        _fail('pg client deadline')
    return value


def _download(url, destination, expected_bytes, expected_sha256, deadline):
    _download_url(url)
    if type(expected_bytes) is not int or expected_bytes <= 0 or expected_bytes > MAX_DOWNLOAD_BYTES:
        _fail('pg client download size')
    if type(expected_sha256) is not str or re.fullmatch(r'[0-9a-f]{64}', expected_sha256) is None:
        _fail('pg client download hash')
    if destination.exists() or destination.is_symlink():
        _fail('pg client download overwrite')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedRedirectHandler())
    request = urllib.request.Request(url, headers={'User-Agent': 'm-local-pg-client-control/1'})
    try:
        response = opener.open(request, timeout=min(25, _remaining(deadline)))
    except (OSError, urllib.error.URLError):
        _fail('pg client download unavailable')
    try:
        with response:
            _download_url(response.geturl())
            status = getattr(response, 'status', None)
            if status is not None and status != 200:
                _fail('pg client download status')
            length = getattr(getattr(response, 'headers', None), 'get', lambda *_: None)('Content-Length')
            if length is not None and length != str(expected_bytes):
                _fail('pg client download length')
            reader = getattr(response, 'read1', None)
            if not callable(reader):
                _fail('pg client download read1')
            digest, total = hashlib.sha256(), 0
            with destination.open('xb') as stream:
                while True:
                    _remaining(deadline)
                    chunk = reader(min(1024 ** 2, expected_bytes + 1 - total))
                    _remaining(deadline)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > expected_bytes:
                        _fail('pg client download bound')
                    digest.update(chunk)
                    stream.write(chunk)
                _remaining(deadline)
                stream.flush()
                os.fsync(stream.fileno())
    except (OSError, urllib.error.URLError):
        _fail('pg client download read')
    if total != expected_bytes or digest.hexdigest() != expected_sha256:
        _fail('pg client download digest')
    os.chown(destination, 0, 0)
    os.chmod(destination, 0o400)
    _private_file(destination, expected_sha256, mode=0o400)


def _validate_manifest(raw):
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('pg client manifest JSON')
    if (type(manifest) is not dict or set(manifest) != MANIFEST_KEYS or
            manifest['schema'] != 'm-local-pg-client-download-pins-v1' or
            manifest['scope'] != DOWNLOAD_SCOPE or manifest['status'] != 'declared_before_extraction' or
            manifest['version'] != '18.6-1.pgdg24.04+2' or
            manifest['repository_documentation'] != REPOSITORY_DOCUMENTATION):
        _fail('pg client manifest schema')
    packages = manifest['packages']
    if type(packages) is not list or len(packages) != 2:
        _fail('pg client manifest packages')
    for row in packages:
        if type(row) is not dict or set(row) != PACKAGE_KEYS:
            _fail('pg client package schema')
        if (row['package'] not in PACKAGE_PINS or row['architecture'] != 'amd64' or
                type(row['bytes']) is not int or type(row['file']) is not str or
                Path(row['file']).name != row['file'] or type(row['version']) is not str or
                type(row['url']) is not str or re.fullmatch(r'[0-9a-f]{64}', row['sha256']) is None):
            _fail('pg client package binding')
        if (row['bytes'], row['file'], row['version'], row['sha256'], row['url']) != PACKAGE_PINS[row['package']]:
            _fail('pg client package pin')
        parsed = urllib.parse.urlparse(row['url'])
        if (parsed.scheme != 'https' or parsed.hostname != 'apt.postgresql.org' or parsed.username is not None or
                parsed.password is not None or parsed.query or parsed.fragment or parsed.port is not None or
                Path(parsed.path).name != row['file']):
            _fail('pg client package URL')
    if {row['package'] for row in packages} != set(PACKAGE_PINS):
        _fail('pg client package identity')
    index = manifest['repository_index']
    if (type(index) is not dict or set(index) != {'bytes', 'sha256', 'url'} or
            type(index['bytes']) is not int or type(index['url']) is not str or
            re.fullmatch(r'[0-9a-f]{64}', index['sha256']) is None or
            (index['bytes'], index['sha256'], index['url']) != INDEX_PIN):
        _fail('pg client index pin')
    _download_url(index['url'])
    return manifest


def _validate_origin(raw, manifest, downloads, expected_sha):
    try:
        receipt = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('pg client origin JSON')
    expected_keys = {'status', 'scope', 'packages', 'index_sha256', 'version',
                     'repository_index_provenance', 'repository_index_downloaded'}
    if (type(receipt) is not dict or set(receipt) != expected_keys or receipt['status'] != 'verified_download' or
            receipt['scope'] != DOWNLOAD_SCOPE or receipt['packages'] != manifest['packages'] or
            receipt['index_sha256'] != manifest['repository_index']['sha256'] or
            receipt['version'] != manifest['version'] or
            receipt['repository_index_provenance'] != manifest['repository_index'] or
            receipt['repository_index_downloaded'] is not False or _sha(raw) != expected_sha):
        _fail('pg client origin binding')
    for row in manifest['packages']:
        actual, size, _ = _hash_file(downloads / row['file'])
        if actual != row['sha256'] or size != row['bytes']:
            _fail('pg client archive binding')
    return receipt


def _owned_directory(path, control):
    info, base = Path(path).stat(), Path(control).stat()
    if (info.st_uid != 65534 or info.st_gid != 65534 or info.st_mode & 0o777 != 0o700 or
            info.st_dev != base.st_dev or Path(path).is_symlink()):
        _fail('pg client workspace identity')


def _validate_frozen_receipt(raw, clients, manifest):
    try:
        receipt = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('pg client frozen receipt JSON')
    if (type(receipt) is not dict or set(receipt) != FROZEN_KEYS or receipt['status'] != 'passed' or
            receipt['scope'] != FROZEN_SCOPE or receipt['workspace'] != str(clients) or
            receipt['package_index_sha256'] != manifest['repository_index']['sha256'] or
            receipt['package_version'] != manifest['version'] or type(receipt['tools']) is not list or
            len(receipt['tools']) != 3):
        _fail('pg client frozen receipt binding')
    names = [row.get('name') if type(row) is dict else None for row in receipt['tools']]
    if names != list(FILE_NAMES):
        _fail('pg client frozen tool identity')
    tool_hashes = {}
    for row in receipt['tools']:
        if (set(row) != FROZEN_TOOL_KEYS or type(row['version']) is not str or
                '(PostgreSQL) 18.6 ' not in row['version'] or
                type(row['sha256']) is not str or re.fullmatch(r'[0-9a-f]{64}', row['sha256']) is None):
            _fail('pg client frozen tool fields')
        path = clients / 'root/usr/lib/postgresql/18/bin' / row['name']
        actual, _, _ = _hash_file(path, 1024 ** 3)
        if actual != row['sha256']:
            _fail('pg client frozen tool hash')
        tool_hashes[row['name']] = actual
    return receipt, tool_hashes


def _parse_ldd(raw, clients, tool):
    text = raw.decode('utf-8', 'replace')
    if not text.strip() or 'not found' in text:
        _fail('pg client dependency resolution')
    paths = []
    for token in re.findall(r'(?<![\w])(/[A-Za-z0-9._+:/-]+)', text):
        path = Path(token)
        if path.is_symlink():
            path = path.resolve()
        if path not in paths and path.is_file() and not path.is_symlink() and path.resolve() == path:
            paths.append(path)
    if not paths:
        _fail('pg client dependency paths')
    private_root = (clients / 'root').resolve()
    if not any('libpq.so' in path.name and private_root in path.parents for path in paths):
        _fail('pg client private libpq binding')
    result = {}
    for path in paths:
        actual, _, _ = _hash_file(path, 1024 ** 3)
        result[str(path)] = actual
    return result


def _validate_log(path):
    return _private_file(path, mode=0o600)


def _validate_probe(raw, clients, manifest):
    try:
        receipt = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('pg client probe JSON')
    if (type(receipt) is not dict or set(receipt) != PROBE_KEYS or receipt['status'] != 'passed' or
            receipt['workspace'] != str(clients) or receipt['uid'] != 65534 or receipt['gid'] != 65534 or
            receipt['supplementary_groups'] != [] or type(receipt['tools']) is not list or
            [row.get('name') if type(row) is dict else None for row in receipt['tools']] != list(FILE_NAMES)):
        _fail('pg client probe binding')
    versions = {}
    for row in receipt['tools']:
        if (set(row) != PROBE_TOOL_KEYS or type(row['version']) is not str or
                '(PostgreSQL) 18.6 ' not in row['version']):
            _fail('pg client probe tool')
        versions[row['name']] = row['version']
    return receipt, versions


def run_control(preflight, runner, fresh_owned_mounted_directory, commit, timeout):
    """Download, extract, and bind the frozen PostgreSQL client prerequisite."""
    if type(timeout) is not int or not 0 < timeout <= 180:
        _fail('pg client timeout')
    deadline = time.monotonic() + timeout
    mount_identity = _mount_identity(runner, fresh_owned_mounted_directory)[1]
    control = Path(fresh_owned_mounted_directory)
    if any(path.exists() or path.is_symlink() for path in control.iterdir()):
        _fail('pg client pre-existing files')
    extractor_raw = preflight['committed_file'](ROOT, commit, EXTRACTOR_RELATIVE)
    manifest_raw = preflight['committed_file'](ROOT, commit, MANIFEST_RELATIVE)
    if _sha(extractor_raw) != EXTRACTOR_SHA256 or _sha(manifest_raw) != MANIFEST_SHA256:
        _fail('pg client input pin')
    manifest = _validate_manifest(manifest_raw)
    downloads = _mkdir_owned(control / 'downloads')
    clients = control / 'clients'
    extractor_path = control / 'extract-pg-client.py'
    extractor_input_path = control / 'extract-pg-client-input.py'
    manifest_path = control / 'pg-client-download-pins-v1.json'
    adapted = adapt_extractor(extractor_raw, downloads, clients)
    _write_private(extractor_input_path, extractor_raw)
    _write_private(extractor_path, adapted)
    _write_private(manifest_path, manifest_raw)
    staged = {extractor_input_path: EXTRACTOR_SHA256, extractor_path: _sha(adapted),
              manifest_path: MANIFEST_SHA256}
    identities = {path: _private_file(path, expected, mode=0o400)[1] for path, expected in staged.items()}
    for row in manifest['packages']:
        _download(row['url'], downloads / row['file'], row['bytes'], row['sha256'], deadline)
    origin = dict(status='verified_download', scope=DOWNLOAD_SCOPE, packages=manifest['packages'],
                  index_sha256=manifest['repository_index']['sha256'], version=manifest['version'],
                  repository_index_provenance=manifest['repository_index'], repository_index_downloaded=False)
    origin_raw = json.dumps(origin, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    _write_private(downloads / 'result.json', origin_raw)
    origin_sha = _sha(origin_raw)
    _validate_origin(origin_raw, manifest, downloads, origin_sha)
    logs = [control / 'extract.log', control / 'ldd-psql.log', control / 'ldd-pg_dump.log',
            control / 'ldd-pg_restore.log', control / 'version-probe.log']
    for path in logs:
        _create_private_log(path)
    environment = _safe_environment(runner)
    runner['run_command']('pg client extract', [sys.executable, '-I', '-B', str(extractor_path)],
                          cwd=control, env=environment, timeout=_remaining(deadline), log=logs[0])
    if _mount_identity(runner, control)[1] != mount_identity:
        _fail('pg client mount changed')
    _validate_log(logs[0])
    if not clients.is_dir() or clients.is_symlink():
        _fail('pg client workspace')
    _owned_directory(clients, control)
    private_root = clients / 'root'
    client_environment = dict(environment)
    client_environment.update(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8',
                              LD_LIBRARY_PATH=str(private_root / 'usr/lib/x86_64-linux-gnu'))
    receipt_path = clients / 'result.json'
    if receipt_path.is_symlink() or not receipt_path.is_file():
        _fail('pg client frozen receipt')
    _, receipt_identity_before = _dropped_file(receipt_path, 'pg client frozen receipt identity')
    frozen_raw = _read_file(receipt_path)
    frozen_receipt, frozen_tool_hashes = _validate_frozen_receipt(frozen_raw, clients, manifest)
    _, receipt_identity_after = _dropped_file(receipt_path, 'pg client frozen receipt identity')
    if receipt_identity_after != receipt_identity_before:
        _fail('pg client frozen receipt changed')
    os.chown(receipt_path, 0, 0)
    os.chmod(receipt_path, 0o400)
    frozen_raw, frozen_identity = _private_file(receipt_path, _sha(frozen_raw), mode=0o400)
    dependency_hashes = {}
    for name, log in zip(FILE_NAMES, logs[1:4]):
        tool = private_root / 'usr/lib/postgresql/18/bin' / name
        runner['run_command']('pg client ldd ' + name, ['/usr/bin/ldd', str(tool)], cwd=clients,
                              env=client_environment, timeout=_remaining(deadline), log=log)
        ldd_raw, _ = _validate_log(log)
        dependency_hashes[name] = _parse_ldd(ldd_raw, clients, tool)
    probe_path = control / 'pg-client-version-probe.py'
    probe_output = clients / 'version-probe.json'
    if probe_output.exists() or probe_output.is_symlink():
        _fail('pg client probe overwrite')
    _write_private(probe_path, VERSION_PROBE_SOURCE)
    runner['run_command']('pg client version probe', [sys.executable, '-I', '-B', str(probe_path), str(clients),
                          str(probe_output), *(str(private_root / 'usr/lib/postgresql/18/bin' / name) for name in FILE_NAMES)],
                          cwd=control, env=client_environment, timeout=_remaining(deadline), log=logs[4])
    if _mount_identity(runner, control)[1] != mount_identity:
        _fail('pg client mount changed')
    _validate_log(logs[4])
    _, probe_identity = _dropped_file(probe_output, 'pg client probe identity')
    probe_raw = _read_file(probe_output)
    probe_receipt, versions = _validate_probe(probe_raw, clients, manifest)
    if _dropped_file(probe_output, 'pg client probe identity')[1] != probe_identity:
        _fail('pg client probe changed')
    os.chown(probe_output, 0, 0)
    os.chmod(probe_output, 0o400)
    _private_file(probe_output, _sha(probe_raw), mode=0o400)
    for path, expected in staged.items():
        if _private_file(path, expected, mode=0o400)[1] != identities[path]:
            _fail('pg client staged input identity')
    if _private_file(extractor_path, _sha(adapted), mode=0o400)[0] != adapted:
        _fail('pg client extractor changed')
    executed_path = control / 'executed-extract-pg-client.py'
    _write_private(executed_path, adapted)
    _private_file(executed_path, _sha(adapted), mode=0o400)
    final_tool_hashes = {}
    final_dependencies = {}
    for name in FILE_NAMES:
        tool = private_root / 'usr/lib/postgresql/18/bin' / name
        actual, _, _ = _hash_file(tool, 1024 ** 3)
        if actual != frozen_tool_hashes[name]:
            _fail('pg client tool changed')
        final_tool_hashes[name] = actual
        final_dependencies[name] = {}
        for path, expected in dependency_hashes[name].items():
            actual, _, _ = _hash_file(path, 1024 ** 3)
            if actual != expected:
                _fail('pg client dependency changed')
            final_dependencies[name][path] = actual
    binding = dict(status='passed', scope=BINDING_SCOPE, workspace=str(clients),
                   frozen_receipt_sha256=_sha(frozen_raw), version_probe_sha256=_sha(probe_raw),
                   tool_binary_sha256=final_tool_hashes, dependency_sha256=final_dependencies,
                   versions=versions, uid=65534, gid=65534, supplementary_groups=[])
    binding_raw = json.dumps(binding, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    binding_path = control / 'binding-receipt.json'
    _write_private(binding_path, binding_raw)
    _private_file(binding_path, _sha(binding_raw), mode=0o400)
    for log in logs:
        _validate_log(log)
    if _private_file(receipt_path, _sha(frozen_raw), mode=0o400)[1] != frozen_identity:
        _fail('pg client frozen receipt changed')
    if _mount_identity(runner, control)[1] != mount_identity:
        _fail('pg client mount changed')
    _remaining(deadline)
    return dict(status='passed', clients_directory=clients, frozen_receipt_path=receipt_path,
                frozen_receipt_sha256=_sha(frozen_raw), binding_receipt_path=binding_path,
                binding_receipt_sha256=_sha(binding_raw), executed_extractor_sha256=_sha(adapted),
                tool_binary_sha256=final_tool_hashes, dependency_sha256=final_dependencies)
