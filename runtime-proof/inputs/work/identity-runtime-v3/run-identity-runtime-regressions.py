from pathlib import Path
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import time

os.umask(0o077)
task = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
fork = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork')
verified = Path('/var/tmp/m-local-kali-operator-056070bz')
app = Path('/var/tmp/m-local-identity-bootstrap-proof-v4-srq_c04w/app')
expected = 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
source_gate = Path('/var/tmp/m-local-identity-bootstrap-proof-v4-srq_c04w')
gate_file = source_gate / 'result.json'
gate = json.loads(gate_file.read_text())
assert hashlib.sha256(gate_file.read_bytes()).hexdigest() == '60b44d053811398c097d1015627489d694dcef13aab6868b67fcc4ecfc8d54d8'
assert gate['status'] == 'passed' and gate['runtime_patch_sha256'] == expected
assert gate['fork_patch_unchanged'] and gate['guard_reason'] is None
assert gate['source_override_explicit'] and gate['fork'] == str(fork)
assert gate['official_binary_sha256'] == '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
assert gate['inherited_native_shim_sha256'] == '02f499e9becacf36161aa9f4b39a9f950f4dd8dbcb744acded0f04618652b4de'
assert hashlib.sha256((fork / 'jac/jaclang/compiler/backends/native/llvm/libjacllvm.so').read_bytes()).hexdigest() == gate['inherited_native_shim_sha256']
assert gate['inherited_typeshed_inventory_sha256'] == '1fd7fa02ccc83ad6a6a1fe7451231911a030a70d6f9d166c6d6b7d2715ce648a'
typeshed = fork / 'jac/jaclang/vendor/typeshed'
typeshed_inputs = {str(file.relative_to(typeshed)): hashlib.sha256(file.read_bytes()).hexdigest()
    for file in sorted(typeshed.rglob('*')) if file.is_file() and '__pycache__' not in file.parts}
assert len(typeshed_inputs) == 749
assert hashlib.sha256(json.dumps(typeshed_inputs, sort_keys=True).encode()).hexdigest() == gate['inherited_typeshed_inventory_sha256']
assert gate['kernel_memory_scope']['controls_confirmed_before_workload'] and gate['kernel_memory_scope']['cleanup']['cgroup_empty']
assert hashlib.sha256((source_gate / 'executed-proof.py').read_bytes()).hexdigest() == gate['executed_proof_sha256']
assert hashlib.sha256((source_gate / 'executed-wrapper.py').read_bytes()).hexdigest() == gate['executed_wrapper_sha256']
assert gate['executed_proof_sha256'] == hashlib.sha256((task / 'work/identity-bootstrap-source-proof-v4.py').read_bytes()).hexdigest()
assert gate['executed_wrapper_sha256'] == hashlib.sha256((task / 'work/run-identity-bootstrap-source-proof-v4.py').read_bytes()).hexdigest()
assert hashlib.sha256((source_gate / 'child-result.json').read_bytes()).hexdigest() == gate['child_receipt_sha256']
child = json.loads((source_gate / 'child-result.json').read_text())
assert child['status'] == 'passed' and child['owned_processes_stopped'] and child['postgres_stopped']
assert len(child['checks']) == 53
assert child['runtime_patch_sha256'] == expected and child['copied_app_digest_verified_before_api_start']
assert child['production_source_digest_sha256'] == '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42'
assert child['executed_proof_sha256'] == gate['executed_proof_sha256']

git_environment = dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8')
patch = subprocess.check_output(['/usr/bin/git', 'diff', '--binary'], cwd=fork, env=git_environment,
    user=65534, group=65534, extra_groups=[])
assert hashlib.sha256(patch).hexdigest() == expected
resources = runpy.run_path(str(task / 'work/kali-build-resources-v2.py'))
storage = resources['verify_storage']()
directory = resources['mounted_empty']('m-local-kali-runtime-regressions-v3-')

def inventory(path):
    return {str(file.relative_to(path)): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(path.rglob('*')) if file.is_file()}

cache = directory / 'cache'
accepted_cache = inventory(source_gate / 'cache')
assert shutil.disk_usage(resources['e_root']).free > sum(file.stat().st_size for file in (source_gate / 'cache').rglob('*') if file.is_file()) + resources['e_floor']
shutil.copytree(source_gate / 'cache', cache)
assert inventory(cache) == accepted_cache
resources['verify_storage']()
(directory / 'accepted-source-cache-inputs.json').write_text(json.dumps(accepted_cache, sort_keys=True, indent=2) + '\n')
scratch = directory / 'scratch'
scratch.mkdir(mode=0o700)
for path in [cache, *cache.rglob('*'), scratch]:
    assert not path.is_symlink()
    os.chown(path, 65534, 65534)
cache.chmod(0o700)
(directory / 'runtime.patch').write_bytes(patch)
(directory / 'executed-runner.py').write_bytes(Path(__file__).read_bytes())
(directory / 'executed-resources.py').write_bytes((task / 'work/kali-build-resources-v2.py').read_bytes())
environment = dict(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', HOME='/nonexistent', LANG='C.UTF-8',
    JAC_CACHE_HOME=str(cache), JAC_DEV_SOURCE=str(fork / 'jac'), TMPDIR=str(scratch),
    JAC_PG_DIST=str(verified / 'cache/pg/dist/linux-amd64-18.6.0'), JAC_DB_RO_UNITS='0',
    JAC_PRECOMPILE_JOBS='1', JAC_PRECOMPILE_RECYCLE_MB='1024', PYTHONDONTWRITEBYTECODE='1',
    NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1')
loader_text = (task / 'work/identity-runtime-v3/runtime-loader-provenance.py').read_text()
assert hashlib.sha256(loader_text.encode()).hexdigest() == '94e4da642dfa1dfff57001517362f701da109acec7246d0c7ad08afe1d5f724c'
receipt = dict(status='running', scope='Corrected source-runtime regression matrix and interface controls; not sealed, HTTP, capacity or deployment',
    workspace=str(directory), application=str(app), runtime_base='58cb97eb75cdff8b5ee78f4094ca2be16376601c', runtime_patch_sha256=expected,
    source_identity_gate_receipt_sha256=hashlib.sha256(gate_file.read_bytes()).hexdigest(),
    source_native_shim_sha256=gate['inherited_native_shim_sha256'], source_typeshed_inventory_sha256=gate['inherited_typeshed_inventory_sha256'],
    cache_origin='Byte-matched copy of the passing source identity gate cache; not a fresh packaging cache',
    cache_input_manifest_sha256=hashlib.sha256((directory / 'accepted-source-cache-inputs.json').read_bytes()).hexdigest(),
    environment_allowlist=sorted(environment), storage_binding=storage, phases=[], interface_proofs=[])
print('Retained bounded identity runtime regression matrix: ' + str(directory), flush=True)

def run(name, probe, additions=None, interface=False):
    source = task / 'work' / probe
    original = source.read_text()
    adapted = original.replace('/var/tmp/m-local-release-readiness-01a1050e', str(app)).replace('/var/tmp/m-local-runtime-fork-01a1050e', str(fork))
    old_guard = "if workspace.parent != Path('/var/tmp') or not workspace.name.startswith(('m-local-release-readiness-', 'm-local-runtime-fork-', 'm-local-runtime-proof.')):"
    assert adapted.count(old_guard) == (1 if probe == 'runtime-probe.py' else 0)
    adapted = adapted.replace(old_guard, 'if workspace != Path(' + repr(str(fork)) + '):')
    executed = directory / (name + '.py')
    executed.write_text(adapted)
    os.chown(executed, 65534, 65534)
    provenance = directory / (name + '-loader.py')
    provenance.write_text(loader_text)
    os.chown(provenance, 65534, 65534)
    values = {'OUTPUT_PATH': str(directory / (name + '-probe-result.json'))} if interface else {}
    code = ('from pathlib import Path; import runpy,signal,sys,json; signal.signal(signal.SIGTERM,lambda s,f: sys.exit(128+s)); '
        'runpy.run_path(' + repr(str(provenance)) + ',init_globals={"OUTPUT_PATH":' + repr(str(directory / (name + '-loader.json'))) + '}); '
        'assert len(json.loads(Path(' + repr(str(directory / (name + '-loader.json'))) + ').read_text())["implementation_files"]) >= 16; '
        'sys.path.insert(0,' + repr(str(app)) + '); runpy.run_path(' + repr(str(executed)) + ',init_globals=' + repr(values) + ',run_name="__main__")')
    child_env = dict(environment, **(additions or {}))
    started = time.monotonic()
    reason = None
    limit = 1200 if name == 'materialization' else 300
    with (directory / (name + '.log')).open('w') as log:
        process, state = resources['launch_scope'](directory, [str(verified / 'runtime/jacpython'), '-c', code], fork, child_env, log)
        try:
            while process.poll() is None:
                resources['sample_scope'](state)
                reason = resources['scope_guard'](state, time.monotonic() - started, limit)
                if reason:
                    break
                time.sleep(.5)
        finally:
            resources['stop_scope'](state, process)
    row = dict(name=name, status='guarded' if reason else 'passed' if process.returncode == 0 else 'failed', exit_code=process.returncode,
        guard_reason=reason, elapsed_seconds=time.monotonic() - started, time_limit_seconds=limit, kernel_memory_scope=state,
        original_probe_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), executed_probe_sha256=hashlib.sha256(executed.read_bytes()).hexdigest(),
        loader_sha256=hashlib.sha256(provenance.read_bytes()).hexdigest(), fault_env=additions or {},
        adaptation='Only application/source paths and the exact disposable cwd guard; fixture and transaction assertions unchanged')
    (receipt['interface_proofs'] if interface else receipt['phases']).append(row)
    receipt['status'] = 'running' if row['status'] == 'passed' else row['status']
    (directory / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k:v for k,v in row.items() if k != 'kernel_memory_scope'}), flush=True)
    assert row['status'] == 'passed', 'Private diagnostic log retained for failed phase ' + name
    assert json.loads((directory / (name + '-loader.json')).read_text())['status'] == 'passed'
    if interface:
        assert json.loads((directory / (name + '-probe-result.json')).read_text())['status'] == 'passed'

run('materialization', 'runtime-materialization-probe.py')
for state in ('40001', '40P01', '55P03', '08006'):
    run('commit-' + state, 'runtime-probe.py', {'MLOCAL_PROBE_SQLSTATE': state, 'MLOCAL_PROBE_ACCEPTED_COMMIT': '1' if state == '08006' else '0'})
for name in ('runtime-boundary-probe', 'runtime-lifecycle-probe', 'runtime-served-probe', 'runtime-request-context-probe', 'runtime-nested-context-probe'):
    run(name, name + '.py')
run('codec', 'runtime-interface-codec-probe.py', interface=True)
run('controls', 'runtime-interface-codec-controls-probe.py', interface=True)
assert len(receipt['phases']) == 10 and len(receipt['interface_proofs']) == 2
assert subprocess.check_output(['/usr/bin/git', 'diff', '--binary'], cwd=fork, env=git_environment,
    user=65534, group=65534, extra_groups=[]) == patch
receipt['status'] = 'passed'
(directory / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('All ten source-runtime phases and both interface proofs passed.', flush=True)

(task / 'work/identity-runtime-v3/regression-result-pointer.json').write_text(json.dumps(dict(workspace=str(directory), receipt_sha256=hashlib.sha256((directory / 'result.json').read_bytes()).hexdigest()), indent=2) + '\n')
