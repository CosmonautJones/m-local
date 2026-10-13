"""Two native APIs share onboarding and graph state through real local TLS SMTP.

This disposable single-host fixture does not send external email or prove
public ingress, independent hosts, browser capacity, or in-flight crash safety.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
import os
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

from recovery_http import (Api, copy_application, digest, input_manifest,
                           private_dir, run_logged, scrub_environment, stable_json,
                           stop_process)
from smtp_sink import SmtpSink


ROOT = Path(__file__).resolve().parents[2]
CHECKS = []
PHASE = 'preflight'


def check(value, label):
    global PHASE
    PHASE = label
    if not value:
        raise AssertionError(label)
    CHECKS.append(label)
    print('PASS ' + label, flush=True)


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def parallel(functions):
    barrier = threading.Barrier(len(functions))
    def invoke(function):
        barrier.wait(timeout=15)
        return function()
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        jobs = [pool.submit(invoke, function) for function in functions]
        return [job.result(timeout=45) for job in jobs]


def main():
    global PHASE
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise RuntimeError('Fixture requires an unprivileged Linux user')
    if os.environ.get('JAC_DB_URL') or os.environ.get('JAC_DEV_SOURCE'):
        raise RuntimeError('Fixture refuses an inherited graph database or source override')
    if shutil.disk_usage('/var/tmp').free < 10 * 1024 ** 3:
        raise RuntimeError('Fixture requires ten GiB of free temporary storage')
    jac = Path(os.environ['JAC_BIN']).resolve()
    if not jac.is_file():
        raise RuntimeError('Pinned Jac executable is unavailable')
    version = subprocess.check_output([str(jac), '--version'], timeout=30, text=True).strip()
    if version.split()[:2] != ['jac', '0.37.23']:
        raise RuntimeError('Fixture requires Jac 0.37.23')
    os.umask(0o077)
    workspace = Path(tempfile.mkdtemp(prefix='m-local-native-onboarding.', dir='/var/tmp'))
    workspace.chmod(0o700)
    workspace_identity = workspace.stat()
    app, cache = workspace / 'app', workspace / 'cache'
    private_dir(app)
    private_dir(cache)
    private_dir(cache / 'tmp')
    copy_application(ROOT, app)
    source_hash = hashlib.sha256(stable_json(input_manifest(app))).hexdigest()
    onboarding = app / '.jac/onboarding'
    environment = scrub_environment(jac, cache, onboarding)
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,::1'
    from jaclang.data.pgembed import PgRuntime
    sys.path.insert(0, str(ROOT))
    from services.email_codes import CodeStore, business_revision
    runtime = PgRuntime(data_dir=str(workspace / 'postgres'), database='onboarding_http',
                        tcp=True, port=free_port())
    processes = []
    active = {}
    with socket.socket() as first, socket.socket() as second:
        first.bind(('127.0.0.1', 0))
        second.bind(('127.0.0.1', 0))
        ports = [first.getsockname()[1], second.getsockname()[1]]

    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)

    def start(index):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', ports[index]))
        log_path = workspace / ('api-' + str(len(processes)) + '.log')
        with log_path.open('wb') as log:
            process = subprocess.Popen([str(jac), 'run', '--no-dev', '--no-client',
                '--host', '127.0.0.1', '--port', str(ports[index])], cwd=app,
                env=environment, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(process)
        active[index] = process

    def ready(index):
        api = Api('http://127.0.0.1:' + str(ports[index]))
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if active[index].poll() is not None:
                raise RuntimeError('Owned API exited during startup')
            try:
                if api.call('current_session').get('authenticated') is False:
                    return api
            except (OSError, RuntimeError, urllib.error.URLError):
                pass
            time.sleep(.5)
        raise TimeoutError('Owned API startup deadline')

    def count(table):
        with closing(sqlite3.connect(onboarding / 'onboarding.sqlite3')) as db:
            return db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

    started = time.monotonic()
    try:
        PHASE = 'private dependency installation'
        run_logged(PHASE, [str(jac), 'install', '--no-npm'], app, environment,
                   workspace / 'install.log', 180)
        connection = runtime.ensure()
        environment['JAC_DB_URL'] = ('postgresql://' + quote(connection.user, safe='') + ':' +
            quote(connection.password, safe='') + '@127.0.0.1:' + str(connection.port) + '/' + connection.database)
        with SmtpSink(workspace / 'smtp') as sink:
            environment.update(MLOCAL_SMTP_HOST='127.0.0.1', MLOCAL_SMTP_PORT=str(sink.port),
                MLOCAL_SMTP_FROM=sink.sender, MLOCAL_SMTP_USERNAME=sink.username,
                MLOCAL_SMTP_PASSWORD=sink.password, SSL_CERT_FILE=str(sink.ca_file))
            # Official 0.37.23 races CREATE TABLE for native identity schemas
            # on an empty PostgreSQL database (SQLSTATE 23505). The supported
            # rollout always initializes that database with one exclusive
            # server. Keep onboarding itself cold for the simultaneous OTP/key
            # tests below; never substitute serial requests for those races.
            PHASE = 'exclusive native identity schema initialization'
            start(0)
            ready(0)
            check(not (onboarding / 'code.key').exists() and not (onboarding / 'onboarding.sqlite3').exists(),
                  'exclusive native schema initialization leaves onboarding keys and accounts cold')
            bootstrap = active.pop(0)
            stop_process(bootstrap)
            processes.remove(bootstrap)
            check(True, 'exclusive schema bootstrap API stops before the concurrent onboarding APIs')
            PHASE = 'concurrent native starts with initialized identity schema and cold onboarding'
            start(0)
            start(1)
            apis = [ready(0), ready(1)]
            run = secrets.token_hex(4)
            business = 'native' + run + '@example.test'
            student = 'native' + run

            def request(index, value, kind='business'):
                email = value + '@umich.edu' if kind == 'student' else value
                sink.allow(email)
                response = apis[index].call('request_email_code', value=value, kind=kind, name='Native fixture')
                check(response.get('ok') and response.get('challenge'), 'native request reaches the TLS mail sink')
                return response['challenge'], sink.take_code(email, timeout=10)

            def verify(index, challenge, code):
                result = apis[index].call('verify_email_code', challenge=challenge, code=code)
                check(result.get('ok') and result.get('token'), 'another API consumes a delivered challenge')
                return result['token']

            sink.allow(business)
            first_requests = parallel([lambda api=api: api.call('request_email_code',
                value=business, kind='business', name='Native fixture') for api in apis])
            winners = [(index, row) for index, row in enumerate(first_requests) if row.get('ok') and row.get('challenge')]
            check(len(winners) == 1 and sink.count() == 1,
                  'cold API onboarding stores publish one key and deliver one challenge')
            state = CodeStore(onboarding)
            check(len(state.key) == 32 and count('accounts') == 0,
                  'native cold-start onboarding key is complete and accounts are empty')
            winner, response = winners[0]
            challenge, code = response['challenge'], sink.take_code(business, timeout=10)
            token = verify(1 - winner, challenge, code)
            owners = [Api(api.origin, token) for api in apis]
            sessions = [owner.call('current_session') for owner in owners]
            actor = sessions[0]['actor_id']
            check(all(s['role'] == 'business' and s['email_verified'] and s['actor_id'] == actor for s in sessions),
                  'new native account and token are visible to both APIs')
            replay = apis[0].call('verify_email_code', challenge=challenge, code=code)
            check(not replay.get('ok') and not replay.get('token'), 'other API rejects a consumed challenge')
            challenge, code = request(1, student, 'student')
            student_token = verify(0, challenge, code)
            students = [Api(api.origin, student_token).call('current_session') for api in apis]
            check(all(s['role'] == 'student' and s['email_verified'] for s in students) and
                  len({s['actor_id'] for s in students}) == 1 and students[0]['actor_id'] != actor,
                  'fixture U-M inbox proof grants the student role on both APIs')

            challenge, code = request(0, business)
            answers = parallel([lambda index=i % 2: apis[index].call('verify_email_code',
                challenge=challenge, code=code) for i in range(8)])
            check(sum(bool(row.get('ok') and row.get('token')) for row in answers) == 1,
                  'eight cross-API consumption attempts have one winner')
            check(count('accounts') == 2 and count('provisioning') == 0,
                  'returning sign-in keeps one business and one student identity')

            fields = dict(name='Native Fixture Cafe', cuisine='Cafe', description='Fictional shared-state fixture',
                address='123 Fixture Street', website='', menu_text='', menu_url='', image_url='', confirmed=True)
            check(owners[0].call('save_business_draft', **fields)['status'] == 'pending_review',
                  'first API saves a private business submission')
            check(owners[1].call('get_business_draft')['name'] == fields['name'],
                  'second API immediately reads the live draft')
            state.approve_business(actor, 'Fixture operator', 'Fictional business authority only',
                                   business_revision(state.draft(actor)))
            state.approve_business(actor, 'Fixture operator', 'Fictional business authority only',
                                   business_revision(state.draft(actor)))
            check(count('business_reviews') == 1 and count('business_approvals') == 1,
                  'repeated host approval records one decision for the same identity')
            activations = parallel([lambda owner=owner: owner.call('save_business_draft', **fields) for owner in owners])
            check(all(row.get('ok') and row.get('status') == 'active' for row in activations),
                  'both APIs activate the once-approved business')
            sessions = [owner.call('current_session') for owner in owners]
            check(all(s['role'] == 'merchant' for s in sessions) and
                len({s['restaurant_id'] for s in sessions}) == 1 and count('business_owners') == 1,
                'concurrent activation keeps one owned business identity')
            fields['description'] = 'Routine edit visible across both APIs'
            check(owners[0].call('save_business_draft', **fields)['status'] == 'active' and
                  owners[1].call('get_business_draft')['description'] == fields['description'],
                  'routine profile writes are shared without another review')
            os.killpg(active[1].pid, signal.SIGKILL)
            active[1].wait(timeout=15)
            stop_process(active[1])
            check(owners[0].call('current_session')['role'] == 'merchant', 'first API remains usable after the idle peer crashes')
            PHASE = 'replacement native API startup'
            start(1)
            apis[1] = ready(1)
            owners[1] = Api(apis[1].origin, token)
            restored = owners[1].call('current_session')
            check(restored['actor_id'] == actor and restored['role'] == 'merchant' and
                  owners[1].call('get_business_draft')['description'] == fields['description'],
                  'replacement API preserves token ownership and committed draft')

            for index in range(3):
                challenge, code = request(index % 2, business)
                verify(1 - index % 2, challenge, code)
            before = sink.count()
            denied = parallel([lambda api=api: api.call('request_email_code', value=business,
                kind='business', name='Native fixture') for api in apis])
            check(all(not row.get('ok') and not row.get('challenge') for row in denied) and sink.count() == before,
                  'five-send per-email budget refuses both APIs without delivery')
            cooldown = 'cooldown' + run + '@example.test'
            sink.allow(cooldown)
            before = sink.count()
            answers = parallel([lambda index=i % 2: apis[index].call('request_email_code',
                value=cooldown, kind='business', name='Native fixture') for i in range(8)])
            check(sum(bool(row.get('ok') and row.get('challenge')) for row in answers) == 1 and sink.count() == before + 1,
                  'eight cross-API resends produce one challenge and delivery')
            for index in range(58 - count('sends')):
                request(index % 2, 'limit' + run + str(index) + '@example.test')
            before = sink.count()
            contenders = ['contender' + run + str(index) + '@example.test' for index in range(8)]
            for email in contenders:
                sink.allow(email)
            answers = parallel([lambda index=index, email=email: apis[index % 2].call('request_email_code',
                value=email, kind='business', name='Native fixture') for index, email in enumerate(contenders)])
            check(sum(bool(row.get('ok')) for row in answers) == 2 and sink.count() == before + 2 and count('sends') == 60,
                  'global hourly budget admits only two of eight remaining send requests')
            deliveries = sink.count()
        check(sink.closed, 'owned TLS mail sink closes')
    finally:
        errors = []
        for process in reversed(processes):
            try:
                stop_process(process)
            except (OSError, AssertionError, subprocess.SubprocessError):
                errors.append('API process cleanup')
        try:
            runtime.stop()
            if runtime.is_running():
                errors.append('PostgreSQL cleanup')
        except (OSError, RuntimeError, subprocess.SubprocessError):
            errors.append('PostgreSQL cleanup')
        if errors:
            raise RuntimeError('Owned fixture cleanup failed')
    check(True, 'all owned API process groups and private PostgreSQL stop')
    current_identity = workspace.stat()
    if (workspace.parent != Path('/var/tmp') or not workspace.name.startswith('m-local-native-onboarding.') or
            workspace.is_symlink() or current_identity.st_uid != os.geteuid() or
            (current_identity.st_dev, current_identity.st_ino) != (workspace_identity.st_dev, workspace_identity.st_ino)):
        raise RuntimeError('Owned disposable workspace identity changed')
    shutil.rmtree(workspace)
    check(not workspace.exists(), 'successful fixture removes its private disposable state')
    print(json.dumps(dict(status='passed', checks=len(CHECKS), check_labels=CHECKS,
        elapsed_seconds=round(time.monotonic() - started, 3), source_input_manifest_sha256=source_hash,
        runtime_version=version, runtime_bin_sha256=digest(jac), github_sha=os.environ.get('GITHUB_SHA', ''),
        shared_local_directory=True, concurrent_api_instances=2, sink_deliveries=deliveries,
        local_tls_smtp=True, external_email_delivery=False, idle_peer_crash_only=True,
        fixture_script_sha256=digest(Path(__file__)),
        native_identity_schema_initialized_exclusively=True, onboarding_cold_before_parallel_apis=True,
        simultaneous_native_schema_creation_supported=False,
        public_ingress=False, independent_host_replication=False, release_acceptance=False), sort_keys=True), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, AssertionError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'failed', 'phase': PHASE, 'error': type(error).__name__,
                          'errno': getattr(error, 'errno', None)}), flush=True)
        raise SystemExit(1) from None
