"""Strict disposable repro of a surviving native writer during stopped backup."""
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import time
from zoneinfo import ZoneInfo


def _process(pid):
    """Private Linux identity; never publish paths, argv or process identifiers."""
    root = Path('/proc') / str(pid)
    try:
        fields = (root / 'stat').read_text().rsplit(')', 1)[1].split()
        result = dict(pid=pid, uid=root.stat().st_uid, state=fields[0], parent=int(fields[1]), group=int(fields[2]),
                      session=int(fields[3]), started=fields[19], cwd=None, argv=[])
    except (OSError, ValueError, IndexError):
        return None
    try:
        result.update(cwd=os.readlink(root / 'cwd'), argv=(root / 'cmdline').read_bytes().split(b'\0')[:-1])
    except OSError:
        pass
    return result


def _same(saved, current):
    return current is not None and all(current[key] == saved[key]
        for key in ('pid', 'uid', 'group', 'session', 'started')) and (current['state'] == 'Z'
        or all(current[key] == saved[key] for key in ('cwd', 'argv')))


def _group_members(group):
    members = []
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():
            continue
        try:
            fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == group:
                member = _process(int(path.name))
                if member is not None:
                    members.append(member)
        except (OSError, ValueError, IndexError):
            pass
    return members


def _stop_captured(saved_members):
    """Signal only the pre-captured, still-identical fixture-owned group."""
    if not saved_members:
        return False
    group = saved_members[0]['group']
    known = {row['pid']: row for row in saved_members}
    if any(row['uid'] != os.getuid() for row in saved_members):
        return False
    members = _group_members(group)
    if not members:
        return True
    if not all(row['pid'] in known and _same(known[row['pid']], row) for row in members):
        return False
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group, signum)
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            members = _group_members(group)
            if not members:
                return True
            if not all(row['pid'] in known and _same(known[row['pid']], row) for row in members):
                return False
            for row in members:
                if row['state'] == 'Z':
                    try:
                        os.waitpid(row['pid'], os.WNOHANG)
                    except (ChildProcessError, ProcessLookupError):
                        pass
            time.sleep(.1)
    return not _group_members(group)


def run_stopped_writer_recovery_checks(f, context):
    """Use real launcher/backup/HTTP; overlapping backup is a strict failure."""
    check, app, workspace = f['check'], Path(f['app']), Path(f['workspace'])
    observe, local = context['observe'], dict(context['local'])
    fingerprint, originals, preserved = context['fingerprint'], context['original_paths'], context['preserved']
    report = dict(disposable_fixture_only=True, changed_store_recovery_certified=False,
        healthy_backup_refused=False, healthy_replacement_refused=False,
        supervisor_only_killed=False, native_survived=False, gateway_survived=False,
        original_port_backup_refused=False, fresh_ports_only_changed=False,
        real_dump_barrier_reached=False, active_backup_excludes_other_backup=False, native_offer_committed_during_backup=False,
        native_offer_read_back=False, native_anchor_before_zero=False, native_anchor_during_one=False,
        postgres_snapshot_changed=False, backup_reported_success=False, real_custom_dump_completed=False,
        orphan_writer_overlapped_backup=False, original_tokens_preserved=False,
        held_qr_preserved=False, original_files_preserved=False, owned_groups_stopped=False,
        owned_listeners_closed=False, database_sessions_stopped=False,
        cold_backup_success=False, cold_backup_exact_package=False, cold_backup_sql_unchanged=False,
        cold_backup_originals_preserved=False, cold_backup_group_stopped=False,
        fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    f['receipt']['stopped_writer_recovery'] = report
    probe = workspace / 'stopped-writer-recovery-probe'
    probe.mkdir(mode=0o700)
    bin_dir = probe / 'bin'
    bin_dir.mkdir(mode=0o700)
    entered, release = probe / 'dump-entered', probe / 'dump-release'
    real_dump = Path(f['tools']) / 'usr/lib/postgresql/18/bin/pg_dump'
    client_lib = Path(f['tools']) / 'usr/lib/x86_64-linux-gnu'
    check(real_dump.is_file() and not real_dump.is_symlink() and client_lib.is_dir(),
          'stopped writer probe uses the owned matching real PostgreSQL18 client')
    expected_dump = probe / 'stopped-writer-fresh-port-backup/postgresql.dump'
    wrapper = bin_dir / 'pg_dump'
    wrapper.write_text('#!/usr/bin/env python3\n' +
        'import os,sys,time\nfrom pathlib import Path\n' +
        'real=' + repr(str(real_dump)) + '\nexpected=' + repr(str(expected_dump)) + '\n' +
        'entered=Path(' + repr(str(entered)) + ')\nrelease=Path(' + repr(str(release)) + ')\n' +
        'if sys.argv[1:]==["--version"]:\n    os.execve(real,[real,*sys.argv[1:]],os.environ)\n' +
        'if len(sys.argv)!=5 or sys.argv[1:4]!=["--format=custom","--no-owner","--file"] or sys.argv[4]!=expected:\n    raise SystemExit(79)\n' +
        'entered.write_text("real client barrier entered")\n' +
        'deadline=time.monotonic()+240\n' +
        'while not release.exists():\n    if time.monotonic()>=deadline: raise SystemExit(80)\n    time.sleep(.05)\n' +
        'os.execve(real,[real,*sys.argv[1:]],os.environ)\n')
    wrapper.chmod(0o700)
    backup_env = dict(local, PATH=str(bin_dir) + os.pathsep + local['PATH'],
                      LD_LIBRARY_PATH=str(client_lib), PYTHONDONTWRITEBYTECODE='1')
    actual_version = subprocess.run([str(real_dump), '--version'], env=backup_env,
        capture_output=True, timeout=10)
    wrapped_version = subprocess.run([str(wrapper), '--version'], env=backup_env,
        capture_output=True, timeout=10)
    check(actual_version.returncode == wrapped_version.returncode == 0
          and actual_version.stdout == wrapped_version.stdout and b' 18.' in actual_version.stdout
          and not entered.exists(), 'owned pg_dump barrier forwards the matching real client version unchanged')
    check(hashlib.sha256(real_dump.read_bytes()).hexdigest()
          == f['receipt']['pg18_distribution']['clients']['pg_dump']['sha256'],
          'stopped writer probe binds the previously verified pg_dump executable bytes')
    supervisor, backup = None, None
    captured, tracked = [], []
    old_ports, fresh_ports = None, None

    def start_backup(label, config_path, command_env=None):
        destination = probe / label
        command = [str(f['root_python']), '-B', str(app / 'deploy/release/package.py'), 'backup',
            '--package', str(f['package']), '--config', str(config_path), '--output', str(destination),
            '--acknowledge-quiesced']
        process = f['start'](command, backup_env if command_env is None else command_env, label)
        tracked.append(process)
        return process, destination

    def native_count(title, key):
        return observe('sql', statements=[("SELECT COUNT(*) FROM public.anchors WHERE arch_type='Offer' "
            "AND props->'archetype'->>'title'=%s AND props->'archetype'->>'create_key'=%s", [title, key])])[0][0][0]

    def session_count():
        return observe('sql', statements=[('SELECT COUNT(*) FROM pg_catalog.pg_stat_activity '
            'WHERE datname=current_database() AND pid<>pg_backend_pid()', [])])[0][0][0]

    try:
        supervisor, gateway, merchant = context['launch']('stopped-writer-owned-launch')
        old_ports = (f['config']['backend_port'], f['config']['gateway_port'])
        owner = _process(supervisor.pid)
        check(owner is not None and owner['uid'] == os.getuid() and owner['group'] == owner['session'] == supervisor.pid
              and Path(owner['cwd']) == app, 'stopped writer probe captures its exact live supervisor identity')
        child_ids = [int(value) for value in (Path('/proc') / str(supervisor.pid) / 'task' / str(supervisor.pid) / 'children').read_text().split()]
        children = [_process(pid) for pid in child_ids]
        check(len(children) == 2 and all(row is not None and row['uid'] == os.getuid() and row['state'] != 'Z' and row['parent'] == supervisor.pid
              and row['group'] == row['session'] == row['pid'] and Path(row['cwd']) == app for row in children),
              'stopped writer probe captures only its two owned native and gateway child groups')
        native = next((row for row in children if row['argv'][:2] == [str(Path(f['package']) / 'runtime/jac').encode(), b'run']), None)
        gateway_child = next((row for row in children if row['argv'][1:2] == [str(app / 'scripts/hosted-gateway.mjs').encode()]), None)
        check(native is not None and gateway_child is not None and native['pid'] != gateway_child['pid'],
              'captured child commands match only the fixture native Jac and gateway entry points')
        captured = [_group_members(row['group']) for row in (native, gateway_child)]
        check(all(group and all(member['uid'] == os.getuid() and Path(member['cwd']) == app for member in group) for group in captured),
              'all captured serving group members belong to the canonical fixture cwd')
        baseline = observe('snapshot')
        healthy, healthy_destination = start_backup('stopped-writer-healthy-backup', f['config_file'])
        report['healthy_backup_refused'] = healthy.wait(timeout=60) != 0 and not healthy_destination.exists() and not entered.exists()
        check(report['healthy_backup_refused'], 'healthy launcher ownership blocks actual coordinated backup before pg_dump')
        duplicate = f['start'](context['launch_args'], local, 'stopped-writer-healthy-replacement')
        tracked.append(duplicate)
        report['healthy_replacement_refused'] = duplicate.wait(timeout=60) != 0 and not f['process_group_alive'](duplicate)
        check(report['healthy_replacement_refused'] and observe('snapshot') == baseline,
              'healthy launcher ownership blocks a real second launcher without SQL mutation')
        check(_same(owner, _process(supervisor.pid)) and all(_same(row, _process(row['pid'])) for row in children),
              'only the pre-captured supervisor is selected for the crash witness')
        os.kill(supervisor.pid, signal.SIGKILL)
        report['supervisor_only_killed'] = supervisor.wait(timeout=15) == -signal.SIGKILL
        current_native, current_gateway = _process(native['pid']), _process(gateway_child['pid'])
        report['native_survived'] = _same(native, current_native) and current_native['state'] != 'Z' and not f['closed'](old_ports[0])
        report['gateway_survived'] = _same(gateway_child, current_gateway) and current_gateway['state'] != 'Z' and not f['closed'](old_ports[1])
        check(report['supervisor_only_killed'] and report['native_survived'] and report['gateway_survived'],
              'killing only the known supervisor leaves its original native and gateway serving groups alive')
        api = f['Api']('http://127.0.0.1:' + str(old_ports[0]), f['merchant_token'])
        tokens_before = all(f['Api'](api.origin, f[role + '_token']).call('current_session').get('actor_id') == f[role + '_actor']
                            for role in ('student', 'merchant', 'historical'))
        held_before = api.call('resolve_claim', qr_payload=context['held']['qr_payload'])
        check(tokens_before and session_count() > 0,
              'orphan native process retains original authenticated actors and a real database session')
        old, old_destination = start_backup('stopped-writer-original-port-backup', f['config_file'])
        report['original_port_backup_refused'] = old.wait(timeout=60) != 0 and not old_destination.exists() and not entered.exists()
        check(report['original_port_backup_refused'], 'old occupied ports block actual backup after supervisor death')
        fresh = dict(f['config'], backend_port=f['next_port'](), gateway_port=f['next_port']())
        fresh_ports = (fresh['backend_port'], fresh['gateway_port'])
        report['fresh_ports_only_changed'] = all(fresh[key] == f['config'][key] for key in fresh if key not in ('backend_port', 'gateway_port'))
        check(report['fresh_ports_only_changed'] and fresh_ports[0] != fresh_ports[1]
              and all(f['closed'](port) for port in fresh_ports),
              'fresh-port backup retains the exact canonical source durable root and database with unused ports')
        fresh_config = probe / 'fresh-ports.json'
        fresh_config.write_text(json.dumps(fresh))
        title, key = 'Stopped writer native offer ' + secrets.token_hex(8), secrets.token_hex(16)
        report['native_anchor_before_zero'] = native_count(title, key) == 0
        before_dump = observe('snapshot')
        backup, destination = start_backup('stopped-writer-fresh-port-backup', fresh_config)
        deadline = time.monotonic() + 60
        while not entered.exists() and backup.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
        report['real_dump_barrier_reached'] = entered.is_file() and backup.poll() is None
        check(report['real_dump_barrier_reached'], 'same-store fresh-port backup reaches its owned real pg_dump barrier while the orphan writer lives')
        contender, contender_destination = start_backup('stopped-writer-active-backup-contender', fresh_config)
        report['active_backup_excludes_other_backup'] = contender.wait(timeout=60) != 0 and not contender_destination.exists() and backup.poll() is None
        check(report['active_backup_excludes_other_backup'],
              'the actual paused backup excludes another actual backup before destination creation or pg_dump')
        check(session_count() > 0 and _same(native, _process(native['pid'])),
              'native database session remains live before the paused real dump starts')
        now = datetime.now(ZoneInfo('America/Detroit'))
        result = api.call('save_offer', offer_id='', create_key=key, title=title,
            description='Disposable stopped-writer recovery witness', price='3.00', regular_price='5.00',
            start_local=(now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M'),
            end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='2',
            eligibility='Fixture student', terms='Synthetic stopped-writer witness', dietary='', menu_item='')
        report['native_offer_read_back'] = bool(result.get('ok')) and any(row.get('id') == result.get('code') for row in api.call('merchant_portal').get('offers', []))
        report['native_anchor_during_one'] = native_count(title, key) == 1
        report['postgres_snapshot_changed'] = observe('snapshot') != before_dump
        report['native_offer_committed_during_backup'] = bool(result.get('ok')) and report['native_anchor_before_zero'] and report['native_anchor_during_one'] and backup.poll() is None
        report['orphan_writer_overlapped_backup'] = report['real_dump_barrier_reached'] and report['native_offer_committed_during_backup']
        check(report['native_offer_read_back'] and report['native_offer_committed_during_backup'] and report['postgres_snapshot_changed'],
              'direct orphan native save_offer commits one independently observed public Offer while real backup is paused')
        release.write_text('release matching real pg_dump')
        report['backup_reported_success'] = backup.wait(timeout=180) == 0
        dump = destination / 'postgresql.dump'
        report['real_custom_dump_completed'] = report['backup_reported_success'] and dump.is_file() and dump.read_bytes()[:5] == b'PGDMP'
        check(report['real_custom_dump_completed'], 'actual matching pg_dump completes a real custom archive after the overlapping native commit')
        f['pkg'].verify_recovery_set(destination)
        report['original_tokens_preserved'] = all(f['Api'](api.origin, f[role + '_token']).call('current_session').get('actor_id') == f[role + '_actor']
                                                for role in ('student', 'merchant', 'historical'))
        held_after = api.call('resolve_claim', qr_payload=context['held']['qr_payload'])
        report['held_qr_preserved'] = held_before.get('ok') is True and held_after.get('ok') is True and held_before.get('claim_id') == held_after.get('claim_id') == context['held']['claim_id']
        report['original_files_preserved'] = fingerprint(originals) == preserved
        check(report['original_tokens_preserved'] and report['held_qr_preserved'] and report['original_files_preserved'],
              'overlap witness preserves original held QR actors SQLite signing keys and original photos')
    finally:
        release.touch(exist_ok=True)
        process_cleanup = True
        for process in reversed(tracked):
            try:
                f['stop_process'](process)
            except (OSError, RuntimeError, AssertionError, subprocess.SubprocessError):
                process_cleanup = False
        group_results = []
        for group in reversed(captured):
            try:
                group_results.append(_stop_captured(group))
            except (OSError, RuntimeError, ValueError):
                group_results.append(False)
        if supervisor is not None:
            try:
                f['stop_process'](supervisor)
            except (OSError, RuntimeError, AssertionError, subprocess.SubprocessError):
                process_cleanup = False
        report['owned_groups_stopped'] = process_cleanup and bool(captured) and all(group_results)
        report['owned_listeners_closed'] = all(f['closed'](port) for pair in (old_ports, fresh_ports) if pair is not None for port in pair)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if session_count() == 0:
                    report['database_sessions_stopped'] = True
                    break
                time.sleep(.2)
        except (OSError, RuntimeError, AssertionError, subprocess.SubprocessError, ValueError):
            report['database_sessions_stopped'] = False
        report['original_files_preserved'] = fingerprint(originals) == preserved
        print('EVIDENCE stopped_writer_recovery ' + json.dumps(report, sort_keys=True), flush=True)
    check(report['owned_groups_stopped'] and report['owned_listeners_closed'] and report['database_sessions_stopped']
          and report['original_files_preserved'], 'stopped writer recovery probe cleans every captured serving group listener and database session')
    # Cold control uses the same supported backup CLI after genuine quiescence,
    # with the matching real client directly, not the previously paused wrapper.
    cold_before = observe('snapshot')
    cold_env = dict(local, PATH=str(real_dump.parent) + os.pathsep + local['PATH'],
                    LD_LIBRARY_PATH=str(client_lib), PYTHONDONTWRITEBYTECODE='1')
    cold, cold_destination = start_backup('stopped-writer-cold-control', fresh_config, cold_env)
    try:
        cold_code = cold.wait(timeout=180)
        cold_dump = cold_destination / 'postgresql.dump'
        report['cold_backup_success'] = cold_code == 0 and cold_dump.is_file() and cold_dump.read_bytes()[:5] == b'PGDMP'
        if report['cold_backup_success']:
            recovery = f['pkg'].verify_recovery_set(cold_destination)
            report['cold_backup_exact_package'] = recovery['canonical_entry'] == f['config']['canonical_entry'] and recovery['package_manifest_sha256'] == f['pkg'].digest(Path(f['package']) / 'manifest.json')
        report['cold_backup_sql_unchanged'] = observe('snapshot') == cold_before
        report['cold_backup_originals_preserved'] = fingerprint(originals) == preserved
    finally:
        try:
            f['stop_process'](cold)
            report['cold_backup_group_stopped'] = not f['process_group_alive'](cold)
        finally:
            print('EVIDENCE stopped_writer_recovery_final ' + json.dumps(report, sort_keys=True), flush=True)
    check(report['cold_backup_success'] and report['cold_backup_exact_package']
          and report['cold_backup_sql_unchanged'] and report['cold_backup_originals_preserved']
          and report['cold_backup_group_stopped'],
          'genuinely stopped native writers allow a real exact-package cold backup without original state mutation')
    check(not report['orphan_writer_overlapped_backup'],
          'strict stopped-writer recovery gate refuses every backup overlapping an orphan native graph writer')
