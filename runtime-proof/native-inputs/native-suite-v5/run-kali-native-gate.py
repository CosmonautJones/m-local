"""Bound the two current exact-package HTTP and capacity proofs."""
from pathlib import Path
import ast
import hashlib
import json
import os
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time

os.umask(0o077)
task = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
verified = Path('/var/tmp/m-local-kali-operator-056070bz')
source = task / 'work/m-local'
mode, package_argument, compatibility_argument = sys.argv[1:4]
assert mode in ('http', 'capacity')
assert len(sys.argv) == (5 if mode == 'capacity' else 4)
package = Path(package_argument).resolve()
assert package.parent == Path('/var/tmp') and package.name.startswith('m-local-runtime-package-')
metadata = json.loads((package / 'result.json').read_text())
binary_hash = hashlib.sha256((package / 'jac').read_bytes()).hexdigest()
assert binary_hash == metadata['candidate_binary_sha256']
assert metadata['runtime_patch_sha256'] == 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
assert not metadata['resumed_build'] and metadata['source_override_in_payload'] is False
assert metadata['diagnostic_path_classification_passed'] and not metadata['fork_path_reference_files']
assert metadata['packed_trailer_region_and_payload_verified']
for name, key in (('assembled-inputs.json', 'assembled_input_manifest_sha256'),
                  ('inherited-inputs.json', 'inherited_input_manifest_sha256'),
                  ('transaction.patch', 'runtime_patch_sha256'), ('executed-recipe.py', 'executed_recipe_sha256')):
    assert hashlib.sha256((package / name).read_bytes()).hexdigest() == metadata[key]
compatibility = Path(compatibility_argument).resolve()
assert compatibility.name == 'result.json' and compatibility.parent.parent == Path('/var/tmp')
assert compatibility.parent.name.startswith('m-local-package-suite-')
compatible = json.loads(compatibility.read_text())
assert compatible['status'] == 'passed' and compatible['binary_sha256'] == binary_hash
assert compatible['test_script_sha256'] == 'ef9ca36358ca219df9562612e19ec08939e468ef563c95b86938d34f2df02068'
assert compatible['fork_and_build_stage_restored'] and all(row['status'] == 'passed' for row in compatible['phases'])
matrix_names = ['materialization', 'commit-40001', 'commit-40P01', 'commit-55P03', 'commit-08006',
    'runtime-boundary-probe', 'runtime-lifecycle-probe', 'runtime-served-probe', 'runtime-request-context-probe', 'runtime-nested-context-probe']
expected_phases = ['package-input-verification', 'catalog-cold-relocation'] + ['runtime-' + name for name in matrix_names] + [
    'install', 'check', 'onboarding', 'analytics', 'core', 'insights', 'python-tooling', 'photo-media', 'ui-unit', 'build', 'ui-dependencies', 'browser']
assert [row['phase'] for row in compatible['phases']] == expected_phases
assert [row['name'] for row in compatible['runtime_matrix_probes']] == matrix_names
assert all(row['guard_reason'] is None and row['kernel_memory_scope']['controls_confirmed_before_workload'] and
    row['kernel_memory_scope']['cleanup']['cgroup_empty'] for row in compatible['phases'])
suite_path = task / 'work/identity-runtime-v5/run-kali-package-suite.py'
suite_hash = hashlib.sha256((compatibility.parent / 'executed-suite.py').read_bytes()).hexdigest()
assert suite_hash == hashlib.sha256(suite_path.read_bytes()).hexdigest() == hashlib.sha256((Path(__file__).parent / 'run-kali-package-suite.py').read_bytes()).hexdigest()
package_input = compatibility.parent / 'package-input-verification.json'
assert hashlib.sha256(package_input.read_bytes()).hexdigest() == compatible['package_input_verification_sha256']
binding = json.loads(package_input.read_text())
assert binding['status'] == 'passed' and binding['candidate_binary_sha256'] == binary_hash
assert binding['package_metadata_sha256'] == hashlib.sha256((package / 'result.json').read_bytes()).hexdigest()
cold_catalog = compatibility.parent / 'catalog-cold-relocation.json'
assert hashlib.sha256(cold_catalog.read_bytes()).hexdigest() == compatible['catalog_cold_relocation_sha256']
cold = json.loads(cold_catalog.read_text())
assert cold['status'] == 'passed' and cold['candidate_binary_sha256'] == binary_hash
assert compatible['fork_and_build_stage_unavailable_throughout_suite'] and compatible['fork_and_build_stage_still_unavailable_before_restore']
assert compatible['source_directory_owner_mode_inode_restored']
assert compatible['source_isolation_denial_before']['uid'] == compatible['source_isolation_denial_after']['uid'] == 65534
http_receipt = None
if mode == 'capacity':
    http_receipt = Path(sys.argv[4]).resolve()
    assert http_receipt.name == 'result.json' and http_receipt.parent.parent == Path('/var/tmp')
    assert http_receipt.parent.name.startswith('m-local-kali-native-http-')
    http = json.loads(http_receipt.read_text())
    assert http['status'] == 'passed' and http['candidate_binary_sha256'] == binary_hash
    assert http['compatibility_receipt_sha256'] == hashlib.sha256(compatibility.read_bytes()).hexdigest()
    assert http['package_input_verification_sha256'] == hashlib.sha256(package_input.read_bytes()).hexdigest()
    assert http['runtime_patch_sha256'] == metadata['runtime_patch_sha256']
    assert http['executed_proof_sha256'] == hashlib.sha256((task / 'work/identity-runtime-v3/kali-packaged-two-api-proof.py').read_bytes()).hexdigest()
    assert http['source_and_stage_restored'] and http['production_source_still_matches'] and http['guard_reason'] is None
helper = task / 'work/export-emergency-checkpoint.py'
digest_node = next(n for n in ast.parse(helper.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'digest')
scope = dict(Path=Path, hashlib=hashlib)
exec(compile(ast.fix_missing_locations(ast.Module(body=[digest_node], type_ignores=[])), str(helper), 'exec'), scope)
app_digest = scope['digest'](source)
if http_receipt:
    assert http['production_source_digest_sha256'] == app_digest
assert app_digest == compatible['source_digest_sha256'] == scope['digest'](task / 'work/m-local') == '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42'

resources = runpy.run_path(str(task / 'work/kali-build-resources-v2.py'))
storage_binding = resources['verify_storage']()
isolation_path = task / 'work/runtime-build-source-isolation.py'
isolation = runpy.run_path(str(isolation_path))
isolation_control_path = resources['e_parent'] / 'runtime-source-isolation-control-v1.json'
isolation_control = json.loads(isolation_control_path.read_text())
assert isolation_control['status'] == 'passed' and isolation_control['exact_restoration_verified']
assert isolation_control['helper_sha256'] == hashlib.sha256(isolation_path.read_bytes()).hexdigest() == compatible['source_isolation_helper_sha256']
assert isolation_control['executed_probe_sha256'] == hashlib.sha256((task / 'work/test-runtime-build-source-isolation.py').read_bytes()).hexdigest()
assert hashlib.sha256(isolation_control_path.read_bytes()).hexdigest() == compatible['source_isolation_control_sha256']
def rollback_setup_mounts(prefixes, before, error):
    stopped = []
    for path in Path('/var/tmp').iterdir():
        if path.name in before or not path.name.startswith(prefixes):
            continue
        prefix = next(prefix for prefix in prefixes if path.name.startswith(prefix))
        assert path.parent == Path('/var/tmp') and len(path.name) == len(prefix) + 8 and not path.is_symlink()
        assert path.stat().st_uid in (0, 65534) and path.stat().st_mode & 0o777 == 0o700
        backing = resources['e_root'] / path.name
        if path.is_mount():
            assert path.stat().st_dev == resources['e_root'].stat().st_dev and backing.is_dir()
            (backing / 'setup-failure.json').write_text(json.dumps(dict(status='failed', phase='setup-before-proof',
                failure_type=type(error).__name__, canonical_alias=str(path), backing=str(backing),
                owned_process_started=False, mount_disposition='Unmounted; any setup files retained privately on E:')) + '\n')
            subprocess.run(['/usr/bin/umount', str(path)], check=True, timeout=20)
        elif backing.exists():
            assert backing.parent == resources['e_root'] and not backing.is_symlink()
            assert backing.stat().st_dev == resources['e_root'].stat().st_dev
            assert backing.stat().st_uid in (0, 65534) and backing.stat().st_mode & 0o777 == 0o700
            assert not any(backing.iterdir()), 'Unestablished mount backing must be empty'
            backing.rmdir()
        assert not path.is_mount() and not any(path.iterdir())
        path.rmdir()
        stopped.append(str(path))
    return stopped


def stage_worker_receipt(source, target):
    assert source.is_file() and not target.exists()
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copyfile(source, target)
    os.chown(target, 65534, 65534)
    target.chmod(0o400)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
    return expected


prefixes = ('m-local-kali-native-' + mode + '-', 'm-local-two-api-' if mode == 'http' else 'm-local-capacity-')
before_setup = {path.name for path in Path('/var/tmp').iterdir() if path.name.startswith(prefixes)}

try:
    directory = resources['mounted_empty']('m-local-kali-native-' + mode + '-')
    prepared_child = resources['mounted_empty']('m-local-two-api-' if mode == 'http' else 'm-local-capacity-')
    shutil.copyfile(task / 'work/kali-build-resources-v2.py', directory / 'executed-resources.py')
    shutil.copyfile(isolation_path, directory / 'executed-source-isolation.py')
    scratch = directory / 'scratch'
    scratch.mkdir(mode=0o700)
    os.chown(scratch, 65534, 65534)
    cache = directory / 'cache'
    cache.mkdir(mode=0o700)
    script = directory / 'executed-proof.py'
    script.write_bytes((task / 'work/identity-runtime-v3' / ('kali-packaged-two-api-proof.py' if mode == 'http' else 'kali-capacity-proof.py')).read_bytes())
    shutil.copyfile(__file__, directory / 'executed-wrapper.py')
    verifier = directory / 'verify-runtime-package-inputs.py'
    shutil.copyfile(task / 'work/identity-runtime-v3/verify-runtime-package-inputs.py', verifier)
    for path in (directory, cache, script, directory / 'executed-wrapper.py', verifier):
        os.chown(path, 65534, 65534)
    assert not any(cache.iterdir())
    environment = dict(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', HOME='/nonexistent', LANG='C.UTF-8',
        JAC_BIN=str(package / 'jac'), JAC_CACHE_HOME=str(cache), JAC_NO_DEV_SOURCE='1', PYTHONDONTWRITEBYTECODE='1',
        JAC_PG_DIST=str(verified / 'cache/pg/dist/linux-amd64-18.6.0'),
        MLOCAL_CANDIDATE_PACKAGE=str(package), MLOCAL_GATE_WORKSPACE_RECEIPT=str(directory / 'child-workspace.json'),
        MLOCAL_GATE_CHILD_WORKSPACE=str(prepared_child), TMPDIR=str(scratch),
        MLOCAL_PACKAGE_BINDING_RECEIPT=str(directory / 'package-input-verification.json'),
        NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1')
    if mode == 'http':
        environment.update(MLOCAL_PROBE_LOST_CREATE_RESPONSE='1', MLOCAL_PROBE_UNKNOWN_COMMIT='1', MLOCAL_PROBE_CONCURRENT_ATTEMPTS='50')
    else:
        for original, filename in ((compatibility, 'prior-compatibility-receipt.json'), (http_receipt, 'prior-http-receipt.json')):
            assert stage_worker_receipt(original, directory / filename) == hashlib.sha256(original.read_bytes()).hexdigest()
        environment.update(MLOCAL_CAPACITY_RECEIPT=str(directory / 'child-result.json'),
            MLOCAL_CAPACITY_COMPATIBILITY_RECEIPT=str(directory / 'prior-compatibility-receipt.json'))
        environment['MLOCAL_CAPACITY_HTTP_RECEIPT'] = str(directory / 'prior-http-receipt.json')
        tools = Path('/var/tmp/m-local-kali-pg-client-01a1050e')
        client_control = json.loads((tools / 'result.json').read_text())
        assert client_control['status'] == 'passed'
        for row in client_control['tools']:
            assert hashlib.sha256((tools / 'root/usr/lib/postgresql/18/bin' / row['name']).read_bytes()).hexdigest() == row['sha256']

    fork = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork')
    assert hashlib.sha256(subprocess.check_output(['/usr/bin/git', '-C', str(fork), 'diff', '--binary'],
        env=dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8'), user=65534, group=65534, extra_groups=[])).hexdigest() == metadata['runtime_patch_sha256']
    for name in subprocess.check_output(['/usr/bin/git', '-C', str(fork), 'diff', '--name-only'], text=True,
        env=dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8'), user=65534, group=65534, extra_groups=[]).splitlines():
        assert name.startswith('jac/jaclang/') and (fork / name).read_bytes() == (package / 'stage/site' / name.removeprefix('jac/')).read_bytes()
    receipt = dict(status='running', scope='Exact sealed package local native ' + mode + '; no SMTP, public ingress, host durability or browser capacity proof',
        workspace=str(directory), storage_binding=storage_binding, storage_scope='Native parent/child app/cache/PostgreSQL/scratch are E:-backed', candidate_binary_sha256=binary_hash, runtime_patch_sha256=metadata['runtime_patch_sha256'],
        production_source_digest_sha256=app_digest, executed_proof_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        compatibility_receipt_sha256=hashlib.sha256(compatibility.read_bytes()).hexdigest(),
        compatibility_suite_sha256=suite_hash,
        executed_wrapper_sha256=hashlib.sha256((directory / 'executed-wrapper.py').read_bytes()).hexdigest(),
        environment_allowlist=sorted(environment), fresh_private_cache=True)
    receipt['source_isolation_helper_sha256'] = hashlib.sha256(isolation_path.read_bytes()).hexdigest()
    if mode == 'capacity':
        receipt['worker_input_receipts'] = {filename: hashlib.sha256((directory / filename).read_bytes()).hexdigest()
            for filename in ('prior-compatibility-receipt.json', 'prior-http-receipt.json')}
    receipt['source_isolation_control_sha256'] = hashlib.sha256(isolation_control_path.read_bytes()).hexdigest()
    receipt['retained_evidence_mounts'] = [dict(path=str(path), backing=str(resources['e_root'] / path.name),
        mount_device_id=path.stat().st_dev, owned_uid=path.stat().st_uid, private_mode='0700')
        for path in (directory, prepared_child)]
    receipt['mount_retention_reason'] = 'Keep completed or guarded proof receipts/private fixtures accessible on E: at their canonical paths for independent review and the later capacity binding. All owned processes are stopped; mounts contain retained files only.'
except BaseException as error:
    rollback_setup_mounts(prefixes, before_setup, error)
    raise

hidden = []
process = None
state = None
reason = None
peak = 0
child_directory = None
timeout = 1800 if mode == 'http' else 4200
started = time.monotonic()

def inspect_processes():
    global child_directory
    marker = directory / 'child-workspace.json'
    if marker.is_file():
        child_directory = Path(json.loads(marker.read_text())['workspace'])
        assert child_directory == prepared_child
        assert child_directory.stat().st_uid == 65534 and child_directory.stat().st_mode & 0o777 == 0o700
        assert child_directory.is_mount() and child_directory.stat().st_dev == directory.stat().st_dev
    return resources['sample_scope'](state)

print('Retained bounded native ' + mode + ' gate: ' + str(directory), flush=True)
try:
    with (directory / 'package-input-verification.log').open('w') as log:
        subprocess.run([sys.executable, '-B', str(verifier), str(package), environment['MLOCAL_PACKAGE_BINDING_RECEIPT']],
            env=dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8', PYTHONDONTWRITEBYTECODE='1'),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120,
            user=65534, group=65534, extra_groups=[])
    new_binding_path = Path(environment['MLOCAL_PACKAGE_BINDING_RECEIPT'])
    new_binding = json.loads(new_binding_path.read_text())
    assert new_binding == binding
    environment['MLOCAL_PACKAGE_BINDING_SHA256'] = hashlib.sha256(new_binding_path.read_bytes()).hexdigest()
    receipt['package_input_verification_sha256'] = environment['MLOCAL_PACKAGE_BINDING_SHA256']
    receipt['catalog_cold_relocation_sha256'] = compatible['catalog_cold_relocation_sha256']
    receipt['prior_http_receipt_sha256'] = hashlib.sha256(http_receipt.read_bytes()).hexdigest() if http_receipt else None
    receipt['environment_allowlist'] = sorted(environment)
    for path in (fork, package / 'stage'):
        hidden.append(isolation['hide_source'](path, '.unavailable-for-' + directory.name))
    receipt['source_isolation_denial_before'] = isolation['prove_denied'](hidden)
    with (directory / 'proof.log').open('w') as log:
        process, state = resources['launch_scope'](directory, [str(package / 'jacpython'), str(script)], directory, environment, log)
        try:
            while process.poll() is None:
                isolation['check_sources'](hidden)
                rss = inspect_processes()
                peak = max(peak, rss)
                reason = resources['scope_guard'](state, time.monotonic() - started, timeout)
                if reason:
                    break
                time.sleep(.5)
        finally:
            resources['stop_scope'](state, process)
        inspect_processes()
        if state['cleanup']['unit_state'].get('Result') == 'oom-kill':
            reason = 'kernel_memory_limit'
    child_path = child_directory / 'result.json' if child_directory else None
    child = json.loads(child_path.read_text()) if child_path and child_path.is_file() else {}
    stopped = child.get('owned_api_processes_stopped') if mode == 'http' else child.get('owned_processes_stopped')
    receipt.update(status='guarded' if reason else 'passed' if process.returncode == 0 and child.get('status') == 'passed' and stopped and child.get('postgres_stopped') else 'failed',
        exit_code=process.returncode, child_status=child.get('status'), child_workspace=str(child_directory),
        child_receipt_sha256=hashlib.sha256(child_path.read_bytes()).hexdigest() if child_path and child_path.is_file() else None)
except BaseException as error:
    receipt.update(status='guarded' if reason else 'failed', failure_type=type(error).__name__)
    raise
finally:
    if process is not None and state is not None and not state.get('cleanup', {}).get('cgroup_empty'):
        resources['stop_scope'](state, process)
    if hidden:
        try:
            receipt['source_isolation_denial_after'] = isolation['prove_denied'](hidden)
        finally:
            isolation['restore_sources'](hidden)
    receipt.update(source_and_stage_restored=len(hidden) == 2 and all(row['original'].is_dir() for row in hidden),
        source_directory_owner_mode_inode_restored=len(hidden) == 2,
        elapsed_seconds=time.monotonic() - started, peak_owned_tree_rss_kib=peak, guard_reason=reason, kernel_memory_scope=state,
        time_guard_seconds=timeout, memory_guard_kib=8 * 1024 * 1024,
        production_source_still_matches=scope['digest'](source) == app_digest)
    (directory / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)
raise SystemExit(0 if receipt['status'] == 'passed' and receipt['source_and_stage_restored'] and receipt['production_source_still_matches'] else 1)

