#!/usr/bin/env python3
"""Generate and verify the small jsdom dependency prerequisite."""

import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib


ROOT = Path(__file__).absolute().parent
CHECKOUT = ROOT.parent
SELF_RELATIVE = 'runtime-proof/generate-ui-dependency-lock.py'
NODE_CONTROL_RELATIVE = 'runtime-proof/run-fresh-node-client-control.py'
NODE_TEST_RELATIVE = 'runtime-proof/test-node-client-control.py'
SOURCE_TEST_RELATIVE = 'runtime-proof/test-source-isolation.py'
PREFLIGHT_RELATIVE = 'runtime-proof/verify-package-preflight.py'
RUNNER_RELATIVE = 'runtime-proof/run-fresh-source.py'
PREFLIGHT_SHA256 = 'd47b342bea74d64fa3575673a07b90d5595fdabe0e87a93f714cc6d7caa7c635'
PACKAGE_RAW = b'''{
  "name": "m-local-ui-test-runtime",
  "version": "1.0.0",
  "private": true,
  "dependencies": {
    "jsdom": "26.1.0"
  }
}
'''
PACKAGE_SCHEMA = 'm-local-ui-dependency-inputs-v1'
PACKAGE_NAME = 'm-local-ui-test-runtime'
PACKAGE_VERSION = '1.0.0'
JSDOM_VERSION = '26.1.0'
JSDOM_INTEGRITY = 'sha512-Cvc9WUhxSMEo4McES3P7oK3QaXldCfNWp7pl2NNeiIFlCoLr3kfq9kb1fxftiwk1FLV7CvpvDfonxtzUDeSOPg=='
REGISTRY_HOST = 'registry.npmjs.org'
NODE_VERSION = '22.16.0'
NPM_VERSION = '10.9.2'
MAX_LOCK_BYTES = 512 * 1024
MAX_TARBALL_BYTES = 5 * 1024 * 1024
MAX_TARBALL_TOTAL = 32 * 1024 * 1024
MAX_PACKAGES = 128
MAX_ARCHIVE_MEMBERS = 20000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_LOG_BYTES = 2 * 1024 * 1024
TOTAL_SECONDS = 360
PARENT_POLICY = 'dependency preparation only; no application suite, adoption, or deployment claim'
SEMVER = re.compile(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z')


def _fail(label):
    raise ValueError(label)


def _sha(raw):
    if type(raw) is not bytes:
        _fail('dependency bytes')
    return hashlib.sha256(raw).hexdigest()


def _hash64(value, label):
    if type(value) is not str or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        _fail(label)
    return value


def _json(raw, label, maximum=MAX_LOCK_BYTES):
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        _fail(label + ' size')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail(label + ' duplicate key')
            result[key] = value
        return result

    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda value: _fail(label + ' nonfinite'))
    except (UnicodeError, ValueError, RecursionError):
        _fail(label + ' JSON')


def _keys(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        _fail(label + ' keys')


def _path_name(path):
    if type(path) is not str or not path.startswith('node_modules/') or '\\' in path or \
            path != posixpath.normpath(path) or any(part in ('', '.', '..') for part in path.split('/')):
        _fail('lock package path')
    parts = path.split('/')
    index = 0
    while True:
        if parts[index] != 'node_modules' or index + 1 >= len(parts):
            _fail('lock package path')
        package = parts[index + 1]
        index += 2
        if package.startswith('@'):
            if index >= len(parts) or parts[index] == 'node_modules' or parts[index].startswith('@'):
                _fail('lock scoped package path')
            package += '/' + parts[index]
            index += 1
        if index == len(parts):
            return package
        if parts[index] != 'node_modules':
            _fail('lock package path')


def _integrity(value):
    if type(value) is not str or not value.startswith('sha512-'):
        _fail('lock integrity')
    encoded = value[7:]
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        _fail('lock integrity')
    if len(decoded) != hashlib.sha512().digest_size or base64.b64encode(decoded).decode('ascii') != encoded:
        _fail('lock integrity')
    return value


def _official_url(value, name=None, version=None):
    if type(value) is not str:
        _fail('lock package URL')
    parsed = urllib.parse.urlparse(value)
    if (parsed.scheme != 'https' or parsed.netloc != REGISTRY_HOST or parsed.hostname != REGISTRY_HOST or
            any(ord(char) < 0x20 or ord(char) == 0x7f for char in value) or '%' in value or '\\' in value or
            parsed.username is not None or
            parsed.password is not None or parsed.port is not None or parsed.query or parsed.fragment or
            not parsed.path.startswith('/') or not parsed.path.endswith('.tgz') or
            parsed.path != posixpath.normpath(parsed.path) or (name is not None and version is None) or
            (name is None and version is not None)):
        _fail('lock package URL')
    if name is not None:
        if type(name) is not str or type(version) is not str or SEMVER.fullmatch(version) is None:
            _fail('lock package URL binding')
        package = name.rsplit('/', 1)[-1]
        if parsed.path != '/' + name + '/-/' + package + '-' + version + '.tgz':
            _fail('lock package URL binding')
    else:
        pieces = parsed.path.strip('/').split('/')
        if len(pieces) < 3 or pieces[-2] != '-':
            _fail('lock package URL binding')
        package_parts = pieces[:-2]
        package = '/'.join(package_parts)
        if (len(package_parts) == 1 and package.startswith('@')) or \
                (len(package_parts) == 2 and not package_parts[0].startswith('@')) or \
                len(package_parts) not in (1, 2):
            _fail('lock package URL binding')
        filename = pieces[-1]
        prefix = package_parts[-1] + '-'
        if not filename.startswith(prefix) or not filename.endswith('.tgz'):
            _fail('lock package URL binding')
        inferred_version = filename[len(prefix):-4]
        if SEMVER.fullmatch(inferred_version) is None or parsed.path != '/' + package + '/-/' + filename:
            _fail('lock package URL binding')
    return value


def parse_lock(raw):
    lock = _json(raw, 'package lock')
    if (type(lock) is not dict or type(lock.get('lockfileVersion')) is not int or
            lock['lockfileVersion'] != 3 or lock.get('requires') is not True):
        _fail('package lock version')
    if lock.get('name') != PACKAGE_NAME or lock.get('version') != PACKAGE_VERSION:
        _fail('package lock identity')
    packages = lock.get('packages')
    if type(packages) is not dict or '' not in packages or len(packages) - 1 > MAX_PACKAGES:
        _fail('package lock packages')
    root = packages['']
    if type(root) is not dict or root.get('name') != PACKAGE_NAME or root.get('version') != PACKAGE_VERSION or \
            root.get('dependencies') != {'jsdom': JSDOM_VERSION}:
        _fail('package lock root')
    rows = []
    for path, value in packages.items():
        if path == '':
            continue
        name = _path_name(path)
        if type(value) is not dict or ('name' in value and value['name'] != name) or \
                type(value.get('version')) is not str or SEMVER.fullmatch(value['version']) is None:
            _fail('package lock package')
        if any(value.get(flag) for flag in ('link', 'bundled', 'inBundle', 'hasInstallScript',
                                            'hasShrinkwrap', 'bundleDependencies', 'bundledDependencies')):
            _fail('package lock package controls')
        if 'resolved' not in value or 'integrity' not in value:
            _fail('package lock package binding')
        url = _official_url(value['resolved'], name, value['version'])
        integrity = _integrity(value['integrity'])
        rows.append({'path': path, 'name': name, 'version': value['version'], 'url': url, 'integrity': integrity})
    rows.sort(key=lambda row: row['path'])
    jsdom = next((row for row in rows if row['path'] == 'node_modules/jsdom'), None)
    if jsdom is None or jsdom['version'] != JSDOM_VERSION or jsdom['url'] != \
            'https://registry.npmjs.org/jsdom/-/jsdom-26.1.0.tgz' or jsdom['integrity'] != JSDOM_INTEGRITY:
        _fail('jsdom lock pin')
    return rows


def validate_tarball(raw, integrity):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_TARBALL_BYTES:
        _fail('dependency tarball size')
    expected = _integrity(integrity)
    actual = 'sha512-' + base64.b64encode(hashlib.sha512(raw).digest()).decode('ascii')
    if actual != expected:
        _fail('dependency tarball integrity')
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            names = {}
            physical_members = 0
            expanded = 0
            for member in archive:
                physical_members += 1
                if physical_members > MAX_ARCHIVE_MEMBERS:
                    _fail('dependency tarball paths')
                name = member.name
                parts = name.split('/')
                normalized = posixpath.normpath(name)
                if (not name or parts[0] != 'package' or name.startswith('/') or '\\' in name or
                        any(ord(char) < 0x20 or ord(char) == 0x7f for char in name) or
                        any(part in ('', '..') for part in parts) or
                        not (normalized == 'package' or normalized.startswith('package/'))):
                    _fail('dependency tarball paths')
                if member.isdir():
                    record = (member.type, stat.S_IMODE(member.mode))
                    if normalized in names and names[normalized] != record:
                        _fail('dependency tarball collision')
                    names[normalized] = record
                    continue
                if not member.isfile() or member.issym() or member.islnk() or member.size < 0:
                    _fail('dependency tarball member type')
                expanded += member.size
                if expanded > MAX_ARCHIVE_BYTES:
                    _fail('dependency tarball expanded size')
                digest = hashlib.sha256()
                length = 0
                with archive.extractfile(member) as payload:
                    while True:
                        chunk = payload.read(min(1024 * 1024, member.size + 1 - length))
                        if not chunk:
                            break
                        length += len(chunk)
                        if length > member.size:
                            _fail('dependency tarball member size')
                        digest.update(chunk)
                if length != member.size:
                    _fail('dependency tarball member size')
                record = (member.type, stat.S_IMODE(member.mode), length, digest.hexdigest())
                if normalized in names and names[normalized] != record:
                    _fail('dependency tarball collision')
                names[normalized] = record
            if not names:
                _fail('dependency tarball paths')
            while True:
                tail = archive.fileobj.read(1024 * 1024)
                if archive.fileobj.tell() > MAX_ARCHIVE_BYTES + MAX_ARCHIVE_MEMBERS * 1024 + 10240:
                    _fail('dependency tarball expanded size')
                if not tail:
                    break
                if any(tail):
                    _fail('dependency tarball trailing data')
    except (OSError, EOFError, zlib.error, tarfile.TarError):
        _fail('dependency tarball archive')


def _canonical_directory(path, label, *, missing=False):
    path = Path(path)
    if not path.is_absolute() or '\x00' in str(path) or path.resolve() != path or path.is_symlink():
        _fail(label + ' path')
    if missing and path.exists():
        _fail(label + ' already exists')
    return path


def _owned_dir(path, mode=0o700):
    path = Path(path)
    if path.exists() or path.is_symlink():
        _fail('dependency pre-existing directory')
    try:
        path.mkdir(mode=mode)
        os.chown(path, 65534, 65534)
        os.chmod(path, mode)
    except OSError:
        _fail('dependency directory create')
    return path


def _write_bytes(path, raw, mode=0o600, owner=(65534, 65534)):
    path = Path(path)
    if path.exists() or path.is_symlink():
        _fail('dependency file overwrite')
    try:
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(path, *owner)
        os.chmod(path, mode)
    except OSError:
        _fail('dependency file create')


def _read_bounded(path, maximum, *, allow_empty=False):
    path = Path(path)
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
                (info.st_size == 0 and not allow_empty) or info.st_size < 0 or info.st_size > maximum):
            _fail('dependency file identity')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
        with os.fdopen(os.open(path, flags), 'rb') as stream:
            raw = stream.read(maximum + 1)
            opened = os.fstat(stream.fileno())
    except OSError:
        _fail('dependency file read')
    if len(raw) != info.st_size or any(getattr(opened, key) != getattr(info, key)
                                       for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns',
                                                   'st_mode', 'st_uid', 'st_gid', 'st_nlink')):
        _fail('dependency file changed')
    return raw


def _safe_env(runner, *, cache, home, folder, offline):
    source = dict(runner['minimal_environment']())
    env = {key: source[key] for key in
           ('PATH', 'HOME', 'LANG', 'LC_ALL', 'PYTHONDONTWRITEBYTECODE', 'GIT_TERMINAL_PROMPT',
            'GIT_CONFIG_NOSYSTEM', 'GIT_CONFIG_GLOBAL') if key in source}
    env.update(PATH=str(folder / 'bin') + ':/usr/bin:/bin', HOME=str(home), LANG='C.UTF-8', LC_ALL='C.UTF-8',
               NPM_CONFIG_USERCONFIG='/dev/null', npm_config_userconfig='/dev/null', NPM_CONFIG_CACHE=str(cache),
               npm_config_cache=str(cache), npm_config_registry='https://' + REGISTRY_HOST,
               npm_config_ignore_scripts='true', npm_config_audit='false', npm_config_fund='false',
               npm_config_bin_links='false', NPM_CONFIG_BIN_LINKS='false')
    if offline:
        env.update(COREPACK_ENABLE_NETWORK='0', npm_config_offline='true', NPM_CONFIG_OFFLINE='true')
    else:
        env.pop('npm_config_offline', None)
        env.pop('NPM_CONFIG_OFFLINE', None)
    return env


def _setpriv(command):
    return ['/usr/bin/setpriv', '--reuid=65534', '--regid=65534', '--clear-groups', '--', *map(str, command)]


def _remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        _fail('dependency deadline')
    return min(180, int(value))


def _download(url, integrity, destination, deadline, total):
    _official_url(url)
    _integrity(integrity)
    if total[0] >= MAX_TARBALL_TOTAL:
        _fail('dependency tarball total')
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        _fail('dependency download overwrite')

    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, file, code, message, newurl):
            if newurl != url:
                _fail('dependency redirect')
            return super().redirect_request(request, file, code, message, newurl)

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirect())
    try:
        response = opener.open(urllib.request.Request(url, headers={'User-Agent': 'm-local-ui-dependency-lock/1'}),
                               timeout=min(25, _remaining(deadline)))
        with response:
            if response.geturl() != url:
                _fail('dependency final URL')
            declared = response.headers.get('Content-Length') if hasattr(response, 'headers') else None
            if declared is not None:
                try:
                    declared = int(declared)
                except (TypeError, ValueError):
                    _fail('dependency content length')
                if declared < 0 or declared > MAX_TARBALL_BYTES or total[0] + declared > MAX_TARBALL_TOTAL:
                    _fail('dependency tarball bound')
            reader = getattr(response, 'read1', None)
            if not callable(reader):
                _fail('dependency read1')
            digest = hashlib.sha256()
            chunks, size = [], 0
            while True:
                _remaining(deadline)
                chunk = reader(min(1024 * 1024, MAX_TARBALL_BYTES + 1 - size))
                _remaining(deadline)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_TARBALL_BYTES or total[0] + size > MAX_TARBALL_TOTAL:
                    _fail('dependency tarball bound')
                chunks.append(chunk)
                digest.update(chunk)
            raw = b''.join(chunks)
            _remaining(deadline)
    except (OSError, urllib.error.URLError):
        _fail('dependency download')
    validate_tarball(raw, integrity)
    try:
        with destination.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(destination, 65534, 65534)
        os.chmod(destination, 0o400)
    except OSError:
        _fail('dependency download write')
    total[0] += len(raw)
    return len(raw), digest.hexdigest(), raw


def _load_verified(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        _fail('dependency module loader')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _committed_dependencies(preflight, commit):
    files = {}
    for relative in (SELF_RELATIVE, NODE_CONTROL_RELATIVE, NODE_TEST_RELATIVE, SOURCE_TEST_RELATIVE,
                     PREFLIGHT_RELATIVE, RUNNER_RELATIVE):
        raw = preflight['committed_file'](CHECKOUT, commit, relative)
        local = _read_bounded(CHECKOUT / relative, 1024 * 1024)
        if local != raw:
            _fail('dependency committed file binding')
        files[relative] = raw
    return files


def _inventory(root):
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root or root.is_symlink() or not root.is_dir():
        _fail('dependency inventory root')
    root_info = root.lstat()
    if root_info.st_uid != 65534 or root_info.st_gid != 65534:
        _fail('dependency inventory owner')
    root_device = root_info.st_dev
    records = []
    total = 0
    count = 0
    records.append({'path': root.name, 'type': 'directory', 'mode': stat.S_IMODE(root_info.st_mode)})

    def visit(path):
        nonlocal total, count
        info = path.lstat()
        if info.st_uid != 65534 or info.st_gid != 65534 or info.st_dev != root_device:
            _fail('dependency inventory identity')
        relative = root.name + '/' + path.relative_to(root).as_posix()
        if path.is_symlink():
            target = os.readlink(path)
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative), target))
            if (not resolved or resolved.startswith('../') or resolved == '..' or resolved.startswith('/')):
                _fail('dependency inventory link')
            records.append({'path': relative, 'type': 'symlink', 'mode': stat.S_IMODE(info.st_mode),
                            'target': target, 'resolved': resolved})
        elif path.is_file():
            raw = _read_bounded(path, 64 * 1024 * 1024, allow_empty=True)
            count += 1
            total += len(raw)
            records.append({'path': relative, 'type': 'file', 'mode': stat.S_IMODE(info.st_mode),
                            'bytes': len(raw), 'sha256': _sha(raw)})
        elif path.is_dir():
            records.append({'path': relative, 'type': 'directory', 'mode': stat.S_IMODE(info.st_mode)})
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                visit(child)
        elif not path.is_dir():
            _fail('dependency inventory type')

    for child in sorted(root.iterdir(), key=lambda item: item.name):
        visit(child)
    records.sort(key=lambda row: row['path'])
    return _sha(json.dumps(records, sort_keys=True, separators=(',', ':')).encode()), count, total


def _public_write(path, raw):
    _write_bytes(path, raw, mode=0o644, owner=(0, 0))


def _private_log(path, *, maximum=MAX_LOG_BYTES, allow_empty=True):
    path = Path(path)
    try:
        info = path.lstat()
    except OSError:
        _fail('dependency log identity')
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o600):
        _fail('dependency log identity')
    return _read_bounded(path, maximum, allow_empty=allow_empty)


def _private_receipt(path, expected, label):
    if path is None:
        _fail(label + ' path')
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        _fail(label + ' path')
    try:
        info = path.lstat()
    except OSError:
        _fail(label + ' identity')
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o400):
        _fail(label + ' identity')
    raw = _read_bounded(path, 1024 * 1024)
    if _sha(raw) != _hash64(expected, label + ' hash'):
        _fail(label + ' hash')
    return raw


def _verify_node_bindings(control_module, clients, result):
    if type(result) is not dict or result.get('status') != 'passed':
        _fail('dependency node control result')
    tools = result.get('tool_binary_sha256')
    dependencies = result.get('dependency_sha256')
    inventory = _hash64(result.get('extracted_inventory_sha256'), 'dependency node inventory')
    if type(tools) is not dict or type(dependencies) is not dict:
        _fail('dependency node binding schema')
    for relative, expected in tools.items():
        if (type(relative) is not str or Path(relative).is_absolute() or '\\' in relative or
                any(part in ('', '.', '..') for part in Path(relative).parts)):
            _fail('dependency node tool path')
        _hash64(expected, 'dependency node tool hash')
    for absolute, expected in dependencies.items():
        if type(absolute) is not str:
            _fail('dependency node dependency path')
        path = Path(absolute)
        if (not path.is_absolute() or path.is_symlink() or
                path.resolve() != path):
            _fail('dependency node dependency path')
        _hash64(expected, 'dependency node dependency hash')
    try:
        actual_tools = control_module._tool_hashes(clients)
        actual_inventory = control_module.verify_inventory(clients, inventory)
    except (AttributeError, OSError, ValueError):
        _fail('dependency node inventory verification')
    if actual_tools != tools or actual_inventory != inventory:
        _fail('dependency node inventory binding')
    actual_dependencies = {}
    for absolute in sorted(dependencies):
        try:
            actual, _, _ = control_module._hash_file(Path(absolute))
        except (AttributeError, OSError, ValueError):
            _fail('dependency node dependency verification')
        actual_dependencies[absolute] = actual
    if actual_dependencies != dependencies:
        _fail('dependency node dependency binding')
    frozen = _private_receipt(result.get('frozen_receipt_path'), result.get('frozen_receipt_sha256'),
                              'dependency node frozen receipt')
    binding = _private_receipt(result.get('binding_receipt_path'), result.get('binding_receipt_sha256'),
                               'dependency node binding receipt')
    return dict(tool_binary_sha256=actual_tools, dependency_sha256=actual_dependencies,
                extracted_inventory_sha256=actual_inventory,
                frozen_receipt_sha256=_sha(frozen), binding_receipt_sha256=_sha(binding))


def generate(output, expected_commit):
    if type(expected_commit) is not str or re.fullmatch(r'[0-9a-f]{40}', expected_commit) is None:
        _fail('dependency commit')
    output = _canonical_directory(output, 'dependency output', missing=True)
    deadline = time.monotonic() + TOTAL_SECONDS
    preflight_path = CHECKOUT / PREFLIGHT_RELATIVE
    if _sha(_read_bounded(preflight_path, 1024 * 1024)) != PREFLIGHT_SHA256:
        _fail('dependency preflight pin')
    preflight_module = _load_verified(preflight_path, 'ui_dependency_preflight')
    preflight = vars(preflight_module)
    preflight['checked_checkout'](CHECKOUT, expected_commit)
    _committed_dependencies(preflight, expected_commit)
    node_tests = _load_verified(CHECKOUT / NODE_TEST_RELATIVE, 'ui_dependency_node_tests')
    if not hasattr(node_tests, 'LinuxRootTests'):
        _fail('dependency Linux fixture')
    wrapper = node_tests.LinuxRootTests('runTest')
    fixture = None
    result = None
    try:
        wrapper.setUpClass()
        fixture = wrapper.fixture()
        base, image, e_root, backing, control, loop = fixture
        preflight_values, fixture_commit = wrapper.preflight()
        if fixture_commit != expected_commit:
            _fail('dependency fixture commit')
        runner = wrapper.runner(base, e_root)
        control_module = wrapper.control
        node_result = control_module.run_control(preflight_values, runner, control, expected_commit,
                                                  min(180, _remaining(deadline)))
        node_binding = _verify_node_bindings(control_module, Path(node_result['clients_directory']), node_result)
        clients = Path(node_result['clients_directory'])
        node = clients / 'bin/node'
        npm = clients / 'bin/npm'
        if node.is_symlink() or not node.is_file() or npm.is_symlink() is False:
            _fail('dependency node tools')
        workspace = _owned_dir(control / 'ui-dependency-work')
        resolve = _owned_dir(workspace / 'resolve')
        resolve_cache = _owned_dir(resolve / 'cache')
        install = _owned_dir(workspace / 'install')
        offline_cache = _owned_dir(workspace / 'offline-cache')
        home = _owned_dir(workspace / 'home')
        downloads = _owned_dir(workspace / 'downloads')
        package_path = resolve / 'package.json'
        _write_bytes(package_path, PACKAGE_RAW)
        environment = _safe_env(runner, cache=resolve_cache, home=home, folder=clients, offline=False)
        logs = []
        for name in ('lock-resolve.log', 'cache-seed.log', 'npm-ci.log', 'jsdom-smoke.log'):
            path = control / name
            _write_bytes(path, b'', mode=0o600, owner=(0, 0))
            logs.append(path)
        runner['run_command']('ui lock resolution', _setpriv([npm, 'install', '--package-lock-only', '--ignore-scripts',
                          '--no-audit', '--no-fund', '--bin-links=false']), cwd=resolve, env=environment,
                          timeout=_remaining(deadline), log=logs[0])
        _private_log(logs[0])
        lock_path = resolve / 'package-lock.json'
        lock_raw = _read_bounded(lock_path, MAX_LOCK_BYTES)
        rows = parse_lock(lock_raw)
        package_before = _read_bounded(package_path, 64 * 1024)
        if package_before != PACKAGE_RAW:
            _fail('dependency package mutation')
        total = [0]
        tarballs = []
        for index, row in enumerate(rows):
            print(json.dumps(dict(stage='dependency_tarball_verification', package=row['name'], version=row['version'])), flush=True)
            destination = downloads / ('package-' + str(index) + '.tgz')
            bytes_count, digest, _ = _download(row['url'], row['integrity'], destination, deadline, total)
            tarballs.append(dict(row, bytes=bytes_count, sha256=digest))
        offline_env = _safe_env(runner, cache=offline_cache, home=home, folder=clients, offline=True)
        for row, index in zip(tarballs, range(len(tarballs))):
            runner['run_command']('ui cache seed', _setpriv([npm, 'cache', 'add', str(downloads / ('package-' + str(index) + '.tgz')),
                              '--offline', '--cache', str(offline_cache)]), cwd=workspace, env=offline_env,
                              timeout=_remaining(deadline), log=logs[1])
            _private_log(logs[1])
        _write_bytes(install / 'package.json', PACKAGE_RAW)
        _write_bytes(install / 'package-lock.json', lock_raw)
        runner['run_command']('ui npm ci', _setpriv([npm, 'ci', '--offline', '--ignore-scripts', '--no-audit', '--no-fund',
                          '--bin-links=false', '--cache', str(offline_cache)]), cwd=install, env=offline_env,
                          timeout=_remaining(deadline), log=logs[2])
        _private_log(logs[2])
        lock_after = _read_bounded(install / 'package-lock.json', MAX_LOCK_BYTES)
        package_after = _read_bounded(install / 'package.json', 64 * 1024)
        if lock_after != lock_raw or package_after != PACKAGE_RAW:
            _fail('dependency package lock changed')
        inventory_sha, file_count, file_bytes = _inventory(install / 'node_modules')
        smoke_command = _setpriv([node, '-e',
            "const {JSDOM}=require('jsdom'); const d=new JSDOM('<!doctype html><p id=x>ok</p>'); "
            "if(d.window.document.querySelector('#x').textContent!=='ok') process.exit(1); "
            "process.stdout.write(JSON.stringify({ok:1,uid:process.getuid(),gid:process.getgid(),groups:process.getgroups()}));"])
        runner['run_command']('ui jsdom smoke', smoke_command, cwd=install, env=offline_env,
                              timeout=_remaining(deadline), log=logs[3])
        smoke_text = _private_log(logs[3], maximum=64 * 1024, allow_empty=False).decode('utf-8', 'replace').strip()
        try:
            smoke = json.loads(smoke_text)
        except (ValueError, TypeError):
            _fail('dependency smoke JSON')
        if type(smoke) is not dict or smoke.get('ok') != 1 or smoke.get('uid') != 65534 or \
                smoke.get('gid') != 65534 or smoke.get('groups') != []:
            _fail('dependency smoke identity')
        final_inventory_sha, final_file_count, final_file_bytes = _inventory(install / 'node_modules')
        if (final_inventory_sha, final_file_count, final_file_bytes) != (inventory_sha, file_count, file_bytes):
            _fail('dependency inventory changed')
        final_node_binding = _verify_node_bindings(control_module, clients, node_result)
        if final_node_binding != node_binding:
            _fail('dependency node binding changed')
        for path in logs:
            _private_log(path)
        package_sha = _sha(PACKAGE_RAW)
        lock_sha = _sha(lock_raw)
        result = {
            'schema': PACKAGE_SCHEMA,
            'status': 'generated_and_offline_verified',
            'evidence_scope': 'dependency_preparation_only',
            'source_commit': expected_commit,
            'node_version': NODE_VERSION,
            'npm_version': NPM_VERSION,
            'package_sha256': package_sha,
            'lock_sha256': lock_sha,
            'tarballs': tarballs,
            'installed_inventory_sha256': inventory_sha,
            'installed_file_count': file_count,
            'installed_file_bytes': file_bytes,
            'uid': smoke['uid'],
            'gid': smoke['gid'],
            'supplementary_groups': smoke['groups'],
            'smoke': {'status': 'passed', 'ok': smoke['ok']},
            'node_binary_sha256': final_node_binding['tool_binary_sha256']['bin/node'],
            'node_client_inventory_sha256': final_node_binding['extracted_inventory_sha256'],
            'node_frozen_receipt_sha256': final_node_binding['frozen_receipt_sha256'],
            'node_binding_receipt_sha256': final_node_binding['binding_receipt_sha256'],
        }
    finally:
        if fixture is not None:
            wrapper.cleanup_fixture(*fixture, strict=True)
    _remaining(deadline)
    output.mkdir(mode=0o755)
    os.chmod(output, 0o755)
    _public_write(output / 'package.json', PACKAGE_RAW)
    _public_write(output / 'package-lock.json', lock_raw)
    _public_write(output / 'dependency-inputs.json', json.dumps(result, sort_keys=True, indent=2).encode() + b'\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--expected-commit', required=True)
    args = parser.parse_args(argv)
    try:
        generate(Path(args.output), args.expected_commit)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        diagnostic = str(error)
        if not re.fullmatch(r'(?:dependency|lock|package lock|jsdom lock|ui) [a-z ]{1,80}', diagnostic):
            diagnostic = 'dependency preparation failed'
        print(json.dumps(dict(status='failed', evidence_scope='dependency_preparation_only', error=diagnostic)))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


__all__ = ['PACKAGE_RAW', 'parse_lock', 'validate_tarball', 'generate']
