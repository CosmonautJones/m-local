"""Run the fresh two-phase cold UserManager compiler gate.

The first fork must reproduce the expected E1030 diagnostic and the corrected
fork must compile cleanly.  Each phase receives a fresh cache and its own
bounded cgroup; no historical compile receipt or cache is read.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import runpy
import signal
import subprocess
import time


IMAGE_ROOT = Path('/var/tmp/m-local-build-e-drive-v2-01a1050e')
CANONICAL_TASK = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
PATCH_BEFORE = '80fd38c7555e31ad60cb36f4e7af904e848d584c98da76f9066bcee950acd0b7'
PATCH_AFTER = 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
HELPER_SHA256 = '72fa698df809ec63c0d2cd7ce1c9d51bd5ee8a9e2b0bfba5bff979814217837b'
OFFICIAL_BINARY_SHA256 = '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
JACPYTHON_SHA256 = '198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542'
MEMORY_HIGH = 7 * 1024 ** 3
MEMORY_MAX = 8 * 1024 ** 3
ACTIVE = None


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


def stop_active():
    process, state = ACTIVE or (None, None)
    if process is None or state is None or not resources:
        return
    try:
        resources['stop_scope'](state, process)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass


def handle_signal(signum, frame):
    stop_active()
    raise SystemExit(128 + signum)


def git_patch(fork):
    environment = dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8')
    return subprocess.check_output(['/usr/bin/git', 'diff', '--binary'], cwd=fork, env=environment,
        user=65534, group=65534, extra_groups=[])


def main():
    global ACTIVE, resources
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-root', type=Path, required=True)
    parser.add_argument('--old-fork', type=Path, required=True)
    parser.add_argument('--fork', type=Path, required=True)
    parser.add_argument('--official-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert_host()
    task = args.task_root.resolve()
    if task != CANONICAL_TASK:
        fail('canonical task path guard')
    old_fork = args.old_fork.resolve()
    fork = args.fork.resolve()
    official = args.official_root.resolve()
    helper = task / 'work/kali-build-resources-v2.py'
    if digest(helper) != HELPER_SHA256:
        fail('storage helper hash guard')
    binary = official / 'runtime/jac'
    jacpython = official / 'runtime/jacpython'
    if not binary.is_file() or binary.is_symlink() or not jacpython.is_file() or jacpython.is_symlink():
        fail('official runtime input guard')
    if digest(binary) != OFFICIAL_BINARY_SHA256 or digest(jacpython) != JACPYTHON_SHA256:
        fail('official runtime hash guard')
    for path in (old_fork, fork):
        if not path.is_dir() or path.is_symlink() or not (path / 'jac').is_dir():
            fail('fresh source fork guard')
    before_patch = git_patch(old_fork)
    after_patch = git_patch(fork)
    if hashlib.sha256(before_patch).hexdigest() != PATCH_BEFORE or hashlib.sha256(after_patch).hexdigest() != PATCH_AFTER:
        fail('fresh source fork patch guard')
    resources = runpy.run_path(str(helper))
    e_root = resources['e_root']
    if e_root != IMAGE_ROOT or not e_root.is_mount() or e_root.is_symlink() or e_root.stat().st_uid != 65534 or e_root.stat().st_mode & 0o777 != 0o700:
        fail('fresh storage mount guard')
    directory = resources['mounted_empty']('m-local-identity-type-compile-v7-')
    rows = []
    started = time.monotonic()
    for name, source_fork, expected_patch in (('before', old_fork, PATCH_BEFORE), ('after', fork, PATCH_AFTER)):
        phase_started = time.monotonic()
        phase = resources['mounted_empty']('m-local-identity-type-' + name + '-v7-')
        cache = phase / 'cache'
        scratch = phase / 'scratch'
        cache.mkdir(mode=0o700)
        scratch.mkdir(mode=0o700)
        os.chown(cache, 65534, 65534)
        os.chown(scratch, 65534, 65534)
        if any(cache.iterdir()):
            fail('fresh empty compile cache guard')
        environment = dict(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', HOME='/nonexistent', LANG='C.UTF-8',
            JAC_CACHE_HOME=str(cache), JAC_DEV_SOURCE=str(source_fork / 'jac'), TMPDIR=str(scratch),
            JAC_PRECOMPILE_JOBS='1', JAC_PRECOMPILE_RECYCLE_MB='1024', PYTHONDONTWRITEBYTECODE='1',
            NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1')
        for key in ('JAC_DB_URL', 'JAC_NO_DEV_SOURCE', 'OPENAI_API_KEY', 'RESEND_API_KEY'):
            environment.pop(key, None)
        log = phase / 'compiler.log'
        reason = None
        with log.open('w') as stream:
            process, state = resources['launch_scope'](phase, [str(binary), 'check', 'jac/jaclang/server/identity/user_manager.jac'], source_fork, environment, stream,
                                                       high=MEMORY_HIGH, maximum=MEMORY_MAX)
            ACTIVE = (process, state)
            try:
                while process.poll() is None:
                    resources['sample_scope'](state)
                    reason = resources['scope_guard'](state, time.monotonic() - phase_started, 1200)
                    if reason:
                        break
                    time.sleep(.5)
            finally:
                resources['stop_scope'](state, process)
                ACTIVE = None
        text = log.read_text()
        expected = (process.returncode != 0 and 'E1030' in text and 'IdentityStorage' in text and 'store' in text) if name == 'before' else process.returncode == 0
        unchanged = git_patch(source_fork) == (before_patch if name == 'before' else after_patch)
        row = dict(name=name, status='expected_failure' if name == 'before' and expected and not reason else 'passed' if expected and not reason else 'guarded' if reason else 'failed',
            exit_code=process.returncode, guard_reason=reason, elapsed_seconds=round(time.monotonic() - phase_started, 2),
            workspace=str(phase), source_override_explicit=True, fresh_empty_cache=True, runtime_patch_sha256=expected_patch,
            fork_patch_unchanged=unchanged, compiler_log_sha256=digest(log), kernel_memory_scope=state,
            official_binary_sha256=OFFICIAL_BINARY_SHA256, jacpython_sha256=JACPYTHON_SHA256)
        rows.append(row)
        if row['status'] not in ('expected_failure', 'passed') or not unchanged:
            fail('cold compile phase')
    receipt = dict(status='passed', scope='Fresh cold targeted UserManager type check before and after correction',
        workspace=str(directory), phases=rows, runtime_patch_sha256=PATCH_AFTER, source_fork=str(fork),
        official_binary_sha256=OFFICIAL_BINARY_SHA256, jacpython_sha256=JACPYTHON_SHA256,
        helper_sha256=HELPER_SHA256, elapsed_seconds=round(time.monotonic() - started, 2),
        private_logs=[row['workspace'] + '/compiler.log' for row in rows])
    serialized = json.dumps(receipt, sort_keys=True, indent=2) + '\n'
    (directory / 'result.json').write_text(serialized)
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.output.write_text(serialized)
    print(json.dumps(dict(status='passed', phase_count=2, expected_failures=1,
                          runtime_patch_sha256=PATCH_AFTER, official_binary_sha256=OFFICIAL_BINARY_SHA256,
                          jacpython_sha256=JACPYTHON_SHA256, elapsed_seconds=receipt['elapsed_seconds']), separators=(',', ':')), flush=True)


resources = {}
if __name__ == '__main__':
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    main()
