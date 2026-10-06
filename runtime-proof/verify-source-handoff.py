#!/usr/bin/env python3
"""Verify a sanitized, hash-bound source handoff without executing its contents.

The bundle is a commitment bundle.  Its source files are checked against the
trusted checkout and its two receipts are checked as sanitized commitments;
the verifier never imports or executes a bundle member.
"""

from pathlib import Path, PurePosixPath
import ast
import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys


MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
SOURCE_MANIFEST_SHA = 'f0ade58e7b59cc49eb5c3c3d0a6c8ca08c4f5b9804dc49ad5ea4f171cc4be037'
ADAPTER_MANIFEST_SHA = '08f0a07fab0c63895d649d0c75835043417d260fe6f817047aaf5f1bec14064c'
PATCH_BEFORE = '80fd38c7555e31ad60cb36f4e7af904e848d584c98da76f9066bcee950acd0b7'
PATCH_AFTER = 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
JAC_BASE = '58cb97eb75cdff8b5ee78f4094ca2be16376601c'
JAC_SHA = '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
JACPYTHON_SHA = '198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542'
APP_REVISION = 'b0f2321016ba004b3a77db6fe05828080c755cd3'
APP_SHA = '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42'
LICENSE_SHA = '35219f6406160fa713fbe9c5a5932da993f2d7c53c33ac6439a38b810ec30a14'
LICENSE_BYTES = 1067
PARENT_POLICY = 'JAC_NO_DEV_SOURCE=1; JAC_DEV_SOURCE and JAC_DB_URL removed; leaf controls are authoritative'
LICENSE_ORIGIN = 'public Jac base MIT notice; mandatory handoff sidecar'
FORBIDDEN = ['cache', 'scratch', 'private logs', 'graph state', 'identity state',
             'fork-generated files', 'credentials', 'tokens', 'raw API bodies']
SOURCE_JAC_PATHS = (
    'source/jac/jaclang/compiler/types/stubcat/reader.jac',
    'source/jac/jaclang/compiler/types/stubcat/writer.jac',
    'source/jac/jaclang/data/impl/serializer.impl.jac',
    'source/jac/jaclang/data/impl/store.impl.jac',
    'source/jac/jaclang/data/serializer.jac',
    'source/jac/jaclang/data/store.jac',
    'source/jac/jaclang/runtime/context.jac',
    'source/jac/jaclang/runtime/impl/context.impl.jac',
    'source/jac/jaclang/scale/memory/impl/context.impl.jac',
    'source/jac/jaclang/server/identity/identity_storage.jac',
    'source/jac/jaclang/server/identity/impl/identity_storage.impl.jac',
    'source/jac/jaclang/server/identity/impl/identity_storage.pg.impl.jac',
    'source/jac/jaclang/server/identity/impl/user_manager.impl.jac',
    'source/jac/jaclang/server/identity/user_manager.jac',
    'source/jac/jaclang/server/impl/server.impl.jac',
    'source/jac/jaclang/server/impl/session.impl.jac',
    'source/jac/jaclang/server/session.jac',
)
ADAPTER_PATHS = (
    'work/identity-runtime-v7/run-source-cold-compile-v7.py',
    'work/identity-runtime-v7/run-source-bootstrap-v7.py',
    'work/identity-runtime-v7/run-source-matrix-v7.py',
    'work/identity-runtime-v7/run-source-stage-v7.py',
)
RECEIPT_NAMES = ('source-bootstrap-receipt.json', 'source-matrix-receipt.json')
HASH_RE = re.compile(r'^[0-9a-f]{64}$')
COMMIT_RE = re.compile(r'^[0-9a-f]{40}$')
RUN_ID_RE = re.compile(r'^[1-9][0-9]*$')
SYSTEMD_ACTIVE = frozenset(('inactive', 'failed'))
SYSTEMD_SUB = frozenset(('dead', 'failed', 'exited', 'stop-sigterm', 'stop-sigkill',
                         'final-sigterm', 'final-sigkill'))
SYSTEMD_RESULT = frozenset(('success', 'exit-code', 'signal', 'core-dump', 'timeout',
                            'watchdog', 'resources', 'protocol', 'start-limit-hit',
                            'oom-kill', 'condition', 'assert'))
POSIX_MODES = os.name == 'posix'


class VerificationError(ValueError):
    """Raised for a malformed, incomplete, or mismatched handoff."""


def _fail(label):
    raise VerificationError(label)


def _hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def _no_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail('duplicate JSON key')
        result[key] = value
    return result


def _read_json(path):
    try:
        value = json.loads(Path(path).read_bytes().decode('utf-8'), object_pairs_hook=_no_duplicate_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, VerificationError):
        _fail('JSON format')
    if not isinstance(value, dict):
        _fail('JSON object required')
    return value


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        _fail(label + ' keys')


def _hash_value(value, label):
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        _fail(label)


def _commit(value, label):
    if not isinstance(value, str) or not COMMIT_RE.fullmatch(value):
        _fail(label)


def _run_id(value, label):
    if not isinstance(value, str) or not RUN_ID_RE.fullmatch(value):
        _fail(label)


def _int(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(label)


def _finite_nonnegative(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        _fail(label)


def _trusted_file(path, label):
    try:
        info = os.lstat(path)
    except OSError:
        _fail(label + ' missing')
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail(label + ' type')
    return Path(path)


def _trusted_inputs(checkout):
    checkout = Path(checkout).resolve()
    if not checkout.is_dir() or checkout.is_symlink():
        _fail('trusted checkout')
    inputs = checkout / 'runtime-proof' / 'inputs'
    runner = _trusted_file(checkout / 'runtime-proof' / 'run-fresh-source.py', 'runner')
    helper = _trusted_file(checkout / 'runtime-proof' / 'kali-build-resources-v2.py', 'helper')
    source_manifest_path = _trusted_file(inputs / 'public-source-manifest.json', 'source manifest')
    adapter_manifest_path = _trusted_file(inputs / 'v7-adapter-manifest.json', 'adapter manifest')
    license_path = _trusted_file(checkout / 'runtime-proof' / 'JAC-LICENSE.txt', 'license')
    try:
        tree = ast.parse(runner.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, SyntaxError):
        _fail('runner syntax')
    runner_constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and \
                isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            runner_constants[node.targets[0].id] = node.value.value
    expected_constants = {
        'SOURCE_MANIFEST_SHA': SOURCE_MANIFEST_SHA, 'ADAPTER_MANIFEST_SHA': ADAPTER_MANIFEST_SHA,
        'PATCH_BEFORE': PATCH_BEFORE, 'PATCH_AFTER': PATCH_AFTER, 'JAC_BASE': JAC_BASE,
        'JAC_SHA': JAC_SHA, 'JACPYTHON_SHA': JACPYTHON_SHA, 'APP_REVISION': APP_REVISION,
        'APP_SHA': APP_SHA, 'JAC_LICENSE_SHA': LICENSE_SHA,
    }
    if any(runner_constants.get(name) != value for name, value in expected_constants.items()):
        _fail('runner pin constants')
    if _hash(source_manifest_path) != SOURCE_MANIFEST_SHA or _hash(adapter_manifest_path) != ADAPTER_MANIFEST_SHA:
        _fail('trusted manifest pin')
    if license_path.stat().st_size != LICENSE_BYTES or _hash(license_path) != LICENSE_SHA:
        _fail('trusted license pin')
    source_manifest = _read_json(source_manifest_path)
    adapter_manifest = _read_json(adapter_manifest_path)
    _keys(source_manifest, ('base', 'direct_use_rule', 'files', 'patch_sha256', 'scope', 'status'), 'source manifest')
    _keys(adapter_manifest, ('files', 'scope', 'status'), 'adapter manifest')
    if source_manifest['status'] != 'staged_not_executed' or source_manifest['base'] != JAC_BASE or \
            source_manifest['patch_sha256'] != PATCH_AFTER or not isinstance(source_manifest['files'], dict) or \
            len(source_manifest['files']) != 34:
        _fail('source manifest identity')
    if adapter_manifest['status'] != 'staged_not_executed' or not isinstance(adapter_manifest['files'], dict) or \
            len(adapter_manifest['files']) != 4 or set(adapter_manifest['files']) != set(ADAPTER_PATHS):
        _fail('adapter manifest identity')
    if {path for path in source_manifest['files'] if path.startswith('source/jac/')} != set(SOURCE_JAC_PATHS):
        _fail('Jac source path inventory')
    if set(source_manifest['files']) != set(SOURCE_JAC_PATHS) | {
            'outputs/identity-bootstrap-source-v2/source-inputs/runtime.patch',
            'work/export-emergency-checkpoint.py',
            'work/identity-bootstrap-source-proof-v4.py',
            'work/identity-runtime-v3/run-identity-runtime-regressions.py',
            'work/identity-runtime-v3/runtime-loader-provenance.py',
            'work/identity-runtime-v3/runtime.patch',
            'work/kali-build-resources-v2.py',
            'work/run-runtime-type-compile-v3.py',
            'work/runtime-boundary-probe.py',
            'work/runtime-interface-codec-controls-probe.py',
            'work/runtime-interface-codec-probe.py',
            'work/runtime-lifecycle-probe.py',
            'work/runtime-materialization-probe.py',
            'work/runtime-nested-context-probe.py',
            'work/runtime-probe.py',
            'work/runtime-request-context-probe.py',
            'work/runtime-served-probe.py'}:
        _fail('source path inventory')
    for relative, metadata in source_manifest['files'].items():
        _keys(metadata, ('bytes', 'kind', 'sha256'), 'source metadata')
        _int(metadata['bytes'], 'source byte metadata')
        _hash_value(metadata['sha256'], 'source hash metadata')
        expected_kind = 'used_runtime_jac_source' if relative in SOURCE_JAC_PATHS else 'public_proof_source'
        if metadata['kind'] != expected_kind:
            _fail('source role metadata')
        source = _trusted_file(inputs / relative, 'trusted source')
        if source.stat().st_size != metadata['bytes'] or _hash(source) != metadata['sha256']:
            _fail('trusted source identity')
    for relative, metadata in adapter_manifest['files'].items():
        _keys(metadata, ('bytes', 'sha256'), 'adapter metadata')
        _int(metadata['bytes'], 'adapter byte metadata')
        _hash_value(metadata['sha256'], 'adapter hash metadata')
        adapter = _trusted_file(inputs / relative, 'trusted adapter')
        if adapter.stat().st_size != metadata['bytes'] or _hash(adapter) != metadata['sha256']:
            _fail('trusted adapter identity')
    try:
        pins = _read_json(_trusted_file(checkout / 'runtime-proof' / 'public-download-pins.json', 'download pins'))
    except VerificationError:
        raise
    if pins.get('application_revision') != APP_REVISION or pins.get('application_digest') != APP_SHA:
        _fail('application pin identity')
    return checkout, source_manifest, adapter_manifest, runner, helper, license_path


def _expected_paths(source_manifest):
    member_paths = ['files/' + relative for relative in source_manifest['files']]
    member_paths.extend(RECEIPT_NAMES)
    files = set(member_paths) | {'contract.json', 'JAC-LICENSE.txt'}
    directories = set()
    for relative in member_paths:
        path = PurePosixPath(relative)
        for index in range(1, len(path.parts)):
            directories.add('/'.join(path.parts[:index]))
    return files, directories, member_paths


def _bundle_inventory(bundle, expected_files, expected_dirs):
    bundle = Path(bundle)
    try:
        root_info = os.lstat(bundle)
    except OSError:
        _fail('bundle missing')
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        _fail('bundle root type')
    if POSIX_MODES and root_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        _fail('writable bundle root')
    found_files = set()
    found_dirs = set()
    total = 0
    stack = [(bundle, '')]
    while stack:
        directory, prefix = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            _fail('bundle directory')
        for entry in entries:
            relative = entry.name if not prefix else prefix + '/' + entry.name
            try:
                info = os.lstat(entry.path)
            except OSError:
                _fail('bundle metadata')
            if stat.S_ISLNK(info.st_mode):
                _fail('bundle symlink')
            if stat.S_ISDIR(info.st_mode):
                if relative not in expected_dirs:
                    _fail('unexpected bundle directory')
                if POSIX_MODES and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                    _fail('writable bundle directory')
                found_dirs.add(relative)
                stack.append((Path(entry.path), relative))
            elif stat.S_ISREG(info.st_mode):
                if relative not in expected_files:
                    _fail('unexpected bundle file')
                if info.st_nlink != 1:
                    _fail('bundle hardlink')
                if info.st_size > MAX_FILE_BYTES:
                    _fail('bundle file size')
                if POSIX_MODES:
                    if info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                        _fail('executable bundle file')
                    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                        _fail('writable bundle file')
                found_files.add(relative)
                total += info.st_size
                if total >= MAX_TOTAL_BYTES:
                    _fail('bundle total size')
            else:
                _fail('nonregular bundle member')
    if found_files != expected_files or found_dirs != expected_dirs:
        _fail('bundle filesystem allowlist')
    return bundle, total


def _validate_cleanup(value):
    _keys(value, ('cgroup_empty', 'unit_state', 'cgroup_kill_fallback_used', 'launcher_stopped'), 'cleanup')
    if any(not isinstance(value[key], bool) for key in ('cgroup_empty', 'cgroup_kill_fallback_used', 'launcher_stopped')):
        _fail('cleanup boolean')
    if not value['cgroup_empty'] or not value['launcher_stopped']:
        _fail('cleanup result')
    state = value['unit_state']
    _keys(state, ('ActiveState', 'SubState', 'Result'), 'unit state')
    if any(not isinstance(state[field], str) for field in ('ActiveState', 'SubState', 'Result')):
        _fail('unit state type')
    if state['ActiveState'] not in SYSTEMD_ACTIVE or state['SubState'] not in SYSTEMD_SUB or state['Result'] not in SYSTEMD_RESULT:
        _fail('unit state value')


def _validate_receipt(receipt, stage, adapter_sha, bootstrap_result_sha=None):
    _keys(receipt, ('status', 'stage', 'wrapper_sha256', 'result_sha256', 'child_result_sha256',
                    'elapsed_seconds', 'parent_policy', 'source_gate_sha256',
                    'cold_compile_receipt_sha256', 'child'), stage + ' receipt')
    if receipt['status'] != 'passed' or receipt['stage'] != stage or receipt['wrapper_sha256'] != adapter_sha:
        _fail(stage + ' receipt identity')
    _hash_value(receipt['result_sha256'], stage + ' result hash')
    if receipt['result_sha256'] != receipt['child_result_sha256']:
        _fail(stage + ' child hash binding')
    _finite_nonnegative(receipt['elapsed_seconds'], stage + ' elapsed')
    if receipt['parent_policy'] != PARENT_POLICY:
        _fail(stage + ' parent policy')
    _hash_value(receipt['cold_compile_receipt_sha256'], stage + ' cold hash') if stage == 'run-source-bootstrap-v7' else None
    if stage == 'run-source-bootstrap-v7':
        if receipt['source_gate_sha256'] is not None:
            _fail('bootstrap source gate')
    else:
        if receipt['cold_compile_receipt_sha256'] is not None or receipt['source_gate_sha256'] != bootstrap_result_sha:
            _fail('matrix source gate')
    child = receipt['child']
    _keys(child, ('status', 'checks', 'phase_count', 'interface_count', 'runtime_patch_sha256',
                  'official_binary_sha256', 'jacpython_sha256', 'source_override_explicit',
                  'cold_compile_receipt_sha256', 'actual_smtp'), stage + ' child')
    for field in ('checks', 'phase_count', 'interface_count'):
        if child[field] is not None:
            _int(child[field], stage + ' child ' + field)
    if child['source_override_explicit'] is not None and not isinstance(child['source_override_explicit'], bool):
        _fail(stage + ' source override type')
    if not isinstance(child['actual_smtp'], bool):
        _fail(stage + ' SMTP type')
    expected = ('passed', 53, None, None, PATCH_AFTER, JAC_SHA, JACPYTHON_SHA, True,
                receipt['cold_compile_receipt_sha256'], False) if stage == 'run-source-bootstrap-v7' else \
        ('passed', None, 10, 2, PATCH_AFTER, JAC_SHA, None, None, None, False)
    if (child['status'], child['checks'], child['phase_count'], child['interface_count'], child['runtime_patch_sha256'],
            child['official_binary_sha256'], child['jacpython_sha256'], child['source_override_explicit'],
            child['cold_compile_receipt_sha256'], child['actual_smtp']) != expected:
        _fail(stage + ' child identity')
    if stage == 'run-source-bootstrap-v7':
        _hash_value(child['cold_compile_receipt_sha256'], stage + ' child cold hash')


def _validate_cold_provenance(value):
    _keys(value, ('status', 'phase_count', 'phase_patches', 'phase_statuses', 'expected_e1030',
                  'corrected_compile', 'leaf_controls'), 'cold provenance')
    _int(value['phase_count'], 'cold phase count')
    if value['status'] != 'passed' or value['phase_count'] != 2 or value['phase_patches'] != [PATCH_BEFORE, PATCH_AFTER] or \
            value['phase_statuses'] != ['expected_failure', 'passed'] or not isinstance(value['leaf_controls'], list) or \
            len(value['leaf_controls']) != 2:
        _fail('cold provenance identity')
    expected = value['expected_e1030']
    _keys(expected, ('status', 'exit_code', 'diagnostic', 'compiler_log_sha256', 'patch_sha256'), 'expected E1030')
    if expected['status'] != 'expected_failure' or expected['diagnostic'] != 'E1030 IdentityStorage/store expected mismatch' or \
            expected['patch_sha256'] != PATCH_BEFORE:
        _fail('expected E1030 identity')
    _int(expected['exit_code'], 'expected exit code')
    if not -255 <= expected['exit_code'] <= 255 or expected['exit_code'] == 0:
        _fail('expected exit code range')
    _hash_value(expected['compiler_log_sha256'], 'expected compiler log hash')
    corrected = value['corrected_compile']
    _keys(corrected, ('status', 'exit_code', 'compiler_log_sha256', 'patch_sha256'), 'corrected compile')
    _int(corrected['exit_code'], 'corrected exit code')
    if corrected['status'] != 'passed' or corrected['exit_code'] != 0 or corrected['patch_sha256'] != PATCH_AFTER:
        _fail('corrected compile identity')
    _hash_value(corrected['compiler_log_sha256'], 'corrected compiler log hash')
    for leaf in value['leaf_controls']:
        _keys(leaf, ('controls_confirmed_before_workload', 'cleanup'), 'cold leaf control')
        if leaf['controls_confirmed_before_workload'] is not True:
            _fail('cold control confirmation')
        _validate_cleanup(leaf['cleanup'])


def verify_bundle(bundle, checkout, *, expected_commit, expected_run_id, expected_contract_sha256):
    """Return a sanitized verification summary for an unexecuted handoff bundle."""
    _commit(expected_commit, 'expected commit')
    _run_id(expected_run_id, 'expected run id')
    _hash_value(expected_contract_sha256, 'expected contract hash')
    checkout, source_manifest, adapters, runner, helper, license_path = _trusted_inputs(checkout)
    expected_files, expected_dirs, member_paths = _expected_paths(source_manifest)
    bundle, total = _bundle_inventory(bundle, expected_files, expected_dirs)
    contract_path = bundle / 'contract.json'
    if _hash(contract_path) != expected_contract_sha256:
        _fail('external contract hash')
    contract = _read_json(contract_path)
    _keys(contract, ('status', 'member_count', 'total_bytes', 'source_manifest_sha256', 'runtime_patch_sha256',
                     'source_bootstrap_receipt_sha256', 'source_matrix_receipt_sha256', 'members',
                     'cold_compile_provenance', 'jac_license_notice', 'forbidden', 'producer'), 'contract')
    _int(contract['member_count'], 'contract member count')
    if contract['status'] != 'prepared_not_uploaded' or contract['member_count'] != 36 or \
            contract['source_manifest_sha256'] != SOURCE_MANIFEST_SHA or contract['runtime_patch_sha256'] != PATCH_AFTER or \
            not isinstance(contract['members'], list) or len(contract['members']) != 36:
        _fail('contract identity')
    _int(contract['total_bytes'], 'contract total bytes')
    _hash_value(contract['source_bootstrap_receipt_sha256'], 'contract bootstrap hash')
    _hash_value(contract['source_matrix_receipt_sha256'], 'contract matrix hash')
    if contract['forbidden'] != FORBIDDEN:
        _fail('forbidden list')
    producer = contract['producer']
    _keys(producer, ('commit_sha', 'run_id', 'source_runner_sha256', 'adapter_manifest_sha256', 'application_revision',
                     'application_digest', 'jac_base', 'official_binary_sha256', 'jacpython_sha256', 'helper_sha256',
                     'entrypoint_policy', 'evidence_scope'), 'producer')
    if producer['commit_sha'] != expected_commit or producer['run_id'] != expected_run_id or \
            producer['adapter_manifest_sha256'] != ADAPTER_MANIFEST_SHA or producer['application_revision'] != APP_REVISION or \
            producer['application_digest'] != APP_SHA or producer['jac_base'] != JAC_BASE or \
            producer['official_binary_sha256'] != JAC_SHA or producer['jacpython_sha256'] != JACPYTHON_SHA or \
            producer['entrypoint_policy'] != 'source_only_via_pinned_adapters' or \
            producer['evidence_scope'] != 'sanitized_commitments_only':
        _fail('producer identity')
    _hash_value(producer['source_runner_sha256'], 'producer runner hash')
    _hash_value(producer['helper_sha256'], 'producer helper hash')
    if producer['source_runner_sha256'] != _hash(runner) or producer['helper_sha256'] != _hash(helper):
        _fail('producer trusted code hash')
    try:
        head = subprocess.run(['git', '-C', str(checkout), 'rev-parse', '--verify', 'HEAD'], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        _fail('trusted checkout HEAD')
    if head != expected_commit:
        _fail('trusted checkout HEAD binding')
    entries = {}
    for entry in contract['members']:
        _keys(entry, ('path', 'bytes', 'sha256'), 'member entry')
        if not isinstance(entry['path'], str) or entry['path'] in entries:
            _fail('member path identity')
        pure = PurePosixPath(entry['path'])
        if pure.is_absolute() or '..' in pure.parts or entry['path'] not in member_paths:
            _fail('member path safety')
        _int(entry['bytes'], 'member byte metadata')
        _hash_value(entry['sha256'], 'member hash metadata')
        entries[entry['path']] = entry
    if [entry['path'] for entry in contract['members']] != member_paths:
        _fail('member order')
    if contract['total_bytes'] != sum(entry['bytes'] for entry in contract['members']):
        _fail('contract member total')
    for relative, metadata in source_manifest['files'].items():
        entry = entries['files/' + relative]
        path = bundle / PurePosixPath(entry['path'])
        if entry['bytes'] != metadata['bytes'] or entry['sha256'] != metadata['sha256'] or path.stat().st_size != entry['bytes'] or _hash(path) != entry['sha256']:
            _fail('source member identity')
    receipts = {}
    for name in RECEIPT_NAMES:
        entry = entries[name]
        path = bundle / name
        if path.stat().st_size != entry['bytes'] or _hash(path) != entry['sha256']:
            _fail('receipt member identity')
        receipts[name] = _read_json(path)
    if _hash(bundle / RECEIPT_NAMES[0]) != contract['source_bootstrap_receipt_sha256'] or \
            _hash(bundle / RECEIPT_NAMES[1]) != contract['source_matrix_receipt_sha256']:
        _fail('contract receipt hash binding')
    _validate_receipt(receipts[RECEIPT_NAMES[0]], 'run-source-bootstrap-v7', adapters['files'][ADAPTER_PATHS[1]]['sha256'])
    _validate_receipt(receipts[RECEIPT_NAMES[1]], 'run-source-matrix-v7', adapters['files'][ADAPTER_PATHS[2]]['sha256'],
                      receipts[RECEIPT_NAMES[0]]['result_sha256'])
    _validate_cold_provenance(contract['cold_compile_provenance'])
    license_notice = contract['jac_license_notice']
    _keys(license_notice, ('path', 'bytes', 'sha256', 'origin', 'text'), 'license notice')
    _int(license_notice['bytes'], 'license notice bytes')
    if license_notice['path'] != 'JAC-LICENSE.txt' or license_notice['bytes'] != LICENSE_BYTES or \
            license_notice['sha256'] != LICENSE_SHA or license_notice['origin'] != LICENSE_ORIGIN or \
            license_notice['text'] != license_path.read_text(encoding='utf-8'):
        _fail('license notice identity')
    sidecar = bundle / 'JAC-LICENSE.txt'
    if sidecar.stat().st_size != LICENSE_BYTES or _hash(sidecar) != LICENSE_SHA or \
            sidecar.read_bytes() != license_path.read_bytes():
        _fail('license sidecar identity')
    return {'status': 'passed', 'scope': 'sanitized commitment bundle verification',
            'member_count': 36, 'total_bytes': contract['total_bytes'], 'contract_sha256': expected_contract_sha256,
            'commit_sha': expected_commit, 'run_id': expected_run_id}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle_path', nargs='?', type=Path)
    parser.add_argument('--bundle', dest='bundle_option', type=Path)
    parser.add_argument('--trusted-checkout', '--checkout', dest='trusted_checkout', required=True, type=Path)
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--expected-run-id', required=True)
    parser.add_argument('--expected-contract-sha256', required=True)
    args = parser.parse_args(argv)
    bundle = args.bundle_option or args.bundle_path
    if bundle is None:
        parser.error('the following argument is required: --bundle or bundle path')
    try:
        result = verify_bundle(bundle, args.trusted_checkout,
                               expected_commit=args.expected_commit,
                               expected_run_id=args.expected_run_id,
                               expected_contract_sha256=args.expected_contract_sha256)
    except (OSError, VerificationError, subprocess.SubprocessError) as error:
        print('verification failed: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
