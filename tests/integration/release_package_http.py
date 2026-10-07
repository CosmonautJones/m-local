"""Private, disposable packaged startup and authenticated logical recovery drill."""
import argparse
from datetime import datetime, timedelta
import getpass
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--durable-base', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        raise RuntimeError('Fresh receipt required')
    spec = importlib.util.spec_from_file_location('package_tool', args.package / 'source/deploy/release/package.py')
    pkg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pkg)
    manifest = pkg.verify_package(args.package)
    helpers = args.package / 'source/tests/integration'
    sys.path.insert(0, str(helpers))
    from recovery_http import Api, PHOTO_PAYLOAD, process_group_alive, stop_process
    from native_hardening_http import free_port
    from smtp_sink import SmtpSink
    workspace = Path(tempfile.mkdtemp(prefix='m-local-package-live.', dir=args.durable_base))
    workspace.chmod(0o700)
    app, onboarding = workspace / 'app', workspace / 'onboarding'
    pg_bin = args.tools / 'usr/lib/postgresql/16/bin'
    environment = {k: v for k, v in os.environ.items() if not k.startswith(('MLOCAL_', 'JAC_')) and k not in ('PYTHONPATH', 'JACPATH')}
    environment.update(PATH=str(pg_bin) + ':' + os.environ['PATH'],
        LD_LIBRARY_PATH=str(args.tools / 'usr/lib/x86_64-linux-gnu'),
        PGHOST='127.0.0.1', PGPORT=str(free_port()), PGUSER=getpass.getuser(),
        NO_PROXY='127.0.0.1,localhost,::1', no_proxy='127.0.0.1,localhost,::1',
        JAC_CACHE_HOME=str(workspace / 'runtime-cache'), MLOCAL_ENV='development',
        MLOCAL_ONBOARDING_DIR=str(onboarding), MLOCAL_SHOW_SAMPLES='0',
        MLOCAL_DEMO_MODE='false', MLOCAL_DEMO_COMPANIES='0', MLOCAL_DEMO_STUDENTS='[]',
        MLOCAL_HOSTED_DATASET='false')
    os.environ.update(environment)
    processes, checks = [], []
    pg_started, sink_closed, sink = False, False, None
    receipt = {'verdict': 'BLOCKED', 'source_sha': manifest['source_sha'],
        'fixture_sha256': pkg.digest(Path(__file__).resolve()),
        'source_tree': manifest['source_tree'], 'manifest_sha256': pkg.digest(args.package / 'manifest.json'),
        'official_runtime': manifest['runtime'], 'disposable_fixture_only': True,
        'live_deployment': False, 'external_email': False, 'hosted_acceptance': False,
        'checks': checks}
    phase = 'initialization'

    def check(value, label):
        nonlocal phase
        phase = label
        if not value:
            raise AssertionError(label)
        checks.append(label)
        print('PASS ' + label, flush=True)

    def command(*command_args):
        result = subprocess.run(command_args, env=environment, capture_output=True, timeout=120)
        if result.returncode:
            (workspace / ('command-' + secrets.token_hex(4) + '.log')).write_bytes(result.stdout + result.stderr)
            raise RuntimeError('Disposable command failed; protected logs retained')
        return result.stdout

    def start(command_args, env, label):
        with (workspace / (label + '.log')).open('wb') as log:
            proc = subprocess.Popen(command_args, cwd=app, env=env, stdout=log,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        processes.append(proc)
        return proc

    def ready(proc, origin, gateway=False):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                if gateway:
                    with urllib.request.urlopen(origin + '/healthz', timeout=5) as response:
                        if json.load(response).get('ready') is True:
                            return Api(origin)
                elif Api(origin).call('current_session').get('authenticated') is False:
                    return Api(origin)
            except (OSError, RuntimeError, ValueError, urllib.error.URLError):
                pass
            time.sleep(.5)
        raise RuntimeError('Owned packaged server failed readiness; protected logs retained')

    def closed(port):
        with socket.socket() as probe:
            probe.settimeout(.5)
            return probe.connect_ex(('127.0.0.1', port)) != 0

    def interrupted(signum, frame):
        raise SystemExit(128 + signum)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)

    try:
        pkg.install_source(args.package, app)
        (app / 'assets/photos').mkdir(parents=True, exist_ok=True)
        pkg.verify_installed_source(args.package, {'canonical_entry': str(app / 'main.jac'),
            'durable_root': str(workspace), 'onboarding_dir': str(onboarding),
            'native_signing_file': str(app / '.jac/data/jwt_secret'), 'photos_dir': str(app / 'assets/photos'),
            'backend_port': 18840, 'gateway_port': 18841, 'topology': 'single-instance-serialized', 'replicas': 1}, require_marker=True)
        check(True, 'complete packaged source and offline libraries install with exact source marker')
        command(str(pg_bin / 'initdb'), '-D', str(workspace / 'postgres'), '--auth=trust', '--no-locale', '--encoding=UTF8',
            '-L', str(args.tools / 'usr/share/postgresql/16'))
        (workspace / 'pg-socket').mkdir(mode=0o700)
        command(str(pg_bin / 'pg_ctl'), '-D', str(workspace / 'postgres'), '-l', str(workspace / 'postgres.log'),
            '-o', '-h 127.0.0.1 -p ' + environment['PGPORT'] + ' -k ' + str(workspace / 'pg-socket'), '-w', 'start')
        pg_started = True
        command(str(pg_bin / 'createdb'), 'package_original')
        command(str(pg_bin / 'createdb'), 'package_restored')
        connection_base = 'postgresql://' + quote(environment['PGUSER'], safe='') + '@127.0.0.1:' + environment['PGPORT'] + '/'
        environment['JAC_DB_URL'] = connection_base + 'package_original'
        os.environ.update(environment)
        backend_port, gateway_port = free_port(), free_port()
        config = dict(canonical_entry=str(app / 'main.jac'), durable_root=str(workspace), onboarding_dir=str(onboarding),
            native_signing_file=str(app / '.jac/data/jwt_secret'), photos_dir=str(app / 'assets/photos'),
            backend_port=backend_port, gateway_port=gateway_port, topology='single-instance-serialized', replicas=1)
        config_file = workspace / 'config.json'
        config_file.write_text(json.dumps(config))
        runtime = args.package / 'runtime/jac'
        sink = SmtpSink(workspace / 'smtp')
        with sink:
            environment.update(MLOCAL_SMTP_HOST='127.0.0.1', MLOCAL_SMTP_PORT=str(sink.port), MLOCAL_SMTP_FROM=sink.sender,
                MLOCAL_SMTP_USERNAME=sink.username, MLOCAL_SMTP_PASSWORD=sink.password, SSL_CERT_FILE=str(sink.ca_file))
            os.environ.update(environment)
            dev = start([str(runtime), 'run', '--no-dev', '--no-client', '--host', '127.0.0.1', '--port', str(backend_port)], environment, 'seed')
            anonymous = ready(dev, 'http://127.0.0.1:' + str(backend_port))

            def account(value, kind, name):
                address = value + '@umich.edu' if kind == 'student' else value
                sink.allow(address)
                requested = anonymous.call('request_email_code', value=value, kind=kind, name=name)
                check(requested.get('ok'), 'disposable account request reaches only the local TLS mail sink')
                verified = anonymous.call('verify_email_code', challenge=requested['challenge'], code=sink.take_code(address, timeout=10))
                check(verified.get('ok') and verified.get('token'), 'packaged passwordless provisioning preserves native actor keys')
                return verified['token']

            run = secrets.token_hex(5)
            student_token = account('packstudent' + run, 'student', 'Disposable package student')
            historical_token = account('packhistory' + run, 'student', 'Disposable historical student')
            merchant_token = account('packmerchant' + run + '@example.test', 'business', 'Disposable package merchant')
            student, merchant = Api(anonymous.origin, student_token), Api(anonymous.origin, merchant_token)
            historical = Api(anonymous.origin, historical_token)
            student_actor, merchant_actor = student.call('current_session')['actor_id'], merchant.call('current_session')['actor_id']
            historical_actor = historical.call('current_session')['actor_id']
            fields = dict(name='Disposable Package Cafe', cuisine='Cafe', description='Fictional package recovery fixture',
                address='123 Fixture Street', website='', menu_text='', menu_url='', image_url='', confirmed=True)
            check(merchant.call('save_business_draft', **fields)['status'] == 'pending_review', 'package keeps manual business admission')
            sys.path.insert(0, str(app))
            os.chdir(app)
            from services.email_codes import CodeStore, business_revision
            state = CodeStore(onboarding)
            state.approve_business(merchant_actor, 'Fixture operator', 'Disposable review only', business_revision(state.draft(merchant_actor)))
            check(merchant.call('save_business_draft', **fields)['status'] == 'active', 'disposable approved merchant owns its original business')
            photo = merchant.call('upload_business_photo', payload=PHOTO_PAYLOAD)
            check(photo.get('ok'), 'original merchant uploads a real owned JPEG into packaged storage')
            now = datetime.now(ZoneInfo('America/Detroit'))
            offer = merchant.call('save_offer', offer_id='', create_key=secrets.token_hex(16), title='Disposable packaged offer',
                description='Original package snapshot', price='3.00', regular_price='5.00',
                start_local=(now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M'),
                end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='3', eligibility='Fixture student',
                terms='Original package terms', dietary='', menu_item='')
            check(offer.get('ok'), 'original approved merchant publishes one dedicated offer')
            claim = student.call('claim_offer', offer_id=offer['code'])
            check(claim.get('ok') and claim.get('qr_payload'), 'original student holds an authenticated claim snapshot')
            historical_claim = historical.call('claim_offer', offer_id=offer['code'])
            check(historical_claim.get('ok') and merchant.call('redeem_claim', qr_payload=historical_claim['qr_payload']).get('ok'),
                'separate original student has a redeemed claim before backup')
            stop_process(dev)
            keys = {name: pkg.digest(path) for name, path in {'code': onboarding / 'code.key', 'jwt': app / '.jac/data/jwt_secret'}.items()}
            original_inventory = pkg.state_inventory(config)
            pkg.install_source(args.package, app, dry_run=True)
            pkg.install_source(args.package, app)
            check(pkg.state_inventory(config) == original_inventory, 'real source dry-run and reinstall preserve existing private stores keys and photos')
            try:
                pkg.require_launch_evidence(config, manifest, pkg.read_json(args.package / 'source/deploy/release/evidence.example.json'))
            except pkg.ReleaseError:
                check(True, 'unchanged default release evidence refuses rollout')
            else:
                raise AssertionError('Default release evidence unexpectedly allows rollout')
            # These assertions grant only a private test fixture launch; they are
            # never exported as approval or hosted runtime acceptance evidence.
            test_evidence = {'disposable_fixture_only': True, 'operator_rollout_approved': True,
                'runtime_safety': dict(verdict='PASS', jac_version=pkg.PIN, topology=config['topology'],
                    source_sha=manifest['source_sha'], jac_sha256=manifest['runtime']['jac'],
                    cases={case: True for case in pkg.REQUIRED_CASES}),
                'host_acceptance': dict(canonical_entry=config['canonical_entry'], durable_storage=True,
                    private_backend=True, exclusive_ingress=True, nonoverlapping_rollout=True)}
            evidence_file = workspace / 'disposable-test-evidence.json'
            evidence_file.write_text(json.dumps(test_evidence))
            environment.update(MLOCAL_INGRESS='restricted-edge', MLOCAL_TRUSTED_HTTPS_EDGE='1')
            os.environ.update(environment)

            def production(label, held=True, redeem_held=False):
                nonlocal phase
                phase = label + ' meaningful readiness'
                proc = start([str(args.package / 'runtime/jacpython'), '-c',
                    'import runpy,sys;sys.argv.pop(0);runpy.run_path(sys.argv[0],run_name="__main__")',
                    str(app / 'deploy/release/package.py'), 'run',
                    '--package', str(args.package), '--config', str(config_file), '--evidence', str(evidence_file)], environment, label)
                api = ready(proc, 'http://127.0.0.1:' + str(gateway_port), gateway=True)
                check(Api(api.origin, student_token).call('current_session')['actor_id'] == student_actor,
                    label + ' preserves original student token and actor')
                check(Api(api.origin, merchant_token).call('current_session')['actor_id'] == merchant_actor,
                    label + ' preserves original merchant token and actor')
                merchant_api = Api(api.origin, merchant_token)
                check(Api(api.origin, historical_token).call('current_session')['actor_id'] == historical_actor,
                    label + ' preserves original redeemed-claim owner token and actor')
                detail = Api(api.origin, student_token).call('get_offer', offer_id=offer['code'])
                check(detail.get('my_claim_id') == claim['claim_id'] and detail.get('my_terms') == 'Original package terms'
                    and detail.get('my_status') == ('claimed' if held else 'redeemed')
                    and (not held or detail.get('my_qr_payload') == claim['qr_payload']),
                    label + ' preserves original claim identity status and snapshot')
                historical_detail = Api(api.origin, historical_token).call('get_offer', offer_id=offer['code'])
                check(historical_detail.get('my_claim_id') == historical_claim['claim_id']
                    and historical_detail.get('my_status') == 'redeemed' and historical_detail.get('my_terms') == 'Original package terms',
                    label + ' preserves original redeemed claim identity and snapshot')
                check(not merchant_api.call('redeem_claim', qr_payload=historical_claim['qr_payload']).get('ok'),
                    label + ' refuses another redemption of original redeemed QR')
                check(not Api(api.origin, historical_token).call('resolve_claim', qr_payload=claim['qr_payload']).get('ok'),
                    label + ' keeps other student unable to inspect original QR')
                check(any(row['id'] == offer['code'] for row in merchant_api.call('merchant_portal')['offers']),
                    label + ' retains original merchant ownership of published offer')
                with urllib.request.urlopen(api.origin + photo['url'], timeout=10) as response:
                    check(response.status == 200 and response.read().startswith(b'\xff\xd8'), label + ' serves the original owned JPEG')
                with urllib.request.urlopen(api.origin + '/', timeout=10) as response:
                    check(response.status == 200 and b'<script' in response.read(), label + ' serves the compiled client')
                for path in ('/user/register', '/user/login', '/healthz/ready'):
                    try:
                        urllib.request.urlopen(api.origin + path, timeout=5)
                    except urllib.error.HTTPError as error:
                        check(error.code == 403, label + ' denies public native path ' + path)
                    else:
                        raise AssertionError('Public native route exposed')
                if redeem_held:
                    check(merchant_api.call('redeem_claim', qr_payload=claim['qr_payload']).get('ok')
                        and not merchant_api.call('redeem_claim', qr_payload=claim['qr_payload']).get('ok'),
                        label + ' redeems restored held QR exactly once')
                    check(Api(api.origin, student_token).call('get_offer', offer_id=offer['code']).get('my_status') == 'redeemed',
                        label + ' reports restored redemption to original student')
                if not held:
                    check(not merchant_api.call('redeem_claim', qr_payload=claim['qr_payload']).get('ok'),
                        label + ' retains single-use refusal across subsequent restart')
                stop_process(proc)
                check(not process_group_alive(proc) and closed(backend_port) and closed(gateway_port),
                    label + ' TERM stops supervisor both children and both listeners')

            production('packaged-startup')
            backup = workspace / 'recovery-set'
            pkg.coordinated_backup(config, backup, args.package)
            pkg.verify_recovery_set(backup)
            check(True, 'actual PostgreSQL graph identity and private stores produce a complete verified recovery set')
            # Preserve the entire original source/stores and original database.
            # Recreate only the same canonical source path and restore into the
            # separate, empty private database; no original data is deleted.
            app.rename(workspace / 'retained-original-app')
            onboarding.rename(workspace / 'retained-original-onboarding')
            pkg.install_source(args.package, app)
            os.environ['MLOCAL_RECOVERY_DB_URL'] = connection_base + 'package_restored'
            pkg.coordinated_restore(backup, config, args.package)
            check(pkg.state_inventory(config) == original_inventory, 'logical restore retains all original private bytes and SQLite row counts')
            environment['JAC_DB_URL'] = connection_base + 'package_restored'
            os.environ.update(environment)
            production('packaged-restored-startup', redeem_held=True)
            production('packaged-post-redemption-restart', held=False)
            check(all(pkg.digest(path) == keys[name] for name, path in {'code': onboarding / 'code.key', 'jwt': app / '.jac/data/jwt_secret'}.items()),
                'restored startup never replaces original native and email signing keys')
        sink_closed = sink.closed
        check(sink_closed, 'owned local TLS SMTP fixture closes')
        receipt['verdict'] = 'PASS'
    except BaseException as error:
        receipt.update(failure_phase=phase, failure_type=type(error).__name__)
        raise
    finally:
        cleanup_errors = []
        for process in reversed(processes):
            try:
                stop_process(process)
            except (OSError, RuntimeError, AssertionError, subprocess.SubprocessError):
                cleanup_errors.append('owned process shutdown')
        if pg_started or (workspace / 'postgres/postmaster.pid').exists():
            try:
                command(str(pg_bin / 'pg_ctl'), '-D', str(workspace / 'postgres'), '-m', 'fast', '-w', 'stop')
            except (OSError, RuntimeError, subprocess.SubprocessError):
                cleanup_errors.append('owned PostgreSQL shutdown')
        sink_closed = sink.closed if sink is not None else True
        receipt['cleanup'] = dict(owned_groups_stopped=all(not process_group_alive(p) for p in processes),
            private_postgres_stopped=not (workspace / 'postgres/postmaster.pid').exists(), local_mail_sink_closed=sink_closed)
        if cleanup_errors or not all(receipt['cleanup'].values()):
            receipt['verdict'] = 'BLOCKED'
            receipt['cleanup_errors'] = cleanup_errors
        receipt['retained_private_fixture'] = str(workspace)
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump(receipt, stream, indent=2)
            stream.write('\n')


if __name__ == '__main__':
    main()
