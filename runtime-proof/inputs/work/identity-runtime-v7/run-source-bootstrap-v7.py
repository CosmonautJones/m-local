"""Run the fresh Ubuntu source/bootstrap identity proof with bounded controls.

This wrapper deliberately does not read historical source receipts or caches.
The remote runner must provision the canonical private storage mount and public
official runtime before invoking it.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import runpy
import signal
import subprocess
import sys
import time


IMAGE_ROOT = Path('/var/tmp/m-local-build-e-drive-v2-01a1050e')
CANONICAL_TASK = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
PROOF = 'work/identity-bootstrap-source-proof-v4.py'
PROOF_SHA256 = 'ca4d3ae731268a40db481dd722e2277c0bd25f9b123173f467059f2be1df4f5d'
PATCH_BEFORE = '80fd38c7555e31ad60cb36f4e7af904e848d584c98da76f9066bcee950acd0b7'
PATCH_SHA256 = 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
HELPER_SHA256 = '72fa698df809ec63c0d2cd7ce1c9d51bd5ee8a9e2b0bfba5bff979814217837b'
OFFICIAL_BINARY_SHA256 = '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
JACPYTHON_SHA256 = '198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542'
MEMORY_HIGH = 7 * 1024 ** 3
MEMORY_MAX = 8 * 1024 ** 3


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(label):
    raise RuntimeError(label)


def assert_host():
    values = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            values[key] = value.strip('"')
    if values.get('ID') != 'ubuntu' or values.get('VERSION_ID') != '24.04':
        fail('Ubuntu 24.04 guard')
    kernel = Path('/proc/version').read_text().lower()
    if os.environ.get('WSL_INTEROP') or 'microsoft' in kernel or 'wsl' in kernel:
        fail('WSL guard')
    if Path('/proc/1/comm').read_text().strip() != 'systemd' or not Path('/sys/fs/cgroup/cgroup.controllers').is_file():
        fail('systemd cgroup-v2 guard')
    if os.getuid() != 0 or int(Path('/proc/meminfo').read_text().split('MemTotal:', 1)[1].split()[0]) * 1024 < 13 * 1024 ** 3:
        fail('host capacity guard')


def git_patch(fork):
    environment = dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8')
    return subprocess.check_output(['/usr/bin/git', 'diff', '--binary'], cwd=fork, env=environment,
        user=65534, group=65534, extra_groups=[])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-root', type=Path, required=True)
    parser.add_argument('--fork', type=Path, required=True)
    parser.add_argument('--official-root', type=Path, required=True)
    parser.add_argument('--cold-compile', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert_host()
    task = args.task_root.resolve()
    if task != CANONICAL_TASK:
        fail('canonical task path guard')
    fork = args.fork.resolve()
    official = args.official_root.resolve()
    cold_receipt = args.cold_compile.resolve()
    proof = task / PROOF
    if digest(proof) != PROOF_SHA256:
        fail('source proof hash guard')
    if digest(task / 'work/kali-build-resources-v2.py') != HELPER_SHA256:
        fail('storage helper hash guard')
    if digest(task / 'work/identity-runtime-v3/runtime.patch') != PATCH_SHA256:
        fail('runtime patch hash guard')
    if not fork.is_dir() or fork.is_symlink() or not (fork / 'jac').is_dir():
        fail('fresh source fork guard')
    patch = git_patch(fork)
    if hashlib.sha256(patch).hexdigest() != PATCH_SHA256:
        fail('fresh source patch guard')
    binary = official / 'runtime/jac'
    jacpython = official / 'runtime/jacpython'
    pg_dist = official / 'cache/pg/dist/linux-amd64-18.6.0'
    if not binary.is_file() or binary.is_symlink() or not jacpython.is_file() or jacpython.is_symlink() or not pg_dist.is_dir():
        fail('official runtime input guard')
    if digest(binary) != OFFICIAL_BINARY_SHA256 or digest(jacpython) != JACPYTHON_SHA256:
        fail('official runtime hash guard')
    if (not cold_receipt.is_file() or cold_receipt.is_symlink() or cold_receipt.parent.parent != Path('/var/tmp') or
            not cold_receipt.parent.name.startswith(('m-local-source-stage-v7-', 'm-local-identity-type-compile-v7-')) or
            cold_receipt.parent.stat().st_mode & 0o777 != 0o700):
        fail('fresh cold compile receipt path guard')
    try:
        cold = json.loads(cold_receipt.read_text())
    except (OSError, ValueError):
        fail('fresh cold compile receipt format')
    cold_phases = cold.get('phases', [])
    if (cold.get('status') != 'passed' or cold.get('runtime_patch_sha256') != PATCH_SHA256 or
            cold.get('source_fork') != str(fork) or cold.get('official_binary_sha256') != OFFICIAL_BINARY_SHA256 or
            cold.get('jacpython_sha256') != JACPYTHON_SHA256 or cold.get('helper_sha256') != HELPER_SHA256 or
            len(cold_phases) != 2 or
            cold_phases[0].get('status') != 'expected_failure' or cold_phases[1].get('status') != 'passed'):
        fail('fresh cold compile receipt gate')
    if (cold_phases[0].get('runtime_patch_sha256') != PATCH_BEFORE or
            cold_phases[1].get('runtime_patch_sha256') != PATCH_SHA256 or
            any(not row.get('fork_patch_unchanged') or not row.get('fresh_empty_cache') or
            not row.get('kernel_memory_scope', {}).get('controls_confirmed_before_workload') or
            not row.get('kernel_memory_scope', {}).get('cleanup', {}).get('cgroup_empty') for row in cold_phases)):
        fail('fresh cold compile controls')
    resources = runpy.run_path(str(task / 'work/kali-build-resources-v2.py'))
    e_root = resources['e_root']
    if e_root != IMAGE_ROOT or not e_root.is_mount() or e_root.is_symlink() or e_root.stat().st_uid != 65534 or e_root.stat().st_mode & 0o777 != 0o700:
        fail('fresh storage mount guard')
    workspace = resources['mounted_empty']('m-local-identity-bootstrap-proof-v4-')
    cache = workspace / 'cache'
    cache.mkdir(mode=0o700)
    cache_was_empty = not any(cache.iterdir())
    scratch = workspace / 'scratch'
    scratch.mkdir(mode=0o700)
    os.chown(cache, 65534, 65534)
    os.chown(scratch, 65534, 65534)
    script = workspace / 'executed-proof.py'
    script.write_bytes(proof.read_bytes())
    os.chown(script, 65534, 65534)
    environment = dict(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', HOME='/nonexistent', LANG='C.UTF-8',
        JAC_BIN=str(binary), JAC_DEV_SOURCE=str(fork / 'jac'), JAC_CACHE_HOME=str(cache),
        JAC_PG_DIST=str(pg_dist), TMPDIR=str(scratch), MLOCAL_IDENTITY_PROOF_WORKSPACE=str(workspace),
        MLOCAL_IDENTITY_PATCH_SHA256=PATCH_SHA256, PYTHONDONTWRITEBYTECODE='1',
        NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1')
    for key in ('JAC_DB_URL', 'MLOCAL_SOURCE_GATE_SHA256', 'JAC_NO_DEV_SOURCE', 'OPENAI_API_KEY', 'RESEND_API_KEY'):
        environment.pop(key, None)
    log = workspace / 'proof.log'
    started = time.monotonic()
    process = None
    state = None
    reason = None
    try:
        with log.open('w') as stream:
            process, state = resources['launch_scope'](workspace, [str(jacpython), '-B', str(script)], workspace, environment, stream,
                                                       high=MEMORY_HIGH, maximum=MEMORY_MAX)
            try:
                while process.poll() is None:
                    resources['sample_scope'](state)
                    reason = resources['scope_guard'](state, time.monotonic() - started, 3600)
                    if reason:
                        break
                    time.sleep(.5)
            finally:
                cleanup = resources['stop_scope'](state, process)
        child_path = workspace / 'child-result.json'
        child = json.loads(child_path.read_text()) if child_path.is_file() else {}
        post_patch = git_patch(fork)
        fork_patch_unchanged = hashlib.sha256(post_patch).hexdigest() == PATCH_SHA256
        passed = process.returncode == 0 and reason is None and child.get('status') == 'passed' and len(child.get('checks', [])) == 53
        passed = passed and child.get('owned_processes_stopped') and child.get('postgres_stopped') and cleanup.get('cgroup_empty') and fork_patch_unchanged
        shim = fork / 'jac/jaclang/compiler/backends/native/llvm/libjacllvm.so'
        typeshed = fork / 'jac/jaclang/vendor/typeshed'
        typeshed_inputs = {str(file.relative_to(typeshed)): digest(file)
            for file in sorted(typeshed.rglob('*')) if file.is_file() and '__pycache__' not in file.parts}
        passed = passed and shim.is_file() and digest(shim) == '02f499e9becacf36161aa9f4b39a9f950f4dd8dbcb744acded0f04618652b4de'
        passed = passed and len(typeshed_inputs) == 749 and hashlib.sha256(json.dumps(typeshed_inputs, sort_keys=True).encode()).hexdigest() == '1fd7fa02ccc83ad6a6a1fe7451231911a030a70d6f9d166c6d6b7d2715ce648a'
        receipt = dict(status='passed' if passed else 'guarded' if reason else 'failed', scope='Fresh source identity/bootstrap proof',
            workspace=str(workspace), fork=str(fork), runtime_patch_sha256=PATCH_SHA256,
            source_override_explicit=True, fork_patch_unchanged=fork_patch_unchanged,
            source_proof_sha256=digest(script), executed_proof_sha256=digest(script),
            executed_wrapper_sha256=digest(Path(__file__)), child_receipt_sha256=digest(child_path) if child_path.is_file() else None,
            application_digest=child.get('production_source_digest_sha256'), checks=len(child.get('checks', [])),
            exit_code=process.returncode, guard_reason=reason, elapsed_seconds=round(time.monotonic() - started, 2),
            official_binary_sha256=digest(binary), jacpython_sha256=digest(jacpython),
            cold_compile_receipt_sha256=digest(cold_receipt), fresh_empty_cache=cache_was_empty,
            inherited_native_shim_sha256=digest(shim) if shim.is_file() else None,
            inherited_typeshed_inventory_sha256=hashlib.sha256(json.dumps(typeshed_inputs, sort_keys=True).encode()).hexdigest(),
            controls={'memory_high': MEMORY_HIGH, 'memory_max': MEMORY_MAX, 'swap_max': 0, 'oom_policy': 'stop',
                      'confirmed_before_workload': state.get('controls_confirmed_before_workload')},
            kernel_memory_scope=state,
            cleanup=cleanup, actual_smtp=False, private_log=str(log))
    except BaseException:
        if process is not None and state is not None and not state.get('cleanup', {}).get('cgroup_empty'):
            resources['stop_scope'](state, process)
        raise
    if not passed:
        fail('fresh source bootstrap proof')
    serialized = json.dumps(receipt, sort_keys=True, indent=2) + '\n'
    workspace_receipt = workspace / 'result.json'
    workspace_receipt.write_text(serialized)
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.output.write_text(serialized)
    print(json.dumps(dict(status=receipt['status'], checks=receipt['checks'], source_gate_sha256=digest(workspace_receipt),
                          elapsed_seconds=receipt['elapsed_seconds'], actual_smtp=False), separators=(',', ':')), flush=True)


if __name__ == '__main__':
    def raise_signal(signum):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, lambda signum, frame: raise_signal(signum))
    signal.signal(signal.SIGINT, lambda signum, frame: raise_signal(signum))
    main()
