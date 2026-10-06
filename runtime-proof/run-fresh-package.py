#!/usr/bin/env python3
"""Assemble and independently verify the frozen runtime on a fresh Ubuntu host.

Package acceptance is separate from application compatibility, native HTTP,
capacity, runtime adoption and deployment. Logs and payloads stay private.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).absolute().parents[1]
PREFLIGHT_SHA = 'd47b342bea74d64fa3575673a07b90d5595fdabe0e87a93f714cc6d7caa7c635'
RUNNER_SHA = '10158a593785e37026e21cbade10e592ede1ebb5ca1392f69ff4b7eede77835f'
ORIGIN_SHA = '1bd1597d02e289e0931375de4e9abecd34a2bc7775564bd08c668b82a3c0e30a'
DOWNLOAD_SHA = '8860ccc2b05ce5e21a4f1dc18ce885de25e6e537a88de608b373b791304a37ed'
CACHE_CHECK_SHA = '4aefeb54a64577594b2408548c7a6a2e3843e6184440bc56947e7e54651427a2'
CLASSIFIER_CONTROL_SHA = '242e1aefd09969e07fd557c5737cc6957fafd97920ba8e069f20b5c517bdf518'
RECIPE_SHA = 'ec820c414d5a83d498f894eddcee105d5eb3e287a030c2d6b87045fe7d32129f'
VERIFIER_SHA = '9f7acdfd45c3a66913c8c3c9205f3afc8b00801147b1082e2af329a17f27d8de'
CLASSIFIER_SHA = '33dd3dbe88aadb16317f60bd518430225a7a8ef466596c70271b16371006f363'
POLICY_SHA = '6d08330483ae7569153701c4eb5d211c838bb7ab6909452aa54bd5ad9e401e5d'
CATALOG_SHA = '8849263964617d4fda67bfbab436402440dbb12755cf5ce534100c94d8421f03'
MIN_HOST_MEMORY = 16 * 1024 ** 3
MIN_HOST_CPUS = 4
ASSEMBLY_SECONDS = 4200
JOB_SECONDS = 21600
SCOPE = 'fresh package assembly and independent byte binding only; compatibility, native HTTP, capacity and adoption remain separate gates'
CONTROL_NAMES = ['fresh-stage-baseline', 'wrong-consumer-with-updated-manifest', 'trailing-jir-bytes']
PACKAGE_HASH_FIELDS = {
    'assembled-inputs.json': 'assembled_input_manifest_sha256',
    'inherited-inputs.json': 'inherited_input_manifest_sha256',
    'transaction.patch': 'runtime_patch_sha256',
    'executed-recipe.py': 'executed_recipe_sha256',
    'payload-build-references.json': 'build_reference_manifest_sha256',
    'executed-classifier.py': 'executed_classifier_sha256',
    'diagnostic-policy.json': 'diagnostic_policy_sha256',
    'stage-path-classification.json': 'stage_classification_sha256',
    'final-payload-path-classification.json': 'final_payload_classification_sha256',
    'frozen-stage-files.json': 'frozen_stage_manifest_sha256',
    'catalog-relocation.json': 'catalog_relocation_receipt_sha256',
    'executed-catalog-probe.py': 'executed_catalog_probe_sha256',
    'stubcat.bin': 'stub_catalog_sha256', 'launcher': 'launcher_sha256',
    'runtime.tar.zst': 'payload_sha256', 'jac': 'candidate_binary_sha256',
}


def fail(label):
    raise ValueError(label)


def trusted_preflight():
    path = ROOT / 'runtime-proof/verify-package-preflight.py'
    if path.resolve() != path or any(item.is_symlink() for item in (path, *path.parents)):
        fail('trusted preflight path')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= 1024 ** 2 or
            (os.name == 'posix' and info.st_mode & 0o022)):
        fail('trusted preflight type')
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_nlink')
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(1024 ** 2 + 1)
        after = os.fstat(stream.fileno())
        if (len(raw) != info.st_size or any(getattr(value, key) != getattr(info, key)
                for value in (opened, after) for key in fields)):
            fail('trusted preflight descriptor')
    if hashlib.sha256(raw).hexdigest() != PREFLIGHT_SHA:
        fail('trusted preflight hash')
    module = {'__file__': str(path), '__name__': 'trusted_package_preflight'}
    exec(compile(raw, str(path), 'exec'), module)
    return module


def load_committed(preflight, relative, commit, *, pin=None):
    raw = preflight['committed_file'](ROOT, commit, relative)
    if pin is not None and preflight['sha'](raw) != pin:
        fail('package helper pin')
    module = {'__file__': str(ROOT / relative), '__name__': 'trusted_package_helper'}
    exec(compile(raw, str(ROOT / relative), 'exec'), module)
    return module


def require_inherited_inputs(fork_receipt):
    values = fork_receipt['inherited_fork_inputs']
    shim = 'jac/jaclang/compiler/backends/native/llvm/libjacllvm.so'
    typeshed = 'jac/jaclang/vendor/typeshed/'
    if (len(values) != 750 or values.get(shim, {}).get('sha256') !=
            '02f499e9becacf36161aa9f4b39a9f950f4dd8dbcb744acded0f04618652b4de' or
            len([name for name in values if name.startswith(typeshed)]) != 749 or
            any(name != shim and not name.startswith(typeshed) for name in values)):
        fail('required official fork inputs')


def adapt_loader(raw, fork):
    original = b"root = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork').resolve()"
    if raw.count(original) != 1:
        fail('loader source binding')
    return raw.replace(original, ('root = Path(' + repr(str(fork)) + ').resolve()').encode())


def mount_identity(path, e_root, prefix, expected=None):
    path, e_root = Path(path), Path(e_root)
    if (path.parent != Path('/var/tmp') or not path.name.startswith(prefix) or
            len(path.name) != len(prefix) + 8 or path.resolve() != path or path.is_symlink() or
            not path.is_mount() or not e_root.is_mount() or e_root.is_symlink()):
        fail('owned package mount path')
    info, backing = path.stat(), (e_root / path.name).lstat()
    root_info = e_root.stat()
    if (root_info.st_uid != 65534 or root_info.st_mode & 0o777 != 0o700 or
            not stat.S_ISDIR(backing.st_mode) or info.st_uid != 65534 or backing.st_uid != 65534 or
            info.st_mode & 0o777 != 0o700 or backing.st_mode & 0o777 != 0o700 or
            info.st_dev != e_root.stat().st_dev or
            (info.st_dev, info.st_ino) != (backing.st_dev, backing.st_ino) or
            (expected is not None and (info.st_dev, info.st_ino) != tuple(expected))):
        fail('owned package mount identity')
    return info.st_dev, info.st_ino


def regular_hash(preflight, path, maximum=1024 ** 3):
    path = Path(path)
    preflight['no_links'](path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum or
            (os.name == 'posix' and info.st_mode & 0o022)):
        fail('package output file type')
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_nlink')
    digest = hashlib.sha256()
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        total = 0
        while True:
            raw = stream.read(1024 ** 2)
            if not raw:
                break
            total += len(raw)
            if total > maximum:
                fail('package output bounds')
            digest.update(raw)
        after = os.fstat(stream.fileno())
        if (total != info.st_size or any(getattr(value, key) != getattr(info, key)
                for value in (opened, after) for key in fields)):
            fail('package output descriptor')
    return digest.hexdigest(), total


def accept_package(preflight, fork, package, independent_raw, loader_raw, controls_raw,
                   declaration, source_manifest, *, expected_metadata_sha256,
                   expected_loader_sha256, expected_controls_sha256, expected_controls_code_sha256,
                   official_cache_raw, expected_official_cache_receipt_sha256,
                   expected_official_cache_code_sha256):
    metadata_raw = preflight['read_regular'](package / 'result.json')
    if preflight['sha'](metadata_raw) != expected_metadata_sha256:
        fail('executed package result binding')
    metadata = json.loads(metadata_raw)
    independent, loader, controls = map(json.loads, (independent_raw, loader_raw, controls_raw))
    official_cache = json.loads(official_cache_raw)
    required = {'executed_recipe_sha256': RECIPE_SHA, 'executed_classifier_sha256': CLASSIFIER_SHA,
                'diagnostic_policy_sha256': POLICY_SHA, 'executed_catalog_probe_sha256': CATALOG_SHA,
                'runtime_base': '58cb97eb75cdff8b5ee78f4094ca2be16376601c',
                'runtime_patch_sha256': 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'}
    if (any(metadata.get(key) != value for key, value in required.items()) or
            metadata.get('candidate') != str(package / 'jac') or
            independent.get('status') != 'passed' or independent.get('executed_verifier_sha256') != VERIFIER_SHA or
            independent.get('package_metadata_sha256') != expected_metadata_sha256 or
            set(independent.get('file_hashes', {})) != set(PACKAGE_HASH_FIELDS)):
        fail('independent package execution binding')
    if (preflight['sha'](official_cache_raw) != expected_official_cache_receipt_sha256 or
            official_cache.get('status') != 'passed' or official_cache.get('recipe_sha256') != RECIPE_SHA or
            official_cache.get('executed_precheck_sha256') != expected_official_cache_code_sha256 or
            official_cache.get('official_binary_sha256') != '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad' or
            official_cache.get('official_payload_sha256') != metadata.get('official_payload_sha256')):
        fail('official cache pre-import binding')
    preflight['require_pattern'](official_cache.get('extracted_inventory_sha256'), r'[0-9a-f]{64}',
                                 'official cache inventory hash')
    for name, key in PACKAGE_HASH_FIELDS.items():
        actual, length = regular_hash(preflight, package / name)
        if actual != metadata.get(key) or actual != independent['file_hashes'][name]:
            fail('independent package output commitment')
        if name == 'jac' and (type(metadata.get('candidate_binary_bytes')) is not int or
                              metadata['candidate_binary_bytes'] != length):
            fail('candidate size binding')
    launcher = package / 'jacpython'
    if (not launcher.is_symlink() or os.readlink(launcher) != 'jac' or
            launcher.resolve() != (package / 'jac').resolve()):
        fail('packaged interpreter link binding')
    if (preflight['sha'](loader_raw) != expected_loader_sha256 or loader.get('status') != 'passed' or
            not loader.get('runtime_roots') or len(loader.get('implementation_files', {})) < 16 or
            any(not Path(name).is_absolute() or Path(name).resolve() != Path(name) or not Path(name).is_relative_to(fork)
                for name in [*loader['runtime_roots'], *loader['implementation_files'].values()])):
        fail('fresh assembly loader binding')
    if (preflight['sha'](controls_raw) != expected_controls_sha256 or controls.get('status') != 'passed' or
            controls.get('executed_controls_sha256') != expected_controls_code_sha256 or
            controls.get('classifier_sha256') != CLASSIFIER_SHA or controls.get('policy_sha256') != POLICY_SHA or
            controls.get('package_metadata_sha256') != expected_metadata_sha256 or
            controls.get('original_stage_classification_sha256') != metadata['stage_classification_sha256'] or
            [row.get('name') for row in controls.get('cases', [])] != CONTROL_NAMES or
            any(row.get('status') != 'passed' for row in controls['cases'])):
        fail('fresh classifier control binding')
    direct_use = preflight['verify_direct_use_assembly'](fork, package / 'assembled-inputs.json',
        declaration, source_manifest, expected_assembled_sha256=metadata['assembled_input_manifest_sha256'])
    require_inherited_inputs(direct_use)
    return dict(status='passed', scope=SCOPE, package_metadata_sha256=expected_metadata_sha256,
                independent_verifier_receipt_sha256=preflight['sha'](independent_raw),
                loader_receipt_sha256=expected_loader_sha256,
                official_cache_receipt_sha256=expected_official_cache_receipt_sha256,
                classifier_control_receipt_sha256=expected_controls_sha256,
                candidate_binary_sha256=metadata['candidate_binary_sha256'],
                payload_sha256=metadata['payload_sha256'],
                runtime_direct_use=dict(direct_use, assembly_observed=True, direct_use_observed=True))


def run_bounded(runner, directory, command, cwd, environment, timeout, label):
    if type(timeout) is not int or not 0 < timeout <= ASSEMBLY_SECONDS:
        fail('package workload deadline')
    helper = runner['resource_helper']()
    process = state = None
    guard = None
    started = time.monotonic()
    with (directory / (label + '.log')).open('xb') as log:
        try:
            process, state = helper['launch_scope'](directory, command, cwd, environment, log)
            runner['ACTIVE'] = process
            while process.poll() is None:
                helper['sample_scope'](state)
                guard = helper['scope_guard'](state, time.monotonic() - started, timeout)
                if guard:
                    break
                time.sleep(.2)
            helper['sample_scope'](state)
            guard = guard or helper['scope_guard'](state, time.monotonic() - started, timeout)
        finally:
            if process is not None and state is not None:
                helper['stop_scope'](state, process)
            runner['ACTIVE'] = None
    if (guard or process.returncode != 0 or state['limits'] != state['requested_limits'] or
            state['requested_limits'] != dict(high=7 * 1024 ** 3, max=8 * 1024 ** 3, swap_max=0) or
            state['oom_policy'] != 'stop' or state['cleanup']['unit_state'].get('Result') == 'oom-kill' or
            not state['controls_confirmed_before_workload'] or
            not state['cleanup']['cgroup_empty'] or not state['cleanup']['launcher_stopped']):
        fail('bounded package ' + label)
    return state


def fresh_mount(runner, prefix):
    directory = runner['resource_helper']()['mounted_empty'](prefix)
    runner['OWNED_MOUNTS'].add(directory)
    identity = mount_identity(directory, runner['E_ROOT'], prefix)
    if any(directory.iterdir()):
        fail('fresh package workspace')
    return directory, identity


def remaining_seconds(deadline, maximum):
    remaining = int(deadline - time.monotonic())
    if remaining <= 0:
        fail('package job deadline')
    return min(maximum, remaining)


def stage_source(preflight, workspace, source_checkout, source_commit, package_commit, run_id):
    try:
        origin_raw = preflight['committed_file'](ROOT, package_commit, 'runtime-proof/verify-source-origin.py')
        if preflight['sha'](origin_raw) != ORIGIN_SHA:
            fail('source origin helper pin')
        downloader = load_committed(preflight, 'runtime-proof/download-source-handoff.py', package_commit, pin=DOWNLOAD_SHA)
        result = downloader['stage_handoff'](workspace / 'source-handoff', source_checkout, ROOT,
            expected_source_commit=source_commit, expected_package_commit=package_commit, expected_run_id=run_id)
    finally:
        # Only authenticated archive retrieval receives repository credentials.
        os.environ.pop('GH_TOKEN', None)
    if (result.get('status') != 'passed' or
            result.get('scope') != 'authenticated source bundle and package commitments only' or
            result.get('origin', {}).get('status') != 'passed' or
            result['origin'].get('run_id') != int(run_id) or
            result.get('preflight', {}).get('status') != 'passed'):
        fail('downloaded source handoff binding')
    return result


def require_fresh_storage(runner):
    for name in ('E_ROOT', 'IMAGE', 'CANONICAL_TASK'):
        path = runner[name]
        if path.exists() or path.is_symlink():
            fail('pre-existing package storage')


def copy_private(preflight, source, destination, expected_hash):
    raw = preflight['read_regular'](source)
    if preflight['sha'](raw) != expected_hash:
        fail('package copied input binding')
    with destination.open('xb') as stream:
        stream.write(raw)
    destination.chmod(0o400)
    os.chown(destination, 65534, 65534)
    return raw


def main(argv=None):
    deadline = time.monotonic() + JOB_SECONDS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trusted-source-checkout', type=Path, required=True)
    parser.add_argument('--expected-source-commit', required=True)
    parser.add_argument('--expected-package-commit', required=True)
    parser.add_argument('--expected-run-id', required=True)
    args = parser.parse_args(argv)
    if os.name != 'posix' or sys.platform != 'linux':
        fail('package Linux host guard')
    preflight = trusted_preflight()
    for value in (args.expected_source_commit, args.expected_package_commit):
        preflight['require_pattern'](value, r'[0-9a-f]{40}', 'package commit format')
    preflight['checked_checkout'](ROOT, args.expected_package_commit)
    parent_raw = preflight['committed_file'](ROOT, args.expected_package_commit, 'runtime-proof/run-fresh-package.py')
    runner = load_committed(preflight, 'runtime-proof/run-fresh-source.py', args.expected_package_commit, pin=RUNNER_SHA)
    for relative, pin in (
            ('runtime-proof/kali-build-resources-v2.py', '72fa698df809ec63c0d2cd7ce1c9d51bd5ee8a9e2b0bfba5bff979814217837b'),
            ('runtime-proof/probe-runner-controls.py', '8beddff8bfb7c550a8efda9fc7f5a8383a9ba5f50e5d47e04a1381b6524cee14'),
            ('runtime-proof/download-pinned-inputs.py', 'dc0ce4776f0d804f3df9e83f68dd11d2663ea367bc3f17fe634680f6fe075e57'),
            ('runtime-proof/public-download-pins.json', '6cf9b071cce3f5fb40f829764d9d5be9550d7aaa25b56e04f96f6d244a529db7')):
        if preflight['sha'](preflight['committed_file'](ROOT, args.expected_package_commit, relative)) != pin:
            fail('fresh package support input binding')
    runner['MIN_HOST_MEMORY'] = MIN_HOST_MEMORY
    runner['host_guard']()
    host_cpus = len(os.sched_getaffinity(0))
    if host_cpus < MIN_HOST_CPUS:
        fail('package host CPU guard')
    workspace = Path(tempfile.mkdtemp(prefix='m-local-fresh-package-v1-', dir='/var/tmp'))
    workspace.chmod(0o700)
    staged = stage_source(preflight, workspace, args.trusted_source_checkout,
                          args.expected_source_commit, args.expected_package_commit, args.expected_run_id)
    source_gate, authenticated = staged['preflight'], staged['origin']
    preflight['verify_direct_use_inputs'](ROOT, args.expected_package_commit)
    pins, manifest, adapters = runner['manifest_inputs']()
    declaration = preflight['committed_file'](ROOT, args.expected_package_commit, preflight['DIRECT_USE_PATH'])
    source_manifest = preflight['committed_file'](ROOT, args.expected_package_commit,
                                                 'runtime-proof/inputs/public-source-manifest.json')
    # Reject foreign storage before entering the owned-storage cleanup block.
    require_fresh_storage(runner)
    runner['PRIVATE_LOG_DIR'] = workspace
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, runner['signal_handler'])
    summary = None
    try:
        probe_path, probe = runner['run_probe'](workspace)
        runner['mount_image']()
        runner['prepare_task'](runner['CANONICAL_TASK'], manifest, adapters, workspace / 'checkout.log')
        official, materialized = runner['materialize_runtime'](workspace, pins, workspace / 'runtime.log')
        old, fork = runner['prepare_forks'](workspace, manifest, workspace / 'forks.log')
        runner['materialize_shim_typeshed'](fork, old, official, workspace)
        require_inherited_inputs(preflight['verify_direct_use_fork'](fork, declaration, source_manifest))
        package_inputs = runner['E_ROOT'] / 'package-inputs-v7'
        package_inputs.mkdir(mode=0o755)
        frozen_manifest = json.loads(preflight['committed_file'](ROOT, args.expected_package_commit,
                                    'runtime-proof/package-inputs/public-package-manifest-v7.json'))
        for name in sorted(frozen_manifest['files']):
            copy_private(preflight, ROOT / 'runtime-proof/package-inputs' / name,
                         package_inputs / name, frozen_manifest['files'][name]['sha256'])
        for name, pin in [('public-package-manifest-v7.json', preflight['PACKAGE_MANIFEST_SHA']),
                          ('public-policy-manifest-v7.json', preflight['POLICY_MANIFEST_SHA'])]:
            copy_private(preflight, ROOT / 'runtime-proof/package-inputs' / name, package_inputs / name, pin)
        original_cache = official / 'cache' / materialized_site(official)
        original_python = original_cache / 'python/bin/python3.14'
        if regular_hash(preflight, original_python)[0] != runner['BUNDLED_PYTHON_SHA']:
            fail('official bundled interpreter binding')
        cache_check, cache_check_identity = fresh_mount(runner, 'm-local-official-cache-precheck-v1-')
        cache_code = preflight['committed_file'](ROOT, args.expected_package_commit,
                                                'runtime-proof/check-official-package-cache.py')
        if preflight['sha'](cache_code) != CACHE_CHECK_SHA:
            fail('official cache precheck pin')
        (cache_check / 'check.py').write_bytes(cache_code)
        (cache_check / 'check.py').chmod(0o400)
        os.chown(cache_check / 'check.py', 65534, 65534)
        run_bounded(runner, cache_check, [str(original_python), '-I', '-B', '-S',
                    str(cache_check / 'check.py'), str(package_inputs / 'package-runtime-candidate-v7.py'),
                    str(official / 'runtime/jac'), str(original_cache), str(cache_check / 'result.json')],
                    cache_check, runner['minimal_environment'](), remaining_seconds(deadline, 900), 'official-cache')
        mount_identity(cache_check, runner['E_ROOT'], 'm-local-official-cache-precheck-v1-', cache_check_identity)
        official_cache_raw = preflight['read_regular'](cache_check / 'result.json')
        official_cache_result = json.loads(official_cache_raw)
        if (official_cache_result.get('status') != 'passed' or
                official_cache_result.get('executed_precheck_sha256') != preflight['sha'](cache_code) or
                official_cache_result.get('recipe_sha256') != RECIPE_SHA or
                official_cache_result.get('official_binary_sha256') != runner['JAC_SHA']):
            fail('official cache precheck execution')
        for name in ('official_payload_sha256', 'extracted_inventory_sha256'):
            preflight['require_pattern'](official_cache_result.get(name), r'[0-9a-f]{64}', 'official cache precheck hash')
        wrapper, wrapper_identity = fresh_mount(runner, 'm-local-kali-package-wrapper-')
        package, package_identity = fresh_mount(runner, 'm-local-runtime-package-')
        for name in ('cache', 'scratch'):
            path = wrapper / name
            path.mkdir(mode=0o700)
            os.chown(path, 65534, 65534)
            if any(path.iterdir()):
                fail('fresh package cache or scratch')
        copy_private(preflight, package_inputs / 'package-runtime-candidate-v7.py', wrapper / 'recipe.py', RECIPE_SHA)
        loader_name = 'work/identity-runtime-v3/runtime-loader-provenance.py'
        loader_source = preflight['committed_file'](ROOT, args.expected_package_commit,
                                                  'runtime-proof/inputs/' + loader_name)
        if preflight['sha'](loader_source) != manifest['files'][loader_name]['sha256']:
            fail('fresh loader input binding')
        loader_script = wrapper / 'loader.py'
        loader_script.write_bytes(adapt_loader(loader_source, fork))
        loader_script.chmod(0o400)
        os.chown(loader_script, 65534, 65534)
        environment = runner['minimal_environment'](dict(JAC_CACHE_HOME=str(wrapper / 'cache'),
            JAC_PRECOMPILE_JOBS='1', JAC_PRECOMPILE_RECYCLE_MB='1024',
            TMPDIR=str(wrapper / 'scratch'), MLOCAL_RUNTIME_PACKAGE_WORKSPACE=str(package)))
        environment['JAC_DEV_SOURCE'] = str(fork / 'jac')
        code = ('import runpy; runpy.run_path(' + repr(str(loader_script)) +
                ',init_globals={"OUTPUT_PATH":' + repr(str(wrapper / 'loader.json')) + '});' +
                'runpy.run_path(' + repr(str(wrapper / 'recipe.py')) + ',run_name="__main__")')
        command = [str(official / 'runtime/jacpython'), '-B', '-c', code, '--fork', str(fork),
                   '--official-binary', str(official / 'runtime/jac'), '--official-cache',
                   str(original_cache),
                   '--package-inputs', str(package_inputs)]
        assembly = run_bounded(runner, wrapper, command, fork, environment,
                               remaining_seconds(deadline, ASSEMBLY_SECONDS), 'assembly')
        mount_identity(wrapper, runner['E_ROOT'], 'm-local-kali-package-wrapper-', wrapper_identity)
        mount_identity(package, runner['E_ROOT'], 'm-local-runtime-package-', package_identity)
        metadata_sha = preflight['sha'](preflight['read_regular'](package / 'result.json'))
        verification, verification_identity = fresh_mount(runner, 'm-local-package-verifier-v1-')
        control_source = preflight['committed_file'](ROOT, args.expected_package_commit,
                                                    'runtime-proof/check-fresh-package-classifier.py')
        if preflight['sha'](control_source) != CLASSIFIER_CONTROL_SHA:
            fail('classifier controls pin')
        (verification / 'controls.py').write_bytes(control_source)
        (verification / 'controls.py').chmod(0o400)
        os.chown(verification / 'controls.py', 65534, 65534)
        controls_command = [str(package / 'stage/python/bin/python3.14'), '-I', '-B', '-S',
                            str(verification / 'controls.py'), str(package), str(verification)]
        run_bounded(runner, verification, controls_command, verification, runner['minimal_environment'](),
                    remaining_seconds(deadline, 900), 'classifier')
        # A separate fresh scope runs the immutable verifier without compiler imports.
        verifier, verifier_identity = fresh_mount(runner, 'm-local-package-independent-v1-')
        copy_private(preflight, package_inputs / 'verify-runtime-package-inputs-v7.py', verifier / 'verifier.py', VERIFIER_SHA)
        run_bounded(runner, verifier, [sys.executable, '-I', '-B', str(verifier / 'verifier.py'),
                    str(package), str(verifier / 'result.json')], verifier, runner['minimal_environment'](),
                    remaining_seconds(deadline, 900), 'independent')
        mount_identity(package, runner['E_ROOT'], 'm-local-runtime-package-', package_identity)
        mount_identity(verification, runner['E_ROOT'], 'm-local-package-verifier-v1-', verification_identity)
        mount_identity(verifier, runner['E_ROOT'], 'm-local-package-independent-v1-', verifier_identity)
        loader_raw = preflight['read_regular'](wrapper / 'loader.json')
        controls_raw = preflight['read_regular'](verification / 'controls.json')
        accepted = accept_package(preflight, fork, package, preflight['read_regular'](verifier / 'result.json'),
            loader_raw, controls_raw, declaration, source_manifest, expected_metadata_sha256=metadata_sha,
            expected_loader_sha256=preflight['sha'](loader_raw), expected_controls_sha256=preflight['sha'](controls_raw),
            expected_controls_code_sha256=preflight['sha'](control_source), official_cache_raw=official_cache_raw,
            expected_official_cache_receipt_sha256=preflight['sha'](official_cache_raw),
            expected_official_cache_code_sha256=preflight['sha'](cache_code))
        remaining_seconds(deadline, 1)
        summary = dict(accepted, source=source_gate['source'], source_job_id=authenticated['job_id'],
                       source_artifact_id=authenticated['artifact_id'],
                       source_archive_sha256=authenticated['artifact_digest'],
                       executed_parent_sha256=preflight['sha'](parent_raw),
                       package_commit=args.expected_package_commit, source_commit=args.expected_source_commit,
                       runner_controls_receipt_sha256=runner['digest'](probe_path),
                       host_cpu_count=host_cpus, minimum_host_memory_bytes=MIN_HOST_MEMORY,
                       controls_confirmed_before_workload=assembly['controls_confirmed_before_workload'],
                       assembly_elapsed_limit_seconds=ASSEMBLY_SECONDS,
                       external_jac_db_url=False, actual_smtp=False)
    finally:
        runner['cleanup_mounts']()
    print(json.dumps(summary, sort_keys=True, separators=(',', ':')), flush=True)
    return 0


def materialized_site(official):
    candidates = [path.parent for path in (official / 'cache/rt').glob('*/site')
                  if path.is_dir() and not path.is_symlink()]
    if len(candidates) != 1:
        fail('fresh official package cache identity')
    root = candidates[0]
    if root.parent != official / 'cache/rt' or root.resolve() != root:
        fail('fresh official package cache path')
    return root.relative_to(official / 'cache')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError, AssertionError, KeyError, TypeError,
            subprocess.SubprocessError):
        print(json.dumps(dict(status='failed', error='fresh package verification failed', scope=SCOPE)), flush=True)
        raise SystemExit(1)
