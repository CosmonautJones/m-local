"""Disposable official-runtime startup, identity preservation and ingress proof.

Uses real native /user/register and /user/login, application HTTP and local TLS
SMTP. No external recipients, hosted state, runtime fork or production data.
Production startup additionally needs an explicit mounted disposable-state base.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
import os
import platform
from pathlib import Path
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from recovery_http import (Api, copy_application, digest, input_manifest, private_dir,
                           process_group_alive, run_logged, scrub_environment,
                           stable_json, stop_process)
from smtp_sink import SmtpSink

ROOT = Path(__file__).resolve().parents[2]
CHECKS = []
PHASE = 'preflight'
# Official v0.37.23 Linux x86_64 asset .sha256 files, retained with the evidence.
OFFICIAL_JAC_SHA256 = '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
OFFICIAL_JACPYTHON_SHA256 = '198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542'


def check(value, label):
    global PHASE
    PHASE = label
    if not value:
        raise AssertionError(label)
    CHECKS.append(label)
    print('PASS ' + label, flush=True)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def post(origin, path, payload):
    request = urllib.request.Request(origin + path, json.dumps(payload).encode(),
        {'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, {}


def parallel(functions):
    barrier = threading.Barrier(len(functions))
    def invoke(function):
        barrier.wait(timeout=15)
        return function()
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        futures = [pool.submit(invoke, function) for function in functions]
        return [future.result(timeout=45) for future in futures]


def main():
    global PHASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--durable-base', type=Path, required=True,
        help='Existing mounted, writable disposable-state base; never a live application volume')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if args.receipt:
        args.receipt = args.receipt.resolve()
    if sys.platform != 'linux' or platform.machine() != 'x86_64' or os.geteuid() == 0:
        raise RuntimeError('Fixture requires an unprivileged Linux x86_64 user')
    if os.environ.get('JAC_DB_URL') or os.environ.get('JAC_DEV_SOURCE'):
        raise RuntimeError('Fixture refuses inherited graph database or runtime overrides')
    jac = Path(os.environ['JAC_BIN']).resolve()
    version = subprocess.check_output([str(jac), '--version'], timeout=30, text=True).strip()
    if version.split()[:2] != ['jac', '0.37.23']:
        raise RuntimeError('Fixture requires official Jac 0.37.23')
    jacpython = Path(str(jac) + 'python')
    if digest(jac) != OFFICIAL_JAC_SHA256 or not jacpython.is_file() or digest(jacpython) != OFFICIAL_JACPYTHON_SHA256:
        raise RuntimeError('Fixture requires exact official Jac and JacPython release checksums, not a version-string-compatible fork')
    os.umask(0o077)
    workspace = Path(tempfile.mkdtemp(prefix='m-local-native-hardening.', dir='/var/tmp'))
    workspace.chmod(0o700)
    workspace_identity = workspace.stat()
    app, cache = workspace / 'app', workspace / 'cache'
    private_dir(app)
    private_dir(cache)
    private_dir(cache / 'tmp')
    copy_application(ROOT, app)
    source_manifest = input_manifest(app)
    source_hash = hashlib.sha256(stable_json(source_manifest)).hexdigest()
    durable = Path(tempfile.mkdtemp(prefix='m-local-hardening-state.', dir=args.durable_base.resolve()))
    durable_identity = durable.stat()
    durable.chmod(0o700)
    onboarding = durable / 'onboarding'
    private_dir(onboarding)
    private_dir(durable / 'native')
    private_dir(durable / 'photos')
    (app / '.jac').mkdir()
    (app / '.jac/data').symlink_to(durable / 'native', target_is_directory=True)
    (app / 'assets/photos').symlink_to(durable / 'photos', target_is_directory=True)
    environment = scrub_environment(jac, cache, onboarding)
    for name in ('JAC_DATA_PATH', 'JAC_SERVE_AUTH_SECRET', 'JAC_SERVE_AUTH_ALGORITHM'):
        environment.pop(name, None)
    environment['MLOCAL_ENV'] = 'development'
    environment['MLOCAL_SHOW_SAMPLES'] = '0'
    # Runtime no-proxy applies to native loopback APIs as well as SMTP.
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,::1'
    from jaclang.data.pgembed import PgRuntime
    # Test the sealed source copy, not a helper that a parallel worker may edit.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(app))
    os.chdir(app)
    from services.email_codes import CodeStore, business_revision
    from services.production_guard import _mounted_volume
    import services.email_codes as copied_codes
    import services.production_guard as copied_guard
    check(Path(copied_codes.__file__).resolve().is_relative_to(app) and
          Path(copied_guard.__file__).resolve().is_relative_to(app),
          'fixture helpers import only the tested source copy')
    if not _mounted_volume(durable):
        raise RuntimeError('Fixture durable-base does not have a writable dedicated persistent mount')
    runtime = PgRuntime(data_dir=str(workspace / 'postgres'), database='native_hardening', tcp=True, port=free_port())
    processes = []
    port, ingress_port = free_port(), free_port()
    origin = 'http://127.0.0.1:' + str(port)
    ingress_origin = 'http://127.0.0.1:' + str(ingress_port)
    active = None

    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)

    def start(env, guarded=False):
        nonlocal active
        log_path = workspace / ('api-' + str(len(processes)) + '.log')
        with log_path.open('wb') as log:
            command = (['bash', 'scripts/production-start.sh'] if guarded else [str(jac), 'run'])
            active = subprocess.Popen(command + ['--no-dev', '--no-client',
                '--host', '127.0.0.1', '--port', str(port)], cwd=app, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(active)
        return active, log_path

    def ready():
        api = Api(origin)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if active.poll() is not None:
                raise RuntimeError('Owned API exited during startup')
            try:
                if api.call('current_session').get('authenticated') is False:
                    feed = api.call('home_feed')
                    if (isinstance(feed, dict) and isinstance(feed.get('items'), list)
                        and isinstance(feed.get('favorites'), list)
                        and isinstance(feed.get('total_deals'), int) and feed['total_deals'] >= 0
                        and all(isinstance(feed.get(flag), bool) for flag in ('signed_in', 'personalized', 'completed'))
                        and all(isinstance(feed.get(text), str) for text in ('price_range', 'note'))):
                        return api
            except (OSError, RuntimeError, urllib.error.URLError):
                pass
            time.sleep(.5)
        raise TimeoutError('Owned API startup deadline')

    def not_listening():
        with socket.socket() as probe:
            probe.settimeout(.5)
            return probe.connect_ex(('127.0.0.1', port)) != 0

    def reject_start(env, label, settings=('MLOCAL_DURABLE_ROOT',), guarded=False):
        process, log_path = start(env, guarded=guarded)
        code = process.wait(timeout=300)
        check(code != 0, label + ' actual server process exits unsuccessfully')
        if guarded:
            check(code == 78, label + ' exits with the configuration refusal status before native startup')
        check(not process_group_alive(process) and not_listening(), label + ' leaves no owned serving child or listener')
        log = log_path.read_text(errors='replace')
        check('M-Local refuses to start' in log and all(name in log for name in settings),
              label + ' reports actionable setting names')
        check(not any(value in log for value in ('hardening-secret-path', 'fixture-db-password', 'hardening-secret-smtp', 'fixture-signing-config-secret')),
              label + ' does not disclose supplied secret values')

    started = time.monotonic()
    try:
        PHASE = 'private dependency installation'
        run_logged(PHASE, [str(jac), 'install', '--no-npm'], app, environment, workspace / 'install.log', 300)
        # Explicit external PostgreSQL means a server DB, not a second embedded store.
        connection = runtime.ensure()
        environment['JAC_DB_URL'] = ('postgresql://' + quote(connection.user, safe='') + ':' +
            quote(connection.password, safe='') + '@127.0.0.1:' + str(connection.port) + '/' + connection.database)
        invalid = {**environment, 'MLOCAL_ENV': 'production', 'MLOCAL_ONBOARDING_DIR': 'hardening-secret-path',
                   'MLOCAL_SMTP_PASSWORD': 'hardening-secret-smtp'}
        reject_start(invalid, 'invalid production configuration')
        PHASE = 'development native startup'
        start(environment, guarded=True)
        anonymous = ready()
        check(True, 'development preflight entry reaches native session and catalog readiness')
        with SmtpSink(workspace / 'smtp') as sink:
            environment.update(MLOCAL_SMTP_HOST='127.0.0.1', MLOCAL_SMTP_PORT=str(sink.port),
                MLOCAL_SMTP_FROM=sink.sender, MLOCAL_SMTP_USERNAME=sink.username,
                MLOCAL_SMTP_PASSWORD=sink.password, SSL_CERT_FILE=str(sink.ca_file))
            stop_process(active)
            start(environment)
            anonymous = ready()
            run = secrets.token_hex(4)
            username = 'preserved' + run
            email = username + '@umich.edu'
            native_password = secrets.token_urlsafe(32)
            payload = dict(identities=[dict(type='email', value=email)],
                credential=dict(type='password', password=native_password), profile=dict(firstname='Native owner'))
            status, registered = post(origin, '/user/register', payload)
            native_data = registered.get('data', {})
            check(status == 201 and registered.get('ok') and native_data.get('token'),
                  'native register reproduces unverified email identity admission')
            original_token = native_data['token']
            native = Api(origin, original_token)
            actor = native.call('current_session')['actor_id']
            check(native.call('current_session')['role'] == 'unverified', 'unverified native registration has no student or merchant authority')
            check(native.call('save_account_profile', display_name='Preserved native preference')['ok'],
                  'native identity has legitimate saved preferences without onboarding')
            state = CodeStore(onboarding)
            key_before = digest(onboarding / 'code.key')
            jwt_before = digest(app / '.jac/data/jwt_secret')

            def request(value, kind='business', name='Hardening fixture'):
                address = value + '@umich.edu' if kind == 'student' else value
                sink.allow(address)
                result = anonymous.call('request_email_code', value=value, kind=kind, name=name)
                check(result.get('ok') and result.get('challenge'), 'email request delivers only to local TLS sink')
                return result['challenge'], sink.take_code(address, timeout=10)

            def verify(value, kind='business'):
                challenge, code = request(value, kind)
                result = anonymous.call('verify_email_code', challenge=challenge, code=code)
                check(result.get('ok') and result.get('token'), 'internal passwordless provisioning remains usable')
                return Api(origin, result['token'])

            # Give the preserved native root real historical app state using only
            # this disposable private store; then simulate a missing recovery row.
            state.remember_account(actor, email, 'student', 'Native owner')
            merchant_email = 'merchant' + run + '@example.test'
            merchant = verify(merchant_email)
            merchant_actor = merchant.call('current_session')['actor_id']
            fields = dict(name='Hardening Fixture Cafe', cuisine='Cafe', description='Fictional preservation test',
                address='123 Fixture Street', website='', menu_text='', menu_url='', image_url='', confirmed=True)
            check(merchant.call('save_business_draft', **fields)['status'] == 'pending_review', 'merchant submission remains private pending manual approval')
            state.approve_business(merchant_actor, 'Fixture operator', 'Fictional authority only', business_revision(state.draft(merchant_actor)))
            check(merchant.call('save_business_draft', **fields)['status'] == 'active', 'manual approval foundation activates one owned merchant')
            now = datetime.now(ZoneInfo('America/Detroit'))
            def offer(title):
                result = merchant.call('save_offer', offer_id='', create_key=secrets.token_hex(16), title=title,
                    description='Fictional preserved terms', price='3.00', regular_price='5.00',
                    start_local=(now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M'),
                    end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='2',
                    eligibility='Fixture student', terms='Preserved original terms', dietary='', menu_item='')
                check(result.get('ok'), 'merchant creates dedicated preservation offer')
                return result['code']
            live_offer, redeemed_offer = offer('Preserved pending claim'), offer('Preserved redeemed claim')
            pending = native.call('claim_offer', offer_id=live_offer)
            redeemed = native.call('claim_offer', offer_id=redeemed_offer)
            check(pending.get('ok') and redeemed.get('ok'), 'native root owns real pending and redeemed claims')
            check(merchant.call('redeem_claim', qr_payload=redeemed['qr_payload'])['ok'], 'merchant redeems one preserved claim once')
            with closing(sqlite3.connect(onboarding / 'onboarding.sqlite3')) as db:
                db.execute('DELETE FROM accounts WHERE actor=?', (actor,))
                db.commit()
            check(state.account(actor) == {}, 'disposable fixture simulates missing onboarding without erasing native graph')
            challenge, code = request(username, 'student')
            answers = parallel([lambda: anonymous.call('verify_email_code', challenge=challenge, code=code) for _ in range(8)])
            check(all(not row.get('ok') and not row.get('token') for row in answers),
                  'eight concurrent collision attempts issue no replacement session')
            replay = anonymous.call('verify_email_code', challenge=challenge, code=code)
            check(not replay.get('ok') and not replay.get('token'), 'repeated collision challenge remains denied')
            status, login = post(origin, '/user/login', dict(identity=dict(type='email', value=email),
                credential=dict(type='password', password=native_password)))
            check(status == 200 and login.get('ok') and login.get('data', {}).get('token'), 'original native credentials remain usable after collision attempts')
            check(Api(origin, login['data']['token']).call('current_session')['actor_id'] == actor,
                  'original native login preserves the exact root identity')
            check(native.call('get_account_profile')['display_name'] == 'Preserved native preference',
                  'preexisting native preferences survive missing-onboarding collision')
            held = native.call('get_offer', offer_id=live_offer)
            used = native.call('get_offer', offer_id=redeemed_offer)
            check(held['my_claim_id'] == pending['claim_id'] and held['my_qr_payload'] == pending['qr_payload'] and
                  held['my_terms'] == 'Preserved original terms', 'pending claim identity credential and snapshots are preserved')
            check(used['my_claim_id'] == redeemed['claim_id'] and used['my_status'] == 'redeemed' and
                  not merchant.call('redeem_claim', qr_payload=redeemed['qr_payload'])['ok'], 'redeemed history remains single use')
            check(merchant.call('current_session')['actor_id'] == merchant_actor and merchant.call('current_session')['role'] == 'merchant',
                  'merchant ownership remains unchanged')
            check(key_before == digest(onboarding / 'code.key') and jwt_before == digest(app / '.jac/data/jwt_secret'),
                  'original onboarding and signing keys are unchanged')
            # Returning proof preserves kind, name, native identity and ownership.
            challenge, code = request(merchant_email, name='Attempted replacement name')
            answers = parallel([lambda: anonymous.call('verify_email_code', challenge=challenge, code=code) for _ in range(8)])
            winners = [row for row in answers if row.get('ok') and row.get('token')]
            check(len(winners) == 1 and Api(origin, winners[0]['token']).call('current_session')['actor_id'] == merchant_actor,
                  'eight returning sign-in attempts consume once and retain the owned root')
            check(state.account(merchant_actor)['name'] == 'Hardening fixture' and state.account(merchant_actor)['kind'] == 'business',
                  'returning email proof preserves saved account kind and name')

            # The ingress denies native handlers while forwarding internal app OTP.
            node = shutil.which('node')
            if not node:
                raise RuntimeError('Native ingress proof requires Node.js')
            gateway_env = {**environment, 'PORT': str(ingress_port), 'MLOCAL_BACKEND_PORT': str(port), 'MLOCAL_INGRESS': 'direct'}
            with (workspace / 'gateway.log').open('wb') as log:
                gateway = subprocess.Popen([node, 'scripts/hosted-gateway.mjs'], cwd=app, env=gateway_env,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            processes.append(gateway)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(ingress_origin + '/healthz', timeout=5) as reply:
                        if json.load(reply).get('ready') is True:
                            break
                except (OSError, urllib.error.URLError):
                    time.sleep(.2)
            else:
                raise TimeoutError('Owned ingress meaningful readiness deadline')
            for path in ('/user/register', '/user/login', '/user/register/challenge', '/graph/data', '/docs', '/admin'):
                check(post(ingress_origin, path, payload)[0] == 403, 'intended ingress denies native/private POST ' + path)
            protected_email = 'ingress' + run + '@example.test'
            sink.allow(protected_email)
            public_api = Api(ingress_origin)
            response = public_api.call('request_email_code', value=protected_email, kind='business', name='Ingress fixture')
            check(response.get('ok') and response.get('challenge'), 'restricted public ingress allows passwordless request')
            response = public_api.call('verify_email_code', challenge=response['challenge'], code=sink.take_code(protected_email, timeout=10))
            check(response.get('ok') and response.get('token'), 'restricted public ingress allows internal passwordless provisioning')
            stop_process(gateway)
            stop_process(active)

            production = {**environment, 'MLOCAL_ENV': 'production', 'MLOCAL_DURABLE_ROOT': str(durable),
                'MLOCAL_PUBLIC_INGRESS': 'restricted', 'MLOCAL_DEPLOYMENT_TOPOLOGY': 'single-instance-serialized', 'MLOCAL_APP_REPLICAS': '1'}
            start(production)
            ready()
            check(True, 'valid production configuration reaches session and catalog readiness')
            check(Api(origin, original_token).call('current_session')['actor_id'] == actor,
                  'valid production startup preserves the preexisting native token and root')
            stop_process(active)
            original_signing_bytes = (durable / 'native/jwt_secret').read_bytes()
            for name, value in (
                ('JAC_DATA_PATH', str(app) + ' '),
                ('MLOCAL_ONBOARDING_DIR', str(onboarding) + ' '),
                ('MLOCAL_DURABLE_ROOT', ' ' + str(durable)),
            ):
                reject_start({**production, name: value}, 'preflight rejects ambiguous ' + name + ' path', (name,), guarded=True)
            check((durable / 'native/jwt_secret').read_bytes() == original_signing_bytes,
                  'ambiguous path refusal preserves original native signing key')
            check(not (Path(str(app) + ' ') / '.jac/data/jwt_secret').exists()
                  and not Path(str(onboarding) + ' ').exists(),
                  'ambiguous path refusal creates no replacement signing or onboarding store')
            configuration = app / 'jac.toml'
            original_configuration = configuration.read_bytes()
            try:
                configuration.write_bytes(original_configuration + b'\n[serve.auth]\nalgorithm = " HS256 "\n')
                reject_start(production, 'raw TOML signing algorithm', ('JAC_SERVE_AUTH_ALGORITHM',))
                configuration.write_bytes(original_configuration + b'\n[serve.auth]\nsecret = "fixture-signing-config-secret"\n')
                reject_start({**production, 'JAC_SERVE_AUTH_SECRET': '   '},
                             'environment signing fallback mismatch', ('JAC_SERVE_AUTH_SECRET',))
                configuration.write_bytes(original_configuration + b'\n[serve.auth]\nsecret = " ' + original_signing_bytes.strip() + b' "\n')
                PHASE = 'supported preflight native production readiness'
                start({**production, 'JAC_SERVE_AUTH_SECRET': '   ', 'JAC_SERVE_AUTH_ALGORITHM': '   '}, guarded=True)
                ready()
                with urllib.request.urlopen(origin + '/healthz/ready', timeout=5) as response:
                    check(response.status == 200 and json.load(response).get('ready') is True,
                          'supported preflight reaches canonical native JSON readiness')
                check(True, 'supported preflight reaches real native readiness with official environment fallback')
                check(Api(origin, original_token).call('current_session')['actor_id'] == actor,
                      'supported preflight preserves returning token and root with official signing fallback')
                check((durable / 'native/jwt_secret').read_bytes() == original_signing_bytes,
                      'supported preflight preserves the original signing file after native initialization')
                stop_process(active)
            finally:
                configuration.write_bytes(original_configuration)
            no_mount = {**production, 'MLOCAL_DURABLE_ROOT': str(workspace)}
            reject_start(no_mount, 'writable unmounted production state')
            deliveries = sink.count()
        check(sink.closed, 'owned local TLS SMTP fixture closes')
    finally:
        errors = []
        for process in reversed(processes):
            try:
                stop_process(process)
            except (OSError, AssertionError, subprocess.SubprocessError):
                errors.append('process cleanup')
        try:
            runtime.stop()
            if runtime.is_running():
                errors.append('PostgreSQL cleanup')
        except (OSError, RuntimeError, subprocess.SubprocessError):
            errors.append('PostgreSQL cleanup')
        if errors:
            raise RuntimeError('Owned fixture cleanup failed')
    check(not_listening(), 'all owned API gateway PostgreSQL processes and listener stop')
    check(input_manifest(app) == source_manifest, 'copied source input manifest is unchanged throughout the native proof')
    receipt = dict(status='passed', checks=len(CHECKS), check_labels=CHECKS,
        elapsed_seconds=round(time.monotonic() - started, 3), source_input_manifest_sha256=source_hash,
        source_input_manifest=source_manifest, runtime_version=version, runtime_bin_sha256=digest(jac),
        jacpython_bin_sha256=digest(jacpython), official_release_checksums_verified=True,
        github_sha=os.environ.get('GITHUB_SHA', ''), native_register_reproduction=True,
        public_ingress_native_post_denied=True, local_tls_smtp=True, sink_deliveries=deliveries,
        external_email_delivery=False, production_config_process_checks=True,
        mounted_volume_fixture=True, provider_durability_acceptance=False,
        transaction_safety_or_capacity_acceptance=False, release_acceptance=False)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    # Keep failed workspaces private for diagnosis; delete only successful exact
    # directories created here after verifying identity and ownership.
    for path, identity, prefix in ((workspace, workspace_identity, 'm-local-native-hardening.'),
                                  (durable, durable_identity, 'm-local-hardening-state.')):
        current = path.stat()
        if path.is_symlink() or not path.name.startswith(prefix) or current.st_uid != os.geteuid() or (
                current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise RuntimeError('Owned disposable workspace identity changed')
        shutil.rmtree(path)
    print(json.dumps({key: value for key, value in receipt.items() if key != 'source_input_manifest'}, sort_keys=True), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, AssertionError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(status='failed', phase=PHASE, error=type(error).__name__, errno=getattr(error, 'errno', None))), flush=True)
        raise SystemExit(1) from None
