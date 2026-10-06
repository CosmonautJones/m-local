#!/usr/bin/env python3
"""Run adapted native compatibility checks against the current accepted package."""

from pathlib import Path
import ast
import hashlib
import json
import os
import re
import stat
import sys
import time


ROOT = Path(__file__).absolute().parents[1]
PREFIX = 'm-local-native-compatibility-v1-'
MAX_TIMEOUT = 8400
SUITE_RELATIVE = 'runtime-proof/native-inputs/native-suite-v5/run-kali-package-suite.py'
SUITE_SHA256 = '284a625ecfeb8dc77034ced6cfcdeadc7d27d171aae43dd34794dfa3dd9a55f5'
ORIGINAL_INPUTS_RELATIVE = 'runtime-proof/native-inputs/native-suite-v5/original-inputs.json'
ORIGINAL_INPUTS_SHA256 = '27d03f9e1d8eb17956789a7b84dbc8ce84bb222dec7644dbb18ce15672e6153f'
ISOLATION_RELATIVE = 'runtime-proof/native-inputs/runtime-build-source-isolation-v1.py'
ISOLATION_SHA256 = 'da9af3a768782c6ca9b28134df2b04ab4bac464a434e8ce3e29b69692c96ec9c'
ISOLATION_PROBE_SHA256 = '92c9a941a1956928be202b687c43aee3eeb0a71be68816c610ee4adb86b92708'
CATALOG_PROBE_RELATIVE = 'runtime-proof/native-inputs/native-suite-v5/runtime-catalog-cold-probe.py'
CATALOG_PROBE_SHA256 = '11aeda9794f7559e3a808c5771c7ad2a154b183090cb3f7ba35fc840bcf706ca'
CATALOG_AUDIT_RELATIVE = 'runtime-proof/native-inputs/native-suite-v5/runtime-catalog-path-audit.py'
CATALOG_AUDIT_SHA256 = 'ce6951fde1842b46cf1c1e26787367118953ff51c819f85728d8d7bd3aa4050e'
CATALOG_CONTROLS_RELATIVE = 'runtime-proof/native-inputs/native-suite-v5/test-runtime-catalog-path-audit.py'
CATALOG_CONTROLS_SHA256 = '3e656b49fb6e1843ac0cef14f8bed77b536dcdcab3526767685adeff569176f6'
SOURCE_DIGEST_RELATIVE = 'runtime-proof/native-inputs/native-suite-v5/export-emergency-checkpoint.py'
SOURCE_DIGEST_SHA256 = 'e73a01554b5b3fccb66b4544773b7dc74928c7d7ce7dbb1fcc60bf3c9f26caf4'
TEST_SCRIPT_SHA256 = 'ef9ca36358ca219df9562612e19ec08939e468ef563c95b86938d34f2df02068'
PRODUCTION_SOURCE_DIGEST_SHA256 = '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42'
LOADER_RELATIVE = 'runtime-proof/native-inputs/native-suite-v5/package-runtime-loader-provenance.py'
LOADER_SHA256 = 'ad3640c0e4efcfee41aa831b67e84456e2da8a6a96ef769cdc1533ab0582ebb2'
PACKAGE_VERIFIER_RELATIVE = 'runtime-proof/package-inputs/verify-runtime-package-inputs-v7.py'
PACKAGE_VERIFIER_SHA256 = '9f7acdfd45c3a66913c8c3c9205f3afc8b00801147b1082e2af329a17f27d8de'
RUNTIME_PATCH_SHA256 = 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
RUNTIME_BASE = '58cb97eb75cdff8b5ee78f4094ca2be16376601c'
OFFICIAL_BINARY_SHA256 = '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
CURRENT_RECIPE_SHA256 = 'ec820c414d5a83d498f894eddcee105d5eb3e287a030c2d6b87045fe7d32129f'
OLD_FORK = '/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork'
MATRIX_FORK = '/var/tmp/m-local-build-e-drive-v2-01a1050e/source-forks-v7/identity-type-source-v3-v7'
OLD_APP = '/var/tmp/m-local-identity-bootstrap-proof-v4-srq_c04w/app'
OLD_TASK = '/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local'
OLD_VERIFIED = '/var/tmp/m-local-kali-operator-056070bz'
PHASES = (
    'package-input-verification', 'catalog-cold-relocation',
    'runtime-materialization', 'runtime-commit-40001', 'runtime-commit-40P01',
    'runtime-commit-55P03', 'runtime-commit-08006',
    'runtime-runtime-boundary-probe', 'runtime-runtime-lifecycle-probe',
    'runtime-runtime-served-probe', 'runtime-runtime-request-context-probe',
    'runtime-runtime-nested-context-probe', 'install', 'check', 'onboarding',
    'analytics', 'core', 'insights', 'python-tooling', 'photo-media', 'ui-unit',
    'build', 'ui-dependencies', 'browser')
MATRIX_PHASES = (
    'materialization', 'commit-40001', 'commit-40P01', 'commit-55P03',
    'commit-08006', 'runtime-boundary-probe', 'runtime-lifecycle-probe',
    'runtime-served-probe', 'runtime-request-context-probe',
    'runtime-nested-context-probe')
INTERFACES = ('codec', 'controls')
SCOPE = 'fresh-native-compatibility-only'
CATALOG_MAX_BYTES = 32 * 1024 ** 2


def _fail(label):
    raise ValueError(label)


def _sha(raw):
    if type(raw) is not bytes:
        _fail('native compatibility bytes')
    return hashlib.sha256(raw).hexdigest()


def _read_path(path, maximum=1024 ** 3, allow_empty=False):
    path = Path(path)
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
                (info.st_size <= 0 and not allow_empty) or info.st_size > maximum):
            _fail('native compatibility regular file')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                     getattr(os, 'O_BINARY', 0))
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            raw = bytearray()
            while len(raw) <= maximum:
                chunk = stream.read(min(1024 ** 2, maximum + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            closed = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mode', 'st_uid', 'st_gid', 'st_nlink',
                  'st_mtime_ns')
        if (len(raw) != info.st_size or any(getattr(item, key) != getattr(info, key)
                for item in (opened, closed) for key in fields)):
            _fail('native compatibility file changed')
        return bytes(raw)
    except OSError:
        _fail('native compatibility file read')


def _read_committed(preflight, relative, commit, expected):
    raw = preflight['committed_file'](ROOT, commit, relative)
    if type(raw) is not bytes or _sha(raw) != expected:
        _fail('native compatibility committed input pin')
    return raw


def _write_private(path, raw, mode=0o444):
    path = Path(path)
    if path.exists() or path.is_symlink() or type(raw) is not bytes:
        _fail('native compatibility pre-existing output')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if hasattr(os, 'chown'):
            os.chown(path, 0, 0)
        os.chmod(path, mode)
    except OSError:
        _fail('native compatibility private output')
    if _sha(_read_path(path, allow_empty=not raw)) != _sha(raw):
        _fail('native compatibility output hash')


def _mount_identity(runner, directory):
    directory = Path(directory)
    e_root = Path(runner.get('E_ROOT', '/var/tmp/m-local-build-e-drive-v2-01a1050e'))
    var_tmp = Path('/var/tmp')
    if (directory.parent != var_tmp or not directory.name.startswith(PREFIX) or
            len(directory.name) != len(PREFIX) + 8 or directory.resolve() != directory or
            directory.is_symlink() or not directory.is_mount() or not e_root.is_mount() or
            e_root.is_symlink() or e_root.resolve() != e_root):
        _fail('native compatibility mount path')
    root_info, mounted_info = e_root.stat(), directory.stat()
    backing = e_root / directory.name
    if backing.is_symlink() or backing.resolve() != backing or not backing.is_dir():
        _fail('native compatibility mount backing')
    backing_info, var_info = backing.stat(), var_tmp.stat()
    if (any(getattr(item, 'st_uid', None) != 65534 or getattr(item, 'st_gid', None) != 65534 or
            item.st_mode & 0o777 != 0o700 for item in (root_info, mounted_info, backing_info)) or
            root_info.st_dev == var_info.st_dev or mounted_info.st_dev != root_info.st_dev or
            (mounted_info.st_dev, mounted_info.st_ino) != (backing_info.st_dev, backing_info.st_ino)):
        _fail('native compatibility mount identity')
    return mounted_info.st_dev, mounted_info.st_ino


def _context_paths(context):
    required = ('package', 'application', 'fork', 'official', 'accepted', 'probe_path',
                'isolation', 'isolation_directory', 'trace', 'node_client',
                'prepared_ui', 'ui_control', 'ui_runner', 'ui_directory',
                'matrix_directory', 'prepared_matrix', 'matrix_control', 'run_bounded')
    if type(context) is not dict or any(key not in context for key in required):
        _fail('native compatibility context fields')
    values = {key: Path(context[key]) for key in
              ('package', 'application', 'fork', 'official', 'probe_path',
               'isolation_directory', 'ui_directory', 'matrix_directory')}
    for key, path in values.items():
        if not path.is_absolute() or path.resolve() != path or path.is_symlink():
            _fail('native compatibility path binding ' + key)
    package = values['package']
    if package.parent != Path('/var/tmp') or not package.name.startswith('m-local-runtime-package-'):
        _fail('native compatibility package path')
    for key in ('application', 'fork'):
        if not values[key].is_dir():
            _fail('native compatibility source path ' + key)
    if not values['official'].is_dir() or not callable(context['run_bounded']):
        _fail('native compatibility official root or bounded runner')
    for key in ('accepted', 'isolation', 'trace', 'node_client', 'prepared_ui', 'prepared_matrix'):
        if type(context[key]) is not dict:
            _fail('native compatibility context object ' + key)
    if context['accepted'].get('status') != 'passed' or context['isolation'].get('status') != 'passed':
        _fail('native compatibility prerequisite status')
    return values


def _hash_checked(path, expected=None, maximum=1024 ** 3, allow_empty=False):
    actual = _sha(_read_path(path, maximum, allow_empty=allow_empty))
    if expected is not None and actual != expected:
        _fail('native compatibility hash binding')
    return actual


def _inventory(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        if any(part == '__pycache__' for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            _fail('native compatibility inventory symlink')
        if path.is_file() and path.name not in ('.ok', '.used'):
            result[str(path.relative_to(root))] = _hash_checked(
                path, maximum=256 * 1024 ** 2, allow_empty=True)
    return result


def _immutable_app_inventory(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if any(part in ('.jac', 'dist', 'node_modules', '__pycache__') for part in relative.parts):
            continue
        if path.is_symlink():
            _fail('native compatibility application symlink')
        if path.is_file() and path.name not in ('.ok', '.used'):
            result[relative.as_posix()] = _hash_checked(
                path, maximum=256 * 1024 ** 2, allow_empty=True)
    return result


def _source_digest(root):
    root = Path(root)
    paths = [root / '.jac-version', root / 'jac.toml']
    for name in ('services', 'client'):
        paths.extend(path for path in (root / name).rglob('*') if path.is_file() and
                     path.suffix in ('.jac', '.py', '.mjs', '.js', '.jsx', '.css') and
                     not path.name.endswith(('.test.jac', '.test.mjs', '.test.js')))
    paths.extend(path for path in root.glob('*.jac') if path.is_file() and not path.name.endswith('.test.jac'))
    paths.extend(path for path in (root / 'data').rglob('*') if path.is_file())
    result = hashlib.sha256()
    for path in sorted(set(paths), key=lambda value: value.relative_to(root).as_posix()):
        result.update(path.relative_to(root).as_posix().encode() + b'\0' +
                     _read_path(path, 256 * 1024 ** 2, allow_empty=True).replace(b'\r\n', b'\n') + b'\0')
    return result.hexdigest()


def _metadata(package):
    try:
        value = json.loads(_read_path(package / 'result.json'))
    except (ValueError, UnicodeError):
        _fail('native compatibility package metadata')
    if type(value) is not dict:
        _fail('native compatibility package metadata shape')
    return value


def _validate_original_inputs(raw):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        _fail('native compatibility original input manifest')
    if (value.get('schema') != 'm-local-native-suite-original-inputs-v1' or
            value.get('status') != 'frozen_not_executed' or
            value.get('evidence_scope') != 'immutable_original_sources_only' or
            value.get('adaptation_required') is not True or len(value.get('sources', [])) != 9 or
            tuple(value.get('compatibility_phases', ())) != PHASES or
            value.get('catalog_mutation_cases') != [
                'complete-physical-catalog', 'unknown-absolute-resolution-field',
                'missing-relative-target', 'payload-containment-escape',
                'python-payload-traversal', 'unreferenced-absolute-string'] or
            value.get('source_interfaces') != list(INTERFACES) or
            value.get('graph_coverage') != {'allowed_skips': 0, 'core_jac': 451,
                                            'insights_jac': 62, 'insights_node': 11,
                                            'insights_python': 12}):
        _fail('native compatibility original input manifest fields')
    return value


def _verify_package(package, accepted, official):
    metadata = _metadata(package)
    binary_hash = _hash_checked(package / 'jac')
    if (type(accepted) is not dict or accepted.get('status') != 'passed' or
            accepted.get('candidate_binary_sha256') != binary_hash or
            accepted.get('package_metadata_sha256') != _sha(_read_path(package / 'result.json'))):
        _fail('native compatibility accepted package binding')
    if (metadata.get('candidate_binary_sha256') != binary_hash or
            type(metadata.get('candidate_binary_bytes')) is not int or
            metadata.get('candidate_binary_bytes') != (package / 'jac').stat().st_size or
            metadata.get('official_binary_sha256') != OFFICIAL_BINARY_SHA256 or
            metadata.get('runtime_base') != RUNTIME_BASE or
            metadata.get('executed_recipe_sha256') != CURRENT_RECIPE_SHA256 or
            metadata.get('runtime_patch_sha256') != RUNTIME_PATCH_SHA256 or
            metadata.get('resumed_build') is not False or
            metadata.get('inherited_python_and_dependencies_byte_matched') is not True or
            metadata.get('fork_path_reference_files') or
            metadata.get('source_override_in_payload') is not False or
            metadata.get('packed_trailer_region_and_payload_verified') is not True):
        _fail('native compatibility package payload metadata')
    package_hash_fields = {
        'assembled-inputs.json': 'assembled_input_manifest_sha256',
        'inherited-inputs.json': 'inherited_input_manifest_sha256',
        'transaction.patch': 'runtime_patch_sha256',
        'executed-recipe.py': 'executed_recipe_sha256',
        'payload-build-references.json': 'build_reference_manifest_sha256',
    }
    for name, field in package_hash_fields.items():
        if _hash_checked(package / name) != metadata.get(field):
            _fail('native compatibility package input commitment')
    if json.loads(_read_path(package / 'payload-build-references.json')) != metadata.get('build_path_reference_files'):
        _fail('native compatibility package build references')
    if _hash_checked(package / 'stage/site/jaclang/_precompiled/MANIFEST.json') != metadata.get('sealed_manifest_sha256'):
        _fail('native compatibility sealed manifest')
    if _hash_checked(package / 'runtime.tar.zst') != metadata.get('payload_sha256'):
        _fail('native compatibility package payload archive')
    inherited = json.loads(_read_path(package / 'inherited-inputs.json'))
    if type(inherited) is not dict or type(inherited.get('python')) is not dict or type(inherited.get('dependencies')) is not dict:
        _fail('native compatibility inherited manifest')
    roots = [path.parent for path in (Path(official) / 'cache/rt').glob('*/site')
             if path.is_dir() and not path.is_symlink()]
    if len(roots) != 1:
        _fail('native compatibility official cache root')
    original = roots[0]
    if (_inventory(original / 'python') != inherited['python'] or
            _inventory(package / 'stage/python') != inherited['python']):
        _fail('native compatibility inherited python')
    for name, expected in inherited['dependencies'].items():
        if (_inventory(original / 'site' / name) != expected or
                _inventory(package / 'stage/site' / name) != expected):
            _fail('native compatibility inherited dependency')
    raw = _read_path(package / 'jac')
    if raw[-80:-72] != b'JACBIN01':
        _fail('native compatibility package trailer')
    payload_length = int.from_bytes(raw[-72:-64], 'little')
    payload_start = len(raw) - 80 - payload_length
    if payload_start <= 32 or hashlib.sha256(raw[payload_start:-80]).hexdigest() != raw[-64:].decode():
        _fail('native compatibility package payload hash')
    descriptor = raw[payload_start - 32:payload_start]
    if descriptor[:8] != b'JSCATRG1':
        _fail('native compatibility package catalog descriptor')
    offset = int.from_bytes(descriptor[8:16], 'little')
    length = int.from_bytes(descriptor[16:24], 'little')
    if (offset + length + 32 != payload_start or
            hashlib.sha256(raw[offset:offset + length]).hexdigest() != metadata.get('stub_catalog_sha256')):
        _fail('native compatibility package catalog hash')
    launcher = package / 'launcher'
    launcher_hash = _hash_checked(launcher)
    if not raw.startswith(_read_path(launcher)) or metadata.get('launcher_sha256') != launcher_hash:
        _fail('native compatibility launcher binding')
    if accepted.get('candidate_binary_sha256') not in (None, binary_hash):
        _fail('native compatibility accepted binary')
    return metadata, binary_hash


def _copy_application(source, destination):
    def copy_tree(source_root, destination_root):
        for path in sorted(source_root.rglob('*')):
            rel = path.relative_to(source_root)
            if any(part == '__pycache__' or part == '.jac' or part.startswith('.env') for part in rel.parts):
                continue
            if path.is_symlink():
                _fail('native compatibility source symlink')
            target = destination_root / rel
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=False)
                os.chmod(target, path.stat().st_mode & 0o777)
            elif path.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                raw = _read_path(path, maximum=64 * 1024 ** 2, allow_empty=True)
                if path.suffix == '.sh':
                    raw = raw.replace(b'\r\n', b'\n')
                _write_private(target, raw, path.stat().st_mode & 0o777 or 0o444)
    destination.mkdir(mode=0o755)
    for name in ('main.jac', 'theme.jac', 'jac.toml', '.jac-version'):
        source_file = source / name
        if not source_file.is_file() or source_file.is_symlink():
            _fail('native compatibility application input')
        _write_private(destination / name, _read_path(source_file, allow_empty=True),
                       source_file.stat().st_mode & 0o777 or 0o444)
    for name in ('services', 'client', 'data', 'tests', 'scripts'):
        copy_tree(source / name, destination / name)
    copy_tree(source / 'assets/brand', destination / 'assets/brand')
    if hasattr(os, 'chown'):
        for path in (destination, *sorted(destination.rglob('*'))):
            os.chown(path, 65534, 65534, follow_symlinks=False)


def _safe_environment(runner, directory, runtime, cache, scratch, official, node_bin, app):
    environment = runner['minimal_environment'](dict(
        JAC_BIN=str(runtime / 'jac'), JAC_CACHE_HOME=str(cache), JAC_NO_DEV_SOURCE='1',
        JAC_TEST_STRICT='1', JAC_PG_DIST=str(official / 'cache/pg/dist/linux-amd64-18.6.0'),
        JAC_PRECOMPILE_JOBS='2', JAC_PRECOMPILE_RECYCLE_MB='1024',
        PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(scratch), MLOCAL_APP_ROOT=str(app)))
    for key in list(environment):
        if ((key.startswith('MLOCAL_') and key != 'MLOCAL_APP_ROOT') or key in (
                'JAC_DEV_SOURCE', 'JAC_DB_URL', 'OPENAI_API_KEY', 'RESEND_API_KEY',
                'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')):
            environment.pop(key, None)
    environment['PATH'] = str(node_bin) + ':' + environment.get('PATH', '/usr/bin:/bin')
    environment['NO_PROXY'] = environment['no_proxy'] = 'localhost,127.0.0.1,::1'
    return environment


def _trace_binding(trace):
    if trace.get('status') != 'passed':
        _fail('native compatibility trace fixture')
    tools = Path(trace['trace_tools_directory'])
    receipt = json.loads(_read_path(trace['tracing_client_receipt_path'], 1024 ** 2))
    if receipt.get('status') != 'passed' or receipt.get('execve_arguments_traced') is not False:
        _fail('native compatibility trace receipt')
    trace_receipt_sha = trace.get('tracing_client_receipt_sha256')
    if (type(trace_receipt_sha) is not str or
            not re.fullmatch(r'[0-9a-f]{64}', trace_receipt_sha) or
            _hash_checked(trace['tracing_client_receipt_path']) != trace_receipt_sha):
        _fail('native compatibility trace receipt hash')
    binary = tools / 'root/usr/bin/strace'
    binary_sha = trace.get('client_binary_sha256')
    if (type(binary_sha) is not str or not re.fullmatch(r'[0-9a-f]{64}', binary_sha) or
            _hash_checked(binary) != binary_sha):
        _fail('native compatibility trace binary')
    tracee_sha = trace.get('tracee_environment_receipt_sha256')
    if (type(tracee_sha) is not str or not re.fullmatch(r'[0-9a-f]{64}', tracee_sha)):
        _fail('native compatibility trace environment hash')
    _hash_checked(trace['tracee_environment_receipt_path'], tracee_sha, 1024 ** 2)
    dependencies = receipt.get('dependency_sha256')
    if type(dependencies) is not dict:
        _fail('native compatibility trace dependency map')
    for path, expected in dependencies.items():
        if type(expected) is not str or not re.fullmatch(r'[0-9a-f]{64}', expected):
            _fail('native compatibility trace dependency hash')
        if _hash_checked(path) != expected:
            _fail('native compatibility trace dependency')
    file_syscalls = receipt.get('file_syscalls')
    if type(file_syscalls) is not str or not file_syscalls:
        _fail('native compatibility trace syscall binding')
    return tools, file_syscalls, trace_receipt_sha


def _check_state(state, label):
    requested = {'high': 7 * 1024 ** 3, 'max': 8 * 1024 ** 3, 'swap_max': 0}
    cleanup = state.get('cleanup', {}) if type(state) is dict else {}
    if (type(state) is not dict or state.get('requested_limits') != requested or
            state.get('limits') != requested or state.get('oom_policy') != 'stop' or
            state.get('controls_confirmed_before_workload') is not True or
            cleanup.get('cgroup_empty') is not True or cleanup.get('launcher_stopped') is not True):
        _fail('native compatibility bounded controls ' + label)


def _run_phase(context, directory, app, label, command, cwd, environment, timeout, trace,
               trace_roots, traced, isolation=None, hidden=None):
    if timeout <= 0:
        _fail('native compatibility phase deadline')
    child_env = dict(environment)
    trace_path = directory / (label + '.file-trace')
    denial_before = None
    denial_after = None
    if traced:
        if isolation is not None and hidden:
            isolation['check_sources'](hidden)
            denial_before = isolation['prove_denied'](hidden)
            if not denial_before:
                _fail('native compatibility source denial before ' + label)
        tools, file_syscalls, _ = _trace_binding(trace)
        if type(file_syscalls) is not str or not file_syscalls:
            _fail('native compatibility trace syscall binding')
        child_env['LD_LIBRARY_PATH'] = str(tools / 'root/usr/lib/x86_64-linux-gnu')
        command = [str(tools / 'root/usr/bin/strace'), '-f', '-qq', '-s', '4096',
                   '-e', 'trace=' + file_syscalls, '-E', 'LD_LIBRARY_PATH', '-o',
                   str(trace_path), *command]
    state = context['run_bounded'](directory, command, cwd, child_env, timeout, label)
    _check_state(state, label)
    row = dict(phase=label, status='passed', kernel_memory_scope=state)
    if traced:
        if isolation is not None and hidden:
            isolation['check_sources'](hidden)
            denial_after = isolation['prove_denied'](hidden)
            if not denial_after:
                _fail('native compatibility source denial after ' + label)
        raw = _read_path(trace_path, 256 * 1024 ** 2)
        trace_text = raw.decode('utf-8', 'replace')
        forbidden = {key: trace_text.count(value) for key, value in trace_roots.items() if key != 'package'}
        if any(forbidden.values()):
            _fail('native compatibility forbidden traced source path ' + label)
        row.update(trace_sha256=_sha(raw), traced_file_operations=len(trace_text.splitlines()),
                   forbidden_build_path_file_operations=forbidden,
                   execve_arguments_traced=False, build_source_aliases_kernel_private=True,
                   source_isolation_denial_before=denial_before,
                   source_isolation_denial_after=denial_after)
    return row


def _adapt_suite(raw, task, verified, source, fork, application):
    text = raw.decode('utf-8')
    replacements = (
        ("task = Path(" + repr(OLD_TASK) + ")", 'task = Path(' + repr(str(task)) + ')'),
        ("verified = Path(" + repr(OLD_VERIFIED) + ")", 'verified = Path(' + repr(str(verified)) + ')'),
        ("source = task / 'work/m-local'", 'source = Path(' + repr(str(source)) + ')'),
        ("assert metadata['executed_recipe_sha256'] == 'f564830f07af1131306c8d65b7f1182047864816572eda46cc7b52b0db40120c'",
         "assert metadata['executed_recipe_sha256'] == '" + CURRENT_RECIPE_SHA256 + "'"),
        ("assert metadata['launcher_sha256'] == 'c6cdf1cf60abba6a64d2b8b06a22b9ba9c8392ab24d8a5bda3cf45efc64c9ce8'",
         "assert metadata['launcher_sha256'] == hashlib.sha256((package / 'launcher').read_bytes()).hexdigest()"),
    )
    for old, new in replacements:
        if text.count(old) != 1:
            _fail('native compatibility suite marker')
        text = text.replace(old, new)
    text = (text.replace(OLD_FORK, str(fork)).replace(OLD_APP, str(application))
                .replace(OLD_VERIFIED, str(verified)))
    legacy = (OLD_VERIFIED, OLD_FORK, OLD_APP) + (() if str(task) == OLD_TASK else (OLD_TASK,))
    if any(value in text for value in legacy):
        _fail('native compatibility suite legacy path')
    try:
        ast.parse(text, filename=SUITE_RELATIVE)
    except SyntaxError:
        _fail('native compatibility adapted suite syntax')
    return text.encode('utf-8')


def _suite_contract_source(adapted, directory, application):
    """Extract and execute the frozen package/input assertions before its runner body."""
    try:
        text = adapted.decode('utf-8')
        helper_old = "helper = task / 'work/export-emergency-checkpoint.py'"
        helper_new = "helper = Path(" + repr(str(directory / 'export-emergency-checkpoint.py')) + ")"
        if text.count(helper_old) != 1:
            _fail('native compatibility suite digest helper marker')
        text = text.replace(helper_old, helper_new)
        source_old = "task / 'work/m-local'"
        if text.count(source_old) != 1:
            _fail('native compatibility suite source digest marker')
        text = text.replace(source_old, 'Path(' + repr(str(application)) + ')')
        tree = ast.parse(text, filename=SUITE_RELATIVE)
        selected = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == 'resources'
                    for target in node.targets):
                break
            selected.append(node)
        if not selected or not any(isinstance(node, ast.Assert) for node in selected):
            _fail('native compatibility frozen suite assertions')
        contract = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
        compile(contract, SUITE_RELATIVE + ':contract', 'exec')
        return ("import sys\n" + ast.unparse(contract) + "\n").encode('utf-8')
    except (SyntaxError, UnicodeError):
        _fail('native compatibility frozen suite contract')


def _catalog_controls_source(raw, audit, catalog, package_root, roots_file, output):
    try:
        text = raw.decode('utf-8')
        bounded_reader = '''
import os
import stat
_CATALOG_MAX_BYTES = 32 * 1024 ** 2
def _read_catalog_bounded(path):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1 or
            info.st_size <= 0 or info.st_size > _CATALOG_MAX_BYTES):
        raise ValueError('catalog size or identity')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                 getattr(os, 'O_BINARY', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mode', 'st_uid', 'st_gid',
                  'st_nlink', 'st_mtime_ns')
        if any(getattr(opened, key) != getattr(info, key) for key in fields):
            raise ValueError('catalog changed before read')
        data = bytearray()
        while len(data) <= _CATALOG_MAX_BYTES:
            chunk = stream.read(min(1024 ** 2, _CATALOG_MAX_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        closed = os.fstat(stream.fileno())
    if (len(data) != info.st_size or
            any(getattr(closed, key) != getattr(info, key) for key in fields)):
        raise ValueError('catalog changed during read')
    return bytes(data)
'''
        if text.count('import sys\n') != 1:
            _fail('native compatibility catalog controls imports')
        text = text.replace('import sys\n', 'import sys\n' + bounded_reader, 1)
        replacements = (
            ("directory = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/runtime-catalog-path-control-v3')",
             'directory = Path(' + repr(str(Path(output).parent)) + ')'),
            ("directory.mkdir()", 'assert directory.is_dir()'),
            ("probe = directory / 'executed-audit.py'", 'probe = Path(' + repr(str(audit)) + ')'),
            ("probe.write_bytes((task / 'work/runtime-catalog-path-audit.py').read_bytes())",
             'assert probe.is_file()'),
            ("(directory / 'executed-controls.py').write_bytes(Path(__file__).read_bytes())",
             "(directory / 'executed-controls.py').write_bytes(Path(__file__).read_bytes())"),
            ("origin = Path('/var/tmp/m-local-runtime-package-70g1w4vw')",
             'origin = Path(' + repr(str(package_root)) + ')'),
            ("data = (origin / 'stubcat.bin').read_bytes()",
             'data = _read_catalog_bounded(Path(' + repr(str(catalog)) + '))'),
            ("str(origin / 'stage/site/jaclang')", repr(str(package_root))),
            ("str(origin / 'classifier-roots.json')", repr(str(roots_file))),
            ("assert hashlib.sha256((origin / 'stubcat.bin').read_bytes()).hexdigest() == original_hash",
             'assert hashlib.sha256(_read_catalog_bounded(Path(' + repr(str(catalog)) + '))).hexdigest() == original_hash'),
            ("(directory / 'result.json').write_text(json.dumps(result, indent=2) + '\\n')",
             'Path(' + repr(str(output)) + ').write_text(json.dumps(result, indent=2) + \'\\n\')'),
        )
        for old, new in replacements:
            if text.count(old) != 1:
                _fail('native compatibility catalog control marker')
            text = text.replace(old, new)
        try:
            ast.parse(text, filename=CATALOG_CONTROLS_RELATIVE)
        except SyntaxError:
            _fail('native compatibility catalog control syntax')
        return text.encode('utf-8')
    except UnicodeError:
        _fail('native compatibility catalog control source')


def _graph_controller_source(path):
    raw = ('''from pathlib import Path
import os, subprocess, sys
from jaclang.data.pgembed import PgRuntime
from jaclang.server.session import shared_pg_data_dir
assert os.getuid() == 65534 and not os.environ.get('JAC_DB_URL')
os.umask(0o077)
pg_path = Path(shared_pg_data_dir())
assert pg_path == Path(os.environ['JAC_CACHE_HOME']) / 'pg/main'
runtime = PgRuntime(data_dir=str(pg_path), database='postgres')
result = None
try:
    runtime.ensure()
    result = subprocess.run(['bash', 'scripts/test.sh', sys.argv[1]], check=False)
finally:
    runtime.stop()
assert result is not None and not runtime.is_running()
raise SystemExit(result.returncode)
''').encode()
    _write_private(path, raw)
    return _sha(raw)


def _assert_graph(path, kind):
    text = _read_path(path, 64 * 1024 ** 2).decode('utf-8', 'replace').lower()
    counter_word = r'(?:skip(?:s|ped)?|fail(?:s|ed)?|failure(?:s)?|error(?:s)?|todo(?:s)?)'
    prefix = r'(?im)(?:^|[(:,;|])[ \t]*(?:#\s*)?'
    suffix = r'(?=[ \t]*(?:$|[,;|.)]))'
    if any(re.search(pattern, text) for pattern in (
            prefix + counter_word + r'[ \t]*(?:[:=][ \t]*|[ \t]+)[1-9]\d*' + suffix,
            prefix + r'[1-9]\d*[ \t]+' + counter_word + suffix)):
        _fail('native compatibility graph counters')
    if kind == 'core' and not re.search(r'\b451 passed(?:\s+in\b|$)', text, re.I):
        _fail('native compatibility core graph count')
    if kind == 'insights' and not (re.search(r'\b62 passed(?:\s+in\b|$)', text, re.I) and
            re.search(r'(?im)^\s*ran\s+12\s+tests?\b', text) and
            re.search(r'(?im)^\s*ok\s*$', text) and
            re.search(r'(?im)^\s*#\s*pass\s+11\b', text) and
            re.search(r'(?im)^\s*#\s*skipped\s+0\b', text) and
            re.search(r'(?im)^\s*#\s*fail\s+0\b', text)):
        _fail('native compatibility insights graph count')


def run_suite(preflight, runner, directory, expected_commit, context, timeout):
    """Run the frozen 24-phase native suite using parent-owned bounded controls."""
    if type(timeout) is not int or not 0 < timeout <= MAX_TIMEOUT:
        _fail('native compatibility timeout')
    values = _context_paths(context)
    mount_identity = _mount_identity(runner, directory)
    directory = Path(directory)
    if any(path.exists() or path.is_symlink() for path in directory.iterdir()):
        _fail('native compatibility pre-existing mount files')
    deadline = time.monotonic() + timeout

    def remaining(limit):
        value = min(limit, int(deadline - time.monotonic()))
        if value <= 0:
            _fail('native compatibility total deadline')
        return value

    suite_raw = _read_committed(preflight, SUITE_RELATIVE, expected_commit, SUITE_SHA256)
    original_inputs_raw = _read_committed(preflight, ORIGINAL_INPUTS_RELATIVE,
                                          expected_commit, ORIGINAL_INPUTS_SHA256)
    _validate_original_inputs(original_inputs_raw)
    isolation_raw = _read_committed(preflight, ISOLATION_RELATIVE, expected_commit, ISOLATION_SHA256)
    probe_raw = _read_committed(preflight, 'runtime-proof/native-inputs/test-runtime-build-source-isolation-v1.py',
                                expected_commit, ISOLATION_PROBE_SHA256)
    catalog_probe_raw = _read_committed(preflight, CATALOG_PROBE_RELATIVE, expected_commit, CATALOG_PROBE_SHA256)
    catalog_audit_raw = _read_committed(preflight, CATALOG_AUDIT_RELATIVE, expected_commit, CATALOG_AUDIT_SHA256)
    catalog_controls_raw = _read_committed(preflight, CATALOG_CONTROLS_RELATIVE, expected_commit, CATALOG_CONTROLS_SHA256)
    digest_raw = _read_committed(preflight, SOURCE_DIGEST_RELATIVE, expected_commit, SOURCE_DIGEST_SHA256)
    loader_raw = _read_committed(preflight, LOADER_RELATIVE, expected_commit, LOADER_SHA256)
    verifier_raw = _read_committed(preflight, PACKAGE_VERIFIER_RELATIVE, expected_commit, PACKAGE_VERIFIER_SHA256)
    metadata, binary_hash = _verify_package(values['package'], context['accepted'], values['official'])
    adapted_suite = _adapt_suite(suite_raw, ROOT, values['official'], values['application'],
                                 values['fork'], values['application'])
    contract_source = _suite_contract_source(adapted_suite, directory, values['application'])
    for name, raw in (
            ('adapted-suite-reference.py', adapted_suite), ('suite-contract.py', contract_source),
            ('export-emergency-checkpoint.py', digest_raw),
            ('executed-source-isolation.py', isolation_raw),
            ('source-isolation-probe.py', probe_raw), ('runtime-catalog-cold-probe.py', catalog_probe_raw),
            ('runtime-catalog-path-audit.py', catalog_audit_raw), ('frozen-catalog-controls.py', catalog_controls_raw),
            ('package-runtime-loader-provenance.py', loader_raw), ('verify-runtime-package-inputs.py', verifier_raw)):
        _write_private(directory / name, raw)
    isolation = {}
    exec(compile(isolation_raw, ISOLATION_RELATIVE, 'exec'), isolation)
    if context['isolation'].get('helper_sha256') != ISOLATION_SHA256:
        _fail('native compatibility source helper fixture binding')
    fixture = context['isolation']
    _hash_checked(fixture['receipt_path'], fixture['receipt_sha256'], 1024 ** 2)
    fixture_root = Path(context['isolation_directory'])
    _hash_checked(fixture_root / 'executed-helper.py', ISOLATION_SHA256, 1024 ** 2)
    _hash_checked(fixture_root / 'executed-probe.py', fixture['probe_sha256'], 1024 ** 2)

    package = values['package']
    app = directory / 'app'
    _copy_application(values['application'], app)
    source_digest = _source_digest(app)
    if source_digest != PRODUCTION_SOURCE_DIGEST_SHA256:
        _fail('native compatibility production source digest')
    test_script_sha = _hash_checked(app / 'scripts/test.sh')
    if test_script_sha != TEST_SCRIPT_SHA256:
        _fail('native compatibility test script')
    if b'[dev]' in _read_path(app / 'jac.toml', 1024 ** 2):
        _fail('native compatibility development source')
    app_input_inventory = _inventory(app)
    app_input_raw = (json.dumps(app_input_inventory, sort_keys=True, indent=2) + '\n').encode()
    _write_private(directory / 'app-input-files.json', app_input_raw)
    app_inventory = _immutable_app_inventory(app)
    fork_inventory = _inventory(values['fork'])
    stage_inventory = _inventory(package / 'stage')
    runtime = directory / 'runtime'
    cache = directory / 'cache'
    scratch = directory / 'scratch'
    npm_cache = directory / 'npm-cache'
    bun_cache = directory / 'bun-cache'
    for path in (runtime, cache, scratch, npm_cache, bun_cache):
        path.mkdir(mode=0o700)
    runtime_binary = runtime / 'jac'
    _write_private(runtime_binary, _read_path(package / 'jac'), 0o555)
    (runtime / 'jacpython').symlink_to('jac')
    for path in (runtime, cache, scratch, npm_cache, bun_cache, app):
        if hasattr(os, 'chown'):
            os.chown(path, 65534, 65534)
        os.chmod(path, 0o700 if path != app else 0o755)

    node_root = Path(context['node_client']['clients_directory'])
    node_bin = node_root / 'bin'
    node_tools = context['node_client'].get('tool_binary_sha256')
    node_dependencies = context['node_client'].get('dependency_sha256')
    if type(node_tools) is not dict or type(node_dependencies) is not dict:
        _fail('native compatibility Node binding maps')
    for relative, expected in node_tools.items():
        if _hash_checked(node_root / relative) != expected:
            _fail('native compatibility Node tool binding')
    for path, expected in node_dependencies.items():
        if _hash_checked(path) != expected:
            _fail('native compatibility Node dependency binding')
    trace_tools, trace_syscalls, trace_receipt_sha = _trace_binding(context['trace'])
    trace_roots = json.loads(_read_path(package / 'classifier-roots.json'))
    environment = _safe_environment(runner, directory, runtime, cache, scratch,
                                     values['official'], node_bin, app)
    environment['npm_config_cache'] = str(npm_cache)
    environment['BUN_INSTALL_CACHE_DIR'] = str(bun_cache)
    hidden = []
    receipt = dict(status='running', scope=SCOPE, workspace=str(directory), phases=[],
                   interfaces=[], original_suite_sha256=SUITE_SHA256,
                   adapted_suite_reference_sha256=_sha(adapted_suite),
                   controller_source_sha256=_sha(_read_path(__file__, 1024 ** 2)),
                   executed_suite_contract_sha256=_sha(contract_source),
                   frozen_suite_contract_sha256=_sha(contract_source),
                   source_digest_helper_sha256=SOURCE_DIGEST_SHA256,
                   source_digest_sha256=source_digest,
                   test_script_sha256=test_script_sha,
                   app_input_manifest_sha256=_sha(app_input_raw),
                   tracing_client_receipt_sha256=trace_receipt_sha,
                   tracing_file_syscalls=trace_syscalls,
                   tracing_tools_directory=str(trace_tools),
                   executed_controller_source_sha256=_sha(_read_path(__file__, 1024 ** 2)),
                   source_isolation_helper_sha256=ISOLATION_SHA256,
                   node_tool_binary_sha256=dict(node_tools),
                   node_dependency_sha256=dict(node_dependencies),
                   package_binary_sha256=binary_hash, runtime_patch_sha256=RUNTIME_PATCH_SHA256,
                   graph_coverage={'core_jac': 451, 'insights_jac': 62,
                                   'insights_node': 11, 'insights_python': 12,
                                   'allowed_skips': 0})
    failure = None
    receipt_raw = None
    try:
        package_input = directory / 'package-input-verification.json'
        contract_code = ('import runpy; runpy.run_path(' + repr(str(directory / 'suite-contract.py')) +
                         ', run_name="__main__"); runpy.run_path(' +
                         repr(str(directory / 'verify-runtime-package-inputs.py')) +
                         ', run_name="__main__")')
        row = _run_phase(context, directory, app, 'package-input-verification',
                         [sys.executable, '-I', '-B', '-S', '-c', contract_code,
                           str(package), str(package_input)], app, environment,
                         remaining(120), context['trace'], trace_roots, False)
        verified = json.loads(_read_path(package_input, 1024 ** 2))
        if verified.get('status') != 'passed' or verified.get('candidate_binary_sha256') != binary_hash:
            _fail('native compatibility package input verification')
        row['receipt_sha256'] = _sha(_read_path(package_input))
        row['frozen_suite_contract_executed'] = True
        row['executed_suite_contract_sha256'] = _sha(contract_source)
        receipt['phases'].append(row)

        for target in (values['fork'], package / 'stage'):
            hidden.append(isolation['hide_source'](target, '.unavailable-for-' + directory.name))
        receipt['source_isolation_denial_before'] = isolation['prove_denied'](hidden)
        isolation['check_sources'](hidden)
        if any(cache.iterdir()):
            _fail('native compatibility cache was warmed before cold relocation')

        audit_path = directory / 'runtime-catalog-path-audit.py'
        catalog_probe_path = directory / 'runtime-catalog-cold-probe.py'
        catalog_output = directory / 'catalog-cold-relocation.json'
        code = ('import runpy; runpy.run_path(' + repr(str(catalog_probe_path)) +
                ',init_globals=' + repr(dict(PACKAGE_PATH=str(package),
                OUTPUT_PATH=str(catalog_output), AUDIT_PATH=str(audit_path))) +
                ',run_name="__main__")')
        row = _run_phase(context, directory, app, 'catalog-cold-relocation',
                         [str(runtime / 'jacpython'), '-B', '-c', code], app, environment,
                         remaining(120), context['trace'], trace_roots, True,
                         isolation, hidden)
        catalog = json.loads(_read_path(catalog_output, 1024 ** 2))
        if (catalog.get('status') != 'passed' or
                catalog.get('candidate_binary_sha256') != binary_hash or
                catalog.get('module_path_records_verified') != 587 or
                catalog.get('module_type_records_verified') != 161):
            _fail('native compatibility cold catalog')
        row.update(receipt_sha256=_sha(_read_path(catalog_output)),
                   module_path_records=587, module_type_records=161)
        receipt['phases'].append(row)

        controls = directory / 'catalog-controls.py'
        controls_output = directory / 'catalog-controls.json'
        sdk_roots = catalog.get('sdk_roots')
        if (type(sdk_roots) is not list or len(sdk_roots) != 1 or
                type(sdk_roots[0]) is not str):
            _fail('native compatibility catalog sdk roots')
        roots = Path(sdk_roots[0])
        if (not roots.is_absolute() or roots.resolve() != roots or roots.is_symlink() or
                not roots.is_dir() or not roots.is_relative_to(cache)):
            _fail('native compatibility catalog sdk root')
        catalog_path = directory / 'packed-catalog.bin'
        if catalog_path.exists() or catalog_path.is_symlink():
            catalog_info = catalog_path.lstat()
            if (not stat.S_ISREG(catalog_info.st_mode) or catalog_path.is_symlink() or
                    catalog_info.st_nlink != 1 or catalog_info.st_size <= 0 or
                    catalog_info.st_size > CATALOG_MAX_BYTES):
                _fail('native compatibility catalog size or identity')
        control_source = _catalog_controls_source(catalog_controls_raw, audit_path,
                                                   catalog_path, roots,
                                                   package / 'classifier-roots.json',
                                                   controls_output)
        _write_private(controls, control_source)
        row = _run_phase(context, directory, app, 'catalog-mutation-controls',
                         [str(runtime / 'jacpython'), '-I', '-B', str(controls)], app,
                         environment, remaining(180), context['trace'], trace_roots, False)
        controls_result = json.loads(_read_path(controls_output, 1024 ** 2))
        expected_cases = ('complete-physical-catalog', 'unknown-absolute-resolution-field',
                          'missing-relative-target', 'payload-containment-escape',
                          'python-payload-traversal', 'unreferenced-absolute-string')
        if (controls_result.get('status') != 'passed' or
                tuple(row.get('name') for row in controls_result.get('cases', [])) != expected_cases or
                controls_result.get('audit_sha256') != CATALOG_AUDIT_SHA256 or
                controls_result.get('executed_controls_sha256') != _sha(control_source) or
                any(set(row) != {'name', 'status', 'exit_code', 'expected_result',
                                  'mutation_sha256', 'diagnostic'} or row.get('status') != 'passed'
                    for row in controls_result.get('cases', []))):
            _fail('native compatibility catalog mutation controls')
        row['receipt_sha256'] = _sha(_read_path(controls_output))
        row['frozen_controls_sha256'] = CATALOG_CONTROLS_SHA256
        row['executed_controls_sha256'] = _sha(control_source)
        row['audit_sha256'] = CATALOG_AUDIT_SHA256
        if _hash_checked(controls, row['executed_controls_sha256'], 1024 ** 2) != row['executed_controls_sha256']:
            _fail('native compatibility catalog controls changed')
        receipt['catalog_controls_sha256'] = row['receipt_sha256']
        receipt['catalog_controls'] = row

        matrix_receipt = json.loads(_read_path(context['prepared_matrix']['receipt_path'], 1024 ** 2))
        context['matrix_control']['verify_prepared'](
            preflight, context['matrix_directory'], context['prepared_matrix'])
        if (matrix_receipt.get('status') != 'prepared_not_executed' or
                len(matrix_receipt.get('phases', [])) != 10 or
                len(matrix_receipt.get('interfaces', [])) != 2):
            _fail('native compatibility prepared matrix binding')
        if (tuple(row.get('name') for row in matrix_receipt['phases']) != MATRIX_PHASES or
                tuple(row.get('name') for row in matrix_receipt['interfaces']) != INTERFACES):
            _fail('native compatibility prepared matrix names')
        expected_row_keys = {'name', 'original_probe_sha256', 'prepared_probe_sha256',
                             'fault_env', 'loader_sha256'}
        if any(set(row) != expected_row_keys for row in
               matrix_receipt['phases'] + matrix_receipt['interfaces']):
            _fail('native compatibility prepared matrix row fields')
        old_app = str(values['application']).encode()
        matrix = directory / 'runtime-matrix'
        matrix.mkdir(mode=0o700)
        if hasattr(os, 'chown'):
            os.chown(matrix, 65534, 65534)
        os.chmod(matrix, 0o700)
        matrix_info = matrix.stat()
        if (matrix_info.st_uid != 65534 or matrix_info.st_gid != 65534 or
                matrix_info.st_mode & 0o777 != 0o700 or matrix.is_symlink()):
            _fail('native compatibility matrix ownership')
        matrix_execution_bindings = []
        for row_data, interface in (
                [(row, False) for row in matrix_receipt['phases']] +
                [(row, True) for row in matrix_receipt['interfaces']]):
            name = row_data['name']
            raw = _read_path(Path(context['matrix_directory']) / (name + '.py'), 256 * 1024)
            expected = context['prepared_matrix']['prepared_file_sha256'].get(name + '.py')
            if expected is None or _sha(raw) != expected:
                _fail('native compatibility prepared probe hash')
            adapted = raw.replace(old_app, str(app).encode())
            for old_root in (str(values['fork']), OLD_FORK, MATRIX_FORK):
                adapted = adapted.replace((old_root + '/jac').encode(), str(roots).encode())
                adapted = adapted.replace(old_root.encode(), str(app).encode())
            adapted = adapted.replace(b"'/var/tmp'", repr(str(scratch)).encode())
            adapted = adapted.replace(b'"/var/tmp"', repr(str(scratch)).encode())
            if OLD_FORK.encode() in adapted or old_app in adapted or OLD_TASK.encode() in adapted:
                _fail('native compatibility matrix legacy path')
            if name == 'runtime-served-probe':
                text = adapted.decode()
                replacements = (
                    ("subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()",
                     repr(metadata.get('runtime_base', RUNTIME_BASE))),
                    ("hashlib.sha256(subprocess.check_output(['git', 'diff', '--binary'])).hexdigest()",
                     repr(metadata['runtime_patch_sha256'])),
                    ("Path('/var/tmp/m-local-kali-operator-056070bz/app/services/models.jac')",
                     'Path(' + repr(str(app / 'services/models.jac')) + ')'))
                for old, new in replacements:
                    if text.count(old) != 1:
                        _fail('native compatibility served probe marker')
                    text = text.replace(old, new)
                adapted = text.encode()
            probe = matrix / (name + '.py')
            _write_private(probe, adapted)
            loader = matrix / (name + '-loader.py')
            _write_private(loader, loader_raw)
            loader_out = matrix / (name + '-loader.json')
            code = ('import runpy,signal,sys; '
                    'signal.signal(signal.SIGTERM,lambda s,f: sys.exit(128+s)); '
                    'runpy.run_path(' + repr(str(loader)) +
                    ',init_globals={"OUTPUT_PATH":' + repr(str(loader_out)) + '}); '
                    'sys.path.insert(0,' + repr(str(app)) + '); '
                    'runpy.run_path(' + repr(str(probe)) + ',init_globals={"OUTPUT_PATH":' +
                    repr(str(matrix / (name + '-probe-result.json'))) +
                    '},run_name="__main__")')
            additions = dict(row_data.get('fault_env', {}), JAC_DB_RO_UNITS='0')
            phase_name = 'runtime-' + name if not interface else 'interface-' + name
            phase_env = dict(environment)
            phase_env.update(additions)
            row = _run_phase(context, directory, app, phase_name,
                             [str(runtime / 'jacpython'), '-c', code], app,
                             phase_env, remaining(300),
                             context['trace'], trace_roots, True, isolation, hidden)
            loader_result = json.loads(_read_path(loader_out, 1024 ** 2))
            cache_root = Path(environment['JAC_CACHE_HOME']).resolve()
            if (loader_result.get('status') != 'passed' or
                    len(loader_result.get('declaring_module_files', {})) < 16 or
                    any(not Path(value).is_relative_to(cache_root) for value in
                        [*loader_result.get('sdk_roots', []),
                         *loader_result.get('declaring_module_files', {}).values()])):
                _fail('native compatibility package loader provenance')
            row.update(original_probe_sha256=row_data['original_probe_sha256'],
                       prepared_probe_sha256=row_data['prepared_probe_sha256'],
                       executed_probe_sha256=_sha(adapted),
                       loader_sha256=LOADER_SHA256,
                       fault_env=additions,
                       loader_receipt_sha256=_sha(_read_path(loader_out)))
            probe_result = matrix / (name + '-probe-result.json')
            if interface:
                result = json.loads(_read_path(probe_result, 1024 ** 2))
                expected_cases = 2 if name == 'codec' else 6
                if result.get('status') != 'passed' or len(result.get('cases', [])) != expected_cases:
                    _fail('native compatibility interface result')
                row['probe_receipt_sha256'] = _sha(_read_path(probe_result))
            if _hash_checked(probe, row['executed_probe_sha256'], 256 * 1024) != row['executed_probe_sha256']:
                _fail('native compatibility executed matrix probe changed')
            if _hash_checked(loader, LOADER_SHA256, 256 * 1024) != LOADER_SHA256:
                _fail('native compatibility matrix loader changed')
            matrix_execution_bindings.append(dict(
                name=name,
                original_probe_sha256=row['original_probe_sha256'],
                prepared_probe_sha256=row['prepared_probe_sha256'],
                executed_probe_sha256=row['executed_probe_sha256'],
                loader_sha256=row['loader_sha256']))
            (receipt['interfaces'] if interface else receipt['phases']).append(row)
        receipt['matrix_execution_bindings'] = matrix_execution_bindings

        runtime_commands = (
            ('install', ['bash', '-c', 'source scripts/runtime.sh\n"$JAC_BIN" install'], 180, False),
            ('check', ['bash', 'scripts/check.sh'], 180, False),
            ('onboarding', ['bash', 'scripts/test.sh', 'onboarding'], 300, False),
            ('analytics', ['python3', '-m', 'unittest', 'discover', '-s',
                           'tests/analytics', '-p', 'test_analytics.py'], 60, False),
            ('python-tooling', ['python3', '-m', 'unittest', 'discover', '-s',
                                'tests/tooling', '-p', 'test_*.py'], 60, False),
            ('photo-media', ['bash', 'scripts/python.sh', '-m', 'unittest',
                             'tests/photo_media.py'], 180, False),
            ('ui-unit', [str(node_bin / 'node'), '--test'], 180, False),
            ('build', ['bash', 'scripts/build.sh'], 480, False))
        ui_unit_paths = sorted(p.relative_to(app).as_posix() for p in (app / 'tests/ui').glob('*.test.mjs'))
        ui_unit_paths += sorted(p.relative_to(app).as_posix() for p in (app / 'tests/tooling').glob('*.test.mjs'))
        if not ui_unit_paths:
            _fail('native compatibility UI unit test set')
        ui_count = len(list((app / 'tests/ui').glob('*.test.mjs')))
        if (not all(path.startswith('tests/ui/') for path in ui_unit_paths[:ui_count]) or
                not any(path.startswith('tests/tooling/') for path in ui_unit_paths)):
            _fail('native compatibility UI test path binding')
        ui_manifest_raw = (json.dumps(ui_unit_paths, indent=2) + '\n').encode()
        _write_private(directory / 'ui-unit-test-paths.json', ui_manifest_raw)
        runtime_commands = tuple(
            (label, (command + ui_unit_paths) if label == 'ui-unit' else command, limit, traced)
            for label, command, limit, traced in runtime_commands)
        for label, command, limit, traced in runtime_commands[:4]:
            row = _run_phase(
                context, directory, app, label, command, app, environment,
                remaining(limit), context['trace'], trace_roots, traced)
            receipt['phases'].append(row)

        graph = directory / 'graph-coverage-controller.py'
        graph_source_sha = _graph_controller_source(graph)
        if type(graph_source_sha) is not str and graph.is_file():
            graph_source_sha = _hash_checked(graph, maximum=1024 ** 2)
        elif type(graph_source_sha) is not str:
            graph_source_sha = None
        receipt['graph_controller_sha256'] = graph_source_sha
        for label, expected in (('core', 451), ('insights', 62)):
            row = _run_phase(context, directory, app, label,
                             [str(runtime / 'jacpython'), '-B', str(graph), label],
                             app, environment, remaining(900), context['trace'],
                             trace_roots, False)
            _assert_graph(directory / (label + '.log'), label)
            if (graph_source_sha is not None and
                    _hash_checked(graph, graph_source_sha, 1024 ** 2) != graph_source_sha):
                _fail('native compatibility graph controller changed')
            row['graph_count'] = expected
            receipt['phases'].append(row)
        for label, command, limit, traced in runtime_commands[4:]:
            receipt['phases'].append(_run_phase(
                context, directory, app, label, command, app, environment,
                remaining(limit), context['trace'], trace_roots, traced))

        ui_dir = values['ui_directory']
        context['ui_control']['verify_prepared'](
            preflight, context['ui_runner'], ui_dir, context['prepared_ui'],
            expected_commit, context['node_client'])
        ui_env = dict(environment,
                      MLOCAL_UI_TEST_MODULES=str(context['prepared_ui']['modules_directory']),
                      MLOCAL_UI_APP_ROOT=str(app),
                      NODE_PATH=str(context['prepared_ui']['modules_directory']))
        ui_smoke = [str(node_bin / 'node'), '-e',
                    "const p=require.resolve('jsdom'); const v=require('jsdom/package.json').version; "
                    "const r=process.env.MLOCAL_UI_TEST_MODULES; if(v!=='26.1.0'||!(p===r||p.startsWith(r+'/'))) process.exit(1); "
                    "const {JSDOM}=require('jsdom'); const d=new JSDOM('<p>x</p>'); "
                    "if(d.window.document.querySelector('p').textContent!=='x') process.exit(1)"]
        ui_install = Path(context['prepared_ui']['install_directory'])
        ui_modules = Path(context['prepared_ui']['modules_directory'])
        for path in (ui_install, ui_modules):
            info = path.stat()
            if (path.resolve() != path or path.is_symlink() or not path.is_dir() or
                    info.st_uid != 65534 or info.st_gid != 65534 or info.st_mode & 0o777 != 0o700):
                _fail('native compatibility UI dependency ownership')
        row = _run_phase(context, directory, app, 'ui-dependencies', ui_smoke,
                         ui_install, ui_env, remaining(120), context['trace'],
                         trace_roots, False)
        row['prepared_ui_receipt_sha256'] = _sha(
            _read_path(context['prepared_ui']['receipt_path'], 1024 ** 2))
        receipt['phases'].append(row)
        ui_tests = sorted(p.relative_to(app).as_posix()
                          for p in (app / 'tests/ui/browser').glob('*.test.mjs'))
        if not ui_tests:
            _fail('native compatibility browser test set')
        browser_row = _run_phase(
            context, directory, app, 'browser',
            [str(node_bin / 'node'), '--test', *ui_tests], app, ui_env,
            remaining(120), context['trace'], trace_roots, False)
        receipt['phases'].append(browser_row)
        context['ui_control']['verify_prepared'](
            preflight, context['ui_runner'], ui_dir, context['prepared_ui'],
            expected_commit, context['node_client'])
        remaining(1)
        actual_phases = tuple(row['phase'] for row in receipt['phases'])
        if actual_phases != PHASES:
            _fail('native compatibility phase order')
        if len(receipt['interfaces']) != 2:
            _fail('native compatibility interface count')
        if _hash_checked(package / 'jac') != binary_hash or _hash_checked(runtime / 'jac') != binary_hash:
            _fail('native compatibility binary changed')
        if _immutable_app_inventory(app) != app_inventory:
            _fail('native compatibility application changed')
        final_app_inventory = _inventory(app)
        if any(final_app_inventory.get(name) != digest for name, digest in app_input_inventory.items()):
            _fail('native compatibility application input changed')
        if _source_digest(app) != source_digest:
            _fail('native compatibility production source changed')
        if _hash_checked(directory / 'app-input-files.json') != receipt['app_input_manifest_sha256']:
            _fail('native compatibility app input manifest')
        if _hash_checked(directory / 'ui-unit-test-paths.json') != _sha(ui_manifest_raw):
            _fail('native compatibility UI input manifest')
        artifact = app / 'dist/mobile-starter.jab'
        artifact_sha = _hash_checked(artifact, maximum=256 * 1024 ** 2)
        if not artifact_sha or artifact.stat().st_size <= 0:
            _fail('native compatibility product artifact')
        receipt.update(artifact_sha256=artifact_sha, artifact_bytes=artifact.stat().st_size,
                       ui_unit_test_paths_sha256=_sha(ui_manifest_raw))
        for path, expected in (
                ('adapted-suite-reference.py', _sha(adapted_suite)),
                ('suite-contract.py', _sha(contract_source)),
                ('export-emergency-checkpoint.py', SOURCE_DIGEST_SHA256),
                ('executed-source-isolation.py', ISOLATION_SHA256),
                ('source-isolation-probe.py', ISOLATION_PROBE_SHA256),
                ('runtime-catalog-cold-probe.py', CATALOG_PROBE_SHA256),
                ('runtime-catalog-path-audit.py', CATALOG_AUDIT_SHA256),
                ('frozen-catalog-controls.py', CATALOG_CONTROLS_SHA256),
                ('package-runtime-loader-provenance.py', LOADER_SHA256),
                ('verify-runtime-package-inputs.py', PACKAGE_VERIFIER_SHA256)):
            _hash_checked(directory / path, expected, 1024 ** 2)
        for row_data in receipt['matrix_execution_bindings']:
            name = row_data['name']
            _hash_checked(directory / 'runtime-matrix' / (name + '.py'),
                          row_data['executed_probe_sha256'], 256 * 1024)
            _hash_checked(directory / 'runtime-matrix' / (name + '-loader.py'),
                          LOADER_SHA256, 256 * 1024)
        if graph_source_sha is not None:
            _hash_checked(graph, graph_source_sha, 1024 ** 2)
        _hash_checked(controls, receipt['catalog_controls']['executed_controls_sha256'],
                      1024 ** 2)
        for path, expected in node_tools.items():
            _hash_checked(node_root / path, expected)
        for path, expected in node_dependencies.items():
            _hash_checked(path, expected)
        _trace_tools_final, _trace_syscalls_final, trace_receipt_final = _trace_binding(
            context['trace'])
        if (trace_receipt_final != trace_receipt_sha or
                _trace_syscalls_final != trace_syscalls):
            _fail('native compatibility trace binding changed')
        _hash_checked(fixture['receipt_path'], fixture['receipt_sha256'], 1024 ** 2)
        _hash_checked(fixture_root / 'executed-helper.py', ISOLATION_SHA256, 1024 ** 2)
        _hash_checked(fixture_root / 'executed-probe.py', fixture['probe_sha256'], 1024 ** 2)
        receipt.update(status='passed', phase_count=24, interface_count=2,
                       catalog_count=6, source_isolation_denial_after=None,
                       source_restoration_verified=False)
    except BaseException as error:
        failure = error
        receipt.update(status='failed', failure_type=type(error).__name__)
    finally:
        if hidden:
            try:
                receipt['source_isolation_denial_after'] = isolation['prove_denied'](hidden)
                if not receipt['source_isolation_denial_after'] and failure is None:
                    failure = ValueError('native compatibility source denial after suite')
            except BaseException as error:
                receipt['source_isolation_denial_after'] = False
                if failure is None:
                    failure = error
            finally:
                try:
                    isolation['restore_sources'](hidden)
                except BaseException as error:
                    if failure is None:
                        failure = error
            try:
                receipt['source_restoration_verified'] = all(
                    row['original'].is_dir() for row in hidden)
                if (not receipt['source_restoration_verified'] or
                        _inventory(values['fork']) != fork_inventory or
                        _inventory(package / 'stage') != stage_inventory):
                    receipt['source_restoration_verified'] = False
                    if failure is None:
                        failure = ValueError('native compatibility source changed')
            except BaseException as error:
                receipt['source_restoration_verified'] = False
                if failure is None:
                    failure = error
        if failure is not None:
            receipt.update(status='failed', failure_type=type(failure).__name__)
        _mount_identity(runner, directory)
        receipt_raw = (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode()
        _write_private(directory / 'result.json', receipt_raw, 0o400)
    if failure is not None:
        raise failure
    return dict(status='passed', scope=SCOPE,
                receipt_path=directory / 'result.json',
                receipt_sha256=_sha(receipt_raw),
                original_suite_sha256=SUITE_SHA256,
                adapted_suite_reference_sha256=receipt['adapted_suite_reference_sha256'],
                executed_suite_contract_sha256=receipt['executed_suite_contract_sha256'],
                phase_count=24, interface_count=2, catalog_count=6,
                source_isolation_denial_before=receipt['source_isolation_denial_before'],
                source_isolation_denial_after=receipt['source_isolation_denial_after'],
                source_restoration_verified=True,
                package_binary_sha256=binary_hash,
                runtime_patch_sha256=RUNTIME_PATCH_SHA256,
                mount_identity=mount_identity)


__all__ = ['run_suite']
