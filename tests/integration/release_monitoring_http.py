"""Disposable official-runtime HTTP-200 domain failure and local TLS mail proof."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
import urllib.error

from native_hardening_http import OFFICIAL_JAC_SHA256, OFFICIAL_JACPYTHON_SHA256, free_port, post
from recovery_http import (Api, copy_application, digest, input_manifest, private_dir,
                           process_group_alive, run_logged, scrub_environment, stable_json, stop_process)
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


def events(path):
    observed = []
    for line in path.read_text(errors='replace').splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get('kind') == 'mlocal_domain_event':
            observed.append(value)
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        raise RuntimeError('Use a fresh receipt; never overwrite earlier evidence')
    jac = Path(os.environ['JAC_BIN']).resolve()
    jacpython = Path(str(jac) + 'python')
    check(digest(jac) == OFFICIAL_JAC_SHA256 and digest(jacpython) == OFFICIAL_JACPYTHON_SHA256,
          'both runtime executables match official Jac 0.37.23 checksums')
    source_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    check(not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=ROOT),
          'source checkout is clean before native monitoring proof')
    os.umask(0o077)
    workspace = Path(tempfile.mkdtemp(prefix='m-local-native-monitoring.', dir='/var/tmp'))
    workspace.chmod(0o700)
    app, cache, private = workspace / 'app', workspace / 'cache', workspace / 'private'
    for path in (app, cache, private, cache / 'tmp'):
        private_dir(path)
    copy_application(ROOT, app)
    manifest = input_manifest(app)
    environment = scrub_environment(jac, cache, private)
    for key in list(environment):
        if key.startswith('MLOCAL_') or key in ('JAC_DATA_PATH', 'JAC_SERVE_AUTH_SECRET', 'JAC_SERVE_AUTH_ALGORITHM'):
            environment.pop(key)
    environment.update(MLOCAL_ENV='development', MLOCAL_SHOW_SAMPLES='0', MLOCAL_DEMO_MODE='0',
                       MLOCAL_HOSTED_DATASET='0', MLOCAL_DEMO_COMPANIES='0', MLOCAL_IMPORT_MODEL='',
                       MLOCAL_ONBOARDING_DIR=str(private), MLOCAL_DOMAIN_EVENT_LOG='stderr',
                       MLOCAL_MERCHANT_OWNERS='{}', MLOCAL_DEMO_STUDENTS='[]')
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,::1'
    from jaclang.data.pgembed import PgRuntime
    runtime = PgRuntime(data_dir=str(workspace / 'postgres'), database='native_monitoring', tcp=True, port=free_port())
    process = None
    port = free_port()
    origin = 'http://127.0.0.1:' + str(port)
    log_path = workspace / 'private-native.log'
    observed = []
    cleanup = False
    started = time.monotonic()
    failure = None
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        run_logged('private dependency installation', [str(jac), 'install', '--no-npm'], app,
                   environment, workspace / 'private-install.log', 300)
        connection = runtime.ensure()
        environment['JAC_DB_URL'] = ('postgresql://' + quote(connection.user, safe='') + ':' +
            quote(connection.password, safe='') + '@127.0.0.1:' + str(connection.port) + '/' + connection.database)
        with SmtpSink(workspace / 'smtp') as sink:
            environment.update(MLOCAL_SMTP_HOST='127.0.0.1', MLOCAL_SMTP_PORT=str(sink.port),
                MLOCAL_SMTP_FROM=sink.sender, MLOCAL_SMTP_USERNAME=sink.username,
                MLOCAL_SMTP_PASSWORD=sink.password, SSL_CERT_FILE=str(sink.ca_file))
            log_path.touch(mode=0o600)
            with log_path.open('wb') as log:
                process = subprocess.Popen([str(jac), 'run', '--no-dev', '--no-client', '--host', '127.0.0.1', '--port', str(port)],
                    cwd=app, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            public = Api(origin)
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('Owned native server exited during startup')
                try:
                    if public.call('current_session').get('authenticated') is False and isinstance(public.call('home_feed').get('items'), list):
                        break
                except (OSError, RuntimeError, urllib.error.URLError):
                    pass
                time.sleep(.2)
            else:
                raise TimeoutError('Owned native server did not reach meaningful readiness')
            check(True, 'real native server reaches anonymous session and catalog readiness')
            private_values = [sink.username, sink.password, sink.sender, 'PRIVATE MONITOR NAME']
            status, invalid = post(origin, '/function/request_email_code', dict(value='PRIVATE INVALID EMAIL', kind='student', name='PRIVATE MONITOR NAME'))
            check(status == 200 and invalid.get('ok') is True and invalid['data']['result']['ok'] is False,
                  'invalid email admission remains a friendly HTTP-200 application failure')
            username = 'monitor' + secrets.token_hex(4)
            email = username + '@umich.edu'
            sink.allow(email)
            private_values.extend([username, email])
            original_sink_password = sink.password
            sink.password = 'fixture-reject-authentication'
            try:
                status, refused = post(origin, '/function/request_email_code', dict(value=username, kind='student', name='PRIVATE MONITOR NAME'))
            finally:
                sink.password = original_sink_password
            check(status == 200 and refused.get('ok') is True and refused['data']['result']['ok'] is False
                  and 'could not send' in refused['data']['result']['message'],
                  'actual local TLS SMTP authentication failure remains a friendly HTTP-200 failure')
            with closing(sqlite3.connect(private / 'onboarding.sqlite3')) as db:
                check(db.execute('SELECT COUNT(*) FROM codes WHERE delivered=1').fetchone()[0] == 0,
                      'actual SMTP failure leaves no usable challenge')
                # Only this disposable fixture's SQLite is seeded, with the native server idle.
                now = time.time()
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM sends')
                db.executemany('INSERT INTO sends VALUES (?,?)', [('private-quota@example.test', now - 1)] * 47
                    + [('private-quota@example.test', now - 3601)] * (239 - 47))
                db.commit()
            status, warning = post(origin, '/function/request_email_code', dict(value=username, kind='student', name='PRIVATE MONITOR NAME'))
            check(status == 200 and warning.get('ok') is True and warning['data']['result']['ok'] is True,
                  'near-quota real TLS delivery preserves successful HTTP behavior')
            private_values.extend([warning['data']['result']['challenge'], sink.take_code(email)])
            with closing(sqlite3.connect(private / 'onboarding.sqlite3')) as db:
                now = time.time()
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM sends')
                db.executemany('INSERT INTO sends VALUES (?,?)', [('private-quota@example.test', now - 1)] * 60
                    + [('private-quota@example.test', now - 3601)] * (300 - 60))
                db.commit()
            quota_username = 'quota' + secrets.token_hex(4)
            status, limited = post(origin, '/function/request_email_code', dict(value=quota_username, kind='student', name='PRIVATE MONITOR NAME'))
            check(status == 200 and limited.get('ok') is True and limited['data']['result']['ok'] is False
                  and 'busy' in limited['data']['result']['message'],
                  'reached global quota still denies a send through real HTTP')
            native_password = secrets.token_urlsafe(32)
            status, native = post(origin, '/user/register', dict(identities=[dict(type='email', value='private-native@example.test')],
                credential=dict(type='password', password=native_password), profile=dict(firstname='PRIVATE MONITOR NAME')))
            check(status == 201 and native.get('ok') is True and native.get('data', {}).get('token'),
                  'disposable private native account supplies a real protected endpoint session')
            token = native['data']['token']
            private_values.extend([native_password, token, 'private-native@example.test', 'private-quota@example.test', quota_username])
            authenticated = Api(origin, token)
            check(authenticated.call('claim_offer', offer_id='PRIVATE OFFER ID').get('ok') is False,
                  'unverified native account still cannot gain claim authority')
            check(authenticated.call('redeem_claim', qr_payload='PRIVATE QR PAYLOAD').get('ok') is False,
                  'native account without merchant ownership still cannot redeem')
            private_values.extend(['PRIVATE OFFER ID', 'PRIVATE QR PAYLOAD', 'PRIVATE INVALID EMAIL'])
            observed = events(log_path)
            for operation in ('email_request', 'claim', 'redeem'):
                check(any(e.get('operation') == operation and e.get('code') == 'OPERATION_FAILED' for e in observed),
                      'actual HTTP application failure emits fixed ' + operation + ' event')
            check(any(e.get('code') == 'SMTP_DELIVERY_FAILED' for e in observed), 'actual TLS SMTP failure emits a fixed failure event')
            check(any(e.get('code') == 'MAIL_QUOTA_NEAR' and e.get('hourly_attempts') == 48 and e.get('daily_attempts') == 240 for e in observed),
                  'actual HTTP request warns at durable 80-percent quota headroom')
            check(any(e.get('code') == 'MAIL_QUOTA_REACHED' and e.get('hourly_attempts') == 60 and e.get('daily_attempts') == 300 for e in observed),
                  'actual HTTP global quota denial emits bounded aggregate counts')
            allowed = {'kind', 'time', 'operation', 'code'}
            quota_fields = {'hourly_attempts', 'hourly_limit', 'daily_attempts', 'daily_limit'}
            check(all(set(e) == allowed | (quota_fields if e['code'] in ('MAIL_QUOTA_NEAR', 'MAIL_QUOTA_REACHED') else set()) for e in observed),
                  'every emitted native event has only the fixed permitted fields')
            safe_text = json.dumps(observed)
            check(not any(value in safe_text for value in private_values), 'native events contain no supplied identity, request, credential or SMTP values')
            check(sink.count() == 1, 'only one allowed disposable TLS sink delivery occurred')
        check(sink.closed, 'owned TLS SMTP fixture closes')
        check(input_manifest(app) == manifest, 'native proof source inputs remain unchanged')
    except BaseException as error:
        failure = error
    finally:
        stop_process(process)
        runtime.stop()
        with socket.socket() as sock:
            sock.settimeout(.5)
            listener_absent = sock.connect_ex(('127.0.0.1', port)) != 0
        cleanup = (process is None or not process_group_alive(process)) and not runtime.is_running() and listener_absent
    check(cleanup, 'all owned native server, child, listener and PostgreSQL stop')
    receipt = dict(status='failed' if failure else 'passed', phase=PHASE, checks=len(CHECKS), check_labels=CHECKS,
        source_sha=source_sha, source_input_manifest_sha256=hashlib.sha256(stable_json(manifest)).hexdigest(),
        source_input_manifest=manifest, jac_sha256=digest(jac), jacpython_sha256=digest(jacpython),
        official_runtime_verified=True, fixed_domain_events=observed, elapsed_seconds=round(time.monotonic()-started, 3),
        local_tls_smtp=True, external_delivery=False, hosted_monitoring_acceptance=False, cleanup=cleanup)
    if failure:
        receipt['failure_type'] = type(failure).__name__
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(receipt, out, sort_keys=True, indent=2)
        out.write('\n')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('source_input_manifest','fixed_domain_events')}), flush=True)
    if failure:
        raise failure


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, AssertionError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(status='failed', phase=PHASE, error=type(error).__name__)), flush=True)
        raise SystemExit(1) from None
