#!/usr/bin/env python3
"""Prepare the authenticated source-form runtime matrix without executing it."""

import ast
import hashlib
import io
import json
import math
import os
from pathlib import Path


MANIFEST_SHA256 = 'f0ade58e7b59cc49eb5c3c3d0a6c8ca08c4f5b9804dc49ad5ea4f171cc4be037'
PATCH_SHA256 = 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
OFFICIAL_BINARY_SHA256 = '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
APPLICATION_PATH = '/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local/work/m-local'
FORK_PATH = '/var/tmp/m-local-build-e-drive-v2-01a1050e/source-forks-v7/identity-type-source-v3-v7'
OLD_APPLICATION = '/var/tmp/m-local-release-readiness-01a1050e'
OLD_FORK = '/var/tmp/m-local-runtime-fork-01a1050e'
OLD_GUARD = "if workspace.parent != Path('/var/tmp') or not workspace.name.startswith(('m-local-release-readiness-', 'm-local-runtime-fork-', 'm-local-runtime-proof.')):"
OLD_LOADER_ROOT = "root = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork').resolve()"
MATRIX_RECEIPT = 'source-matrix-receipt.json'
CONTROLLER = 'work/identity-runtime-v3/run-identity-runtime-regressions.py'
LOADER = 'work/identity-runtime-v3/runtime-loader-provenance.py'
PATCH = 'work/identity-runtime-v3/runtime.patch'
PROBES = (
    'work/runtime-materialization-probe.py',
    'work/runtime-probe.py',
    'work/runtime-boundary-probe.py',
    'work/runtime-lifecycle-probe.py',
    'work/runtime-served-probe.py',
    'work/runtime-request-context-probe.py',
    'work/runtime-nested-context-probe.py',
    'work/runtime-interface-codec-probe.py',
    'work/runtime-interface-codec-controls-probe.py',
)
SOURCE_INPUTS = (CONTROLLER, LOADER, PATCH) + PROBES


def _fail(label):
    raise RuntimeError(label)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash_value(value, label):
    if type(value) is not str or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
        _fail(label)
    return value


def _json(raw, label):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail(label + ' duplicate key')
            result[key] = value
        return result

    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=lambda value: _fail(label + ' nonfinite'))
    except (UnicodeError, ValueError, RecursionError):
        _fail(label + ' JSON')


def _keys(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        _fail(label + ' keys')


def _universal_text(raw, label):
    try:
        with io.TextIOWrapper(io.BytesIO(raw), encoding='utf-8', newline=None) as stream:
            return stream.read()
    except (UnicodeError, ValueError):
        _fail(label + ' encoding')


def _canonical_path(value, label, expected):
    text = str(value)
    if not text or '\x00' in text or '\r' in text or '\n' in text:
        _fail(label + ' text')
    if not text.startswith('/') and not (len(text) >= 3 and text[1] == ':' and text[2] in '/\\'):
        _fail(label + ' absolute')
    pieces = text.replace('\\', '/').split('/')
    if any(piece in ('', '.') for piece in pieces[1:] if piece == '.') or '..' in pieces:
        _fail(label + ' traversal')
    if text != expected:
        _fail(label + ' binding')
    path = Path(text)
    try:
        if path.exists() and (path.is_symlink() or path.resolve() != path):
            _fail(label + ' symlink')
    except OSError:
        _fail(label + ' identity')
    return text


def _fresh_directory(directory):
    path = Path(directory)
    if not path.is_absolute() or path.is_symlink() or path.resolve() != path or not path.is_dir():
        _fail('prepared directory identity')
    try:
        for parent in (path, *path.parents):
            if parent.is_symlink() or parent.resolve() != parent:
                _fail('prepared directory ancestor')
        if any(path.iterdir()):
            _fail('prepared directory not empty')
    except OSError:
        _fail('prepared directory access')
    return path


def _read_regular(preflight, path, label):
    reader = preflight.get('read_regular') if type(preflight) is dict else None
    if not callable(reader):
        _fail('preflight reader')
    try:
        raw = reader(path)
    except (OSError, RuntimeError, ValueError, TypeError):
        _fail(label + ' read')
    if type(raw) is not bytes:
        _fail(label + ' bytes')
    return raw


def _source_path(bundle, relative):
    base = Path(bundle)
    if not base.is_absolute() or base.is_symlink() or base.resolve() != base:
        _fail('source bundle identity')
    path = base / 'files' / relative
    if path.is_symlink() or path.resolve() != path:
        _fail('source member identity')
    return path


def _validate_manifest(manifest_raw):
    if type(manifest_raw) is not bytes or _sha(manifest_raw) != MANIFEST_SHA256:
        _fail('source manifest hash')
    manifest = _json(manifest_raw, 'source manifest')
    if type(manifest) is not dict or manifest.get('status') != 'staged_not_executed' or \
            manifest.get('scope') != 'Only public source/probes and two reviewed patches; no historical receipt, cache, graph, account, image or private log':
        _fail('source manifest scope')
    files = manifest.get('files')
    if type(files) is not dict:
        _fail('source manifest files')
    if manifest.get('patch_sha256') != PATCH_SHA256:
        _fail('source manifest patch')
    for relative in SOURCE_INPUTS:
        metadata = files.get(relative)
        if type(metadata) is not dict or type(metadata.get('bytes')) is not int or metadata['bytes'] <= 0 or \
                _hash_value(metadata.get('sha256'), 'source manifest member') != metadata['sha256']:
            _fail('source manifest member')
    return manifest


def _validate_handoff(source_gate, origin):
    if type(source_gate) is not dict or source_gate.get('status') != 'passed' or \
            source_gate.get('scope') != 'source and package input commitment verification only':
        _fail('source gate scope')
    source = source_gate.get('source')
    if type(source) is not dict:
        _fail('source summary')
    _keys(source, ('status', 'scope', 'member_count', 'total_bytes', 'contract_sha256', 'commit_sha', 'run_id'),
          'source summary')
    if source.get('status') != 'passed' or \
            source.get('scope') != 'sanitized commitment bundle verification' or \
            type(source.get('member_count')) is not int or source.get('member_count') != 36 or \
            type(source.get('total_bytes')) is not int or source['total_bytes'] <= 0:
        _fail('source summary')
    contract = _hash_value(source.get('contract_sha256'), 'source contract')
    commit = source.get('commit_sha')
    run_id = source.get('run_id')
    if type(commit) is not str or len(commit) != 40 or any(char not in '0123456789abcdef' for char in commit) or \
            type(run_id) is not str or not run_id.isdigit() or run_id.startswith('0'):
        _fail('source summary identity')
    if type(origin) is not dict or origin.get('status') != 'passed' or \
            origin.get('scope') != 'successful source-proof origin commitment' or origin.get('contract_sha256') != contract or \
            type(origin.get('run_id')) is not int or origin['run_id'] != int(run_id):
        _fail('source origin binding')
    origin_fields = {}
    for key in ('job_id', 'artifact_id', 'artifact_digest', 'artifact_size'):
        value = origin.get(key)
        if key.endswith('_id') or key == 'artifact_size':
            if type(value) is not int or value <= 0:
                _fail('source origin ' + key)
        elif key == 'artifact_digest':
            if type(value) is not str or value[:7] != 'sha256:' or len(value) != 71 or \
                    any(char not in '0123456789abcdef' for char in value[7:]):
                _fail('source origin artifact digest')
        origin_fields[key] = value
    return source, contract, commit, run_id, origin_fields


def _validate_contract(raw, source, origin, manifest_hash, matrix_hash):
    contract = _json(raw, 'source contract')
    expected = ('cold_compile_provenance', 'forbidden', 'jac_license_notice', 'member_count', 'members',
                'producer', 'runtime_patch_sha256', 'source_bootstrap_receipt_sha256', 'source_manifest_sha256',
                'source_matrix_receipt_sha256', 'status', 'total_bytes')
    _keys(contract, expected, 'source contract')
    if contract.get('status') != 'prepared_not_uploaded' or contract.get('member_count') != 36 or \
            type(contract.get('total_bytes')) is not int or contract['total_bytes'] <= 0 or \
            contract['total_bytes'] != source['total_bytes'] or \
            contract.get('source_manifest_sha256') != manifest_hash or contract.get('runtime_patch_sha256') != PATCH_SHA256 or \
            contract.get('source_matrix_receipt_sha256') != matrix_hash:
        _fail('source contract scope')
    producer = contract.get('producer')
    _keys(producer, ('commit_sha', 'run_id', 'source_runner_sha256', 'adapter_manifest_sha256',
                    'application_revision', 'application_digest', 'jac_base', 'official_binary_sha256',
                    'jacpython_sha256', 'helper_sha256', 'entrypoint_policy', 'evidence_scope'),
          'source contract producer')
    if type(producer) is not dict or producer.get('commit_sha') != source['commit_sha'] or \
            producer.get('run_id') != source['run_id'] or origin.get('contract_sha256') != _sha(raw):
        _fail('source contract producer')
    for key in ('source_runner_sha256', 'adapter_manifest_sha256', 'application_digest', 'jacpython_sha256',
                'helper_sha256', 'official_binary_sha256'):
        _hash_value(producer.get(key), 'source contract producer ' + key)
    if producer.get('official_binary_sha256') != OFFICIAL_BINARY_SHA256 or \
            producer.get('entrypoint_policy') != 'source_only_via_pinned_adapters' or \
            producer.get('evidence_scope') != 'sanitized_commitments_only':
        _fail('source contract producer scope')
    return contract


def _validate_matrix(raw, contract, expected_hash):
    if _sha(raw) != expected_hash:
        _fail('source matrix hash')
    receipt = _json(raw, 'source matrix receipt')
    outer_keys = ('child', 'child_result_sha256', 'cold_compile_receipt_sha256', 'elapsed_seconds',
                  'parent_policy', 'result_sha256', 'source_gate_sha256', 'stage', 'status', 'wrapper_sha256')
    _keys(receipt, outer_keys, 'source matrix receipt')
    if receipt.get('status') != 'passed' or receipt.get('stage') != 'run-source-matrix-v9' or \
            receipt.get('parent_policy') != 'JAC_NO_DEV_SOURCE=1; JAC_DEV_SOURCE and JAC_DB_URL removed; leaf controls are authoritative' or \
            receipt.get('cold_compile_receipt_sha256') is not None or \
            receipt.get('child_result_sha256') != receipt.get('result_sha256'):
        _fail('source matrix receipt scope')
    for key in ('child_result_sha256', 'result_sha256', 'source_gate_sha256', 'wrapper_sha256'):
        _hash_value(receipt.get(key), 'source matrix ' + key)
    if type(receipt.get('elapsed_seconds')) not in (int, float) or isinstance(receipt['elapsed_seconds'], bool) or \
            not math.isfinite(receipt['elapsed_seconds']) or receipt['elapsed_seconds'] < 0:
        _fail('source matrix elapsed')
    child = receipt.get('child')
    child_keys = ('actual_smtp', 'checks', 'cold_compile_receipt_sha256', 'interface_count', 'jacpython_sha256',
                  'official_binary_sha256', 'phase_count', 'runtime_patch_sha256', 'source_override_explicit', 'status')
    _keys(child, child_keys, 'source matrix child')
    if child.get('status') != 'passed' or type(child.get('phase_count')) is not int or child.get('phase_count') != 10 or \
            type(child.get('interface_count')) is not int or child.get('interface_count') != 2 or \
            child.get('runtime_patch_sha256') != PATCH_SHA256 or child.get('actual_smtp') is not False or \
            child.get('checks') is not None or child.get('cold_compile_receipt_sha256') is not None or \
            child.get('jacpython_sha256') is not None or child.get('source_override_explicit') is not None:
        _fail('source matrix child scope')
    if child.get('official_binary_sha256') != OFFICIAL_BINARY_SHA256:
        _fail('source matrix binary')
    return receipt


def _derive_cases(controller):
    try:
        ast.parse(controller, filename=CONTROLLER)
    except SyntaxError:
        _fail('source controller syntax')
    markers = (
        "run('materialization', 'runtime-materialization-probe.py')",
        "for state in ('40001', '40P01', '55P03', '08006'):",
        "run('commit-' + state, 'runtime-probe.py', {'MLOCAL_PROBE_SQLSTATE': state, 'MLOCAL_PROBE_ACCEPTED_COMMIT': '1' if state == '08006' else '0'})",
        "for name in ('runtime-boundary-probe', 'runtime-lifecycle-probe', 'runtime-served-probe', 'runtime-request-context-probe', 'runtime-nested-context-probe'):",
        "run(name, name + '.py')",
        "run('codec', 'runtime-interface-codec-probe.py', interface=True)",
        "run('controls', 'runtime-interface-codec-controls-probe.py', interface=True)",
    )
    if any(controller.count(marker) != 1 for marker in markers):
        _fail('source controller derivation')
    phases = [('materialization', 'runtime-materialization-probe.py', {}),
              *[('commit-' + state, 'runtime-probe.py',
                 {'MLOCAL_PROBE_SQLSTATE': state, 'MLOCAL_PROBE_ACCEPTED_COMMIT': '1' if state == '08006' else '0'})
                for state in ('40001', '40P01', '55P03', '08006')],
              *[(name, name + '.py', {}) for name in ('runtime-boundary-probe', 'runtime-lifecycle-probe',
                                                       'runtime-served-probe', 'runtime-request-context-probe',
                                                       'runtime-nested-context-probe')]]
    interfaces = [('codec', 'runtime-interface-codec-probe.py', {}),
                  ('controls', 'runtime-interface-codec-controls-probe.py', {})]
    return phases, interfaces


def _adapt_probe(raw, relative, application, fork):
    text = _universal_text(raw, relative)
    name = Path(relative).name
    expected_app = 1 if name == 'runtime-served-probe.py' else 0
    expected_fork = 0 if name == 'runtime-probe.py' else 1
    if text.count(OLD_APPLICATION) != expected_app or text.count(OLD_FORK) != expected_fork:
        _fail(relative + ' path markers')
    if text.count(OLD_GUARD) != (1 if name == 'runtime-probe.py' else 0):
        _fail(relative + ' guard marker')
    adapted = text.replace(OLD_APPLICATION, application).replace(OLD_FORK, fork)
    if name == 'runtime-probe.py':
        adapted = adapted.replace(OLD_GUARD, 'if workspace != Path(' + repr(fork) + '):')
    if OLD_APPLICATION in adapted or OLD_FORK in adapted or OLD_GUARD in adapted:
        _fail(relative + ' legacy binding')
    try:
        ast.parse(adapted, filename=relative)
    except SyntaxError:
        _fail(relative + ' adapted syntax')
    return adapted.encode('utf-8')


def _adapt_loader(raw, fork):
    text = _universal_text(raw, LOADER)
    if text.count(OLD_LOADER_ROOT) != 1:
        _fail('source loader marker')
    text = text.replace(OLD_LOADER_ROOT, 'root = Path(' + repr(fork) + ').resolve()')
    if OLD_LOADER_ROOT in text:
        _fail('source loader legacy binding')
    try:
        ast.parse(text, filename=LOADER)
    except SyntaxError:
        _fail('source loader syntax')
    return text.encode('utf-8')


def _write_private(path, raw):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(str(path), flags | nofollow, 0o400)
        try:
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    _fail('prepared output write')
                view = view[written:]
            if hasattr(os, 'fchmod'):
                os.fchmod(fd, 0o400)
            else:
                os.chmod(str(path), 0o400)
        finally:
            os.close(fd)
    except (OSError, TypeError):
        _fail('prepared output write')


def _read_output(path):
    try:
        info = os.lstat(path)
        if not os.path.isfile(path) or os.path.islink(path) or info.st_nlink != 1 or \
                info.st_size <= 0 or info.st_size > 1024 ** 2:
            _fail('prepared output identity')
        if os.name == 'posix' and (info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o777 != 0o400):
            _fail('prepared output ownership')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
        fd = os.open(str(path), flags)
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            fields = ('st_dev', 'st_ino', 'st_size', 'st_mode', 'st_uid', 'st_gid', 'st_nlink')
            if any(getattr(info, key) != getattr(opened, key) for key in fields):
                _fail('prepared output replacement')
            raw = stream.read(info.st_size + 1)
            closed = os.fstat(stream.fileno())
            if len(raw) != info.st_size or any(getattr(opened, key) != getattr(closed, key) for key in fields):
                _fail('prepared output read')
            return raw
    except OSError:
        _fail('prepared output read')


def verify_prepared(preflight, directory, prepared):
    directory = Path(directory)
    if not directory.is_absolute() or directory.is_symlink() or directory.resolve() != directory or not directory.is_dir():
        _fail('prepared directory identity')
    if os.name == 'posix':
        directory_info = os.lstat(directory)
        if directory_info.st_uid != 65534 or directory_info.st_gid != 65534 or directory_info.st_mode & 0o777 != 0o700:
            _fail('prepared directory ownership')
    if not isinstance(prepared, dict) or prepared.get('status') != 'prepared_not_executed' or prepared.get('executed') is not False:
        _fail('prepared result status')
    receipt_path = Path(prepared.get('receipt_path', ''))
    if receipt_path != directory / 'prepared-result.json':
        _fail('prepared receipt path')
    receipt_raw = _read_output(receipt_path)
    if _sha(receipt_raw) != prepared.get('receipt_sha256'):
        _fail('prepared receipt hash')
    receipt = _json(receipt_raw, 'prepared receipt')
    if receipt.get('status') != 'prepared_not_executed' or receipt.get('executed') is not False:
        _fail('prepared receipt status')
    inventory = receipt.get('prepared_file_sha256')
    if type(inventory) is not dict or prepared.get('prepared_file_sha256') != inventory or \
            prepared.get('prepared_inventory_sha256') != _sha(json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode()):
        _fail('prepared inventory binding')
    phases, interfaces = receipt.get('phases'), receipt.get('interfaces')
    if type(phases) is not list or len(phases) != 10 or type(interfaces) is not list or len(interfaces) != 2:
        _fail('prepared matrix cardinality')
    row_keys = ('name', 'original_probe_sha256', 'prepared_probe_sha256', 'fault_env', 'loader_sha256')
    for rows in (phases, interfaces):
        for row in rows:
            _keys(row, row_keys, 'prepared matrix row')
            if type(row['name']) is not str or not row['name'] or type(row['fault_env']) is not dict:
                _fail('prepared matrix row values')
            _hash_value(row['original_probe_sha256'], 'prepared original probe hash')
            _hash_value(row['prepared_probe_sha256'], 'prepared probe hash')
            _hash_value(row['loader_sha256'], 'prepared loader hash')
    expected_members = [row['name'] + '.py' for row in phases]
    expected_members.extend(row['name'] + '.py' for row in interfaces)
    expected_members.append('source-loader.py')
    if set(inventory) != set(expected_members) or len(expected_members) != len(set(expected_members)):
        _fail('prepared inventory members')
    expected_on_disk = set(inventory) | {'prepared-result.json'}
    try:
        on_disk = {item.name for item in directory.iterdir()}
    except OSError:
        _fail('prepared output inventory')
    if on_disk != expected_on_disk or any((directory / name).is_symlink() or not (directory / name).is_file()
                                          for name in on_disk):
        _fail('prepared output inventory')
    for relative, expected in inventory.items():
        raw = _read_output(directory / relative)
        if _sha(raw) != expected:
            _fail('prepared file hash')
    return prepared['prepared_inventory_sha256']


def prepare_matrix(preflight, bundle: Path, directory: Path, *, source_gate: dict, origin: dict,
                   manifest_raw: bytes, application: Path, fork: Path) -> dict:
    directory = _fresh_directory(directory)
    application = _canonical_path(application, 'application', APPLICATION_PATH)
    fork = _canonical_path(fork, 'fork', FORK_PATH)
    manifest = _validate_manifest(manifest_raw)
    source, contract, commit, run_id, origin_fields = _validate_handoff(source_gate, origin)
    contract_raw = _read_regular(preflight, Path(bundle) / 'contract.json', 'source contract')
    if _sha(contract_raw) != contract:
        _fail('source contract hash')
    matrix_hash = _hash_value(_json(contract_raw, 'source contract').get('source_matrix_receipt_sha256'), 'source matrix binding')
    _validate_contract(contract_raw, source, origin, MANIFEST_SHA256, matrix_hash)
    matrix_raw = _read_regular(preflight, Path(bundle) / MATRIX_RECEIPT, MATRIX_RECEIPT)
    matrix = _validate_matrix(matrix_raw, contract, matrix_hash)

    input_hashes = { 'manifest.json': _sha(manifest_raw), MATRIX_RECEIPT: _sha(matrix_raw) }
    originals = {}
    for relative in SOURCE_INPUTS:
        raw = _read_regular(preflight, _source_path(bundle, relative), relative)
        metadata = manifest['files'][relative]
        if len(raw) != metadata['bytes'] or _sha(raw) != metadata['sha256']:
            _fail(relative + ' source hash')
        originals[relative] = raw
        input_hashes[relative] = _sha(raw)
    if _sha(originals[PATCH]) != PATCH_SHA256:
        _fail('runtime patch source hash')

    controller_text = _universal_text(originals[CONTROLLER], CONTROLLER)
    phases, interfaces = _derive_cases(controller_text)
    loader = _adapt_loader(originals[LOADER], fork)
    loader_hash = _sha(loader)
    generated = {'source-loader.py': loader}
    phase_rows, interface_rows = [], []
    for name, probe, fault_env in phases + interfaces:
        relative = 'work/' + probe
        prepared = _adapt_probe(originals[relative], relative, application, fork)
        output_name = name + '.py'
        generated[output_name] = prepared
        row = {'name': name, 'original_probe_sha256': _sha(originals[relative]),
               'prepared_probe_sha256': _sha(prepared), 'fault_env': dict(fault_env), 'loader_sha256': loader_hash}
        (interface_rows if (name, probe, fault_env) in interfaces else phase_rows).append(row)
    if len(phase_rows) != 10 or len(interface_rows) != 2:
        _fail('prepared matrix cardinality')
    inventory = {name: _sha(raw) for name, raw in sorted(generated.items())}
    inventory_hash = _sha(json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    source_evidence = {'status': 'passed', 'scope': 'source-only aggregate', 'contract_sha256': contract,
                       'source_matrix_receipt_sha256': matrix_hash, 'commit_sha': commit, 'run_id': run_id,
                       'phase_count': 10, 'interface_count': 2, 'runtime_patch_sha256': PATCH_SHA256,
                       'origin': origin_fields}
    receipt = {'status': 'prepared_not_executed', 'executed': False,
               'scope': 'prepared source-runtime matrix; source form only; no execution or package claims',
               'workspace': str(directory), 'application': application, 'fork': fork,
               'manifest_sha256': MANIFEST_SHA256, 'contract_sha256': contract, 'commit_sha': commit, 'run_id': run_id,
               'source_matrix_receipt_sha256': matrix_hash, 'source_inputs': input_hashes,
               'prepared_file_sha256': inventory, 'prepared_inventory_sha256': inventory_hash,
               'source_evidence': source_evidence,
               'phases': phase_rows, 'interfaces': interface_rows}
    receipt_raw = json.dumps(receipt, sort_keys=True, indent=2, separators=(',', ': ')).encode('utf-8') + b'\n'

    output_names = tuple(generated) + ('prepared-result.json',)
    if any((directory / name).exists() or (directory / name).is_symlink() for name in output_names):
        _fail('prepared output collision')
    for name, raw in generated.items():
        _write_private(directory / name, raw)
    _write_private(directory / 'prepared-result.json', receipt_raw)
    result = {'status': 'prepared_not_executed', 'executed': False, 'receipt_path': directory / 'prepared-result.json',
              'receipt_sha256': _sha(receipt_raw), 'prepared_inventory_sha256': inventory_hash,
              'prepared_file_sha256': inventory, 'source_inputs': input_hashes}
    verify_prepared(preflight, directory, result)
    return result


__all__ = ['prepare_matrix', 'verify_prepared']
