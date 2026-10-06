#!/usr/bin/env python3
"""Run the fresh Ubuntu source/bootstrap/matrix proof on one disposable host.

The runner owns only its fresh checkout, forks, downloads, image mount and
child process groups.  It emits a sanitized summary; logs and intermediate
receipts stay in a private temporary directory for the remote job.
"""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import os
import runpy
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / 'runtime-proof' / 'inputs'
PINS_PATH = ROOT / 'runtime-proof' / 'public-download-pins.json'
SOURCE_MANIFEST_PATH = INPUTS / 'public-source-manifest.json'
ADAPTER_MANIFEST_PATH = INPUTS / 'v9-adapter-manifest.json'
DOWNLOAD_HELPER = ROOT / 'runtime-proof' / 'download-pinned-inputs.py'
PROBE = ROOT / 'runtime-proof' / 'probe-runner-controls.py'
HELPER = ROOT / 'runtime-proof' / 'kali-build-resources-v2.py'
HANDOFF_VERIFIER = ROOT / 'runtime-proof' / 'verify-source-handoff-v9.py'
HANDOFF_VERIFIER_BASE = ROOT / 'runtime-proof' / 'verify-source-handoff-v8.py'
SOURCE_EXPORT = ROOT / 'runtime-proof' / 'source-handoff-export'
SOURCE_MANIFEST_SHA = 'f0ade58e7b59cc49eb5c3c3d0a6c8ca08c4f5b9804dc49ad5ea4f171cc4be037'
ADAPTER_MANIFEST_SHA = '91a9b2f303a57b0178f1ff0c3b876f4d13a84913ce7270b8eb883f144056a81e'
ADAPTER_PATHS = (
    'work/identity-runtime-v7/run-source-cold-compile-v7.py',
    'work/identity-runtime-v7/run-source-bootstrap-v7.py',
    'work/identity-runtime-v9/run-source-matrix-v9.py',
    'work/identity-runtime-v9/run-source-stage-v9.py',
    'work/identity-runtime-v8/run-source-matrix-v8.py',
    'work/identity-runtime-v8/run-source-stage-v8.py',
)
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

CANONICAL_TASK = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
IMAGE = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/linux-build-storage-v2.ext4')
E_ROOT = Path('/var/tmp/m-local-build-e-drive-v2-01a1050e')
APP_REPOSITORY = 'https://github.com/CosmonautJones/m-local.git'
APP_REVISION = 'b0f2321016ba004b3a77db6fe05828080c755cd3'
JAC_REPOSITORY = 'https://github.com/jaseci-labs/jac.git'
JAC_BASE = '58cb97eb75cdff8b5ee78f4094ca2be16376601c'
PATCH_BEFORE = '80fd38c7555e31ad60cb36f4e7af904e848d584c98da76f9066bcee950acd0b7'
PATCH_AFTER = 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
JAC_SHA = '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
JACPYTHON_SHA = '198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542'
BUNDLED_PYTHON_SHA = '7056deaf70cc1b593bf7378abcd4c04d22a9f9510a88655fcd6d45951473afc3'
SHIM_SHA = '02f499e9becacf36161aa9f4b39a9f950f4dd8dbcb744acded0f04618652b4de'
TYPESHED_SHA = '1fd7fa02ccc83ad6a6a1fe7451231911a030a70d6f9d166c6d6b7d2715ce648a'
JAC_LICENSE_PATH = ROOT / 'runtime-proof' / 'JAC-LICENSE.txt'
JAC_LICENSE_SHA = '35219f6406160fa713fbe9c5a5932da993f2d7c53c33ac6439a38b810ec30a14'
APP_SHA = '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42'
MEMORY_HIGH = 7 * 1024 ** 3
MEMORY_MAX = 8 * 1024 ** 3
SOURCE_JOB_SECONDS = 12_600
MIN_HOST_MEMORY = 13 * 1024 ** 3
ACTIVE = None
PRIVATE_LOG_DIR = None
IMAGE_LOOP = None
MOUNT_BASELINE = set()
OWNED_MOUNTS = set()
RESOURCE_HELPER = None
SCOPED_COMMAND_LABELS = {
    'public application checkout', 'public application revision', 'application revision read',
    'public Jac clone', 'public Jac base checkout', 'Jac base revision read',
    'old source fork clone', 'current source fork clone', 'old source diff format',
    'current source diff format', 'old patch apply', 'current patch apply',
    'source fork diff identity-type-source-old-v7', 'source fork diff identity-type-source-v3-v7',
    'official Jac version', 'official Jac help', 'official Jac cache materialization',
    'pinned download jac', 'pinned download jacpython', 'pinned download postgres',
    'PostgreSQL version', 'declared dependency priming', 'Pillow dependency guard',
}
MATRIX_PHASE_NAMES = (
    'materialization', 'commit-40001', 'commit-40P01', 'commit-55P03', 'commit-08006',
    'runtime-boundary-probe', 'runtime-lifecycle-probe', 'runtime-served-probe',
    'runtime-request-context-probe', 'runtime-nested-context-probe', 'codec', 'controls',
)
FAILURE_DIAGNOSTICS = dict(operation='setup', last_scoped_command=None, body_completed=False,
                           body_failure_type=None, cleanup_failures=[], matrix_failure=None)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fail(label):
    raise RuntimeError(label)


def sanitized_failure_context(error):
    allowed = {
        'owned mount cleanup guard', 'cold stage mount receipt', 'cold stage mount identity',
        'source stage mount parent', 'source stage mount path', 'source stage mount backing identity',
        'source stage receipt missing', 'source stage wrapper binding', 'source stage child path guard',
        'source stage child binding', 'source stage child status', 'source leaf phase receipt',
        'source leaf kernel control receipt', 'source job global deadline', 'cold phase patch order',
        'bootstrap leaf gate', 'matrix leaf gate', 'matrix result path gate',
        'matrix storage receipt', 'matrix storage mount gate',
    } | {
        'source ' + stage + ' ' + reason
        for stage in ('cold-compile', 'bootstrap', 'matrix')
        for reason in ('failed', 'timeout', 'unavailable', 'unidentified mount cleanup',
                       'unidentified mounts', 'retained receipt binding')
    } | {
        command + ' ' + reason for command in SCOPED_COMMAND_LABELS
        for reason in ('failed', 'scope kernel_memory_limit', 'scope kernel_control_mismatch',
                       'scope disk', 'scope timeout', 'scope cleanup', 'scope bind cleanup')
    }
    labels = []
    seen = set()
    while error is not None and id(error) not in seen and len(seen) < 8:
        seen.add(id(error))
        if type(error) is RuntimeError and len(error.args) == 1 and type(error.args[0]) is str:
            label = error.args[0]
            if label in allowed and label not in labels:
                labels.append(label)
        error = error.__cause__ if error.__cause__ is not None else (
            None if error.__suppress_context__ else error.__context__)
    return labels


def sanitized_matrix_failure(value):
    if type(value) is not dict:
        return None
    name, status = value.get('name'), value.get('status')
    code, reason = value.get('exit_code'), value.get('guard_reason')
    if (type(name) is not str or name not in MATRIX_PHASE_NAMES or
            type(status) is not str or status not in {'failed', 'guarded'} or
            type(code) is not int or not -255 <= code <= 255):
        return None
    if (status == 'failed' and reason is not None) or (status == 'guarded' and
            (type(reason) is not str or reason not in {'kernel_memory_limit', 'kernel_control_mismatch', 'disk', 'timeout'})):
        return None
    return dict(name=name, status=status, exit_code=code, guard_reason=reason)


def sanitized_failure_diagnostics():
    state = FAILURE_DIAGNOSTICS if type(FAILURE_DIAGNOSTICS) is dict else {}
    operations = {
        'setup', 'producer-binding', 'host-controls', 'manifest-inputs', 'runner-controls',
        'storage-mount', 'application-checkout', 'runtime-materialization', 'source-forks',
        'shim-typeshed', 'dependency-priming', 'cold-compile', 'bootstrap', 'matrix',
        'handoff-build', 'handoff-export', 'summary',
    }
    families = {'RuntimeError', 'OSError', 'SubprocessError', 'AssertionError', 'ValueError',
                'KeyError', 'TypeError', 'IndexError', 'SystemExit', 'other'}
    cleanup_labels = {'owned bind unmount', 'owned bind target cleanup', 'image unmount',
                      'loop detach', 'loop detach confirmation', 'image target cleanup'}

    def finite(value, allowed):
        return value if type(value) is str and value in allowed else None

    failures = state.get('cleanup_failures', [])
    failures = failures[:64] if type(failures) is list else []
    return dict(operation=finite(state.get('operation'), operations),
                last_scoped_command=finite(state.get('last_scoped_command'), SCOPED_COMMAND_LABELS),
                body_completed=state.get('body_completed') is True,
                body_failure_type=finite(state.get('body_failure_type'), families),
                matrix_failure=sanitized_matrix_failure(state.get('matrix_failure')),
                cleanup_failures=list(dict.fromkeys(label for label in failures
                                                   if finite(label, cleanup_labels) is not None)))


def minimal_environment(extra=None):
    environment = dict(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                       HOME='/nonexistent', LANG='C.UTF-8', LC_ALL='C.UTF-8',
                       PYTHONDONTWRITEBYTECODE='1', GIT_TERMINAL_PROMPT='0',
                       GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
    if extra:
        environment.update(extra)
    for key in ('JAC_DB_URL', 'JAC_DEV_SOURCE', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
                'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'RUNNER_TOKEN', 'AWS_ACCESS_KEY_ID',
                'AWS_SECRET_ACCESS_KEY', 'AZURE_CLIENT_SECRET', 'NPM_TOKEN', 'PIP_INDEX_URL',
                'PIP_EXTRA_INDEX_URL', 'OPENAI_API_KEY', 'RESEND_API_KEY', 'SMTP_HOST', 'SMTP_URL'):
        environment.pop(key, None)
    return environment


def is_mount(path):
    try:
        return Path(path).is_mount()
    except NotImplementedError:
        return False


def private_write(path, value):
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def set_private(path):
    path = Path(path)
    path.chmod(0o700)
    return path


def stop_process(process, first_signal=signal.SIGTERM):
    if process is None:
        return
    try:
        os.killpg(process.pid, first_signal)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=20)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass


def signal_handler(signum, _frame):
    stop_process(ACTIVE, signal.SIGINT)
    raise SystemExit(128 + signum)


def run_command(label, command, *, cwd=None, env=None, timeout=60, log=None,
                capture=False, first_signal=signal.SIGTERM):
    global ACTIVE
    if log is None:
        log = PRIVATE_LOG_DIR / (label.replace(' ', '-') + '.log')
    log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    stream = subprocess.PIPE if capture else log.open('ab')
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        ACTIVE = process
        started = time.monotonic()
        while process.poll() is None and time.monotonic() - started < timeout:
            time.sleep(.2)
        if process.poll() is None:
            stop_process(process, first_signal)
            fail(label + ' timeout')
        if process.returncode != 0:
            fail(label + ' failed')
        if capture:
            output = process.stdout.read()
            process.stdout.close()
            return output.decode('utf-8', 'replace').strip()
        return ''
    except (OSError, subprocess.SubprocessError):
        fail(label + ' unavailable')
    finally:
        if capture and stream is not subprocess.PIPE:
            stream.close()
        elif not capture:
            stream.close()
        ACTIVE = None


def host_guard():
    if os.geteuid() != 0:
        fail('root provisioning guard')
    release = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            release[key] = value.strip('"')
    if release.get('ID') != 'ubuntu' or release.get('VERSION_ID') != '24.04':
        fail('Ubuntu 24.04 guard')
    kernel = Path('/proc/version').read_text().lower()
    if os.environ.get('WSL_INTEROP') or 'microsoft' in kernel or 'wsl' in kernel:
        fail('non-WSL guard')
    if Path('/proc/1/comm').read_text().strip() != 'systemd':
        fail('systemd PID 1 guard')
    if not Path('/sys/fs/cgroup/cgroup.controllers').is_file():
        fail('cgroup v2 guard')
    memtotal = int(Path('/proc/meminfo').read_text().split('MemTotal:', 1)[1].split()[0]) * 1024
    if memtotal < MIN_HOST_MEMORY:
        fail('host memory guard')
    if os.environ.get('JAC_DB_URL') or os.environ.get('JAC_DEV_SOURCE'):
        fail('external source/database environment guard')
    if any(os.environ.get(key) for key in ('GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN',
                                           'RUNNER_TOKEN', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
                                           'AZURE_CLIENT_SECRET', 'NPM_TOKEN', 'PIP_INDEX_URL', 'PIP_EXTRA_INDEX_URL')):
        fail('credential environment guard')
    if shutil.disk_usage('/').free < 10 * 1024 ** 3:
        fail('root disk guard')


def manifest_inputs():
    try:
        if digest(SOURCE_MANIFEST_PATH) != SOURCE_MANIFEST_SHA or digest(ADAPTER_MANIFEST_PATH) != ADAPTER_MANIFEST_SHA:
            fail('public manifest byte identity')
        pins = json.loads(PINS_PATH.read_text())
        manifest = json.loads(SOURCE_MANIFEST_PATH.read_text())
        adapters = json.loads(ADAPTER_MANIFEST_PATH.read_text())
    except (OSError, ValueError):
        fail('public input manifest format')
    if manifest.get('status') != 'staged_not_executed' or len(manifest.get('files', {})) != 34:
        fail('public source manifest identity')
    if adapters.get('status') != 'staged_not_executed' or set(adapters.get('files', {})) != set(ADAPTER_PATHS):
        fail('v9 adapter manifest identity')
    if {relative for relative in manifest.get('files', {}) if relative.startswith('source/jac/')} != set(SOURCE_JAC_PATHS):
        fail('public Jac source path inventory')
    if manifest.get('base') != JAC_BASE or manifest.get('patch_sha256') != PATCH_AFTER:
        fail('public source base and patch identity')
    if pins.get('application_revision') != APP_REVISION or pins.get('application_digest') != APP_SHA:
        fail('public application pin identity')
    return pins, manifest, adapters


def verify_staged_file(relative, metadata):
    path = INPUTS / relative
    pure = PurePosixPath(relative)
    if pure.is_absolute() or '..' in pure.parts or path.is_symlink() or not path.is_file():
        fail('staged public path guard')
    if path.stat().st_size != metadata['bytes'] or digest(path) != metadata['sha256']:
        fail('staged public byte hash guard')
    return path


def copy_staged_inputs(task, manifest, adapters):
    for relative, metadata in manifest['files'].items():
        source = verify_staged_file(relative, metadata)
        destination = task / Path(relative)
        if destination.exists() or destination.is_symlink():
            fail('fresh staged destination guard')
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    for relative, metadata in adapters['files'].items():
        source = verify_staged_file(relative, metadata)
        destination = task / Path(relative)
        if destination.exists() or destination.is_symlink():
            fail('fresh adapter destination guard')
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(0o755)


def app_digest(root):
    paths = [root / '.jac-version', root / 'jac.toml']
    for name in ('services', 'client'):
        paths.extend(p for p in (root / name).rglob('*') if p.is_file() and
                     p.suffix in ('.jac', '.py', '.mjs', '.js', '.jsx', '.css') and
                     not p.name.endswith(('.test.jac', '.test.mjs', '.test.js')))
    paths.extend(p for p in root.glob('*.jac') if p.is_file() and not p.name.endswith('.test.jac'))
    paths.extend(p for p in (root / 'data').rglob('*') if p.is_file())
    result = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.relative_to(root).as_posix()):
        result.update(path.relative_to(root).as_posix().encode() + b'\0' +
                     path.read_bytes().replace(b'\r\n', b'\n') + b'\0')
    return result.hexdigest()


def copy_app_tree(source, destination):
    for name in ('main.jac', 'theme.jac', 'jac.toml', '.jac-version'):
        source_file = source / name
        if not source_file.is_file() or source_file.is_symlink():
            fail('application source entry guard')
        shutil.copyfile(source_file, destination / name)
    for name in ('services', 'client', 'data', 'scripts', 'tests'):
        source_dir = source / name
        if not source_dir.is_dir() or source_dir.is_symlink():
            fail('application source directory guard')
        if any(path.is_symlink() for path in source_dir.rglob('*')):
            fail('application source symlink guard')
        shutil.copytree(source_dir, destination / name,
                        ignore=shutil.ignore_patterns('.env*', '.jac', '.git', '__pycache__', 'node_modules', '.venv'))
    brand = source / 'assets' / 'brand'
    if not brand.is_dir() or brand.is_symlink():
        fail('application brand directory guard')
    if any(path.is_symlink() for path in brand.rglob('*')):
        fail('application brand symlink guard')
    shutil.copytree(brand, destination / 'assets' / 'brand')


def prepare_task(task, manifest, adapters, log):
    c_root = task.parents[5]
    if c_root != Path('/mnt/c'):
        fail('canonical task parent guard')
    if c_root.exists() and c_root.is_symlink():
        fail('canonical local root symlink guard')
    c_root.mkdir(mode=0o755, parents=True, exist_ok=True)
    for ancestor in task.parents:
        if ancestor == Path('/mnt/c').parent:
            break
        if ancestor.exists() and ancestor.is_symlink():
            fail('canonical task ancestor symlink guard')
        if ancestor.exists() and (ancestor.stat().st_uid != 0 or ancestor.stat().st_mode & 0o022 or
                                 ancestor.stat().st_mode & 0o777 not in (0o700, 0o750, 0o755)):
            fail('canonical task ancestor ownership guard')
    for ancestor in (c_root, Path('/mnt')):
        if ancestor.exists() and (ancestor.is_symlink() or ancestor.stat().st_uid != 0 or ancestor.stat().st_mode & 0o022 or
                                  ancestor.stat().st_mode & 0o777 not in (0o700, 0o750, 0o755)):
            fail('canonical task root ownership guard')
    if c_root.stat().st_dev != Path('/').stat().st_dev:
        fail('canonical local root device guard')
    if task.exists() or task.is_symlink():
        fail('fresh canonical task guard')
    task.mkdir(mode=0o700, parents=True)
    (task / 'work').mkdir(mode=0o700)
    os.chown(task, 65534, 65534)
    os.chown(task / 'work', 65534, 65534)
    app = task / 'work' / 'm-local'
    environment = minimal_environment()
    scoped_command('public application checkout', ['git', 'clone', '--quiet', APP_REPOSITORY, str(app)],
                   cwd=task, environment=environment, workspace=Path(log).parent, timeout=900)
    scoped_command('public application revision', ['git', '-C', str(app), 'checkout', '--quiet', '--detach', APP_REVISION],
                   cwd=task, environment=environment, workspace=Path(log).parent, timeout=180)
    revision_scope = scoped_command('application revision read', ['git', '-C', str(app), 'rev-parse', 'HEAD'],
                                    cwd=task, environment=environment, workspace=Path(log).parent, timeout=30)
    revision = Path(revision_scope['log_path']).read_text(errors='replace').strip()
    if revision != APP_REVISION or app_digest(app) != APP_SHA:
        fail('public application identity guard')
    copy_staged_inputs(task, manifest, adapters)
    return app


def git_diff_bytes(fork, workspace):
    result = scoped_command('source fork diff ' + fork.name, ['/usr/bin/git', 'diff', '--binary'], cwd=fork,
                            environment=minimal_environment(), workspace=workspace, timeout=60)
    try:
        return Path(result['log_path']).read_bytes()
    except (OSError, ValueError):
        fail('source fork diff read')


def chown_tree(root):
    root = Path(root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink():
                fail('source fork symlink guard')
            os.chown(path, 65534, 65534)
    os.chown(root, 65534, 65534)


def resource_helper():
    global RESOURCE_HELPER
    if RESOURCE_HELPER is None:
        RESOURCE_HELPER = runpy.run_path(str(HELPER))
        if Path(RESOURCE_HELPER['e_root']).resolve() != E_ROOT.resolve():
            fail('resource helper storage binding')
    return RESOURCE_HELPER


def scoped_command(label, command, *, cwd, environment, workspace, timeout=900):
    global ACTIVE
    FAILURE_DIAGNOSTICS['last_scoped_command'] = label
    helper = resource_helper()
    mountpoint = helper['mounted_empty']('m-local-runtime-materialize-v7-')
    OWNED_MOUNTS.add(mountpoint)
    stream = None
    process = None
    state = None
    stopped = False
    try:
        log_path = workspace / (label.replace(' ', '-') + '-scope.log')
        log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        stream = log_path.open('ab')
        process, state = helper['launch_scope'](mountpoint, list(command), Path(cwd), dict(environment), stream,
                                               high=MEMORY_HIGH, maximum=MEMORY_MAX)
        ACTIVE = process
        started = time.monotonic()
        while process.poll() is None:
            helper['sample_scope'](state)
            reason = helper['scope_guard'](state, time.monotonic() - started, timeout)
            if reason:
                fail(label + ' scope ' + reason)
            time.sleep(.2)
        process.wait()
        helper['sample_scope'](state)
        reason = helper['scope_guard'](state, time.monotonic() - started, timeout)
        if reason:
            fail(label + ' scope ' + reason)
        if process.returncode != 0:
            fail(label + ' failed')
        cleanup = helper['stop_scope'](state, process)
        stopped = True
        if not cleanup.get('cgroup_empty') or not cleanup.get('launcher_stopped'):
            fail(label + ' scope cleanup')
        return dict(controls_confirmed_before_workload=state.get('controls_confirmed_before_workload'),
                    requested_limits=state.get('requested_limits'), cleanup=cleanup,
                    elapsed_seconds=round(time.monotonic() - started, 3), log_path=str(log_path))
    except BaseException:
        if state is not None and process is not None and not stopped:
            helper['stop_scope'](state, process)
            stopped = True
        raise
    finally:
        ACTIVE = None
        if stream is not None:
            stream.close()
        try:
            if is_mount(mountpoint):
                result = subprocess.run(['/usr/bin/umount', str(mountpoint)], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                if result.returncode or is_mount(mountpoint):
                    fail(label + ' scope bind cleanup')
            if mountpoint.exists() and not mountpoint.is_symlink():
                mountpoint.rmdir()
            backing = E_ROOT / mountpoint.name
            if backing.exists() and not backing.is_symlink():
                backing.rmdir()
            OWNED_MOUNTS.discard(mountpoint)
        except (OSError, subprocess.SubprocessError):
            fail(label + ' scope bind cleanup')


def prepare_forks(workspace, manifest, log):
    parent = E_ROOT / 'source-forks-v7'
    parent.mkdir(mode=0o700)
    os.chown(parent, 65534, 65534)
    base = parent / 'jac-base'
    old = parent / 'identity-type-source-old-v7'
    current = parent / 'identity-type-source-v3-v7'
    environment = minimal_environment()
    scoped_command('public Jac clone', ['git', 'clone', '--quiet', JAC_REPOSITORY, str(base)],
                   cwd=parent, environment=environment, workspace=workspace, timeout=1200)
    scoped_command('public Jac base checkout', ['git', '-C', str(base), 'checkout', '--quiet', '--detach', JAC_BASE],
                   cwd=parent, environment=environment, workspace=workspace, timeout=180)
    revision_scope = scoped_command('Jac base revision read', ['git', '-C', str(base), 'rev-parse', 'HEAD'],
                                    cwd=parent, environment=environment, workspace=workspace, timeout=30)
    revision = Path(revision_scope['log_path']).read_text(errors='replace').strip()
    if revision != JAC_BASE:
        fail('Jac base revision guard')
    scoped_command('old source fork clone', ['git', 'clone', '--quiet', '--no-local', str(base), str(old)],
                   cwd=parent, environment=environment, workspace=workspace, timeout=600)
    scoped_command('current source fork clone', ['git', 'clone', '--quiet', '--no-local', str(base), str(current)],
                   cwd=parent, environment=environment, workspace=workspace, timeout=600)
    for label, fork in [('old', old), ('current', current)]:
        scoped_command(label + ' source diff format', ['git', '-C', str(fork), 'config', 'core.abbrev', '7'],
                       cwd=parent, environment=environment, workspace=workspace, timeout=30)
    old_patch = CANONICAL_TASK / 'outputs/identity-bootstrap-source-v2/source-inputs/runtime.patch'
    current_patch = CANONICAL_TASK / 'work/identity-runtime-v3/runtime.patch'
    if digest(old_patch) != PATCH_BEFORE or digest(current_patch) != PATCH_AFTER:
        fail('source patch identity guard')
    scoped_command('old patch apply', ['git', '-C', str(old), 'apply', '--binary', str(old_patch)],
                   cwd=parent, environment=environment, workspace=workspace, timeout=180)
    scoped_command('current patch apply', ['git', '-C', str(current), 'apply', '--binary', str(current_patch)],
                   cwd=parent, environment=environment, workspace=workspace, timeout=180)
    chown_tree(old)
    chown_tree(current)
    for label, fork, expected in [('old', old, PATCH_BEFORE), ('current', current, PATCH_AFTER)]:
        patch = git_diff_bytes(fork, workspace)
        actual = hashlib.sha256(patch).hexdigest()
        if actual != expected:
            widths = sorted({len(value) for line in patch.splitlines() if line.startswith(b'index ')
                             for value in line.split()[1].split(b'..')})
            fail('source fork patch diff guard ' + label + ' sha256=' + actual + ' bytes=' + str(len(patch)) +
                 ' index_widths=' + ','.join(str(value) for value in widths))
    for relative, metadata in manifest['files'].items():
        if not relative.startswith('source/jac/'):
            continue
        staged = verify_staged_file(relative, metadata)
        target = current / Path(relative[len('source/'):])
        if digest(target) != metadata['sha256'] or target.stat().st_size != metadata['bytes'] or target.read_bytes() != staged.read_bytes():
            fail('current Jac source byte match guard')
    return old, current


def inventory(root):
    values = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file():
            if path.is_symlink():
                fail('typeshed symlink guard')
            continue
        relative = path.relative_to(root).as_posix()
        values[relative] = digest(path)
    return values


def materialize_shim_typeshed(current, old, official, workspace):
    cache = official / 'cache'
    cache.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chown(cache, 65534, 65534)
    cache.chmod(0o755)
    environment = dict(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', HOME='/nonexistent',
                       LANG='C.UTF-8', JAC_CACHE_HOME=str(cache), JAC_NO_DEV_SOURCE='1',
                       PYTHONDONTWRITEBYTECODE='1', NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1')
    for key in ('JAC_DB_URL', 'JAC_DEV_SOURCE', 'OPENAI_API_KEY', 'RESEND_API_KEY', 'SMTP_HOST', 'SMTP_URL'):
        environment.pop(key, None)
    jac = official / 'runtime/jac'
    scoped_command('official Jac version', [str(jac), '--version'], cwd=cache, environment=environment,
                   workspace=workspace, timeout=60)
    scoped_command('official Jac help', [str(jac), '--help'], cwd=cache, environment=environment,
                   workspace=workspace, timeout=60)
    source = cache / 'source-materialize.jac'
    if source.exists() or source.is_symlink():
        fail('fresh Jac materialization source guard')
    source.write_text('with entry { print("runtime-proof"); }\n')
    source.chmod(0o644)
    os.chown(source, 65534, 65534)
    sites = []
    for site in cache.rglob('site'):
        if site.is_symlink() or not site.is_dir():
            continue
        shim = site / 'jaclang/compiler/backends/native/llvm/libjacllvm.so'
        typeshed = site / 'jaclang/vendor/typeshed'
        if shim.is_file() and not shim.is_symlink() and digest(shim) == SHIM_SHA and typeshed.is_dir() and not typeshed.is_symlink():
            sites.append((site, shim, typeshed))
    if not sites:
        scoped_command('official Jac cache materialization', [str(jac), 'run', source.name], cwd=cache,
                       environment=environment, workspace=workspace, timeout=120)
        for site in cache.rglob('site'):
            if site.is_symlink() or not site.is_dir():
                continue
            shim = site / 'jaclang/compiler/backends/native/llvm/libjacllvm.so'
            typeshed = site / 'jaclang/vendor/typeshed'
            if shim.is_file() and not shim.is_symlink() and digest(shim) == SHIM_SHA and typeshed.is_dir() and not typeshed.is_symlink():
                sites.append((site, shim, typeshed))
    if len(sites) != 1:
        fail('fresh official cache site identity guard')
    site, shim, official_typeshed = sites[0]
    type_inventory = inventory(official_typeshed)
    if len(type_inventory) != 749 or hashlib.sha256(json.dumps(type_inventory, sort_keys=True).encode()).hexdigest() != TYPESHED_SHA:
        fail('typeshed inventory guard')
    if not site.resolve().is_relative_to(cache.resolve()):
        fail('official cache site path guard')
    for target in (current, old):
        shim_destination = target / 'jac/jaclang/compiler/backends/native/llvm/libjacllvm.so'
        shim_destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if shim_destination.exists() or shim_destination.is_symlink():
            if shim_destination.is_symlink() or not shim_destination.is_file() or digest(shim_destination) != SHIM_SHA:
                fail('fork shim identity guard')
        else:
            shutil.copyfile(shim, shim_destination)
        destination = target / 'jac/jaclang/vendor/typeshed'
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_dir():
                fail('fork typeshed identity guard')
            if any(type_inventory.get(name) != value for name, value in inventory(destination).items()):
                fail('fork typeshed identity guard')
        shutil.copytree(official_typeshed, destination, symlinks=False, dirs_exist_ok=True)
    if (digest(shim) != SHIM_SHA or inventory(official_typeshed) != type_inventory or
            digest(current / 'jac/jaclang/compiler/backends/native/llvm/libjacllvm.so') != SHIM_SHA or
            digest(old / 'jac/jaclang/compiler/backends/native/llvm/libjacllvm.so') != SHIM_SHA or
            inventory(current / 'jac/jaclang/vendor/typeshed') != type_inventory or
            inventory(old / 'jac/jaclang/vendor/typeshed') != type_inventory):
        fail('official shim/typeshed copy guard')
    return dict(site_relative=site.relative_to(cache).as_posix(), typeshed_files=len(type_inventory),
                typeshed_inventory_sha256=hashlib.sha256(json.dumps(type_inventory, sort_keys=True).encode()).hexdigest(),
                shim_sha256=digest(shim))


def safe_extract_jar(jar, target):
    extracted = target.parent / 'postgres-jar-extracted-v7'
    if extracted.exists() or extracted.is_symlink():
        fail('fresh PostgreSQL extraction guard')
    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    extracted.mkdir(mode=0o700)
    links = []
    txz_payloads = []
    with zipfile.ZipFile(jar) as archive:
        for info in archive.infolist():
            name = info.filename.replace('\\', '/')
            pure = PurePosixPath(name)
            if pure.is_absolute() or not name or '..' in pure.parts:
                fail('PostgreSQL archive escape guard')
            destination = extracted.joinpath(*pure.parts)
            if destination.exists() or destination.is_symlink():
                fail('PostgreSQL archive duplicate guard')
            mode = (info.external_attr >> 16) & 0o170000
            if mode in (stat.S_IFBLK, stat.S_IFCHR, stat.S_IFIFO, stat.S_IFSOCK):
                fail('PostgreSQL archive device guard')
            if name.endswith('/') or mode == stat.S_IFDIR:
                destination.mkdir(mode=0o755, parents=True, exist_ok=True)
            elif mode == stat.S_IFLNK:
                links.append((destination, archive.read(info).decode('utf-8')))
            else:
                destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                payload = archive.read(info)
                with destination.open('xb') as stream:
                    stream.write(payload)
                destination.chmod(0o755 if mode & 0o111 else 0o644)
                if name.endswith('.txz'):
                    txz_payloads.append(payload)
    if len(txz_payloads) != 1:
        fail('PostgreSQL txz payload guard')
    for destination, link in links:
        if not link or Path(link).is_absolute() or '\\' in link:
            fail('PostgreSQL symlink guard')
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        destination.symlink_to(link)
    tar_root = extracted / 'postgres-txz-v7'
    tar_root.mkdir(mode=0o700)
    tar_links = []
    try:
        with tarfile.open(fileobj=io.BytesIO(txz_payloads[0]), mode='r:xz') as archive:
            for member in archive.getmembers():
                pure = PurePosixPath(member.name.replace('\\', '/'))
                parts = tuple(part for part in pure.parts if part not in ('', '.'))
                if pure.is_absolute() or not parts or '..' in parts:
                    fail('PostgreSQL txz escape guard')
                destination = tar_root.joinpath(*parts)
                if destination.exists() or destination.is_symlink():
                    fail('PostgreSQL txz duplicate guard')
                if member.isdir():
                    destination.mkdir(mode=0o755, parents=True, exist_ok=True)
                elif member.issym():
                    tar_links.append((destination, member.linkname))
                elif member.isreg():
                    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                    parent = destination.parent
                    while parent != tar_root:
                        if parent.is_symlink():
                            fail('PostgreSQL txz parent symlink guard')
                        parent = parent.parent
                    source = archive.extractfile(member)
                    if source is None:
                        fail('PostgreSQL txz file guard')
                    with destination.open('xb') as stream:
                        shutil.copyfileobj(source, stream)
                    destination.chmod(0o755 if member.mode & 0o111 else 0o644)
                else:
                    fail('PostgreSQL txz device guard')
    except (tarfile.TarError, OSError, UnicodeError):
        fail('PostgreSQL txz format guard')
    for destination, link in tar_links:
        if not link or Path(link).is_absolute() or '\\' in link:
            fail('PostgreSQL txz symlink guard')
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        parent = destination.parent
        while parent != tar_root:
            if parent.is_symlink():
                fail('PostgreSQL txz parent symlink guard')
            parent = parent.parent
        destination.symlink_to(link)
    root = extracted.resolve()
    for path in extracted.rglob('*'):
        if path.is_symlink():
            target_path = (path.parent / os.readlink(path)).resolve()
            if not target_path.is_relative_to(root) or not target_path.is_file():
                fail('PostgreSQL symlink target guard')
    candidates = [path.parent.parent for path in extracted.rglob('bin/postgres')
                  if path.is_file() and not path.is_symlink()]
    if len(candidates) != 1:
        fail('PostgreSQL distribution root guard')
    candidate = candidates[0]
    if target.exists() or target.is_symlink():
        fail('fresh PostgreSQL target guard')
    shutil.copytree(candidate, target, symlinks=True)
    target.chmod(0o755)
    return target


def pg_inventory(root):
    values = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            target = os.readlink(path)
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
                fail('PostgreSQL inventory symlink guard')
            values[path.relative_to(root).as_posix()] = 'symlink:' + target + ':' + digest(resolved)
        elif path.is_file():
            mode = path.stat().st_mode
            if not stat.S_ISREG(mode):
                fail('PostgreSQL inventory regular-file guard')
            values[path.relative_to(root).as_posix()] = digest(path)
        elif not path.is_dir():
            fail('PostgreSQL inventory device guard')
    return values


def pinned_download(name, entry, destination, workspace):
    code = (
        "import importlib.util,json,sys\ntry:\n"
        " spec=importlib.util.spec_from_file_location('download_helper',sys.argv[1]);"
        "module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);"
        "result=module.download(json.loads(sys.argv[2]),sys.argv[3]);"
        "print(json.dumps({'sha256':result['sha256'],'bytes':result['bytes']}))\n"
        "except Exception as error:\n"
        " print(json.dumps({'failure_type':type(error).__name__,'http_status':getattr(error,'code',None)}));"
        "sys.exit(1)\n"
    )
    try:
        result = scoped_command('pinned download ' + name,
                                [sys.executable, '-B', '-c', code, str(destination.parent / DOWNLOAD_HELPER.name),
                                 json.dumps(entry, separators=(',', ':')), str(destination)],
                                cwd=destination.parent, environment=minimal_environment(),
                                workspace=workspace, timeout=180)
    except RuntimeError:
        try:
            error = json.loads((workspace / ('pinned-download-' + name + '-scope.log')).read_bytes().splitlines()[-1])
        except (OSError, ValueError, IndexError):
            raise RuntimeError('pinned download ' + name + ' failed') from None
        if isinstance(error, dict) and error.get('failure_type') in ('HTTPError', 'URLError', 'PermissionError', 'FileNotFoundError',
                                         'TimeoutError', 'RuntimeError', 'OSError'):
            status = error.get('http_status')
            suffix = ' HTTP ' + str(status) if type(status) is int and 100 <= status <= 599 else ''
            fail('pinned download ' + name + ' ' + error['failure_type'] + suffix)
        raise
    lines = Path(result['log_path']).read_bytes().splitlines()
    if len(lines) != 1:
        fail('pinned download receipt format')
    try:
        fetched = json.loads(lines[0])
    except (ValueError, TypeError):
        fail('pinned download receipt format')
    if fetched.get('bytes') != entry['bytes'] or fetched.get('sha256') != entry['sha256']:
        fail('pinned download byte identity guard')
    return fetched


def materialize_runtime(workspace, pins, log):
    runtime = E_ROOT / 'official-runtime-v7'
    if runtime.exists() or runtime.is_symlink():
        fail('fresh official runtime guard')
    runtime.mkdir(mode=0o755)
    (runtime / 'runtime').mkdir(mode=0o755)
    downloads = E_ROOT / 'pinned-downloads-v7'
    if downloads.exists() or downloads.is_symlink():
        fail('fresh pinned download directory guard')
    downloads.mkdir(mode=0o700)
    os.chown(downloads, 65534, 65534)
    helper = downloads / DOWNLOAD_HELPER.name
    shutil.copyfile(DOWNLOAD_HELPER, helper)
    os.chown(helper, 65534, 65534)
    helper.chmod(0o400)
    if digest(helper) != digest(DOWNLOAD_HELPER):
        fail('private download helper byte identity')
    fetched = {}
    for name in ('jac', 'jacpython', 'postgres'):
        destination = downloads / (name + ('.jar' if name == 'postgres' else '.bin'))
        fetched[name] = pinned_download(name, pins['downloads'][name], destination, Path(log).parent)
    for name in ('jac', 'jacpython'):
        target = runtime / 'runtime' / name
        shutil.copyfile(downloads / (name + '.bin'), target)
        target.chmod(0o755)
        expected = pins['downloads'][name]
        if target.stat().st_size != expected['bytes'] or digest(target) != expected['sha256']:
            fail('official runtime byte identity guard')
    pg = safe_extract_jar(downloads / 'postgres.jar', runtime / 'cache/pg/dist/linux-amd64-18.6.0')
    postgres = pg / 'bin/postgres'
    if not postgres.is_file() or postgres.is_symlink():
        fail('PostgreSQL binary guard')
    cache = runtime / 'cache'
    os.chown(cache, 65534, 65534)
    cache.chmod(0o755)
    environment = dict(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', HOME='/nonexistent',
                       LANG='C.UTF-8', JAC_NO_DEV_SOURCE='1', PYTHONDONTWRITEBYTECODE='1',
                       LD_LIBRARY_PATH=str(pg / 'lib'))
    version_scope = scoped_command('PostgreSQL version', [str(postgres), '--version'], cwd=pg,
                                   environment=environment, workspace=Path(log).parent, timeout=30)
    version_log = Path(version_scope['log_path'])
    version = version_log.read_text(errors='replace').strip()
    if '18.6' not in version:
        fail('PostgreSQL version identity guard')
    pg_files = pg_inventory(pg)
    if not pg_files or 'bin/postgres' not in pg_files or 'bin/pg_ctl' not in pg_files:
        fail('PostgreSQL inventory guard')
    return runtime, {'downloads': fetched, 'postgres_version': version, 'postgres_inventory_sha256': hashlib.sha256(json.dumps(pg_files, sort_keys=True).encode()).hexdigest()}


def dependency_interpreter_provenance(runtime, cache, resolved):
    jac = runtime / 'runtime/jac'
    if jac.is_symlink() or not jac.is_file() or digest(jac) != JAC_SHA:
        fail('bundled dependency interpreter binary')
    end = jac.stat().st_size
    with jac.open('rb') as stream:
        def trailer_at(offset):
            if offset < 80:
                fail('bundled dependency interpreter trailer')
            stream.seek(offset - 80)
            raw = stream.read(80)
            if len(raw) != 80 or any(value not in b'0123456789abcdef' for value in raw[16:]):
                fail('bundled dependency interpreter trailer')
            length = int.from_bytes(raw[8:16], 'little')
            if not 0 < length <= offset - 80:
                fail('bundled dependency interpreter trailer')
            return raw, length

        trailer, length = trailer_at(end)
        if trailer[:8] == b'JABOVL01':
            end -= 80 + length
            trailer, length = trailer_at(end)
        if trailer[:8] != b'JACBIN01':
            fail('bundled dependency interpreter trailer')
    payload_hash = trailer[16:].decode('ascii')
    extracted = cache / 'rt' / payload_hash[:16]
    expected = extracted / 'python/bin/python3.14'
    if resolved != expected:
        fail('bundled dependency interpreter target')
    for directory in [cache, cache / 'rt', extracted, extracted / 'python', expected.parent]:
        if (directory.is_symlink() or not directory.is_dir() or directory.resolve() != directory or
                directory.stat().st_uid != 65534 or directory.stat().st_mode & 0o022 or
                (directory == cache and directory.stat().st_mode & 0o777 != 0o700)):
            fail('bundled dependency interpreter directories')
    marker = extracted / '.ok'
    if (marker.is_symlink() or not marker.is_file() or marker.stat().st_size != 0 or
            marker.stat().st_uid != 65534 or marker.stat().st_mode & 0o133):
        fail('bundled dependency interpreter marker')
    if (expected.is_symlink() or not expected.is_file() or not expected.stat().st_mode & 0o111 or
            expected.stat().st_uid != 65534 or expected.stat().st_mode & 0o022 or
            expected.stat().st_size > 128 * 1024 ** 2 or digest(expected) != BUNDLED_PYTHON_SHA):
        fail('bundled dependency interpreter fingerprint')
    return dict(interpreter_target_class='bundled_runtime_cache', interpreter_target_relative=expected.relative_to(cache).as_posix(),
                interpreter_target_sha256=BUNDLED_PYTHON_SHA, runtime_payload_sha256=payload_hash,
                runtime_binary_sha256=JAC_SHA, completion_marker=True)


def dependency_priming(app, runtime, workspace, log):
    candidate = E_ROOT / 'dependency-candidate-v7'
    if candidate.exists() or candidate.is_symlink():
        fail('fresh dependency candidate guard')
    candidate.mkdir(mode=0o700)
    copy_app_tree(app, candidate)
    chown_tree(candidate)
    cache = E_ROOT / 'dependency-cache-v7'
    if cache.exists() or cache.is_symlink():
        fail('fresh dependency cache guard')
    cache.mkdir(mode=0o700)
    os.chown(cache, 65534, 65534)
    environment = dict(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', HOME='/nonexistent',
                       LANG='C.UTF-8', JAC_CACHE_HOME=str(cache), JAC_NO_DEV_SOURCE='1',
                       PYTHONDONTWRITEBYTECODE='1', NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1')
    for key in ('JAC_DB_URL', 'JAC_DEV_SOURCE', 'OPENAI_API_KEY', 'RESEND_API_KEY', 'SMTP_HOST', 'SMTP_URL'):
        environment.pop(key, None)
    scoped_command('declared dependency priming', [str(runtime / 'runtime/jac'), 'install', '--no-npm'],
                   cwd=candidate, environment=environment, workspace=Path(log).parent, timeout=900)
    venv = candidate / '.jac/venv'
    bin_dir = venv / 'bin'
    if venv.is_symlink() or not venv.is_dir() or bin_dir.is_symlink() or not bin_dir.is_dir() or \
            (venv / 'pyvenv.cfg').is_symlink() or not (venv / 'pyvenv.cfg').is_file():
        fail('declared dependency environment guard')
    python_candidates = sorted(bin_dir.glob('python*'))
    python = next((path for path in python_candidates if path.is_file() and (path.stat().st_mode & 0o111)), None)
    if python is None:
        fail('declared dependency interpreter guard')
    resolved = python.resolve()
    if not resolved.is_file() or not (resolved.stat().st_mode & 0o111):
        fail('declared dependency interpreter target guard')
    if not resolved.is_relative_to(cache.resolve()):
        origin = next((name for name, root in [('official-runtime', runtime), ('dependency-cache', cache)]
                       if resolved.is_relative_to(root.resolve())), 'outside-approved-roots')
        label = 'declared dependency target ' + origin
        if origin != 'outside-approved-roots':
            label += ' sha256=' + digest(resolved)
        fail(label)
    interpreter = dependency_interpreter_provenance(runtime, cache, resolved)
    pillow = scoped_command('Pillow dependency guard', [str(python), '-c',
                            'from PIL import Image; Image.new("RGB", (1, 1))'], cwd=candidate,
                            environment=environment, workspace=Path(log).parent, timeout=60)
    pillow.pop('log_path', None)
    return dict(status='passed', install='jac install --no-npm', pillow_import=True, cache_private=True,
                venv_layout='candidate/.jac/venv with pyvenv.cfg and discovered executable',
                interpreter_relative=python.relative_to(candidate).as_posix(), interpreter=interpreter, pillow_scope=pillow)


def mounts():
    try:
        output = subprocess.check_output(['/usr/bin/findmnt', '--list', '--noheadings', '--output', 'TARGET'], text=True,
                                         stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        fail('mount inventory probe')
    return {Path(line.strip()) for line in output.splitlines() if line.strip()}


def assert_no_new_mounts(before, after, label):
    if after - before:
        fail(label + ' unidentified mount cleanup')


def capture_matrix_failure(before):
    try:
        new = mounts() - before
        if len(new) != 1:
            return None
        directory = next(iter(new))
        backing = E_ROOT / directory.name
        if (directory.parent != Path('/var/tmp') or not directory.name.startswith('m-local-kali-runtime-regressions-v3-') or
                Path('/var/tmp').is_symlink() or E_ROOT.is_symlink() or not is_mount(E_ROOT) or
                E_ROOT.resolve() != E_ROOT or directory.is_symlink() or backing.is_symlink() or
                directory.resolve() != directory or backing.resolve() != backing or not is_mount(directory)):
            return None
        root, mounted, original = E_ROOT.stat(), directory.stat(), backing.stat()
        if (any(item.st_uid != 65534 or item.st_mode & 0o777 != 0o700 for item in (root, mounted, original)) or
                mounted.st_dev != root.st_dev or
                (mounted.st_dev, mounted.st_ino) != (original.st_dev, original.st_ino)):
            return None
        result = directory / 'result.json'
        metadata = result.lstat()
        nofollow = getattr(os, 'O_NOFOLLOW', None)
        if (nofollow is None or not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or
                metadata.st_mode & 0o777 != 0o600 or metadata.st_nlink != 1 or
                not 0 < metadata.st_size <= 1024 ** 2):
            return None
        with os.fdopen(os.open(result, os.O_RDONLY | nofollow), 'rb') as stream:
            opened = os.fstat(stream.fileno())
            fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_uid', 'st_nlink')
            if any(getattr(opened, key) != getattr(metadata, key) for key in fields):
                return None
            raw = stream.read(1024 ** 2 + 1)
            closed = os.fstat(stream.fileno())
            if len(raw) != metadata.st_size or any(getattr(closed, key) != getattr(opened, key) for key in fields):
                return None
        receipt = json.loads(raw)
        if type(receipt) is not dict:
            return None
        phases, interfaces = receipt.get('phases'), receipt.get('interface_proofs')
        if (type(phases) is not list or type(interfaces) is not list or
                not 1 <= len(phases) <= 10 or len(interfaces) > 2 or
                (interfaces and (len(phases) != 10 or any(type(row) is not dict or row.get('status') != 'passed' for row in phases)))):
            return None
        for rows, expected in ((phases, MATRIX_PHASE_NAMES[:10]), (interfaces, MATRIX_PHASE_NAMES[10:])):
            if any(type(row) is not dict or row.get('name') != expected[index] for index, row in enumerate(rows)):
                return None
        rows = phases + interfaces
        if any(row.get('status') != 'passed' for row in rows[:-1]):
            return None
        failure = sanitized_matrix_failure(rows[-1])
        return failure if failure is not None and receipt.get('status') == failure['status'] else None
    except (OSError, ValueError, TypeError, RuntimeError):
        return None


def register_stage_mounts(stage, before, child):
    prefixes = {'cold-compile': 'm-local-identity-type-compile-v7-',
                'bootstrap': 'm-local-identity-bootstrap-proof-v4-',
                'matrix': 'm-local-kali-runtime-regressions-v3-'}
    expected = {Path(child.get('workspace', '')): prefixes[stage]}
    if stage == 'cold-compile':
        phases = child.get('phases', [])
        if len(phases) != 2 or [row.get('name') for row in phases] != ['before', 'after']:
            fail('cold stage mount receipt')
        for row in phases:
            expected[Path(row.get('workspace', ''))] = 'm-local-identity-type-' + row['name'] + '-v7-'
        if len(expected) != 3:
            fail('cold stage mount identity')
    if mounts() - before != set(expected):
        fail('source ' + stage + ' unidentified mounts')
    if E_ROOT.is_symlink() or not is_mount(E_ROOT) or Path('/var/tmp').is_symlink():
        fail('source stage mount parent')
    for path, prefix in expected.items():
        backing = E_ROOT / path.name
        if (not path.is_absolute() or path.parent != Path('/var/tmp') or not path.name.startswith(prefix) or
                path.is_symlink() or backing.is_symlink() or path.resolve() != path or
                backing.resolve() != backing or not is_mount(path)):
            fail('source stage mount path')
        mounted, original = path.stat(), backing.stat()
        if (mounted.st_uid != 65534 or original.st_uid != 65534 or
                mounted.st_mode & 0o777 != 0o700 or original.st_mode & 0o777 != 0o700 or
                mounted.st_dev != E_ROOT.stat().st_dev or
                (mounted.st_dev, mounted.st_ino) != (original.st_dev, original.st_ino)):
            fail('source stage mount backing identity')
    OWNED_MOUNTS.update(expected)


def mount_image():
    global IMAGE_LOOP, MOUNT_BASELINE
    MOUNT_BASELINE = mounts()
    if not IMAGE.is_file() or IMAGE.is_symlink() or IMAGE.stat().st_size != 64 * 1024 ** 3:
        fail('fresh storage image identity guard')
    if E_ROOT.exists() or E_ROOT.is_symlink():
        fail('fresh storage mount target guard')
    E_ROOT.mkdir(mode=0o700)
    IMAGE_LOOP = Path(run_command('owned loop attach', ['/usr/sbin/losetup', '--find', '--show', str(IMAGE)],
                                 timeout=60, log=PRIVATE_LOG_DIR / 'loop-attach.log', capture=True))
    if IMAGE_LOOP.parent != Path('/dev') or not IMAGE_LOOP.name.startswith('loop'):
        fail('owned loop path guard')
    run_command('owned image mount', ['/usr/bin/mount', '-o', 'nosuid,nodev', str(IMAGE_LOOP), str(E_ROOT)],
                timeout=60, log=PRIVATE_LOG_DIR / 'image-mount.log')
    os.chown(E_ROOT, 65534, 65534)
    E_ROOT.chmod(0o700)
    fields = run_command('owned mount inspection', ['/usr/bin/findmnt', '--noheadings', '--output', 'SOURCE,FSTYPE,OPTIONS', str(E_ROOT)],
                         timeout=30, log=PRIVATE_LOG_DIR / 'mount-inspection.log', capture=True).split(None, 2)
    if len(fields) != 3 or fields[0] != str(IMAGE_LOOP) or fields[1] != 'ext4' or \
            'nosuid' not in fields[2].split(',') or 'nodev' not in fields[2].split(','):
        fail('owned mount option guard')
    if E_ROOT.stat().st_uid != 65534 or E_ROOT.stat().st_mode & 0o777 != 0o700:
        fail('owned mount ownership guard')
    MOUNT_BASELINE = mounts()


def cleanup_mounts():
    FAILURE_DIAGNOSTICS['cleanup_failures'] = []
    if IMAGE_LOOP is None and not is_mount(E_ROOT) and not E_ROOT.exists():
        return
    errors = []
    owned = sorted(OWNED_MOUNTS, key=lambda path: len(path.parts), reverse=True)
    for path in owned:
        if path == E_ROOT:
            continue
        try:
            result = subprocess.run(['/usr/bin/umount', str(path)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30) if is_mount(path) else None
        except (OSError, subprocess.SubprocessError):
            errors.append('owned bind unmount')
            continue
        if result is not None and (result.returncode or is_mount(path)):
            errors.append('owned bind unmount')
        elif path.exists() and not path.is_symlink():
            try:
                path.rmdir()
            except OSError:
                errors.append('owned bind target cleanup')
    if is_mount(E_ROOT):
        try:
            result = subprocess.run(['/usr/bin/umount', str(E_ROOT)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except (OSError, subprocess.SubprocessError):
            errors.append('image unmount')
            result = None
        if result is not None and (result.returncode or is_mount(E_ROOT)):
            errors.append('image unmount')
    if IMAGE_LOOP is not None:
        try:
            result = subprocess.run(['/usr/sbin/losetup', '--detach', str(IMAGE_LOOP)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except (OSError, subprocess.SubprocessError):
            errors.append('loop detach')
            result = None
        if result is not None and result.returncode:
            errors.append('loop detach')
        try:
            check = subprocess.run(['/usr/sbin/losetup', '--associated', str(IMAGE)], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30)
            if check.returncode != 0 or check.stdout.strip():
                errors.append('loop detach confirmation')
        except (OSError, subprocess.SubprocessError):
            errors.append('loop detach confirmation')
    if E_ROOT.exists() and not is_mount(E_ROOT) and not E_ROOT.is_symlink():
        try:
            E_ROOT.rmdir()
        except OSError:
            errors.append('image target cleanup')
    if errors:
        FAILURE_DIAGNOSTICS['cleanup_failures'] = list(dict.fromkeys(errors))
        fail('owned mount cleanup guard')
    OWNED_MOUNTS.clear()


def run_probe(workspace):
    before = mounts()
    existing = {path for path in Path('/var/tmp').glob('m-local-runtime-proof.*') if path.is_dir()}
    if existing:
        fail('fresh runner probe workspace guard')
    log = workspace / 'runner-controls.log'
    try:
        run_command('runner controls probe', [sys.executable, '-B', str(PROBE)], cwd=ROOT,
                    timeout=900, log=log, first_signal=signal.SIGTERM)
    finally:
        assert_no_new_mounts(before, mounts(), 'runner controls probe')
    new = {path for path in Path('/var/tmp').glob('m-local-runtime-proof.*') if path.is_dir() and path not in before}
    if len(new) != 1 or not (next(iter(new)) / 'result.json').is_file():
        fail('runner controls receipt path')
    receipt_path = next(iter(new)) / 'result.json'
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('status') != 'passed' or receipt.get('controls', {}).get('memory_high') != MEMORY_HIGH or \
            receipt.get('controls', {}).get('memory_max') != MEMORY_MAX or receipt.get('controls', {}).get('swap_max') != 0 or \
            receipt.get('controls', {}).get('oom_policy') != 'stop' or \
            not receipt.get('controls', {}).get('confirmed_before_workload') or \
            not receipt.get('cleanup', {}).get('cgroup_empty') or \
            not receipt.get('cleanup', {}).get('launcher_stopped') or \
            not receipt.get('cleanup', {}).get('image_unmounted') or not receipt.get('cleanup', {}).get('loop_detached') or \
            receipt.get('probe_sha256') != digest(PROBE) or receipt.get('helper_sha256') != digest(HELPER):
        fail('runner controls receipt guard')
    required_checks = {'ubuntu-24.04', 'not-wsl', 'fresh-64Gi-sparse-image', 'ext4-60Gi-capacity', 'nosuid-nodev',
                       'uid65534-mode0700', 'loopback-device', 'case-sensitive', 'symlink-in-filesystem',
                       'bind-mounted-empty', 'scope-controls-before-workload', 'bounded-sleeper',
                       'cgroup-empty-child-cleanup', 'loop-backing-file-match', 'image-unmounted', 'loop-detached'}
    if set(receipt.get('checks', [])) != required_checks or len(receipt.get('checks', [])) != 16:
        fail('runner controls check inventory guard')
    if Path(receipt['image_path']).resolve() != IMAGE.resolve() or receipt['image_bytes'] != 64 * 1024 ** 3:
        fail('runner controls image identity')
    return receipt_path, receipt


def run_stage(task, workspace, stage, fork, official, *, old_fork=None, cold=None, gate=None, deadline=None):
    if deadline is not None and time.monotonic() >= deadline:
        fail('source job global deadline')
    output = workspace / (stage + '-stage.json')
    command = [sys.executable, '-B', str(task / 'work/identity-runtime-v9/run-source-stage-v9.py'),
               '--stage', stage, '--task-root', str(task), '--fork', str(fork), '--official-root', str(official),
               '--output', str(output)]
    if old_fork is not None:
        command.extend(['--old-fork', str(old_fork)])
    if cold is not None:
        command.extend(['--cold-compile', str(cold)])
    if gate is not None:
        command.extend(['--source-gate', str(gate)])
    remaining = SOURCE_JOB_SECONDS if deadline is None else max(1, int(deadline - time.monotonic()))
    before_mounts = mounts()
    try:
        run_command('source ' + stage, command, cwd=task, timeout=remaining, log=workspace / (stage + '.log'),
                    first_signal=signal.SIGINT)
    except BaseException:
        if stage == 'matrix':
            FAILURE_DIAGNOSTICS['matrix_failure'] = capture_matrix_failure(before_mounts)
        assert_no_new_mounts(before_mounts, mounts(), 'source ' + stage)
        raise
    if not output.is_file():
        fail('source stage receipt missing')
    outer = json.loads(output.read_text())
    leaf = task / {
        'cold-compile': 'work/identity-runtime-v7/run-source-cold-compile-v7.py',
        'bootstrap': 'work/identity-runtime-v7/run-source-bootstrap-v7.py',
        'matrix': 'work/identity-runtime-v9/run-source-matrix-v9.py',
    }[stage]
    if outer.get('wrapper_sha256') != digest(leaf):
        fail('source stage wrapper binding')
    child_input = Path(outer.get('child_result_path', ''))
    if (not child_input.is_absolute() or child_input.is_symlink() or child_input.parent.parent != Path('/var/tmp') or
            not child_input.parent.name.startswith('m-local-source-stage-v7-') or child_input.parent.is_symlink() or
            child_input.parent.stat().st_uid != 0 or child_input.parent.stat().st_mode & 0o777 != 0o700 or
            not child_input.is_file()):
        fail('source stage child path guard')
    child_path = child_input.resolve()
    if outer.get('status') != 'passed' or outer.get('child_result_sha256') != digest(child_path):
        fail('source stage child binding')
    child = json.loads(child_path.read_text())
    if child.get('status') != 'passed':
        fail('source stage child status')
    register_stage_mounts(stage, before_mounts, child)
    if stage in ('cold-compile', 'bootstrap'):
        retained = Path(child['workspace']) / 'result.json'
        if retained.is_symlink() or not retained.is_file() or digest(retained) != digest(child_path):
            fail('source ' + stage + ' retained receipt binding')
        child_path = retained
    return outer, child, child_path


def verify_leaf_controls(child, *, phases_key=None):
    if phases_key:
        rows = child.get(phases_key, [])
        if not rows:
            fail('source leaf phase receipt')
        for row in rows:
            scope = row.get('kernel_memory_scope', {})
            if not scope.get('controls_confirmed_before_workload') or not scope.get('cleanup', {}).get('cgroup_empty'):
                fail('source leaf kernel control receipt')
        return
    scope = child.get('kernel_memory_scope', {})
    controls = child.get('controls', {})
    if not child.get('source_override_explicit') or not controls.get('confirmed_before_workload') or \
            not scope.get('cleanup', {}).get('cgroup_empty'):
        fail('source leaf kernel control receipt')


def producer_binding():
    commit = os.environ.get('GITHUB_SHA', '')
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or not re.fullmatch(r'[1-9][0-9]*', run_id):
        fail('source producer context')
    command = ['/usr/bin/git', '-C', str(ROOT)]
    head = subprocess.check_output(command + ['rev-parse', '--verify', 'HEAD'], stderr=subprocess.DEVNULL).decode('ascii').strip()
    if head != commit:
        fail('source producer HEAD binding')
    runner = ROOT / 'runtime-proof' / 'run-fresh-source.py'
    for source in (runner, HELPER, HANDOFF_VERIFIER, HANDOFF_VERIFIER_BASE):
        if source.is_symlink() or not source.is_file():
            fail('source producer code type')
        committed = subprocess.check_output(command + ['show', 'HEAD:' + source.relative_to(ROOT).as_posix()], stderr=subprocess.DEVNULL)
        if hashlib.sha256(committed).hexdigest() != digest(source):
            fail('source producer code binding')
    return dict(commit_sha=commit, run_id=run_id, source_runner_sha256=digest(runner),
                adapter_manifest_sha256=ADAPTER_MANIFEST_SHA, application_revision=APP_REVISION,
                application_digest=APP_SHA, jac_base=JAC_BASE, official_binary_sha256=JAC_SHA,
                jacpython_sha256=JACPYTHON_SHA, helper_sha256=digest(HELPER),
                entrypoint_policy='source_only_via_pinned_adapters', evidence_scope='sanitized_commitments_only')


def scrub_stage(stage, child):
    return dict(status=stage.get('status'), stage=stage.get('stage'), wrapper_sha256=stage.get('wrapper_sha256'),
                result_sha256=stage.get('result_sha256'), child_result_sha256=stage.get('child_result_sha256'),
                elapsed_seconds=stage.get('elapsed_seconds'),
                parent_policy='JAC_NO_DEV_SOURCE=1; JAC_DEV_SOURCE and JAC_DB_URL removed; leaf controls are authoritative',
                source_gate_sha256=stage.get('source_gate_sha256'),
                cold_compile_receipt_sha256=child.get('cold_compile_receipt_sha256') if stage.get('stage') == 'run-source-bootstrap-v7' else None,
                child=dict(status=child.get('status'), checks=child.get('checks'), phase_count=child.get('phase_count'),
                           interface_count=child.get('interface_count'), runtime_patch_sha256=child.get('runtime_patch_sha256'),
                           official_binary_sha256=child.get('official_binary_sha256'), jacpython_sha256=child.get('jacpython_sha256'),
                           source_override_explicit=child.get('source_override_explicit'),
                           cold_compile_receipt_sha256=child.get('cold_compile_receipt_sha256'),
                           actual_smtp=child.get('actual_smtp')))


def build_handoff(workspace, manifest, cold_stage, bootstrap_stage, matrix_stage, cold, bootstrap, matrix, *, producer):
    handoff = workspace / 'source-handoff-v7'
    members = handoff / 'files'
    members.mkdir(mode=0o700, parents=True)
    entries = []
    for relative, metadata in manifest['files'].items():
        source = verify_staged_file(relative, metadata)
        destination = members / Path(relative)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        entries.append(dict(path='files/' + relative, bytes=destination.stat().st_size, sha256=digest(destination)))
    private_write(handoff / 'source-bootstrap-receipt.json', json.dumps(scrub_stage(bootstrap_stage, bootstrap), sort_keys=True).encode() + b'\n')
    private_write(handoff / 'source-matrix-receipt.json', json.dumps(scrub_stage(matrix_stage, matrix), sort_keys=True).encode() + b'\n')
    entries.extend([
        dict(path='source-bootstrap-receipt.json', bytes=(handoff / 'source-bootstrap-receipt.json').stat().st_size,
             sha256=digest(handoff / 'source-bootstrap-receipt.json')),
        dict(path='source-matrix-receipt.json', bytes=(handoff / 'source-matrix-receipt.json').stat().st_size,
             sha256=digest(handoff / 'source-matrix-receipt.json'))])
    if len(entries) != 36:
        fail('36-file handoff count guard')
    total = sum(item['bytes'] for item in entries)
    if total >= 1024 * 1024:
        fail('36-file handoff size guard')
    cold_rows = cold.get('phases', [])
    if len(cold_rows) != 2:
        fail('cold compile provenance contract')
    cold_provenance = dict(status=cold.get('status'), phase_count=len(cold_rows),
                           phase_patches=[row.get('runtime_patch_sha256') for row in cold_rows],
                           phase_statuses=[row.get('status') for row in cold_rows],
                           expected_e1030=dict(status=cold_rows[0].get('status'), exit_code=cold_rows[0].get('exit_code'),
                                               diagnostic='E1030 IdentityStorage/store expected mismatch',
                                               compiler_log_sha256=cold_rows[0].get('compiler_log_sha256'),
                                               patch_sha256=cold_rows[0].get('runtime_patch_sha256')),
                           corrected_compile=dict(status=cold_rows[1].get('status'), exit_code=cold_rows[1].get('exit_code'),
                                                 compiler_log_sha256=cold_rows[1].get('compiler_log_sha256'),
                                                 patch_sha256=cold_rows[1].get('runtime_patch_sha256')),
                           leaf_controls=[dict(controls_confirmed_before_workload=row.get('kernel_memory_scope', {}).get('controls_confirmed_before_workload'),
                                               cleanup=row.get('kernel_memory_scope', {}).get('cleanup')) for row in cold_rows])
    if cold_provenance['phase_patches'] != [PATCH_BEFORE, PATCH_AFTER] or cold_provenance['phase_statuses'] != ['expected_failure', 'passed']:
        fail('cold compile provenance identity')
    if digest(JAC_LICENSE_PATH) != JAC_LICENSE_SHA:
        fail('Jac license identity guard')
    private_write(handoff / 'JAC-LICENSE.txt', JAC_LICENSE_PATH.read_bytes())
    contract = dict(status='prepared_not_uploaded', member_count=len(entries), total_bytes=total,
                    source_manifest_sha256=digest(SOURCE_MANIFEST_PATH), runtime_patch_sha256=PATCH_AFTER,
                    source_bootstrap_receipt_sha256=digest(handoff / 'source-bootstrap-receipt.json'),
                    source_matrix_receipt_sha256=digest(handoff / 'source-matrix-receipt.json'), members=entries,
                    cold_compile_provenance=cold_provenance,
                    jac_license_notice=dict(path='JAC-LICENSE.txt', bytes=JAC_LICENSE_PATH.stat().st_size,
                                            sha256=JAC_LICENSE_SHA, origin='public Jac base MIT notice; mandatory handoff sidecar',
                                            text=JAC_LICENSE_PATH.read_text()),
                    producer=producer,
                    forbidden=['cache', 'scratch', 'private logs', 'graph state', 'identity state', 'fork-generated files',
                               'credentials', 'tokens', 'raw API bodies'])
    private_write(handoff / 'contract.json', json.dumps(contract, sort_keys=True, indent=2).encode() + b'\n')
    return dict(status=contract['status'], member_count=36, total_bytes=total,
                contract_sha256=digest(handoff / 'contract.json'))


def export_handoff(workspace, summary, producer):
    verify = runpy.run_path(str(HANDOFF_VERIFIER))['verify_bundle']
    bindings = dict(expected_commit=producer['commit_sha'], expected_run_id=producer['run_id'],
                    expected_contract_sha256=summary['contract_sha256'])
    bundle = workspace / 'source-handoff-v7'
    private_result = verify(bundle, ROOT, **bindings)
    if SOURCE_EXPORT.exists() or SOURCE_EXPORT.is_symlink():
        fail('source export destination occupied')
    shutil.copytree(bundle, SOURCE_EXPORT, copy_function=shutil.copyfile)
    SOURCE_EXPORT.chmod(0o755)
    for path in SOURCE_EXPORT.rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o644)
    exported = verify(SOURCE_EXPORT, ROOT, **bindings)
    if exported != private_result:
        fail('source export verification binding')
    return exported


def main():
    global PRIVATE_LOG_DIR
    FAILURE_DIAGNOSTICS.update(operation='producer-binding', last_scoped_command=None,
                               body_completed=False, body_failure_type=None, cleanup_failures=[], matrix_failure=None)
    producer = producer_binding()
    FAILURE_DIAGNOSTICS['operation'] = 'host-controls'
    host_guard()
    FAILURE_DIAGNOSTICS['operation'] = 'manifest-inputs'
    pins, manifest, adapters = manifest_inputs()
    workspace = set_private(Path(tempfile.mkdtemp(prefix='m-local-fresh-source-v7-', dir='/var/tmp')))
    PRIVATE_LOG_DIR = workspace / 'logs'
    PRIVATE_LOG_DIR.mkdir(mode=0o700)
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, signal_handler)
    deadline = time.monotonic() + SOURCE_JOB_SECONDS
    summary = None
    try:
        FAILURE_DIAGNOSTICS.update(operation='runner-controls', last_scoped_command=None)
        probe_path, probe = run_probe(workspace)
        FAILURE_DIAGNOSTICS.update(operation='storage-mount', last_scoped_command=None)
        mount_image()
        task = CANONICAL_TASK
        FAILURE_DIAGNOSTICS.update(operation='application-checkout', last_scoped_command=None)
        app = prepare_task(task, manifest, adapters, workspace / 'checkout.log')
        FAILURE_DIAGNOSTICS.update(operation='runtime-materialization', last_scoped_command=None)
        official, runtime = materialize_runtime(workspace, pins, workspace / 'runtime.log')
        FAILURE_DIAGNOSTICS.update(operation='source-forks', last_scoped_command=None)
        old_fork, current_fork = prepare_forks(workspace, manifest, workspace / 'forks.log')
        FAILURE_DIAGNOSTICS.update(operation='shim-typeshed', last_scoped_command=None)
        type_inventory = materialize_shim_typeshed(current_fork, old_fork, official, workspace)
        FAILURE_DIAGNOSTICS.update(operation='dependency-priming', last_scoped_command=None)
        dependency = dependency_priming(app, official, workspace, workspace / 'dependencies.log')
        FAILURE_DIAGNOSTICS.update(operation='cold-compile', last_scoped_command=None)
        cold_stage, cold, cold_path = run_stage(task, workspace, 'cold-compile', current_fork, official,
                                                old_fork=old_fork, deadline=deadline)
        cold_phases = cold.get('phases', [])
        if len(cold_phases) != 2 or cold_phases[0].get('runtime_patch_sha256') != PATCH_BEFORE or \
                cold_phases[1].get('runtime_patch_sha256') != PATCH_AFTER:
            fail('cold phase patch order')
        FAILURE_DIAGNOSTICS.update(operation='bootstrap', last_scoped_command=None)
        bootstrap_stage, bootstrap, bootstrap_path = run_stage(task, workspace, 'bootstrap', current_fork, official,
                                                               cold=cold_path, deadline=deadline)
        if bootstrap.get('checks') != 53 or bootstrap.get('cold_compile_receipt_sha256') != digest(cold_path) or \
                not bootstrap.get('source_override_explicit') or bootstrap.get('official_binary_sha256') != JAC_SHA or \
                bootstrap.get('jacpython_sha256') != JACPYTHON_SHA:
            fail('bootstrap leaf gate')
        verify_leaf_controls(cold, phases_key='phases')
        verify_leaf_controls(bootstrap, phases_key=None)
        FAILURE_DIAGNOSTICS.update(operation='matrix', last_scoped_command=None)
        matrix_stage, matrix, matrix_path = run_stage(task, workspace, 'matrix', current_fork, official,
                                                     gate=bootstrap_path, deadline=deadline)
        if matrix.get('phase_count') != 10 or matrix.get('interface_count') != 2 or \
                matrix.get('source_gate_sha256') != digest(bootstrap_path) or matrix.get('official_binary_sha256') != JAC_SHA:
            fail('matrix leaf gate')
        matrix_result = Path(matrix['workspace']) / 'result.json'
        workspace_path = matrix_result.parent
        if (not matrix_result.is_file() or matrix_result.is_symlink() or workspace_path.parent != Path('/var/tmp') or
                workspace_path.is_symlink() or Path('/var/tmp').is_symlink() or
                workspace_path.stat().st_mode & 0o777 != 0o700 or
                workspace_path.stat().st_uid != 65534):
            fail('matrix result path gate')
        matrix_inner = json.loads(matrix_result.read_text())
        storage = matrix_inner.get('storage_binding', {})
        if not isinstance(storage, dict) or not storage.get('storage_root'):
            fail('matrix storage receipt')
        storage_root = Path(storage['storage_root'])
        if storage_root.resolve() != E_ROOT.resolve() or not is_mount(storage_root) or storage_root.is_symlink() or \
                storage_root.stat().st_uid != 65534 or storage_root.stat().st_mode & 0o777 != 0o700:
            fail('matrix storage mount gate')
        verify_leaf_controls(matrix_inner, phases_key='phases')
        verify_leaf_controls(matrix_inner, phases_key='interface_proofs')
        FAILURE_DIAGNOSTICS.update(operation='handoff-build', last_scoped_command=None)
        handoff = build_handoff(workspace, manifest, cold_stage, bootstrap_stage, matrix_stage, cold, bootstrap, matrix, producer=producer)
        FAILURE_DIAGNOSTICS.update(operation='handoff-export', last_scoped_command=None)
        handoff['verification'] = export_handoff(workspace, handoff, producer)
        FAILURE_DIAGNOSTICS.update(operation='summary', last_scoped_command=None)
        summary = dict(status='passed', checks=['host-controls', 'fresh-64Gi-storage', 'public-app-revision',
            'public-pinned-downloads', 'postgres-distribution', 'dependency-priming-pillow', 'fresh-forks-80fd-d363',
            'cold-compile-before-after', 'bootstrap-53', 'matrix-10-plus-2', 'scrubbed-36-file-contract'],
            application_revision=APP_REVISION, application_digest=APP_SHA, jac_base=JAC_BASE,
            github_sha=os.environ.get('GITHUB_SHA', ''),
            jac_sha256=JAC_SHA, jacpython_sha256=JACPYTHON_SHA, shim_sha256=SHIM_SHA,
            typeshed_inventory_sha256=TYPESHED_SHA, postgres_distribution=pins['downloads']['postgres']['distribution'],
            postgres_inventory_sha256=runtime['postgres_inventory_sha256'], dependency=dependency,
            shim_typeshed=type_inventory,
            probe_sha256=digest(PROBE), probe_receipt_sha256=digest(probe_path), helper_sha256=digest(HELPER),
            source_job_elapsed_seconds=round(SOURCE_JOB_SECONDS - max(0, deadline - time.monotonic()), 2),
            cold_receipt_sha256=digest(cold_path), bootstrap_receipt_sha256=digest(bootstrap_path), matrix_receipt_sha256=digest(matrix_path),
            handoff=handoff, external_jac_db_url=False, source_override='leaf receipts only',
            status_scope='prepared source proof; no package/adoption/deployment')
        FAILURE_DIAGNOSTICS['body_completed'] = True
    except BaseException as error:
        FAILURE_DIAGNOSTICS['body_failure_type'] = next((family.__name__ for family in
            (RuntimeError, OSError, subprocess.SubprocessError, AssertionError, ValueError,
             KeyError, TypeError, IndexError, SystemExit) if isinstance(error, family)), 'other')
        raise
    finally:
        cleanup_mounts()
    print(json.dumps(summary, sort_keys=True, separators=(',', ':')), flush=True)


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        label = str(error).splitlines()[0][:120] or 'source runner aborted'
        print(json.dumps(dict(status='failed', error=label, failure_context=sanitized_failure_context(error),
                             failure_diagnostics=sanitized_failure_diagnostics(),
                             private_logs=str(PRIVATE_LOG_DIR or '/var/tmp/m-local-fresh-source-v7.*')),
                          sort_keys=True, separators=(',', ':')), flush=True)
        raise SystemExit(1)
    except (OSError, subprocess.SubprocessError, AssertionError, ValueError, KeyError, TypeError, UnicodeError,
            IndexError, SystemExit) as error:
        print(json.dumps(dict(status='failed', error='source runner aborted',
                              failure_context=sanitized_failure_context(error),
                              failure_diagnostics=sanitized_failure_diagnostics(),
                              private_logs=str(PRIVATE_LOG_DIR or '/var/tmp/m-local-fresh-source-v7.*')),
                         sort_keys=True, separators=(',', ':')), flush=True)
        raise SystemExit(1)
