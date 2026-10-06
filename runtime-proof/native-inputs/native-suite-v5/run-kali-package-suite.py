from pathlib import Path
import ast
import hashlib
import json
import os
import re
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
package = Path(sys.argv[1]).resolve()
assert package.parent == Path('/var/tmp') and package.name.startswith('m-local-runtime-package-')
metadata = json.loads((package / 'result.json').read_text())
assert metadata['official_binary_sha256'] == '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
assert metadata['runtime_base'] == '58cb97eb75cdff8b5ee78f4094ca2be16376601c'
assert metadata['executed_recipe_sha256'] == 'f564830f07af1131306c8d65b7f1182047864816572eda46cc7b52b0db40120c'
assert metadata['launcher_sha256'] == 'c6cdf1cf60abba6a64d2b8b06a22b9ba9c8392ab24d8a5bda3cf45efc64c9ce8'
assert hashlib.sha256((verified / 'runtime/jac').read_bytes()).hexdigest() == metadata['official_binary_sha256']
binary_hash = hashlib.sha256((package / 'jac').read_bytes()).hexdigest()
assert binary_hash == metadata['candidate_binary_sha256']
assert metadata['runtime_patch_sha256'] == 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
assert metadata['resumed_build'] is False
assert hashlib.sha256((package / 'assembled-inputs.json').read_bytes()).hexdigest() == metadata['assembled_input_manifest_sha256']
assert metadata['inherited_python_and_dependencies_byte_matched'] and not metadata['fork_path_reference_files']
assert metadata['source_override_in_payload'] is False
assert metadata['packed_trailer_region_and_payload_verified']
def inventory(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file() and path.name not in ('.ok', '.used') and '__pycache__' not in path.parts}

def assert_zero_summary_counters(text):
    counter_word = r'(?:skip(?:s|ped)?|fail(?:s|ed)?|failure(?:s)?|error(?:s)?|todo(?:s)?)'
    prefix = r'(?im)(?:^|[(:,;|])[ \t]*(?:#\s*)?'
    suffix = r'(?=[ \t]*(?:$|[,;|.)]))'
    for pattern in (
        prefix + counter_word + r'[ \t]*(?:[:=][ \t]*|[ \t]+)[1-9]\d*' + suffix,
        prefix + r'[1-9]\d*[ \t]+' + counter_word + suffix):
        assert not re.search(pattern, text)

def assert_strict_graph_coverage(core_log, insights_log):
    assert re.search(r'\b451 passed(?:\s+in\b|$)', core_log, re.IGNORECASE)
    assert_zero_summary_counters(core_log)
    assert re.search(r'\b62 passed(?:\s+in\b|$)', insights_log, re.IGNORECASE)
    assert re.search(r'(?im)^\s*ran\s+12\s+tests?\b', insights_log)
    assert re.search(r'(?im)^\s*ok\s*$', insights_log)
    assert re.search(r'(?im)^\s*#\s*pass\s+11\b', insights_log)
    assert re.search(r'(?im)^\s*#\s*skipped\s+0\b', insights_log)
    assert re.search(r'(?im)^\s*#\s*fail\s+0\b', insights_log)
    assert_zero_summary_counters(insights_log)
inherited_file = package / 'inherited-inputs.json'
assert hashlib.sha256(inherited_file.read_bytes()).hexdigest() == metadata['inherited_input_manifest_sha256']
inherited = json.loads(inherited_file.read_text())
original = verified / 'cache/rt/9014fba108b7f76e'
assert inventory(original / 'python') == inherited['python'] == inventory(package / 'stage/python')
for name, expected in inherited['dependencies'].items():
    assert inventory(original / 'site' / name) == expected == inventory(package / 'stage/site' / name)
assert hashlib.sha256((package / 'stage/site/jaclang/_precompiled/MANIFEST.json').read_bytes()).hexdigest() == metadata['sealed_manifest_sha256']
assert hashlib.sha256((package / 'transaction.patch').read_bytes()).hexdigest() == metadata['runtime_patch_sha256']
assert hashlib.sha256((package / 'executed-recipe.py').read_bytes()).hexdigest() == metadata['executed_recipe_sha256']
assert hashlib.sha256((package / 'payload-build-references.json').read_bytes()).hexdigest() == metadata['build_reference_manifest_sha256']
assert json.loads((package / 'payload-build-references.json').read_text()) == metadata['build_path_reference_files']
raw = (package / 'jac').read_bytes()
assert raw[-80:-72] == b'JACBIN01'
payload_length = int.from_bytes(raw[-72:-64], 'little')
payload_start = len(raw) - 80 - payload_length
assert hashlib.sha256(raw[payload_start:-80]).hexdigest() == raw[-64:].decode() == metadata['payload_sha256']
assert hashlib.sha256((package / 'runtime.tar.zst').read_bytes()).hexdigest() == metadata['payload_sha256']
descriptor = raw[payload_start-32:payload_start]
assert descriptor[:8] == b'JSCATRG1'
offset, length = int.from_bytes(descriptor[8:16], 'little'), int.from_bytes(descriptor[16:24], 'little')
assert offset + length + 32 == payload_start
assert hashlib.sha256(raw[offset:offset+length]).hexdigest() == metadata['stub_catalog_sha256']
launcher = (package / 'launcher').read_bytes()
assert raw[:len(launcher)] == launcher and hashlib.sha256(launcher).hexdigest() == metadata['launcher_sha256']
helper = task / 'work/export-emergency-checkpoint.py'
node = next(n for n in ast.parse(helper.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'digest')
scope = dict(Path=Path, hashlib=hashlib)
exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(helper), 'exec'), scope)
assert scope['digest'](source) == scope['digest'](task / 'work/m-local') == '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42'
resources = runpy.run_path(str(task / 'work/kali-build-resources-v2.py'))
storage_binding = resources['verify_storage']()
isolation_path = task / 'work/runtime-build-source-isolation.py'
isolation = runpy.run_path(str(isolation_path))
isolation_control_path = resources['e_parent'] / 'runtime-source-isolation-control-v1.json'
isolation_control = json.loads(isolation_control_path.read_text())
assert isolation_control['status'] == 'passed' and isolation_control['exact_restoration_verified']
assert isolation_control['helper_sha256'] == hashlib.sha256(isolation_path.read_bytes()).hexdigest()
assert isolation_control['executed_probe_sha256'] == hashlib.sha256((task / 'work/test-runtime-build-source-isolation.py').read_bytes()).hexdigest()
directory = resources['mounted_empty']('m-local-package-suite-')
shutil.copyfile(task / 'work/kali-build-resources-v2.py', directory / 'executed-resources.py')
shutil.copyfile(isolation_path, directory / 'executed-source-isolation.py')
scratch = directory / 'scratch'
scratch.mkdir(mode=0o700)
os.chown(scratch, 65534, 65534)
runtime = directory / 'runtime'
runtime.mkdir(mode=0o700)
cache = directory / 'cache'
cache.mkdir(mode=0o700)
assert not any(cache.iterdir())
shutil.copyfile(package / 'jac', runtime / 'jac')
os.chmod(runtime / 'jac', 0o755)
(runtime / 'jacpython').symlink_to('jac')
assert hashlib.sha256((runtime / 'jac').read_bytes()).hexdigest() == binary_hash
app = directory / 'app'
def copy_application(source, destination):
    def copy_tree(source_root, destination_root):
        for path in source_root.rglob('*'):
            relative = path.relative_to(source_root)
            if any(part == '__pycache__' or part == '.jac' or part.startswith('.env') for part in relative.parts):
                continue
            target = destination_root / relative
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                content = path.read_bytes()
                target.write_bytes(content.replace(b'\r\n', b'\n') if path.suffix == '.sh' else content)
                target.chmod(path.stat().st_mode & 0o777)
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('main.jac', 'theme.jac', 'jac.toml', '.jac-version'):
        path = source / name
        assert path.is_file()
        target = destination / name
        target.write_bytes(path.read_bytes())
        target.chmod(path.stat().st_mode & 0o777)
    for name in ('services', 'client', 'data', 'tests', 'scripts'):
        copy_tree(source / name, destination / name)
    copy_tree(source / 'assets/brand', destination / 'assets/brand')

copy_application(source, app)
test_script_sha256 = hashlib.sha256((app / 'scripts/test.sh').read_bytes()).hexdigest()
assert test_script_sha256 == 'ef9ca36358ca219df9562612e19ec08939e468ef563c95b86938d34f2df02068'
graph_controller = directory / 'graph-coverage-controller.py'
graph_controller.write_text('''from pathlib import Path
import os
import subprocess
import sys
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
assert result is not None and not runtime.is_running(), 'Owned isolated test PostgreSQL was not stopped'
raise SystemExit(result.returncode)
''')
os.chown(graph_controller, 65534, 65534)
assert '[dev]' not in (app / 'jac.toml').read_text()
inputs = {str(p.relative_to(app)): hashlib.sha256(p.read_bytes()).hexdigest() for p in app.rglob('*') if p.is_file()}
(directory / 'app-input-files.json').write_text(json.dumps(inputs, sort_keys=True, indent=2) + '\n')
shutil.copyfile(__file__, directory / 'executed-suite.py')
for name in ('verify-runtime-package-inputs.py', 'runtime-catalog-cold-probe.py', 'runtime-catalog-path-audit.py'):
    shutil.copyfile(task / ('work/identity-runtime-v3' if name == 'verify-runtime-package-inputs.py' else 'work') / name, directory / name)
for path in [directory, *directory.rglob('*')]:
    assert not path.is_symlink() or path == runtime / 'jacpython'
    os.chown(path, 65534, 65534, follow_symlinks=False)
environment = dict(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', HOME='/nonexistent', LANG='C.UTF-8',
    JAC_BIN=str(runtime / 'jac'), JAC_CACHE_HOME=str(directory / 'cache'),
    JAC_NO_DEV_SOURCE='1', JAC_TEST_STRICT='1', JAC_PG_DIST=str(verified / 'cache/pg/dist/linux-amd64-18.6.0'),
    JAC_PRECOMPILE_JOBS='2', JAC_PRECOMPILE_RECYCLE_MB='1024', PYTHONDONTWRITEBYTECODE='1',
    TMPDIR=str(scratch), NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1')
for key in list(environment):
    if key.startswith('MLOCAL_') or key in ('JAC_DEV_SOURCE', 'JAC_DB_URL', 'JAC_CHECK_JOBS', 'OPENAI_API_KEY', 'RESEND_API_KEY',
            'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        environment.pop(key)
node_bin = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/client-tools/node-v22.16.0-linux-x64/bin')
assert (node_bin / 'node').is_file()
environment['PATH'] = str(node_bin) + ':' + environment['PATH']
for key, name in (('npm_config_cache', 'npm-cache'), ('BUN_INSTALL_CACHE_DIR', 'bun-cache')):
    cache = directory / name
    cache.mkdir(mode=0o700)
    os.chown(cache, 65534, 65534)
    assert not any(cache.iterdir()) and cache.stat().st_uid == 65534 and cache.stat().st_mode & 0o777 == 0o700
    environment[key] = str(cache)
receipt = dict(status='running', scope='Fresh exact sealed derivative canonical project compatibility suite; no runtime adoption/deployment',
    test_script_sha256=test_script_sha256, graph_coverage_controller_sha256=hashlib.sha256(graph_controller.read_bytes()).hexdigest(),
    workspace=str(directory), storage_binding=storage_binding, storage_scope='Suite app/runtime/client caches/scratch are private E:-backed', application_path=str(app), binary_sha256=binary_hash,
    runtime_patch_sha256=metadata['runtime_patch_sha256'], source_override=False,
    source_digest_sha256=scope['digest'](app), owned_uid=65534,
    relocated_binary_sha256=hashlib.sha256((runtime / 'jac').read_bytes()).hexdigest(),
    runtime_relocated_from_build_workspace=True,
    fresh_private_client_caches=True, environment_allowlist=sorted(environment),
    node_binary_sha256=hashlib.sha256((node_bin / 'node').read_bytes()).hexdigest(),
    input_manifest_sha256=hashlib.sha256((directory / 'app-input-files.json').read_bytes()).hexdigest(), phases=[])
receipt['source_isolation_helper_sha256'] = hashlib.sha256(isolation_path.read_bytes()).hexdigest()
receipt['source_isolation_control_sha256'] = hashlib.sha256(isolation_control_path.read_bytes()).hexdigest()
trace_tools = Path('/var/tmp/m-local-kali-file-trace-01a1050e')
trace_control = json.loads((trace_tools / 'result.json').read_text())
assert trace_control['status'] == 'passed' and trace_control['execve_arguments_traced'] is False
trace_binary = trace_tools / 'root/usr/bin/strace'
assert hashlib.sha256(trace_binary.read_bytes()).hexdigest() == trace_control['binary_sha256']
for path, expected in trace_control['dependency_sha256'].items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
trace_environment_control = Path('/var/tmp/m-local-trace-environment-control-ofcxft7w')
strip_control = json.loads((trace_environment_control / 'result.json').read_text())
assert strip_control['status'] == 'passed'
assert hashlib.sha256((trace_environment_control / 'executed-probe.py').read_bytes()).hexdigest() == strip_control['executed_probe_sha256']
receipt['tracing_client_control_sha256'] = hashlib.sha256((trace_tools / 'result.json').read_bytes()).hexdigest()
receipt['tracee_environment_control_sha256'] = hashlib.sha256((trace_environment_control / 'result.json').read_bytes()).hexdigest()
trace_roots = json.loads((package / 'classifier-roots.json').read_text())


def run(name, command, timeout, max_rss=8 * 1024 * 1024):
    started = time.monotonic()
    peak = 0
    guarded = False
    traced = name.startswith('runtime-') or name == 'catalog-cold-relocation'
    if traced:
        isolation['check_sources'](hidden)
    child_env = dict(environment)
    trace_path = directory / (name + '.file-trace')
    if traced:
        child_env['LD_LIBRARY_PATH'] = str(trace_tools / 'root/usr/lib/x86_64-linux-gnu')
        command = [str(trace_binary), '-f', '-qq', '-s', '4096', '-e', 'trace=' + trace_control['file_syscalls'],
            '-E', 'LD_LIBRARY_PATH', '-o', str(trace_path), *command]
    with (directory / (name + '.log')).open('w') as log:
        phase_scope = directory / (directory.name + '-' + name)
        phase_scope.mkdir(mode=0o700)
        os.chown(phase_scope, 65534, 65534)
        process, state = resources['launch_scope'](phase_scope, command, app, child_env, log)
        reason = None
        try:
            while process.poll() is None:
                resources['sample_scope'](state)
                reason = resources['scope_guard'](state, time.monotonic() - started, timeout)
                if reason:
                    break
                time.sleep(.5)
        finally:
            resources['stop_scope'](state, process)
    if traced:
        isolation['check_sources'](hidden)
    if state['cleanup']['unit_state'].get('Result') == 'oom-kill':
        reason = 'kernel_memory_limit'
    row = dict(phase=name, status='guarded' if reason else 'passed' if process.returncode == 0 else 'failed',
        exit_code=process.returncode, elapsed_seconds=time.monotonic() - started,
        guard_reason=reason, kernel_memory_scope=state,
        peak_process_group_rss_kib=state['peak_process_rss_kib'], owned_process_stopped=state['cleanup']['cgroup_empty'])
    if traced:
        trace_text = trace_path.read_text()
        references = {label: trace_text.count(value) for label, value in trace_roots.items() if label != 'package'}
        row.update(file_trace_sha256=hashlib.sha256(trace_path.read_bytes()).hexdigest(),
            traced_file_operations=len(trace_text.splitlines()), forbidden_build_path_file_operations=references,
            build_source_aliases_kernel_private=True,
            tracing_client_environment_removed_from_tracee=True, execve_arguments_traced=False)
        if any(references.values()):
            row['status'] = 'failed'
            row['failure_reason'] = 'A build-source path appeared in a traced file operation'
    receipt['phases'].append(row)
    receipt['status'] = 'running' if row['status'] == 'passed' else row['status']
    (directory / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(row), flush=True)
    if row['status'] != 'passed':
        raise SystemExit(1)


def interrupted(signum, frame):
    raise SystemExit(128 + signum)

signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)

print('Retained exact-package fresh compatibility suite: ' + str(directory), flush=True)
hidden = []
try:
    run('package-input-verification', [sys.executable, '-B', str(directory / 'verify-runtime-package-inputs.py'),
        str(package), str(directory / 'package-input-verification.json')], 120)
    package_input = json.loads((directory / 'package-input-verification.json').read_text())
    assert package_input['status'] == 'passed' and package_input['candidate_binary_sha256'] == binary_hash
    receipt['package_input_verification_sha256'] = hashlib.sha256((directory / 'package-input-verification.json').read_bytes()).hexdigest()
    receipt['package_metadata_sha256'] = package_input['package_metadata_sha256']
    catalog_control = task / 'outputs/runtime-catalog-path-controls-v2/result.json'
    controls = json.loads(catalog_control.read_text())
    assert controls['status'] == 'passed' and len(controls['cases']) == 6
    assert controls['audit_sha256'] == hashlib.sha256((directory / 'runtime-catalog-path-audit.py').read_bytes()).hexdigest()
    receipt['catalog_path_control_receipt_sha256'] = hashlib.sha256(catalog_control.read_bytes()).hexdigest()
    for path in (Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork'), package / 'stage'):
        hidden.append(isolation['hide_source'](path, '.unavailable-for-suite'))
    receipt['source_isolation_denial_before'] = isolation['prove_denied'](hidden)
    receipt['fork_and_build_stage_unavailable_throughout_suite'] = True
    catalog_output = directory / 'catalog-cold-relocation.json'
    catalog_code = 'import runpy; runpy.run_path(' + repr(str(directory / 'runtime-catalog-cold-probe.py')) + ',init_globals=' + repr(dict(
        PACKAGE_PATH=str(package), OUTPUT_PATH=str(catalog_output), AUDIT_PATH=str(directory / 'runtime-catalog-path-audit.py'))) + ',run_name="__main__")'
    run('catalog-cold-relocation', [str(runtime / 'jacpython'), '-B', '-c', catalog_code], 120)
    isolation['check_sources'](hidden)
    catalog = json.loads(catalog_output.read_text())
    assert catalog['status'] == 'passed' and catalog['candidate_binary_sha256'] == binary_hash
    receipt['catalog_cold_relocation_sha256'] = hashlib.sha256(catalog_output.read_bytes()).hexdigest()
    receipt['catalog_complete_physical_path_audit_sha256'] = catalog['complete_physical_path_audit_sha256']
    receipt['catalog_audit_script_sha256'] = catalog['executed_audit_sha256']
    receipt['catalog_coverage'] = dict(module_paths=catalog['module_path_records_verified'], module_types=catalog['module_type_records_verified'])
    source_proof = Path('/var/tmp/m-local-kali-runtime-regressions-v3-sy04oid7')
    golden = json.loads((source_proof / 'result.json').read_text())
    assert golden['status'] == 'passed' and len(golden['phases']) == 10
    assert golden['runtime_patch_sha256'] == metadata['runtime_patch_sha256']
    assert hashlib.sha256((source_proof / 'result.json').read_bytes()).hexdigest() == '044ef0ac18a4948ef829f504a7fa49cf908ee6c34d3ce01abb6e6e3fd38085da'
    matrix = directory / 'runtime-matrix'
    matrix.mkdir(mode=0o700)
    os.chown(matrix, 65534, 65534)
    receipt['runtime_matrix_source_receipt_sha256'] = hashlib.sha256((source_proof / 'result.json').read_bytes()).hexdigest()
    receipt['runtime_matrix_probes'] = []
    for phase in golden['phases']:
        name = phase['name']
        original = source_proof / (name + '.py')
        assert hashlib.sha256(original.read_bytes()).hexdigest() == phase['executed_probe_sha256']
        adapted = original.read_text()
        for expression in ('Path.cwd().resolve()', 'workspace'):
            cwd_guard = 'assert ' + expression + " == Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork')"
            assert adapted.count(cwd_guard) <= 1
            adapted = adapted.replace(cwd_guard, 'assert ' + expression + ' == Path(' + repr(str(app)) + ')')
        disposable_guard = "if workspace != Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork'):"
        assert adapted.count(disposable_guard) <= 1
        adapted = adapted.replace(disposable_guard, 'if workspace != Path(' + repr(str(app)) + '):')
        if name == 'runtime-served-probe':
            receipt_bindings = {
                "subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()": repr(metadata['runtime_base']),
                "hashlib.sha256(subprocess.check_output(['git', 'diff', '--binary'])).hexdigest()": repr(metadata['runtime_patch_sha256']),
                "Path('/var/tmp/m-local-kali-operator-056070bz/app/services/models.jac')": 'Path(' + repr(str(app / 'services/models.jac')) + ')',
                'Real PostgreSQL served-manager diagnostic; permission admission substituted; source override; not HTTP or capacity':
                    'Real PostgreSQL served-manager diagnostic; permission admission substituted; exact sealed package; no source override; not HTTP or capacity',
            }
            for original_binding, package_binding in receipt_bindings.items():
                assert adapted.count(original_binding) == 1
                adapted = adapted.replace(original_binding, package_binding)
        probe = matrix / (name + '.py')
        probe.write_text(adapted)
        os.chown(probe, 65534, 65534)
        loader = matrix / (name + '-loader.py')
        loader.write_bytes((task / 'work/identity-runtime-v3/package-runtime-loader-provenance.py').read_bytes())
        os.chown(loader, 65534, 65534)
        code = ('import runpy,signal,sys; '
            'signal.signal(signal.SIGTERM,lambda s,f: sys.exit(128+s)); '
            'runpy.run_path(' + repr(str(loader)) + ',init_globals={"OUTPUT_PATH":' + repr(str(matrix / (name + '-loader.json'))) + '}); '
            'sys.path.insert(0,' + repr(str(app)) + '); '
            'runpy.run_path(' + repr(str(probe)) + ',run_name="__main__")')
        before = dict(environment)
        environment.update(phase.get('fault_env', {}), JAC_DB_RO_UNITS='0')
        try:
            run('runtime-' + name, [str(runtime / 'jacpython'), '-c', code], 300)
        finally:
            environment.clear()
            environment.update(before)
        assert json.loads((matrix / (name + '-loader.json')).read_text())['status'] == 'passed'
        assert len(json.loads((matrix / (name + '-loader.json')).read_text())['declaring_module_files']) >= 16
        receipt['runtime_matrix_probes'].append(dict(name=name, source_probe_sha256=phase['executed_probe_sha256'],
            executed_probe_sha256=hashlib.sha256(probe.read_bytes()).hexdigest(),
            adaptation='Historical workspace guards accept only the exact fresh test app; served receipt metadata binds the verified sealed package and fresh model path; transaction assertions and fixture body unchanged',
            loader_sha256=hashlib.sha256(loader.read_bytes()).hexdigest(), fault_env=phase.get('fault_env', {})))
    run('install', ['bash', '-c', 'source scripts/runtime.sh\n"$JAC_BIN" install'], 180)
    run('check', ['bash', 'scripts/check.sh'], 180)
    run('onboarding', ['bash', 'scripts/test.sh', 'onboarding'], 300)
    run('analytics', ['python3', '-m', 'unittest', 'discover', '-s', 'tests/analytics', '-p', 'test_analytics.py'], 60)
    graph_command = [str(runtime / 'jacpython'), '-B', str(graph_controller)]
    run('core', graph_command + ['core'], 900)
    core_log = (directory / 'core.log').read_text().lower()
    run('insights', graph_command + ['insights'], 900)
    insights_log = (directory / 'insights.log').read_text().lower()
    assert_strict_graph_coverage(core_log, insights_log)
    run('python-tooling', ['python3', '-m', 'unittest', 'discover', '-s', 'tests/tooling', '-p', 'test_*.py'], 60)
    run('photo-media', ['bash', 'scripts/python.sh', '-m', 'unittest', 'tests/photo_media.py'], 180)
    ui_unit_tests = [str(path.relative_to(app)) for path in sorted((app / 'tests/ui').glob('*.test.mjs'))]
    tooling_unit_tests = [str(path.relative_to(app)) for path in sorted((app / 'tests/tooling').glob('*.test.mjs'))]
    assert ui_unit_tests and tooling_unit_tests
    assert all(path.startswith('tests/ui/') for path in ui_unit_tests)
    assert all(path.startswith('tests/tooling/') for path in tooling_unit_tests)
    ui_unit_paths = ui_unit_tests + tooling_unit_tests
    ui_unit_manifest = directory / 'ui-unit-test-paths.json'
    ui_unit_manifest.write_text(json.dumps(ui_unit_paths, indent=2) + '\n')
    receipt['ui_unit_test_paths_sha256'] = hashlib.sha256(ui_unit_manifest.read_bytes()).hexdigest()
    run('ui-unit', ['node', '--test', *ui_unit_paths], 180)
    run('build', ['bash', 'scripts/build.sh'], 480)
    run('ui-dependencies', ['npm', 'install', '--prefix', '.jac/ui-test-runtime', '--no-save', '--package-lock=false', 'jsdom@26.1.0'], 120)
    tests = [str(p.relative_to(app)) for p in sorted((app / 'tests/ui/browser').glob('*.test.mjs'))]
    assert tests
    run('browser', ['node', '--test', *tests], 120)
    dependencies = inventory(app / '.jac/ui-test-runtime/node_modules')
    assert json.loads((app / '.jac/ui-test-runtime/node_modules/jsdom/package.json').read_text())['version'] == '26.1.0'
    (directory / 'ui-dependency-inputs.json').write_text(json.dumps(dependencies, indent=2, sort_keys=True) + '\n')
    receipt['ui_dependency_manifest_sha256'] = hashlib.sha256((directory / 'ui-dependency-inputs.json').read_bytes()).hexdigest()
    assert scope['digest'](app) == receipt['source_digest_sha256']
    artifact = app / 'dist/mobile-starter.jab'
    receipt.update(status='passed', artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(), artifact_bytes=artifact.stat().st_size)
    (directory / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(dict(status='passed', workspace=str(directory), artifact_sha256=receipt['artifact_sha256'])), flush=True)
except BaseException as error:
    if receipt['status'] == 'running':
        receipt['status'] = 'failed'
        receipt['failure_type'] = type(error).__name__
    raise
finally:
    if hidden:
        try:
            receipt['source_isolation_denial_after'] = isolation['prove_denied'](hidden)
            receipt['fork_and_build_stage_still_unavailable_before_restore'] = True
        finally:
            isolation['restore_sources'](hidden)
    receipt['fork_and_build_stage_restored'] = len(hidden) == 2 and all(row['original'].is_dir() for row in hidden)
    receipt['source_directory_owner_mode_inode_restored'] = receipt['fork_and_build_stage_restored']
    (directory / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
