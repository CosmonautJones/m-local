"""Finite Ubuntu CI capability probe for the isolated runtime proof.

This provisions one fresh sparse ext4 image and one bounded systemd scope. It
does not build the application and never reads historical storage receipts.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import runpy
import signal
import shutil
import subprocess
import tempfile
import time


IMAGE_BYTES = 64 * 1024 ** 3
MIN_FREE_BYTES = IMAGE_BYTES + 20 * 1024 ** 3
E_ROOT = Path('/var/tmp/m-local-build-e-drive-v2-01a1050e')
IMAGE = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/linux-build-storage-v2.ext4')
ROOT_STAT = Path('/mnt/c')
HELPER = Path(__file__).with_name('kali-build-resources-v2.py')
PRIVATE_LOG_HINT = '/var/tmp/m-local-runtime-proof.*'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(label):
    raise RuntimeError(label)


def run(label, command, *, timeout=30):
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        fail(label)
    if result.returncode:
        fail(label)
    return result.stdout.strip()


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def reject_symlink_chain(path):
    current = path
    while current != current.parent:
        if current.is_symlink():
            fail('path symlink guard')
        current = current.parent


def parse_os_release():
    values = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            values[key] = value.strip('"')
    if values.get('ID') != 'ubuntu' or values.get('VERSION_ID') != '24.04':
        fail('Ubuntu 24.04 host guard')
    kernel_text = Path('/proc/version').read_text().lower()
    if os.environ.get('WSL_INTEROP') or 'microsoft' in kernel_text or 'wsl' in kernel_text:
        fail('WSL host guard')
    if Path('/proc/1/comm').read_text().strip() != 'systemd' or not Path('/sys/fs/cgroup/cgroup.controllers').is_file():
        fail('systemd cgroup-v2 host guard')
    return {key: values[key] for key in ('ID', 'VERSION_ID', 'PRETTY_NAME') if key in values}


def preflight():
    if os.getuid() != 0:
        fail('root capability probe guard')
    for path in (IMAGE, E_ROOT, ROOT_STAT, IMAGE.parent):
        reject_symlink_chain(path)
    if IMAGE.exists():
        fail('fresh image overwrite guard')
    if E_ROOT.exists():
        fail('fresh image mount target guard')
    if IMAGE.parent.exists():
        fail('fresh image parent guard')
    for ancestor in IMAGE.parent.parents:
        if ancestor.is_symlink() or (ancestor.exists() and ancestor.stat().st_uid != 0):
            fail('image parent ancestor guard')
    if ROOT_STAT.exists() and (ROOT_STAT.is_symlink() or not ROOT_STAT.is_dir() or ROOT_STAT.stat().st_uid != 0):
        fail('root stat directory guard')
    for command in ('/usr/bin/mount', '/usr/bin/umount', '/usr/bin/sudo', '/usr/sbin/losetup', '/usr/sbin/blockdev',
                    '/usr/sbin/mkfs.ext4', '/usr/bin/systemd-run', '/usr/bin/systemctl', '/usr/sbin/runuser'):
        if not Path(command).is_file():
            fail('required host capability guard')
    parse_os_release()
    storage_root = IMAGE.parent
    while not storage_root.exists():
        storage_root = storage_root.parent
    parent_free = shutil.disk_usage(storage_root).free
    if parent_free <= MIN_FREE_BYTES:
        fail('image parent free-space guard')
    return parent_free


def prove_case_and_symlink():
    case_dir = E_ROOT / 'case-proof'
    upper = E_ROOT / 'CASE-PROOF'
    marker = case_dir / 'marker'
    link = E_ROOT / 'case-link'
    case_dir.mkdir(mode=0o700)
    marker.write_bytes(b'capability')
    if upper.exists():
        fail('case-sensitive filesystem guard')
    link.symlink_to('case-proof', target_is_directory=True)
    try:
        if link.resolve() != case_dir.resolve() or (link / 'marker').read_bytes() != b'capability':
            fail('symlink filesystem guard')
    finally:
        link.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        case_dir.rmdir()


def cleanup_scope(bind_mount, loop_device, created_root_stat, created_image_parent, cleanup_errors):
    candidates = []
    if bind_mount is not None:
        candidates.append(bind_mount)
    seen = set()
    for mount in candidates:
        if mount in seen:
            continue
        seen.add(mount)
        try:
            if mount.is_mount():
                result = subprocess.run(['/usr/bin/umount', str(mount)], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
                if result.returncode:
                    cleanup_errors.append('bind unmount')
            backing = E_ROOT / mount.name
            if mount.exists() and not mount.is_mount() and not mount.is_symlink():
                mount.rmdir()
            if backing.exists() and not backing.is_mount() and not backing.is_symlink():
                backing.rmdir()
        except (OSError, subprocess.SubprocessError):
            cleanup_errors.append('bind cleanup')
    try:
        if E_ROOT.is_mount():
            result = subprocess.run(['/usr/bin/umount', str(E_ROOT)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if result.returncode:
                cleanup_errors.append('image unmount')
    except (OSError, subprocess.SubprocessError):
        cleanup_errors.append('image unmount')
    try:
        if E_ROOT.exists() and not E_ROOT.is_mount() and not E_ROOT.is_symlink():
            E_ROOT.rmdir()
    except OSError:
        cleanup_errors.append('image target cleanup')
    if loop_device:
        try:
            result = subprocess.run(['/usr/sbin/losetup', '--detach', loop_device], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            cleanup_errors.append('loop detach')
        else:
            if result.returncode:
                cleanup_errors.append('loop detach')
    if created_root_stat and ROOT_STAT.exists() and not any(ROOT_STAT.iterdir()):
        try:
            ROOT_STAT.rmdir()
        except OSError:
            cleanup_errors.append('root stat cleanup')
    if created_image_parent and IMAGE.parent.exists() and not IMAGE.parent.is_symlink() and not IMAGE.exists():
        try:
            IMAGE.parent.rmdir()
        except OSError:
            cleanup_errors.append('image parent cleanup')


def main():
    global PRIVATE_LOG_HINT
    parent_free = preflight()
    created_image_parent = False
    created_root_stat = False
    workspace = Path(tempfile.mkdtemp(prefix='m-local-runtime-proof.', dir='/var/tmp'))
    workspace.chmod(0o700)
    logs = workspace / 'logs'
    logs.mkdir(mode=0o700)
    PRIVATE_LOG_HINT = str(logs)
    probe_log = logs / 'probe.log'
    probe_log.touch(mode=0o600)
    probe_log.chmod(0o600)
    loop_device = ''
    bind_mount = None
    cleanup_errors = []
    failure = None
    receipt = None
    try:
        IMAGE.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
        created_image_parent = True
        if IMAGE.parent.is_symlink() or not IMAGE.parent.is_dir() or IMAGE.parent.stat().st_uid != 0 or \
                IMAGE.parent.stat().st_mode & 0o777 != 0o700:
            fail('image parent ownership guard')
        E_ROOT.mkdir(mode=0o700, exist_ok=False)
        if E_ROOT.is_symlink() or not E_ROOT.is_dir() or E_ROOT.stat().st_uid != 0 or \
                E_ROOT.stat().st_mode & 0o777 != 0o700:
            fail('image target ownership guard')
        created_root_stat = not ROOT_STAT.exists()
        if created_root_stat:
            ROOT_STAT.mkdir(mode=0o755, exist_ok=False)
        if ROOT_STAT.is_symlink() or not ROOT_STAT.is_dir() or ROOT_STAT.stat().st_uid != 0:
            fail('root stat ownership guard')
        image_parent_device = IMAGE.parent.stat().st_dev
        root_device = ROOT_STAT.stat().st_dev
        if shutil.disk_usage(IMAGE.parent).free <= MIN_FREE_BYTES:
            fail('image parent free-space guard')
        with IMAGE.open('xb') as stream:
            stream.truncate(IMAGE_BYTES)
        if IMAGE.stat().st_size != IMAGE_BYTES:
            fail('sparse image size guard')
        run('ext4 image format', ['/usr/sbin/mkfs.ext4', '-F', '-q', str(IMAGE)], timeout=120)
        loop_device = run('loopback attach', ['/usr/sbin/losetup', '--find', '--show', str(IMAGE)])
        loop_path = Path(loop_device)
        if loop_path.parent != Path('/dev') or not loop_path.name.startswith('loop'):
            fail('loop device path guard')
        run('image mount', ['/usr/bin/mount', '-o', 'nosuid,nodev', loop_device, str(E_ROOT)], timeout=60)
        os.chown(E_ROOT, 65534, 65534)
        E_ROOT.chmod(0o700)
        if E_ROOT.stat().st_uid != 65534 or E_ROOT.stat().st_mode & 0o777 != 0o700:
            fail('image ownership guard')
        mount_line = run('mount option inspection', ['/usr/bin/findmnt', '--noheadings', '--output', 'SOURCE,FSTYPE,OPTIONS', str(E_ROOT)])
        mount_fields = mount_line.split(None, 2)
        if len(mount_fields) != 3 or mount_fields[0] != loop_device or mount_fields[1] != 'ext4' or \
                'nosuid' not in mount_fields[2].split(',') or 'nodev' not in mount_fields[2].split(','):
            fail('image mount option guard')
        if E_ROOT.stat().st_dev == image_parent_device or loop_path.stat().st_rdev != E_ROOT.stat().st_dev:
            fail('loop and image device identity guard')
        fs_total = shutil.disk_usage(E_ROOT).total
        if not 60 * 1024 ** 3 <= fs_total <= IMAGE_BYTES:
            fail('ext4 capacity guard')
        if int(run('loop capacity', ['/usr/sbin/blockdev', '--getsize64', loop_device])) != IMAGE_BYTES:
            fail('loop capacity identity guard')
        loop_backing = run('loop backing identity', ['/usr/sbin/losetup', '--noheadings', '--output', 'BACK-FILE', loop_device])
        if Path(loop_backing).resolve() != IMAGE.resolve():
            fail('loop backing image identity guard')
        prove_case_and_symlink()
        helper_source = sha256(HELPER)
        helper = runpy.run_path(str(HELPER))
        mounted_empty = helper['mounted_empty']
        launch_scope = helper['launch_scope']
        sample_scope = helper['sample_scope']
        scope_guard = helper['scope_guard']
        stop_scope = helper['stop_scope']
        created_mounts = []
        helper_tempfile = helper['tempfile']
        original_mkdtemp = helper_tempfile.mkdtemp
        def tracked_mkdtemp(*args, **kwargs):
            path = original_mkdtemp(*args, **kwargs)
            if kwargs.get('prefix') == 'm-local-runtime-proof-scope-':
                created_mounts.append(Path(path))
            return path
        helper_tempfile.mkdtemp = tracked_mkdtemp
        try:
            bind_mount = mounted_empty('m-local-runtime-proof-scope-')
        except BaseException:
            bind_mount = created_mounts[0] if created_mounts else None
            raise
        finally:
            helper_tempfile.mkdtemp = original_mkdtemp
        if not bind_mount.is_mount() or any(bind_mount.iterdir()) or bind_mount.stat().st_dev != E_ROOT.stat().st_dev or \
                bind_mount.stat().st_dev == Path('/var/tmp').stat().st_dev:
            fail('bind mount device and empty guard')
        sleeper = ['/usr/bin/python3', '-B', '-c', 'import os,time; assert os.getuid()==65534; time.sleep(2)']
        environment = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'PYTHONUNBUFFERED': '1'}
        scope_log = logs / 'scope.log'
        scope_log.touch(mode=0o600)
        scope_log.chmod(0o600)
        requested_high = 7 * 1024 ** 3
        requested_max = 8 * 1024 ** 3
        startup_deadline = 5
        workload_deadline = 15
        started = time.monotonic()
        with scope_log.open('ab') as stream:
            process, state = launch_scope(bind_mount, sleeper, bind_mount, environment, stream,
                                          high=requested_high, maximum=requested_max)
        cleanup = None
        try:
            startup_elapsed = time.monotonic() - started
            if startup_elapsed > startup_deadline or not state['controls_confirmed_before_workload'] or \
                    state['limits'] != dict(high=requested_high, max=requested_max, swap_max=0) or \
                    state['requested_limits'] != \
                    dict(high=requested_high, max=requested_max, swap_max=0):
                fail('scope controls before workload guard')
            reason = None
            while process.poll() is None and time.monotonic() - started < workload_deadline:
                sample_scope(state)
                reason = scope_guard(state, time.monotonic() - started, workload_deadline)
                if reason:
                    break
                time.sleep(.1)
            if process.poll() is None and reason is None:
                reason = 'timeout'
            sample_scope(state)
        finally:
            cleanup = stop_scope(state, process)
        if reason or process.returncode != 0 or not cleanup.get('cgroup_empty') or not cleanup.get('launcher_stopped'):
            fail('bounded scope workload guard')
        elapsed = round(time.monotonic() - started, 3)
        probe_hash = sha256(Path(__file__))
        os_release = parse_os_release()
        receipt = dict(status='passed', checks=['ubuntu-24.04', 'not-wsl', 'fresh-64Gi-sparse-image',
            'ext4-60Gi-capacity', 'nosuid-nodev', 'uid65534-mode0700', 'loopback-device', 'case-sensitive',
            'symlink-in-filesystem', 'bind-mounted-empty', 'scope-controls-before-workload', 'bounded-sleeper',
            'cgroup-empty-child-cleanup'], elapsed_seconds=elapsed, probe_sha256=probe_hash,
            helper_sha256=helper_source, os_release=os_release, kernel=platform.release(),
            root_stat_device=root_device, image_parent_device=image_parent_device, image_device=E_ROOT.stat().st_dev,
            image_path=str(IMAGE), mount_path=str(E_ROOT), root_stat_path=str(ROOT_STAT),
            storage_identity=dict(
                linux_root=dict(path=str(ROOT_STAT.resolve()), device=root_device),
                sparse_image=dict(path=str(IMAGE.resolve()), file_device=IMAGE.stat().st_dev,
                                  parent_device=image_parent_device),
                mounted_image=dict(path=str(E_ROOT.resolve()), device=E_ROOT.stat().st_dev)),
            loop_device=loop_device, loop_backing_file=loop_backing, image_bytes=IMAGE_BYTES, filesystem_bytes=fs_total,
            parent_free_bytes=parent_free, root_free_bytes=shutil.disk_usage(ROOT_STAT).free,
            startup_elapsed_seconds=round(startup_elapsed, 3), startup_deadline_seconds=startup_deadline,
            workload_deadline_seconds=workload_deadline,
            controls={'memory_high': requested_high, 'memory_max': requested_max, 'swap_max': 0,
                      'oom_policy': 'stop', 'confirmed_before_workload': True}, cleanup=cleanup)
    except (OSError, RuntimeError, subprocess.SubprocessError, AssertionError, ValueError) as error:
        failure = error
    finally:
        cleanup_scope(bind_mount, loop_device, created_root_stat, created_image_parent, cleanup_errors)
    if cleanup_errors:
        fail('mount and loop cleanup guard')
    if failure is not None:
        raise failure
    if E_ROOT.is_mount():
        fail('image unmount confirmation')
    if bind_mount is not None and bind_mount.is_mount():
        fail('bind unmount confirmation')
    loop_check = subprocess.run(['/usr/sbin/losetup', '--associated', str(IMAGE)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    if loop_check.returncode != 0 or loop_check.stdout.strip():
        fail('loop detach confirmation')
    receipt['checks'].extend(['loop-backing-file-match', 'image-unmounted', 'loop-detached'])
    receipt['cleanup']['image_unmounted'] = True
    receipt['cleanup']['loop_detached'] = True
    private_write(workspace / 'result.json', json.dumps(receipt, sort_keys=True, indent=2).encode() + b'\n')
    print(json.dumps(receipt, sort_keys=True, separators=(',', ':')), flush=True)


if __name__ == '__main__':
    def terminate(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError, AssertionError, ValueError):
        raise SystemExit('FAIL; private runtime-proof logs: ' + PRIVATE_LOG_HINT)
