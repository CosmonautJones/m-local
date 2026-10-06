"""Bounded controller for the fresh v7 source/bootstrap and 10+2 jobs.

Each job receives a fresh public checkout, fork, official runtime and private
storage mount on an Ubuntu 24.04 runner.  The controller retains only a
sanitized stage receipt; child logs remain private on the runner.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time


CANONICAL_TASK = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
BOOTSTRAP = 'work/identity-runtime-v7/run-source-bootstrap-v7.py'
MATRIX = 'work/identity-runtime-v7/run-source-matrix-v7.py'
COLD_COMPILE = 'work/identity-runtime-v7/run-source-cold-compile-v7.py'
BOOTSTRAP_LIMIT = 3600
MATRIX_LIMIT = 4500
COLD_COMPILE_LIMIT = 2400
GRACE = 30
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
    process = ACTIVE
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=GRACE)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=GRACE)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass


def handle_signal(signum, frame):
    stop_active()
    raise SystemExit(128 + signum)


def run_job(task, script, command, output, limit, log):
    global ACTIVE
    environment = dict(os.environ, PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                       HOME='/nonexistent', LANG='C.UTF-8', JAC_NO_DEV_SOURCE='1',
                       PYTHONDONTWRITEBYTECODE='1', NO_PROXY='localhost,127.0.0.1,::1',
                       no_proxy='localhost,127.0.0.1,::1')
    for key in ('JAC_DB_URL', 'JAC_DEV_SOURCE', 'OPENAI_API_KEY', 'RESEND_API_KEY', 'SMTP_HOST', 'SMTP_URL'):
        environment.pop(key, None)
    started = time.monotonic()
    reason = None
    with log.open('w') as stream:
        ACTIVE = subprocess.Popen(command, cwd=task, env=environment, stdin=subprocess.DEVNULL,
                                  stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while ACTIVE.poll() is None and time.monotonic() - started < limit:
                time.sleep(.5)
            if ACTIVE.poll() is None:
                reason = 'stage_timeout'
                stop_active()
            else:
                ACTIVE.wait(timeout=GRACE)
        finally:
            if ACTIVE.poll() is None:
                stop_active()
            if ACTIVE.poll() is None:
                fail('stage process cleanup; private log ' + str(log))
        exit_code = ACTIVE.returncode
    process = ACTIVE
    ACTIVE = None
    if reason or exit_code != 0:
        fail('stage execution; private log ' + str(log))
    if not output.is_file():
        fail('stage receipt missing; private log ' + str(log))
    receipt = json.loads(output.read_text())
    if receipt.get('status') != 'passed':
        fail('stage receipt status; private log ' + str(log))
    source_job = script == MATRIX
    return dict(status='passed', stage=Path(script).stem, wrapper_sha256=digest(task / script),
                result_sha256=digest(output), elapsed_seconds=round(time.monotonic() - started, 2),
                controls={'JAC_NO_DEV_SOURCE': not source_job, 'JAC_DEV_SOURCE': source_job, 'JAC_DB_URL': False,
                          'child_exit_code': process.returncode}, child_result_path=str(output),
                child_result_sha256=digest(output), private_log=str(log))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=('cold-compile', 'bootstrap', 'matrix'), required=True)
    parser.add_argument('--task-root', type=Path, required=True)
    parser.add_argument('--fork', type=Path, required=True)
    parser.add_argument('--official-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-gate', type=Path)
    parser.add_argument('--old-fork', type=Path)
    parser.add_argument('--cold-compile', type=Path)
    args = parser.parse_args()
    assert_host()
    task = args.task_root.resolve()
    if task != CANONICAL_TASK or not task.is_dir() or task.is_symlink():
        fail('canonical task path guard')
    fork = args.fork.resolve()
    official = args.official_root.resolve()
    if not fork.is_dir() or fork.is_symlink() or not official.is_dir() or official.is_symlink():
        fail('fresh input path guard')
    work = Path(tempfile.mkdtemp(prefix='m-local-source-stage-v7-', dir='/var/tmp'))
    work.chmod(0o700)
    log = work / (args.stage + '.log')
    output = args.output.resolve()
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        fail('fresh output path guard')
    if args.stage == 'cold-compile':
        if args.old_fork is None:
            fail('old source fork input required')
        old_fork = args.old_fork.resolve()
        if not old_fork.is_dir() or old_fork.is_symlink():
            fail('old source fork input guard')
        script = COLD_COMPILE
        result = work / 'cold-compile-summary.json'
        command = [sys.executable, '-B', str(task / script), '--task-root', str(task), '--old-fork', str(old_fork),
                   '--fork', str(fork), '--official-root', str(official), '--output', str(result)]
        limit = COLD_COMPILE_LIMIT
    elif args.stage == 'bootstrap':
        if args.cold_compile is None:
            fail('cold compile receipt required')
        cold = args.cold_compile.resolve()
        if not cold.is_file() or cold.is_symlink():
            fail('cold compile receipt input guard')
        script = BOOTSTRAP
        result = work / 'bootstrap-summary.json'
        command = [sys.executable, '-B', str(task / script), '--task-root', str(task), '--fork', str(fork),
                   '--official-root', str(official), '--cold-compile', str(cold), '--output', str(result)]
        limit = BOOTSTRAP_LIMIT
    else:
        if args.source_gate is None:
            fail('source gate input required')
        gate = args.source_gate.resolve()
        if not gate.is_file() or gate.is_symlink():
            fail('fresh source gate input guard')
        script = MATRIX
        result = work / 'matrix-summary.json'
        command = [sys.executable, '-B', str(task / script), '--task-root', str(task), '--source-gate', str(gate),
                   '--fork', str(fork), '--official-root', str(official), '--output', str(result)]
        limit = MATRIX_LIMIT
    stage = run_job(task, script, command, result, limit, log)
    stage['input_paths'] = {'task_root': str(task), 'source_fork': str(fork), 'official_runtime_root': str(official)}
    if args.stage == 'matrix':
        stage['source_gate_sha256'] = digest(args.source_gate.resolve())
    if args.stage == 'bootstrap':
        stage['cold_compile_receipt_sha256'] = digest(args.cold_compile.resolve())
    serialized = json.dumps(stage, sort_keys=True, indent=2) + '\n'
    output.write_text(serialized)
    print(json.dumps({key: stage[key] for key in ('status', 'stage', 'wrapper_sha256', 'result_sha256', 'elapsed_seconds')},
                     sort_keys=True, separators=(',', ':')), flush=True)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    main()
