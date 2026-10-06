#!/usr/bin/env python3
"""Prepare and verify the private Node.js client prerequisite."""
from pathlib import Path
import hashlib
import json
import os
import posixpath
import re
import stat
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).absolute().parents[1]
E_ROOT = Path('/var/tmp/m-local-build-e-drive-v2-01a1050e')
CONTROL_PREFIX = 'm-local-node-client-control-v1-'
PREPARE_RELATIVE = 'runtime-proof/native-inputs/prepare-node-client-v1.py'
MANIFEST_RELATIVE = 'runtime-proof/native-inputs/node-client-download-pins-v1.json'
PREPARE_SHA256 = 'c6e41ddd4f43460f73c81046412d6ecaac56a4651566e744d87686560cd41bf9'
MANIFEST_SHA256 = 'e328e11253f55f6edd4e66e91e57c1c11f544c8678e62e498f9115ba8aeb8708'
PREPARE_SHA = PREPARE_SHA256
MANIFEST_SHA = MANIFEST_SHA256
NODE_VERSION = '22.16.0'
NPM_VERSION = '10.9.2'
COREPACK_VERSION = '0.32.0'
PREPARE_SCOPE = 'Fixed official Node.js test-tool archive; private extraction only, with no application runtime or system installation change'
FROZEN_SCOPE = 'Prepared hash-verified official Node.js client tools only; no system package or application runtime change'
BINDING_SCOPE = 'Hash-bound private Node.js client binaries, dependencies, versions, inventory, and dropped-privilege probe'
PROVENANCE = 'Exact test-tool version matching the installed Windows Node; archive matches official HTTPS SHA-256 manifest. Not an application dependency or production runtime change.'
MAX_DOWNLOAD_BYTES = 64 * 1024 ** 2
MAX_MEMBER_BYTES = 256 * 1024 ** 2
MAX_EXPANDED_BYTES = 256 * 1024 ** 2
EXPECTED_MEMBER_COUNT = 5928
EXPECTED_DIRECTORY_COUNT = 1118
EXPECTED_FILE_COUNT = 4807
EXPECTED_SYMLINK_COUNT = 3
MANIFEST_KEYS = {'archive', 'checksums', 'release_documentation', 'schema', 'scope', 'status', 'version', 'npm_version'}
ASSET_KEYS = {'bytes', 'file', 'sha256', 'url'}
PROBE_KEYS = {'status', 'workspace', 'uid', 'gid', 'supplementary_groups', 'tools', 'js_smoke'}
PROBE_TOOL_KEYS = {'name', 'version'}
TOOL_NAMES = ('node', 'npm', 'npx', 'corepack')
ARCHIVE_PIN = (30425588, 'node-v22.16.0-linux-x64.tar.xz',
               'f4cb75bb036f0d0eddf6b79d9596df1aaab9ddccd6a20bf489be5abe9467e84e',
               'https://nodejs.org/dist/v22.16.0/node-v22.16.0-linux-x64.tar.xz')
CHECKSUM_PIN = (3777, 'SHASUMS256.txt',
                'e1f5ad5e2a5654721e7b89d84d27f406e582c46ca0b5cde304c5dcdd7bab8b31',
                'https://nodejs.org/dist/v22.16.0/SHASUMS256.txt')
RELEASE_DOCUMENTATION = 'https://nodejs.org/en/blog/release/v22.16.0'
VERSION_PROBE_SOURCE = b'''from pathlib import Path
import json
import os
import subprocess
import sys

os.umask(0o077)
root = Path(sys.argv[1])
output = Path(sys.argv[2])
node, npm, npx, corepack = (Path(value) for value in sys.argv[3:])
os.setgroups([])
os.setgid(65534)
os.setuid(65534)
assert os.getuid() == 65534 and os.getgid() == 65534 and os.getgroups() == []
env = dict(PATH=str(root / 'bin') + ':/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8',
           LC_ALL='C.UTF-8', COREPACK_ENABLE_NETWORK='0', npm_config_offline='true',
           NPM_CONFIG_USERCONFIG='/dev/null')
commands = ((node, '--version'), (npm, '--version'), (npx, '--version'), (corepack, '--version'))
rows = []
for path, argument in commands:
    assert path.parent == root / 'bin'
    version = subprocess.check_output([str(path), argument], env=env, text=True,
                                      stderr=subprocess.STDOUT).strip()
    rows.append(dict(name=path.name, version=version))
smoke = subprocess.check_output(
    [str(node), '-e', "process.stdout.write(JSON.stringify({node:process.version,ok:1}))"],
    env=env, text=True, stderr=subprocess.STDOUT).strip()
assert smoke == '{"node":"v22.16.0","ok":1}'
result = dict(status='passed', workspace=str(root), uid=os.getuid(), gid=os.getgid(),
              supplementary_groups=os.getgroups(), tools=rows, js_smoke=smoke)
output.write_text(json.dumps(result, sort_keys=True) + chr(10))
print(json.dumps(result))
'''


def _fail(label):
    raise ValueError(label)


def _sha(raw):
    if type(raw) is not bytes:
        _fail('node client bytes')
    return hashlib.sha256(raw).hexdigest()


def _hash_file(path, maximum=MAX_MEMBER_BYTES, allow_empty=False):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            (info.st_size <= 0 and not allow_empty) or info.st_size > maximum):
        _fail('node client regular file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        stream = os.fdopen(os.open(path, flags), 'rb')
    except OSError:
        _fail('node client file open')
    digest, total = hashlib.sha256(), 0
    with stream:
        opened = os.fstat(stream.fileno())
        while True:
            chunk = stream.read(1024 ** 2)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                _fail('node client file bound')
            digest.update(chunk)
        closed = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_uid', 'st_gid', 'st_nlink')
    if (total != info.st_size or any(getattr(item, field) != getattr(info, field)
            for item in (opened, closed) for field in fields)):
        _fail('node client file changed')
    return digest.hexdigest(), total, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                                      info.st_mode, info.st_uid, info.st_gid, info.st_nlink)


def _read_file(path, maximum=MAX_MEMBER_BYTES):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_size <= 0 or info.st_size > maximum):
        _fail('node client read regular file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        stream = os.fdopen(os.open(path, flags), 'rb')
    except OSError:
        _fail('node client read open')
    with stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(maximum + 1)
        closed = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_uid', 'st_gid', 'st_nlink')
    if (len(raw) != info.st_size or any(getattr(item, field) != getattr(info, field)
            for item in (opened, closed) for field in fields)):
        _fail('node client read changed')
    return raw


def _private_file(path, expected=None, mode=None):
    path = Path(path)
    info = path.lstat()
    modes = (0o400, 0o600) if mode is None else (mode,)
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o777 not in modes):
        _fail('node client private file')
    raw = _read_file(path)
    if expected is not None and _sha(raw) != expected:
        _fail('node client private hash')
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
        _fail('node client private create')
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
        _fail('node client private log create')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or
            info.st_mode & 0o777 != 0o600 or info.st_nlink != 1 or info.st_size != 0):
        _fail('node client private log identity')


def _mkdir_owned(path):
    path = Path(path)
    if path.exists() or path.is_symlink():
        _fail('node client pre-existing directory')
    try:
        path.mkdir(mode=0o700)
        os.chown(path, 65534, 65534)
        os.chmod(path, 0o700)
    except OSError:
        _fail('node client directory create')
    return path


def _private_path(*paths):
    values = tuple(map(Path, paths))
    if any(not path.is_absolute() or path.resolve() != path for path in values):
        _fail('node client private path')
    return values


def _dropped_file(path, label, mode=0o600):
    digest, _, identity = _hash_file(path)
    if (identity[4] & 0o777 != mode or identity[5] != 65534 or
            identity[6] != 65534 or identity[7] != 1):
        _fail(label)
    return digest, identity


def _replace_once(raw, marker, replacement, label):
    if raw.count(marker) != 1:
        _fail(label)
    return raw.replace(marker, replacement)


def adapt_prepare(raw, assets):
    if type(raw) is not bytes or _sha(raw) != PREPARE_SHA256:
        _fail('node client prepare pin')
    (assets,) = _private_path(assets)
    adapted = _replace_once(raw,
        b"assets = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/client-tools')",
        b'assets = Path(' + repr(str(assets)).encode() + b')', 'node client assets binding')
    adapted = _replace_once(adapted,
        b"origin = f'https://nodejs.org/dist/v{version}/'",
        b'origin = None', 'node client origin binding')
    adapted = _replace_once(adapted,
        b"checks = urllib.request.urlopen(origin + 'SHASUMS256.txt', timeout=30).read()",
        b"checks = (assets / 'official-checksums.txt').read_bytes()", 'node client checks binding')
    network_block = b"""if not archive.exists():
    with urllib.request.urlopen(origin + name, timeout=30) as response, archive.open('xb') as stream:
        while data := response.read(1024 * 1024):
            stream.write(data)"""
    local_block = b"""assert archive.is_file() and not archive.is_symlink()
with archive.open('rb') as response:
    while response.read(1024 * 1024):
        pass"""
    adapted = _replace_once(adapted, network_block, local_block, 'node client archive binding')
    adapted = adapted.replace(b'import urllib.request\n', b'import urllib.request\nimport os\n', 1)
    adapted = _replace_once(adapted, b"assets = Path(",
                            b"os.umask(0o077)\nos.setgroups([])\nos.setgid(65534)\nos.setuid(65534)\nassert os.getuid() == 65534 and os.getgid() == 65534 and os.getgroups() == []\nassets = Path(",
                            'node client privilege binding')
    if (b'urllib.request.urlopen' in adapted or
            b'/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/client-tools' in adapted or
            b'https://nodejs.org/dist/' in adapted):
        _fail('node client legacy binding')
    return adapted


def _mount_identity(runner, directory):
    directory = Path(directory)
    e_root = Path(runner.get('E_ROOT', E_ROOT))
    var_tmp = Path('/var/tmp')
    suffix = directory.name[len(CONTROL_PREFIX):] if directory.name.startswith(CONTROL_PREFIX) else ''
    if (not directory.is_absolute() or directory.parent != var_tmp or
            not directory.name.startswith(CONTROL_PREFIX) or len(suffix) != 8 or
            re.fullmatch(r'[A-Za-z0-9_]{8}', suffix) is None or directory.resolve() != directory or
            directory.is_symlink() or not directory.is_mount() or var_tmp.is_symlink() or
            not e_root.is_absolute() or e_root.resolve() != e_root or e_root.is_symlink() or
            not e_root.is_mount()):
        _fail('node client mount path')
    root_info, mounted_info = e_root.stat(), directory.stat()
    backing = e_root / directory.name
    if backing.is_symlink() or backing.resolve() != backing or not backing.is_dir():
        _fail('node client mount backing')
    backing_info, var_info = backing.stat(), var_tmp.stat()
    if (any(item.st_uid != 65534 or item.st_gid != 65534 or item.st_mode & 0o777 != 0o700
            for item in (root_info, mounted_info, backing_info)) or root_info.st_dev == var_info.st_dev or
            mounted_info.st_dev != root_info.st_dev or
            (mounted_info.st_dev, mounted_info.st_ino) != (backing_info.st_dev, backing_info.st_ino)):
        _fail('node client mount identity')
    return e_root, (mounted_info.st_dev, mounted_info.st_ino, mounted_info.st_uid,
                    mounted_info.st_gid, mounted_info.st_mode & 0o777)


def _safe_environment(runner):
    environment = dict(runner['minimal_environment']())
    for key in list(environment):
        upper = key.upper()
        if (upper.endswith('_PROXY') or upper.startswith(('NPM_CONFIG_', 'COREPACK_')) or
                any(word in upper for word in ('TOKEN', 'PASSWORD', 'PASSWD', 'SECRET', 'CREDENTIAL', 'AUTH')) or
                key in {'PIP_INDEX_URL', 'PIP_EXTRA_INDEX_URL', 'NETRC', 'NODE_OPTIONS',
                        'NODE_EXTRA_CA_CERTS'}):
            environment.pop(key, None)
    return environment


def _download_url(url):
    if type(url) is not str:
        _fail('node client download URL')
    if url not in {ARCHIVE_PIN[3], CHECKSUM_PIN[3]}:
        _fail('node client download URL')
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'nodejs.org' or
            parsed.username is not None or parsed.password is not None or parsed.query or
            parsed.fragment or parsed.port is not None):
        _fail('node client download URL')


class _PinnedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        _download_url(newurl)
        return super().redirect_request(request, file, code, message, headers, newurl)


def _remaining(deadline):
    value = int(deadline - time.monotonic())
    if value <= 0:
        _fail('node client deadline')
    return value


def _download(url, destination, expected_bytes, expected_sha256, deadline):
    _download_url(url)
    if type(expected_bytes) is not int or expected_bytes <= 0 or expected_bytes > MAX_DOWNLOAD_BYTES:
        _fail('node client download size')
    if type(expected_sha256) is not str or re.fullmatch(r'[0-9a-f]{64}', expected_sha256) is None:
        _fail('node client download hash')
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        _fail('node client download overwrite')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedRedirectHandler())
    request = urllib.request.Request(url, headers={'User-Agent': 'm-local-node-client-control/1'})
    try:
        response = opener.open(request, timeout=min(25, _remaining(deadline)))
    except (OSError, urllib.error.URLError):
        _fail('node client download unavailable')
    try:
        with response:
            _download_url(response.geturl())
            status = getattr(response, 'status', None)
            if status is not None and status != 200:
                _fail('node client download status')
            length = getattr(getattr(response, 'headers', None), 'get', lambda *_: None)('Content-Length')
            if length is not None and length != str(expected_bytes):
                _fail('node client download length')
            reader = getattr(response, 'read1', None)
            if not callable(reader):
                _fail('node client download read1')
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
                        _fail('node client download bound')
                    digest.update(chunk)
                    stream.write(chunk)
                _remaining(deadline)
                stream.flush()
                os.fsync(stream.fileno())
    except (OSError, urllib.error.URLError):
        _fail('node client download read')
    if total != expected_bytes or digest.hexdigest() != expected_sha256:
        _fail('node client download digest')
    os.chown(destination, 65534, 65534)
    os.chmod(destination, 0o400)
    _dropped_file(destination, 'node client download identity', mode=0o400)


def _validate_manifest(raw):
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('node client manifest JSON')
    if (type(manifest) is not dict or set(manifest) != MANIFEST_KEYS or
            manifest['schema'] != 'm-local-node-client-download-pins-v1' or
            manifest['scope'] != PREPARE_SCOPE or manifest['status'] != 'declared_before_extraction' or
            manifest['version'] != NODE_VERSION or manifest['npm_version'] != NPM_VERSION or
            manifest['release_documentation'] != RELEASE_DOCUMENTATION):
        _fail('node client manifest schema')
    for name, expected in (('archive', ARCHIVE_PIN), ('checksums', CHECKSUM_PIN)):
        row = manifest[name]
        if (type(row) is not dict or set(row) != ASSET_KEYS or type(row['bytes']) is not int or
                type(row['file']) is not str or Path(row['file']).name != row['file'] or
                type(row['url']) is not str or re.fullmatch(r'[0-9a-f]{64}', row['sha256']) is None or
                (row['bytes'], row['file'], row['sha256'], row['url']) != expected):
            _fail('node client manifest asset')
        parsed = urllib.parse.urlparse(row['url'])
        if (parsed.scheme != 'https' or parsed.hostname != 'nodejs.org' or parsed.username is not None or
                parsed.password is not None or parsed.query or parsed.fragment or parsed.port is not None or
                Path(parsed.path).name != row['file']):
            _fail('node client manifest URL')
    return manifest


def _validate_checks(raw, manifest):
    expected = manifest['checksums']
    if _sha(raw) != expected['sha256'] or len(raw) != expected['bytes']:
        _fail('node client checks hash')
    try:
        lines = raw.decode('ascii').splitlines()
    except UnicodeDecodeError:
        _fail('node client checks encoding')
    target = manifest['archive']
    matches = [line for line in lines if len(line.split()) == 2 and line.split()[1] == target['file']]
    if len(matches) != 1 or matches[0].split()[0] != target['sha256']:
        _fail('node client checks binding')


def _member_name(name, prefix):
    if (type(name) is not str or not name or '\\' in name or name.startswith('/') or
            name != posixpath.normpath(name) or any(part in {'', '.', '..'} for part in name.split('/')) or
            not (name == prefix.rstrip('/') or name.startswith(prefix))):
        _fail('node client archive path')


def _link_target(name, target, prefix):
    expected = {
        prefix + 'bin/npm': '../lib/node_modules/npm/bin/npm-cli.js',
        prefix + 'bin/npx': '../lib/node_modules/npm/bin/npx-cli.js',
        prefix + 'bin/corepack': '../lib/node_modules/corepack/dist/corepack.js',
    }
    if name not in expected or target != expected[name] or target.startswith('/') or '\\' in target:
        _fail('node client archive link')
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
    if not resolved.startswith(prefix) or resolved == prefix.rstrip('/'):
        _fail('node client archive link target')
    return resolved


def _archive_inventory(archive, manifest):
    prefix = 'node-v' + manifest['version'] + '-linux-x64/'
    try:
        tar = tarfile.open(archive, mode='r:*')
    except (OSError, tarfile.TarError):
        _fail('node client archive open')
    records, names, regular_names = [], set(), set()
    total_bytes = 0
    try:
        entries = tar.getmembers()
        if len(entries) != EXPECTED_MEMBER_COUNT:
            _fail('node client archive member count')
        for member in entries:
            _member_name(member.name, prefix)
            if member.name in names:
                _fail('node client archive duplicate')
            names.add(member.name)
            mode = stat.S_IMODE(member.mode)
            if member.mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
                _fail('node client archive special mode')
            if member.islnk() or member.ischr() or member.isblk() or member.isfifo() or member.isdev():
                _fail('node client archive special type')
            if member.isdir():
                records.append(dict(path=member.name, type='directory', mode=0o700))
            elif member.isfile():
                if member.size < 0 or member.size > MAX_MEMBER_BYTES or total_bytes + member.size > MAX_EXPANDED_BYTES:
                    _fail('node client archive expanded size')
                stream = tar.extractfile(member)
                if stream is None:
                    _fail('node client archive file')
                digest, total = hashlib.sha256(), 0
                while True:
                    chunk = stream.read(1024 ** 2)
                    if not chunk:
                        break
                    total += len(chunk)
                    digest.update(chunk)
                if total != member.size:
                    _fail('node client archive file size')
                total_bytes += total
                regular_names.add(member.name)
                records.append(dict(path=member.name, type='file', mode=mode, bytes=total,
                                    sha256=digest.hexdigest()))
            elif member.issym():
                resolved = _link_target(member.name, member.linkname, prefix)
                records.append(dict(path=member.name, type='symlink', mode=mode,
                                    target=member.linkname, resolved=resolved))
            else:
                _fail('node client archive type')
        counts = {kind: sum(row['type'] == kind for row in records)
                  for kind in ('directory', 'file', 'symlink')}
        if counts != {'directory': EXPECTED_DIRECTORY_COUNT, 'file': EXPECTED_FILE_COUNT,
                      'symlink': EXPECTED_SYMLINK_COUNT}:
            _fail('node client archive type count')
        links = [row for row in records if row['type'] == 'symlink']
        if {row['path'] for row in links} != {prefix + 'bin/npm', prefix + 'bin/npx', prefix + 'bin/corepack'}:
            _fail('node client archive links')
        for row in links:
            if row['resolved'] not in regular_names:
                _fail('node client archive link target')
    finally:
        tar.close()
    records.sort(key=lambda row: row['path'])
    raw = json.dumps(records, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    return records, _sha(raw)


def _tree_inventory(tools_directory):
    root = Path(tools_directory)
    if (not root.is_absolute() or root.resolve() != root or root.is_symlink() or not root.is_dir()):
        _fail('node client inventory root')
    root_info = root.lstat()
    if root_info.st_uid != 65534 or root_info.st_gid != 65534:
        _fail('node client inventory owner')
    root_device = root_info.st_dev
    records = []

    def visit(path):
        info = path.lstat()
        if info.st_uid != 65534 or info.st_gid != 65534 or info.st_dev != root_device:
            _fail('node client inventory identity')
        relative = path.relative_to(root.parent).as_posix()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISDIR(info.st_mode):
            records.append(dict(path=relative, type='directory', mode=mode))
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            digest, total, _ = _hash_file(path, allow_empty=True)
            records.append(dict(path=relative, type='file', mode=mode, bytes=total, sha256=digest))
        elif stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative), target))
            if not resolved.startswith(root.name + '/'):
                _fail('node client inventory link')
            records.append(dict(path=relative, type='symlink', mode=mode, target=target, resolved=resolved))
        else:
            _fail('node client inventory type')

    visit(root)
    records.sort(key=lambda row: row['path'])
    return records


def _inventory_digest(records):
    return _sha(json.dumps(records, sort_keys=True, separators=(',', ':')).encode() + b'\n')


def verify_inventory(tools_directory, expected_sha256):
    records = _tree_inventory(tools_directory)
    digest = _inventory_digest(records)
    if type(expected_sha256) is not str or digest != expected_sha256:
        _fail('node client inventory hash')
    return digest


def _validate_log(path):
    return _private_file(path, mode=0o600)


def _parse_receipt(raw, folder, manifest):
    try:
        receipt = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeError):
        _fail('node client frozen receipt JSON')
    if (type(receipt) is not dict or set(receipt) != {'node_version', 'archive_sha256', 'tools_directory', 'provenance'} or
            receipt['node_version'] != manifest['version'] or receipt['archive_sha256'] != manifest['archive']['sha256'] or
            receipt['tools_directory'] != str(folder) or receipt['provenance'] != PROVENANCE):
        _fail('node client frozen receipt binding')
    return receipt


def _tool_paths(folder):
    bin_dir = Path(folder) / 'bin'
    paths = {name: bin_dir / name for name in TOOL_NAMES}
    for name, path in paths.items():
        info = path.lstat()
        if name == 'node':
            if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or not info.st_mode & 0o111:
                _fail('node client node binary')
        else:
            expected = {
                'npm': '../lib/node_modules/npm/bin/npm-cli.js',
                'npx': '../lib/node_modules/npm/bin/npx-cli.js',
                'corepack': '../lib/node_modules/corepack/dist/corepack.js',
            }[name]
            if not path.is_symlink() or os.readlink(path) != expected:
                _fail('node client tool link')
        resolved = path.resolve()
        if not resolved.is_absolute() or folder not in resolved.parents or resolved.is_symlink() or not resolved.is_file():
            _fail('node client tool target')
    return paths


def _tool_hashes(folder):
    paths = _tool_paths(folder)
    return {path.resolve().relative_to(folder).as_posix(): _hash_file(path.resolve())[0]
            for path in paths.values()}


def _parse_ldd(raw, folder):
    text = raw.decode('utf-8', 'replace')
    if not text.strip() or 'not found' in text:
        _fail('node client dependency resolution')
    paths = []
    for token in re.findall(r'(?<![\w])(/[A-Za-z0-9._+:/-]+)', text):
        path = Path(token)
        if path.is_symlink():
            path = path.resolve()
        if path not in paths and path.is_file() and not path.is_symlink() and path.resolve() == path:
            paths.append(path)
    if not paths:
        _fail('node client dependency paths')
    dependencies = {}
    for path in paths:
        dependencies[str(path)] = _hash_file(path)[0]
    return dependencies


def _validate_probe(raw, folder, manifest):
    try:
        receipt = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('node client probe JSON')
    if (type(receipt) is not dict or set(receipt) != PROBE_KEYS or receipt['status'] != 'passed' or
            receipt['workspace'] != str(folder) or receipt['uid'] != 65534 or receipt['gid'] != 65534 or
            receipt['supplementary_groups'] != [] or receipt['js_smoke'] != '{"node":"v22.16.0","ok":1}' or
            type(receipt['tools']) is not list or
            [row.get('name') if type(row) is dict else None for row in receipt['tools']] != list(TOOL_NAMES)):
        _fail('node client probe binding')
    versions = {}
    expected = {'node': 'v' + manifest['version'], 'npm': manifest['npm_version'],
                'npx': manifest['npm_version'], 'corepack': COREPACK_VERSION}
    for row in receipt['tools']:
        if (type(row) is not dict or set(row) != PROBE_TOOL_KEYS or row['name'] not in expected or
                type(row['version']) is not str or row['version'] != expected[row['name']]):
            _fail('node client probe tool')
        versions[row['name']] = row['version']
    return receipt, versions


def run_control(preflight, runner, fresh_owned_mounted_directory, commit, timeout):
    """Download, extract, and bind the frozen Node.js client prerequisite."""
    if type(timeout) is not int or not 0 < timeout <= 180:
        _fail('node client timeout')
    deadline = time.monotonic() + timeout
    mount_identity = _mount_identity(runner, fresh_owned_mounted_directory)[1]
    control = Path(fresh_owned_mounted_directory)
    if any(path.exists() or path.is_symlink() for path in control.iterdir()):
        _fail('node client pre-existing files')
    prepare_raw = preflight['committed_file'](ROOT, commit, PREPARE_RELATIVE)
    manifest_raw = preflight['committed_file'](ROOT, commit, MANIFEST_RELATIVE)
    if _sha(prepare_raw) != PREPARE_SHA256 or _sha(manifest_raw) != MANIFEST_SHA256:
        _fail('node client input pin')
    manifest = _validate_manifest(manifest_raw)
    clients = _mkdir_owned(control / 'clients')
    prepare_input_path = control / 'prepare-node-client-input.py'
    prepare_path = control / 'prepare-node-client.py'
    manifest_path = control / 'node-client-download-pins-v1.json'
    adapted = adapt_prepare(prepare_raw, clients)
    _write_private(prepare_input_path, prepare_raw)
    _write_private(prepare_path, adapted)
    _write_private(manifest_path, manifest_raw)
    staged = {prepare_input_path: PREPARE_SHA256, prepare_path: _sha(adapted), manifest_path: MANIFEST_SHA256}
    identities = {path: _private_file(path, expected, mode=0o400)[1] for path, expected in staged.items()}
    archive_path = clients / manifest['archive']['file']
    checks_path = clients / 'official-checksums.txt'
    _download(manifest['checksums']['url'], checks_path, manifest['checksums']['bytes'],
              manifest['checksums']['sha256'], deadline)
    _download(manifest['archive']['url'], archive_path, manifest['archive']['bytes'],
              manifest['archive']['sha256'], deadline)
    checks_raw = _read_file(checks_path)
    _validate_checks(checks_raw, manifest)
    _, archive_identity = _dropped_file(archive_path, 'node client archive identity', mode=0o400)
    _, checks_identity = _dropped_file(checks_path, 'node client checks identity', mode=0o400)
    archive_records, inventory_sha = _archive_inventory(archive_path, manifest)
    prefix = 'node-v' + manifest['version'] + '-linux-x64'
    folder = clients / prefix
    if (folder.exists() or folder.is_symlink() or (clients / 'SHASUMS256.txt').exists() or
            (clients / 'SHASUMS256.txt').is_symlink()):
        _fail('node client pre-existing output')
    logs = [control / 'prepare.log', control / 'ldd-node.log', control / 'version-probe.log']
    for path in logs:
        _create_private_log(path)
    environment = _safe_environment(runner)
    runner['run_command']('node client prepare', [sys.executable, '-I', '-B', str(prepare_path)],
                          cwd=control, env=environment, timeout=_remaining(deadline), log=logs[0])
    if _mount_identity(runner, control)[1] != mount_identity:
        _fail('node client mount changed')
    _validate_log(logs[0])
    receipt_log, _ = _validate_log(logs[0])
    try:
        receipt = json.loads(receipt_log.decode('utf-8'))
    except (ValueError, UnicodeError):
        _fail('node client prepare receipt JSON')
    _parse_receipt(receipt_log, folder, manifest)
    checks_output = clients / 'SHASUMS256.txt'
    if checks_output.is_symlink() or not checks_output.is_file():
        _fail('node client checks output')
    checks_output_digest, checks_output_identity = _dropped_file(checks_output, 'node client checks output identity')
    if _read_file(checks_output) != checks_raw or checks_output_digest != _sha(checks_raw):
        _fail('node client checks output binding')
    os.chown(checks_output, 0, 0)
    os.chmod(checks_output, 0o400)
    _private_file(checks_output, checks_output_digest, mode=0o400)
    if _dropped_file(archive_path, 'node client archive changed', mode=0o400)[1] != archive_identity:
        _fail('node client archive changed')
    folder_records = _tree_inventory(folder)
    if folder_records != archive_records or _inventory_digest(folder_records) != inventory_sha:
        _fail('node client inventory binding')
    tool_hashes = _tool_hashes(folder)
    node_path = folder / 'bin/node'
    tool_environment = dict(environment)
    tool_environment.update(PATH=str(folder / 'bin') + ':/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8',
                            LC_ALL='C.UTF-8', COREPACK_ENABLE_NETWORK='0', npm_config_offline='true',
                            NPM_CONFIG_USERCONFIG='/dev/null')
    runner['run_command']('node client ldd', ['/usr/bin/ldd', str(node_path)], cwd=folder,
                          env=tool_environment, timeout=_remaining(deadline), log=logs[1])
    if _mount_identity(runner, control)[1] != mount_identity:
        _fail('node client mount changed')
    ldd_raw, _ = _validate_log(logs[1])
    dependency_hashes = _parse_ldd(ldd_raw, folder)
    probe_path = control / 'node-client-version-probe.py'
    probe_output = clients / 'version-probe.json'
    if probe_output.exists() or probe_output.is_symlink():
        _fail('node client probe overwrite')
    _write_private(probe_path, VERSION_PROBE_SOURCE)
    probe_path_identity = _private_file(probe_path, _sha(VERSION_PROBE_SOURCE), mode=0o400)[1]
    runner['run_command']('node client version probe', [sys.executable, '-I', '-B', str(probe_path), str(folder),
                          str(probe_output), *(str(folder / 'bin' / name) for name in TOOL_NAMES)], cwd=control,
                          env=tool_environment, timeout=_remaining(deadline), log=logs[2])
    if _mount_identity(runner, control)[1] != mount_identity:
        _fail('node client mount changed')
    if _private_file(probe_path, _sha(VERSION_PROBE_SOURCE), mode=0o400)[1] != probe_path_identity:
        _fail('node client probe script changed')
    _validate_log(logs[2])
    probe_digest, probe_identity = _dropped_file(probe_output, 'node client probe identity')
    probe_raw = _read_file(probe_output)
    probe_receipt, versions = _validate_probe(probe_raw, folder, manifest)
    probe_digest_after, probe_identity_after = _dropped_file(probe_output, 'node client probe identity')
    if probe_digest_after != probe_digest or probe_identity_after != probe_identity:
        _fail('node client probe changed')
    if probe_digest != _sha(probe_raw):
        _fail('node client probe hash')
    os.chown(probe_output, 0, 0)
    os.chmod(probe_output, 0o400)
    _private_file(probe_output, probe_digest, mode=0o400)
    for path, expected in staged.items():
        if _private_file(path, expected, mode=0o400)[1] != identities[path]:
            _fail('node client staged input identity')
    if _private_file(prepare_path, _sha(adapted), mode=0o400)[0] != adapted:
        _fail('node client prepare changed')
    executed_path = control / 'executed-prepare-node-client.py'
    _write_private(executed_path, adapted)
    _private_file(executed_path, _sha(adapted), mode=0o400)
    final_tool_hashes = _tool_hashes(folder)
    if final_tool_hashes != tool_hashes:
        _fail('node client tool changed')
    final_dependencies = {}
    for path, expected in dependency_hashes.items():
        actual, _, _ = _hash_file(path)
        if actual != expected:
            _fail('node client dependency changed')
        final_dependencies[path] = actual
    final_inventory = verify_inventory(folder, inventory_sha)
    binding = dict(status='passed', scope=BINDING_SCOPE, workspace=str(folder),
                   frozen_receipt_sha256=_sha(json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode() + b'\n'),
                   version_probe_sha256=probe_digest, archive_sha256=manifest['archive']['sha256'],
                   checksums_sha256=manifest['checksums']['sha256'], tool_binary_sha256=final_tool_hashes,
                   dependency_sha256=final_dependencies, extracted_inventory_sha256=final_inventory,
                   versions=versions, uid=65534, gid=65534, supplementary_groups=[])
    binding_raw = json.dumps(binding, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    frozen_raw = json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    receipt_path = clients / 'result.json'
    if receipt_path.exists() or receipt_path.is_symlink():
        _fail('node client receipt overwrite')
    _write_private(receipt_path, frozen_raw)
    binding_path = control / 'binding-receipt.json'
    _write_private(binding_path, binding_raw)
    for log in logs:
        _validate_log(log)
    if _dropped_file(archive_path, 'node client archive changed', mode=0o400)[1] != archive_identity:
        _fail('node client archive changed')
    if _dropped_file(checks_path, 'node client checks changed', mode=0o400)[1] != checks_identity:
        _fail('node client checks changed')
    if _private_file(receipt_path, _sha(frozen_raw), mode=0o400)[0] != frozen_raw:
        _fail('node client frozen receipt changed')
    if _mount_identity(runner, control)[1] != mount_identity:
        _fail('node client mount changed')
    _remaining(deadline)
    return dict(status='passed', clients_directory=folder, frozen_receipt_path=receipt_path,
                frozen_receipt_sha256=_sha(frozen_raw), binding_receipt_path=binding_path,
                binding_receipt_sha256=_sha(binding_raw), executed_prepare_sha256=_sha(adapted),
                tool_binary_sha256=final_tool_hashes, dependency_sha256=final_dependencies,
                extracted_inventory_sha256=final_inventory)
