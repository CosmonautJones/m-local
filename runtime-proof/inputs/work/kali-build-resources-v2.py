from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time

task = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
e_root = Path('/var/tmp/m-local-build-e-drive-v2-01a1050e')
e_parent = Path('/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004')
c_floor = 10 * 1024 ** 3
e_floor = 3 * 1024 ** 3


def verify_storage():
    receipt = e_parent / 'linux-build-storage-v2.json'
    storage = json.loads(receipt.read_text())
    assert storage['status'] == 'passed'
    assert storage['executed_prepare_sha256'] == hashlib.sha256((task / 'work/prepare-e-drive-linux-build-v2.py').read_bytes()).hexdigest()
    assert e_root.is_mount() and not e_root.is_symlink()
    assert e_root.stat().st_uid == 65534 and e_root.stat().st_mode & 0o777 == 0o700
    assert e_root.stat().st_dev == storage['mount_device_id'] != Path('/var/tmp').stat().st_dev
    loop = Path(storage['loop_device'])
    assert loop.parent == Path('/dev') and loop.name.startswith('loop')
    assert loop.stat().st_rdev == e_root.stat().st_dev
    image = Path(storage['image'])
    assert image.parent == e_parent and image.name == 'linux-build-storage-v2.ext4'
    assert storage['image_bytes'] == 64 * 1024 ** 3
    backing = subprocess.check_output(['/usr/sbin/losetup', '--noheadings', '--output', 'BACK-FILE', str(loop)], text=True).strip()
    assert Path(backing).resolve() == image.resolve() and image.stat().st_size == storage['image_bytes']
    assert int(subprocess.check_output(['/usr/sbin/blockdev', '--getsize64', str(loop)], text=True)) == storage['image_bytes']
    assert 60 * 1024 ** 3 <= shutil.disk_usage(e_root).total <= storage['image_bytes']
    control_path = e_parent / 'memory-scope-control-v6.json'
    control = json.loads(control_path.read_text())
    assert control['status'] == 'passed' and len(control['cases']) == 4
    assert control['executed_probe_sha256'] == hashlib.sha256((task / 'work/test-kali-memory-scope-v2.py').read_bytes()).hexdigest()
    assert control['resource_helper_sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    assert all(row['status'] == 'passed' and row['cleanup']['cgroup_empty'] for row in control['cases'])
    assert all(row['controls_confirmed_before_workload'] for row in control['cases'])
    pending_path = e_parent / 'memory-pending-control-v2.json'
    pending = json.loads(pending_path.read_text())
    assert pending['status'] == 'passed' and pending['unbounded_defaults_rejected'] and pending['finite_controls_accepted'] and pending['empty_kernel_group_removed']
    assert pending['executed_probe_sha256'] == hashlib.sha256((task / 'work/test-kali-pending-memory-controls-v2.py').read_bytes()).hexdigest()
    assert pending['resource_helper_sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    assert shutil.disk_usage('/mnt/c').free >= c_floor and shutil.disk_usage(e_root).free >= e_floor
    return dict(storage_control_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
                memory_control_sha256=hashlib.sha256(control_path.read_bytes()).hexdigest(),
                pending_memory_control_sha256=hashlib.sha256(pending_path.read_bytes()).hexdigest(),
                resource_helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                image=str(image), loop_device=str(loop), mount_device_id=e_root.stat().st_dev,
                c_free_space_guard_bytes=c_floor, e_image_free_space_guard_bytes=e_floor)


def mounted_empty(prefix):
    directory = Path(tempfile.mkdtemp(prefix=prefix, dir='/var/tmp'))
    backing = e_root / directory.name
    assert not backing.exists() and not directory.is_symlink()
    backing.mkdir(mode=0o700)
    subprocess.run(['/usr/bin/mount', '--bind', str(backing), str(directory)], check=True)
    os.chown(directory, 65534, 65534)
    assert directory.is_mount() and directory.stat().st_dev == e_root.stat().st_dev and not any(directory.iterdir())
    return directory


def launch_scope(directory, command, cwd, environment, log, high=7 * 1024 ** 3, maximum=8 * 1024 ** 3):
    unit = 'm-local-' + directory.name + '.scope'
    group = Path('/sys/fs/cgroup/system.slice') / unit
    assert directory.name.startswith(('m-local-', 'memory-scope-control-')) and not group.exists()
    state = dict(unit=unit, cgroup=str(group), requested_limits=dict(high=high, max=maximum, swap_max=0),
                 limits={}, oom_policy=None, peak_bytes=0, peak_process_rss_kib=0, events={},
                 controls_confirmed_before_workload=False, startup_control_samples=0,
                 minimum_c_free_bytes=shutil.disk_usage('/mnt/c').free,
                 minimum_e_image_free_bytes=shutil.disk_usage(e_root).free)
    ready = directory / '.scope-ready'
    assert not ready.exists()
    bootstrap = ('import os,time; from pathlib import Path; ready=Path(' + repr(str(ready)) + '); '
        'deadline=time.monotonic()+10\nwhile not ready.exists():\n'
        ' assert time.monotonic()<deadline, "Scope supervisor did not confirm kernel controls"\n time.sleep(.005)\n'
        'ready.unlink(); os.execvpe(' + repr(command[0]) + ',' + repr(command) + ',os.environ)')
    process = subprocess.Popen(['/usr/bin/systemd-run', '--scope', '--quiet', '--unit=' + unit,
        '--property=MemoryHigh=' + str(high), '--property=MemoryMax=' + str(maximum),
        '--property=MemorySwapMax=0', '--property=OOMPolicy=stop',
        '/usr/sbin/runuser', '-u', 'nobody', '--', '/usr/bin/python3', '-B', '-c', bootstrap], cwd=cwd, env=environment,
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 5
    try:
        while process.poll() is None and time.monotonic() < deadline:
            sample_scope(state)
            state['startup_control_samples'] += 1
            if state['limits'] == state['requested_limits'] and state['oom_policy'] == 'stop':
                break
            time.sleep(.005)
        assert state['limits'] == state['requested_limits'] and state['oom_policy'] == 'stop', state
        state['controls_confirmed_before_workload'] = True
        ready.touch(exist_ok=False)
    except BaseException:
        stop_scope(state, process)
        raise
    return process, state


def sample_scope(state):
    group = Path(state['cgroup'])
    rss = 0
    if group.exists():
        try:
            limits = {name: (group / ('memory.' + name)).read_text().strip() for name in ('high', 'max', 'swap.max')}
            state['limits'] = {name: value if value == 'max' else int(value) for name, value in limits.items()}
            state['limits']['swap_max'] = state['limits'].pop('swap.max')
            state['peak_bytes'] = max(state['peak_bytes'], int((group / 'memory.peak').read_text()))
            state['events'] = dict(line.split() for line in (group / 'memory.events').read_text().splitlines())
            if state['oom_policy'] != 'stop':
                state['oom_policy'] = subprocess.check_output(['/usr/bin/systemctl', 'show', state['unit'], '--property=OOMPolicy', '--value'], text=True).strip()
            for pid in (group / 'cgroup.procs').read_text().splitlines():
                try:
                    rss += next((int(line.split()[1]) for line in (Path('/proc') / pid / 'status').read_text().splitlines() if line.startswith('VmRSS:')), 0)
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    pass
        except FileNotFoundError:
            pass
    state['peak_process_rss_kib'] = max(state['peak_process_rss_kib'], rss)
    state['minimum_c_free_bytes'] = min(state['minimum_c_free_bytes'], shutil.disk_usage('/mnt/c').free)
    state['minimum_e_image_free_bytes'] = min(state['minimum_e_image_free_bytes'], shutil.disk_usage(e_root).free)
    return rss


def scope_guard(state, elapsed, timeout):
    if int(state['events'].get('oom_kill', '0')):
        return 'kernel_memory_limit'
    if state['limits'] and (state['limits'] != state['requested_limits'] or state['oom_policy'] != 'stop'):
        return 'kernel_control_mismatch'
    if state['minimum_c_free_bytes'] < c_floor or state['minimum_e_image_free_bytes'] < e_floor:
        return 'disk'
    if elapsed > timeout:
        return 'timeout'
    return None


def stop_scope(state, process):
    group = Path(state['cgroup'])
    assert group.parent == Path('/sys/fs/cgroup/system.slice') and group.name == state['unit']
    assert group.name.startswith('m-local-') and group.name.endswith('.scope')
    def pids():
        try:
            return (group / 'cgroup.procs').read_text().strip()
        except FileNotFoundError:
            return ''
    if group.exists() or process.poll() is None:
        subprocess.run(['/usr/bin/systemctl', 'stop', state['unit']], timeout=20, capture_output=True)
    deadline = time.monotonic() + 5
    while pids() and time.monotonic() < deadline:
        time.sleep(.05)
    used_kill = False
    if pids():
        (group / 'cgroup.kill').write_text('1')
        used_kill = True
    process.wait(timeout=10)
    deadline = time.monotonic() + 5
    while pids() and time.monotonic() < deadline:
        time.sleep(.05)
    empty = not pids()
    result = subprocess.run(['/usr/bin/systemctl', 'show', state['unit'], '--property=ActiveState,SubState,Result'], capture_output=True, text=True)
    unit_state = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    assert empty and unit_state.get('ActiveState') in ('inactive', 'failed')
    state['cleanup'] = dict(cgroup_empty=empty, unit_state=unit_state, cgroup_kill_fallback_used=used_kill,
                            launcher_stopped=process.poll() is not None)
    return state['cleanup']
