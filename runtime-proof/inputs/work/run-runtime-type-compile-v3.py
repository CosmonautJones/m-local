from pathlib import Path
import hashlib
import json
import os
import runpy
import subprocess
import time

os.umask(0o077)
task = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
prepared = json.loads((task/'work/identity-runtime-v3/prepared-source.json').read_text())
old = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-bootstrap-source-v2-qn8iz625/fork')
new = Path(prepared['fork'])
resources = runpy.run_path(str(task/'work/kali-build-resources.py'))
storage = resources['verify_storage']()
directory = resources['mounted_empty']('m-local-identity-type-compile-v3-')
verified = Path('/var/tmp/m-local-kali-operator-056070bz')
official = verified/'runtime/jac'
assert hashlib.sha256(official.read_bytes()).hexdigest() == '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
rows = []
print(json.dumps(dict(status='running', workspace=str(directory), scope='Fresh cold targeted UserManager type check before and after correction')), flush=True)
for name, fork, expected_patch in [('before', old, prepared['previous_runtime_patch_sha256']), ('after', new, prepared['runtime_patch_sha256'])]:
    git_env = dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8')
    patch = subprocess.check_output(['/usr/bin/git', 'diff', '--binary'], cwd=fork, env=git_env, user=65534, group=65534, extra_groups=[])
    assert hashlib.sha256(patch).hexdigest() == expected_patch
    phase = resources['mounted_empty']('m-local-identity-type-'+name+'-')
    for child in ('cache', 'scratch'):
        (phase/child).mkdir(mode=0o700)
        os.chown(phase/child, 65534, 65534)
    environment = dict(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', HOME='/nonexistent', LANG='C.UTF-8',
        JAC_CACHE_HOME=str(phase/'cache'), JAC_DEV_SOURCE=str(fork/'jac'), TMPDIR=str(phase/'scratch'),
        JAC_PRECOMPILE_JOBS='1', JAC_PRECOMPILE_RECYCLE_MB='1024', PYTHONDONTWRITEBYTECODE='1',
        NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1')
    started = time.monotonic()
    reason = None
    with (phase/'compiler.log').open('w') as log:
        process, state = resources['launch_scope'](phase, [str(official), 'check', 'jac/jaclang/server/identity/user_manager.jac'], fork, environment, log)
        try:
            while process.poll() is None:
                resources['sample_scope'](state)
                reason = resources['scope_guard'](state, time.monotonic()-started, 1200)
                if reason:
                    break
                time.sleep(.5)
        finally:
            resources['stop_scope'](state, process)
    text = (phase/'compiler.log').read_text()
    expected = process.returncode != 0 and 'E1030' in text and 'IdentityStorage' in text and 'store' in text if name == 'before' else process.returncode == 0
    row = dict(name=name, status='expected_failure' if name == 'before' and expected and not reason else 'passed' if expected and not reason else 'guarded' if reason else 'failed',
        exit_code=process.returncode, guard_reason=reason, elapsed_seconds=round(time.monotonic()-started, 2),
        workspace=str(phase), source_override_explicit=True, fresh_empty_cache=True, runtime_patch_sha256=expected_patch,
        compiler_log_sha256=hashlib.sha256((phase/'compiler.log').read_bytes()).hexdigest(), kernel_memory_scope=state)
    rows.append(row)
    receipt = dict(status='running' if expected and not reason else 'failed', phases=rows, storage_binding=storage,
        scope='Cold targeted compiler evidence only; full source regression matrix, sealed assembly and application compatibility remain separate gates',
        executed_runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (directory/'result.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({k:v for k,v in row.items() if k != 'kernel_memory_scope'}), flush=True)
    assert expected and not reason, 'Targeted type-check expectation failed; compiler diagnostic retained in owned phase'
receipt['status'] = 'passed'
(directory/'result.json').write_text(json.dumps(receipt, indent=2)+'\n')
(task/'work/identity-runtime-v3/compile-result-pointer.json').write_text(json.dumps(dict(workspace=str(directory), receipt_sha256=hashlib.sha256((directory/'result.json').read_bytes()).hexdigest()), indent=2)+'\n')
print('Targeted failing/passing cold compiler proof passed.', flush=True)
