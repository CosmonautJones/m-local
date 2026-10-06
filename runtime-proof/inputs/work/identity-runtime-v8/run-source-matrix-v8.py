"""Run fresh source-runtime 10+2 proofs against a fresh bootstrap receipt.

The v3 runner is adapted in memory to bind the fresh gate receipt, fork,
loader root and task paths. Historical receipt hashes and historical storage verification are
never accepted.
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


MATRIX_SOURCE = 'work/identity-runtime-v3/run-identity-runtime-regressions.py'
BOOTSTRAP_WRAPPER = 'work/identity-runtime-v7/run-source-bootstrap-v7.py'
MATRIX_SHA256 = 'c2cdc4b2c7015891ac7c24241f04985e73df9a2c9c20f1fdd4981c05f6e6f657'
PATCH_SHA256 = 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
LOADER_SHA256 = '94e4da642dfa1dfff57001517362f701da109acec7246d0c7ad08afe1d5f724c'
HELPER_SHA256 = '72fa698df809ec63c0d2cd7ce1c9d51bd5ee8a9e2b0bfba5bff979814217837b'
OFFICIAL_BINARY_SHA256 = '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
JACPYTHON_SHA256 = '198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542'
MEMORY_HIGH = 7 * 1024 ** 3
MEMORY_MAX = 8 * 1024 ** 3
CANONICAL_TASK = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
CHILD_PROCESS = None


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


def stop_child():
    process = CHILD_PROCESS
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=30)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=30)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass


def handle_signal(signum, frame):
    stop_child()
    raise SystemExit(128 + signum)


def adapt(source, task, gate, fork, pointer, gate_sha):
    text = source.read_text()
    if "import shutil\n" not in text:
        fail('source matrix signal import guard')
    text = text.replace("import shutil\n", "import shutil\nimport signal\nimport sys\n", 1)
    old_verify_call = "resources['verify_" + "storage']()"
    old_cache = text[text.index("cache = directory / 'cache'"):text.index("scratch = directory / 'scratch'")]
    expected_cache = ("cache = directory / 'cache'\n"
        "accepted_cache = inventory(source_gate / 'cache')\n"
        "assert shutil.disk_usage(resources['e_root']).free > sum(file.stat().st_size for file in (source_gate / 'cache').rglob('*') if file.is_file()) + resources['e_floor']\n"
        "shutil.copytree(source_gate / 'cache', cache)\n"
        "assert inventory(cache) == accepted_cache\n"
        + old_verify_call + "\n"
        "(directory / 'accepted-source-cache-inputs.json').write_text(json.dumps(accepted_cache, sort_keys=True, indent=2) + '\\n')\n")
    if old_cache != expected_cache:
        fail('source matrix cache adaptation guard')
    text = text.replace(old_cache, "cache = directory / 'cache'\ncache.mkdir(mode=0o700)\nassert not any(cache.iterdir())\naccepted_cache = {}\n(directory / 'accepted-source-cache-inputs.json').write_text('{}\\n')\n\n")
    gate_assertions = [line for line in text.splitlines() if line.startswith("assert hashlib.sha256(gate_file.read_bytes()).hexdigest() ==")]
    if len(gate_assertions) != 1:
        fail('source matrix gate assertion guard')
    text = text.replace(gate_assertions[0], "assert hashlib.sha256(gate_file.read_bytes()).hexdigest() == os.environ['MLOCAL_SOURCE_GATE_SHA256']")
    substitutions = (
        ("task = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')",
         'task = Path(' + repr(str(task)) + ')'),
        ("fork = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork')",
         "fork = Path(os.environ['MLOCAL_SOURCE_FORK'])"),
        ("source_gate = Path('/var/tmp/m-local-identity-bootstrap-proof-v4-srq_c04w')",
         "source_gate = Path(os.environ['MLOCAL_SOURCE_GATE'])"),
        ("app = Path('/var/tmp/m-local-identity-bootstrap-proof-v4-srq_c04w/app')",
         "app = Path(os.environ['MLOCAL_SOURCE_GATE_APP'])"),
        ("verified = Path('/var/tmp/m-local-kali-operator-056070bz')",
         "verified = Path(os.environ['MLOCAL_OFFICIAL_ROOT'])"),
        ("resources = runpy.run_path(str(task / 'work/kali-build-resources-v2.py'))\nstorage = " + old_verify_call,
         "resources = runpy.run_path(str(task / 'work/kali-build-resources-v2.py'))\n"
         "def fresh_storage_binding():\n"
         "    root = resources['e_root']\n"
         "    assert root.is_mount() and not root.is_symlink() and root.stat().st_uid == 65534 and root.stat().st_mode & 0o777 == 0o700\n"
         "    return dict(status='fresh', storage_root=str(root), mount_device_id=root.stat().st_dev, private=True)\n"
         "storage = fresh_storage_binding()"),
        ("cache_origin='Byte-matched copy of the passing source identity gate cache; not a fresh packaging cache'",
         "cache_origin='Fresh empty private matrix cache; bootstrap cache was not transported'"),
        ("assert hashlib.sha256((source_gate / 'executed-proof.py').read_bytes()).hexdigest() == gate['executed_proof_sha256']\n"
         "assert hashlib.sha256((source_gate / 'executed-wrapper.py').read_bytes()).hexdigest() == gate['executed_wrapper_sha256']\n"
         "assert gate['executed_proof_sha256'] == hashlib.sha256((task / 'work/identity-bootstrap-source-proof-v4.py').read_bytes()).hexdigest()\n"
         "assert gate['executed_wrapper_sha256'] == hashlib.sha256((task / 'work/run-identity-bootstrap-source-proof-v4.py').read_bytes()).hexdigest()\n"
         "assert hashlib.sha256((source_gate / 'child-result.json').read_bytes()).hexdigest() == gate['child_receipt_sha256']",
         "assert hashlib.sha256((source_gate / 'executed-proof.py').read_bytes()).hexdigest() == gate['executed_proof_sha256']\n"
         "assert gate['executed_proof_sha256'] == hashlib.sha256((task / 'work/identity-bootstrap-source-proof-v4.py').read_bytes()).hexdigest()\n"
         "assert hashlib.sha256((source_gate / 'child-result.json').read_bytes()).hexdigest() == gate['child_receipt_sha256']\n"
         "assert gate['executed_wrapper_sha256'] == os.environ['MLOCAL_SOURCE_BOOTSTRAP_WRAPPER_SHA256']"),
        ("(task / 'work/identity-runtime-v3/regression-result-pointer.json').write_text(",
         "Path(os.environ['MLOCAL_SOURCE_MATRIX_POINTER']).write_text("),
    )
    for old, new in substitutions:
        if old not in text:
            fail('source matrix adaptation guard')
        text = text.replace(old, new)
    loader_guard = "assert hashlib.sha256(loader_text.encode()).hexdigest() == '94e4da642dfa1dfff57001517362f701da109acec7246d0c7ad08afe1d5f724c'"
    if text.count(loader_guard) != 1:
        fail('source matrix loader binding guard')
    loader_root = "root = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork').resolve()"
    bound_root = 'root = Path(' + repr(str(fork)) + ').resolve()'
    text = text.replace(loader_guard, loader_guard + '\nloader_root = ' + repr(loader_root) +
                        "\nassert loader_text.count(loader_root) == 1, 'fresh source loader root marker'" +
                        '\nloader_text = loader_text.replace(loader_root, ' + repr(bound_root) + ', 1)', 1)
    text = text.replace("expected = 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'",
                        "expected = os.environ['MLOCAL_RUNTIME_PATCH_SHA256']")
    marker = "run('materialization', 'runtime-materialization-probe.py')"
    handlers = ("def _source_matrix_signal(signum, frame):\n"
                "    raise SystemExit(128 + signum)\n"
                "signal.signal(signal.SIGTERM, _source_matrix_signal)\n"
                "signal.signal(signal.SIGINT, _source_matrix_signal)\n")
    if text.count(marker) != 1:
        fail('source matrix signal handler guard')
    text = text.replace(marker, handlers + marker, 1)
    return text


def main():
    global CHILD_PROCESS
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-root', type=Path, required=True)
    parser.add_argument('--source-gate', type=Path, required=True)
    parser.add_argument('--fork', type=Path, required=True)
    parser.add_argument('--official-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert_host()
    task = args.task_root.resolve()
    if task != CANONICAL_TASK:
        fail('canonical task path guard')
    source = task / MATRIX_SOURCE
    gate_file = args.source_gate.resolve()
    fork = args.fork.resolve()
    official = args.official_root.resolve()
    if digest(source) != MATRIX_SHA256 or digest(task / 'work/identity-runtime-v3/runtime-loader-provenance.py') != LOADER_SHA256:
        fail('source matrix input hash guard')
    if digest(task / 'work/kali-build-resources-v2.py') != HELPER_SHA256:
        fail('storage helper hash guard')
    if not gate_file.is_file() or gate_file.parent.parent != Path('/var/tmp') or not gate_file.parent.name.startswith('m-local-identity-bootstrap-proof-v4-'):
        fail('fresh source gate path guard')
    gate_sha = digest(gate_file)
    gate = json.loads(gate_file.read_text())
    if gate.get('status') != 'passed' or gate.get('checks') != 53 or gate.get('runtime_patch_sha256') != PATCH_SHA256:
        fail('fresh source gate receipt guard')
    if (gate.get('fork') != str(fork) or gate.get('official_binary_sha256') != OFFICIAL_BINARY_SHA256 or
            gate.get('jacpython_sha256') != JACPYTHON_SHA256 or not gate.get('cold_compile_receipt_sha256') or
            not gate.get('cleanup', {}).get('cgroup_empty')):
        fail('fresh source gate identity guard')
    if gate.get('executed_wrapper_sha256') != digest(task / BOOTSTRAP_WRAPPER):
        fail('fresh source bootstrap wrapper guard')
    if (not official.is_dir() or not (official / 'runtime/jac').is_file() or not (official / 'runtime/jacpython').is_file() or
            digest(official / 'runtime/jac') != OFFICIAL_BINARY_SHA256 or digest(official / 'runtime/jacpython') != JACPYTHON_SHA256):
        fail('official runtime input guard')
    if gate.get('official_binary_sha256') != digest(official / 'runtime/jac'):
        fail('official runtime provenance guard')
    if not fork.is_dir() or fork.is_symlink() or digest(task / 'work/identity-runtime-v3/runtime.patch') != PATCH_SHA256:
        fail('fresh source fork guard')
    work = Path(tempfile.mkdtemp(prefix='m-local-source-matrix-v7-', dir='/var/tmp'))
    work.chmod(0o700)
    pointer = work / 'regression-result-pointer.json'
    executed = work / 'executed-source-matrix.py'
    executed.write_text(adapt(source, task, gate_file.parent, fork, pointer, gate_sha))
    executed.chmod(0o700)
    environment = dict(os.environ, MLOCAL_SOURCE_GATE=str(gate_file.parent), MLOCAL_SOURCE_GATE_APP=str(gate_file.parent / 'app'),
                       MLOCAL_SOURCE_GATE_SHA256=gate_sha, MLOCAL_SOURCE_FORK=str(fork),
                       MLOCAL_SOURCE_MATRIX_POINTER=str(pointer), MLOCAL_RUNTIME_PATCH_SHA256=PATCH_SHA256,
                       MLOCAL_OFFICIAL_ROOT=str(official),
                       MLOCAL_SOURCE_BOOTSTRAP_WRAPPER_SHA256=digest(task / BOOTSTRAP_WRAPPER),
                       PYTHONDONTWRITEBYTECODE='1',
                       NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1')
    for key in ('JAC_DB_URL', 'JAC_DEV_SOURCE', 'JAC_NO_DEV_SOURCE', 'OPENAI_API_KEY', 'RESEND_API_KEY'):
        environment.pop(key, None)
    started = time.monotonic()
    reason = None
    with (work / 'matrix.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-B', str(executed)], cwd=task, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        CHILD_PROCESS = process
        try:
            while process.poll() is None and time.monotonic() - started < 4500:
                time.sleep(.5)
            if process.poll() is None:
                reason = 'source_matrix_timeout'
                stop_child()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                stop_child()
                process.wait(timeout=30)
        finally:
            stop_child()
            CHILD_PROCESS = None
    if reason or process.returncode != 0 or not pointer.is_file():
        fail('fresh source matrix execution')
    pointer_data = json.loads(pointer.read_text())
    result_path = Path(pointer_data['workspace']) / 'result.json'
    if result_path.parent.parent != Path('/var/tmp') or not result_path.is_file():
        fail('fresh source matrix result path')
    result = json.loads(result_path.read_text())
    phases = result.get('phases', [])
    interfaces = result.get('interface_proofs', [])
    if result.get('status') != 'passed' or len(phases) != 10 or len(interfaces) != 2:
        fail('fresh source matrix receipt')
    if result.get('runtime_patch_sha256') != PATCH_SHA256 or result.get('source_identity_gate_receipt_sha256') != gate_sha:
        fail('fresh source matrix provenance')
    if any(row.get('status') != 'passed' or not row.get('kernel_memory_scope', {}).get('controls_confirmed_before_workload') or
           not row.get('kernel_memory_scope', {}).get('cleanup', {}).get('cgroup_empty') for row in phases + interfaces):
        fail('fresh source matrix controls')
    receipt = dict(status='passed', scope='Fresh source-runtime 10+2 matrix', workspace=str(result_path.parent), source_gate_sha256=gate_sha,
        source_gate_receipt_sha256=gate_sha, source_matrix_source_sha256=digest(source),
        executed_matrix_sha256=digest(executed), result_sha256=digest(result_path),
        runtime_patch_sha256=PATCH_SHA256, official_binary_sha256=digest(official / 'runtime/jac'),
        phase_count=len(phases), interface_count=len(interfaces), elapsed_seconds=round(time.monotonic() - started, 2),
        memory_high=MEMORY_HIGH, memory_max=MEMORY_MAX, swap_max=0, private_log=str(work / 'matrix.log'))
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    print(json.dumps(dict(status=receipt['status'], phase_count=receipt['phase_count'],
                          interface_count=receipt['interface_count'], source_gate_sha256=gate_sha,
                          elapsed_seconds=receipt['elapsed_seconds'], actual_smtp=False),
                     sort_keys=True, separators=(',', ':')), flush=True)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    main()
