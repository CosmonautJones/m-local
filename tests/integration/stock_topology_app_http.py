"""Real native M-Local APIs through the experimental serialized local ingress.

Disposable native identities/graph; no real email, deployment or runtime patch.
Fifty clients start simultaneously, then enter the bounded gateway queue. This
is a correctness test of one exclusive backend, not load/capacity certification.
The final release SHA must repeat it after integration. Private credentials and
QRs are retained only in the mode-0700 fixture, never in the public receipt.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote
import urllib.error
import urllib.request
from uuid import UUID
from zoneinfo import ZoneInfo

from recovery_http import (Api, copy_application, digest, input_manifest,
                           private_dir, run_logged, scrub_environment, stable_json, stop_process)
from stock_topology_app_faults import verify_actual_faults
from stock_topology_http import verify_stock_binaries

ROOT = Path(__file__).resolve().parents[2]
NATIVE_PORT, GATEWAY_PORT = 18880, 18881


def native_post(origin, route, params):
    req = urllib.request.Request(origin + route, json.dumps(params).encode(),
        {'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as response:
        envelope = json.load(response)
    if not envelope.get('ok'):
        raise AssertionError('Native disposable identity creation/login failed')
    return envelope['data']


def parallel(functions):
    barrier = threading.Barrier(len(functions))
    def run(fn):
        barrier.wait(timeout=30)
        return fn()
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        jobs = [pool.submit(run, fn) for fn in functions]
        return [job.result(timeout=60) for job in jobs]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-hold-cap', action='store_true',
                        help='Require the integrated two-active-hold-per-student policy')
    parser.add_argument('--skip-faults', action='store_true',
                        help='Run only normal correctness races; cannot close the topology fault gate')
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise RuntimeError('Run as an unprivileged WSL/Linux user')
    if os.environ.get('JAC_DB_URL') or os.environ.get('JAC_DEV_SOURCE'):
        raise RuntimeError('Inherited DB/source override refused')
    jac = Path(os.environ['JAC_BIN']).resolve()
    version = subprocess.check_output([str(jac), '--version'], text=True, timeout=30).strip()
    if version.split()[:2] != ['jac', '0.37.23']:
        raise RuntimeError('Official Jac0.37.23 required')
    verify_stock_binaries(jac)
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node is required for the actual ingress')
    os.umask(0o077)
    workspace = Path(tempfile.mkdtemp(prefix='m-local-stock-app.', dir='/var/tmp'))
    app, cache = workspace / 'app', workspace / 'cache'
    private_dir(app)
    private_dir(cache)
    private_dir(cache / 'tmp')
    copy_application(ROOT, app)
    inputs = input_manifest(app)
    environment = scrub_environment(jac, cache, app / '.jac/onboarding')
    environment['MLOCAL_DEMO_MODE'] = '1'
    instrumentation = {}
    if not args.skip_faults:
        entry = app / 'main.jac'
        original = entry.read_bytes()
        entry.write_bytes(original + b'\nimport from tests.integration.stock_topology_app_hook { install_fault_hook }\nwith entry { install_fault_hook(); }\n')
        environment['STOCK_APP_PROOF_ROOT'] = str(workspace)
        instrumentation = dict(test_only=True, kind='appended disposable entry imports one-shot PgStore.commit hook',
            original_entry_sha256=hashlib.sha256(original).hexdigest(), instrumented_entry_sha256=digest(entry),
            hook_sha256=digest(app / 'tests/integration/stock_topology_app_hook.py'),
            installed_runtime_edited=False, private_session_methods_modified=False)
    from jaclang.data.pgembed import PgRuntime
    from jaclang.data.store import PgStore
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        pg_port = probe.getsockname()[1]
    runtime = PgRuntime(data_dir=str(workspace / 'postgres'), database='stock_app_http',
                        tcp=True, port=pg_port)
    processes, checks = [], []
    receipt = dict(schema=1, verdict='INCOMPLETE', checks=checks, workspace=str(workspace),
        candidate_sha=subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        source_manifest_sha256=hashlib.sha256(stable_json(inputs)).hexdigest(),
        source_manifest=inputs, version=version, jac_sha256=digest(jac),
        jacpython_sha256=digest(Path(str(jac) + 'python')), source_override=False,
        topology='one exclusive native backend, one single-instance-serialized gateway; no operator writes',
        configuration=dict(native_port=NATIVE_PORT, gateway_port=GATEWAY_PORT,
            max_queued_requests=64, queue_wait_ms=10000, backend_workers='stock default'),
        limitations=['local correctness under bounded50-client bursts, not capacity certification',
            'no SMTP/physical-device/hosted or multi-host proof',
            'existing stock competing-writer retry defect remains; exclusive topology is mandatory',
            'final integrated candidate requires a fresh receipt'])
    receipt['configuration']['require_hold_cap'] = args.require_hold_cap
    receipt['configuration']['actual_app_faults_required'] = not args.skip_faults
    receipt['test_only_instrumentation'] = instrumentation
    native = 'http://127.0.0.1:' + str(NATIVE_PORT)
    gateway = 'http://127.0.0.1:' + str(GATEWAY_PORT)
    active_backend = active_gateway = None

    def check(value, label):
        if not value:
            raise AssertionError(label)
        checks.append(label)
        print('PASS ' + label, flush=True)

    def start_backend():
        nonlocal active_backend
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', NATIVE_PORT))
        log = workspace / ('native-' + str(len(processes)) + '.log')
        with log.open('wb') as stream:
            active_backend = subprocess.Popen([str(jac), 'run', '--no-dev', '--no-client',
                '--host', '127.0.0.1', '--port', str(NATIVE_PORT)], cwd=app, env=environment,
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(active_backend)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            if active_backend.poll() is not None:
                raise RuntimeError('Owned full-app native API exited')
            try:
                if Api(native).call('current_session').get('authenticated') is False:
                    return
            except (OSError, RuntimeError, ValueError, urllib.error.URLError):
                pass
            time.sleep(.3)
        raise TimeoutError('Native full-app readiness exceeded240s')

    def start_gateway():
        nonlocal active_gateway
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', GATEWAY_PORT))
        source = ('import {createShareProxy} from "./scripts/phone-share-proxy.mjs";'
            'createShareProxy({upstreamHost:"127.0.0.1",upstreamPort:18880,trustCloudflare:false,'
            'healthCheck:true,deploymentTopology:"single-instance-serialized",'
            'maxQueuedRequests:64,queueWaitMs:10000}).listen(18881,"127.0.0.1");')
        log = workspace / ('gateway-' + str(len(processes)) + '.log')
        with log.open('wb') as stream:
            active_gateway = subprocess.Popen([node, '--input-type=module', '-e', source],
                cwd=app, env=environment, stdin=subprocess.DEVNULL, stdout=stream,
                stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(active_gateway)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if active_gateway.poll() is not None:
                raise RuntimeError('Owned gateway exited')
            try:
                with socket.create_connection(('127.0.0.1', GATEWAY_PORT), timeout=.5):
                    return
            except OSError:
                time.sleep(.1)
        raise TimeoutError('Owned ingress did not listen')

    def rows(query, params=None):
        observer = PgStore(conninfo=connection, auto_schema=False)
        try:
            return observer.rows(query, params or {})
        finally:
            observer.close()

    def restart_both():
        nonlocal active_gateway, active_backend
        stop_process(active_gateway)
        active_gateway = None
        stop_process(active_backend)
        active_backend = None
        start_backend()
        start_gateway()

    def durable(record_id):
        observer = PgStore(conninfo=connection, auto_schema=False)
        try:
            return observer.load_full([UUID(record_id)])[UUID(record_id)]
        finally:
            observer.close()

    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        run_logged('private full-app dependency install', [str(jac), 'install', '--no-npm'],
                   app, environment, workspace / 'install.log', 180)
        connection = runtime.ensure()
        environment['JAC_DB_URL'] = ('postgresql://' + quote(connection.user, safe='') + ':' +
            quote(connection.password, safe='') + '@127.0.0.1:' + str(connection.port) + '/' + connection.database)
        start_backend()
        identities = []
        for index in range(52):
            email = 'stock-' + secrets.token_hex(8) + '@example.test'
            credential = {'type': 'password', 'password': secrets.token_urlsafe(24)}
            native_post(native, '/user/register', dict(identities=[dict(type='email', value=email)], credential=credential))
            identities.append(native_post(native, '/user/login', dict(identity=dict(type='email', value=email), credential=credential)))
        environment['MLOCAL_DEMO_STUDENTS'] = json.dumps([row['root_id'] for row in identities[:50]])
        environment['MLOCAL_MERCHANT_OWNERS'] = json.dumps(dict(
            **{'arbor-leaf-kitchen': identities[50]['root_id'], 'maize-noodle-lab': identities[51]['root_id']}))
        (workspace / 'private-native-identities.json').write_text(json.dumps(identities))
        stop_process(active_backend)
        active_backend = None
        start_backend()
        start_gateway()
        public = Api(gateway)
        students = [Api(gateway, row['token']) for row in identities[:50]]
        merchant = Api(gateway, identities[50]['token'])
        feeds = parallel([lambda: public.call('home_feed') for _ in range(50)])
        check(all(feed['total_deals'] > 0 for feed in feeds), '50simultaneous cold feeds complete through serialized ingress')
        counts = rows("SELECT props->'archetype'->>'slug', COUNT(*) FROM anchors WHERE arch_type='Restaurant' GROUP BY props->'archetype'->>'slug'")
        check(all(int(row[1]) == 1 for row in counts), 'independent database observer finds no duplicate cold restaurant slug')
        check(int(rows("SELECT COUNT(*) FROM anchors WHERE arch_type='CatalogBootstrap'")[0][0]) == 1,
              'one durable cold catalog bootstrap')
        with urllib.request.urlopen(gateway + '/healthz', timeout=30) as health:
            check(health.headers.get_content_type() == 'application/json' and json.load(health).get('ready') is True,
                  'serialized public readiness verifies actual native JSON readiness and feed')
        check(merchant.call('current_session')['role'] == 'merchant', 'native preserved merchant identity owns fixture catalog')
        check(all(student.call('current_session')['role'] == 'student' for student in students),
              '50distinct disposable native students are recognized')
        tastes = parallel([lambda: students[0].call('save_taste', categories='coffee', diets='vegan', price_range='') for _ in range(50)])
        check(all(row['ok'] and row['completed'] for row in tastes), '50same-account taste writes return durable completion')
        check(int(rows("SELECT COUNT(*) FROM anchors WHERE arch_type='TasteProfile'")[0][0]) == 1,
              'one durable taste profile after50simultaneous creation requests')
        favorites = parallel([lambda: students[0].call('toggle_favorite', slug='arbor-leaf-kitchen') for _ in range(50)])
        check(all(row['ok'] for row in favorites) and students[0].call('taste_choices')['favorites'] == [],
              '50favorite toggles produce even parity without duplicate favorites')
        check(int(rows("SELECT COUNT(*) FROM anchors WHERE arch_type='Favorite'")[0][0]) == 0,
              'independent database observer confirms no favorite remains')
        now = datetime.now(ZoneInfo('America/Detroit'))
        post = dict(offer_id='', create_key=secrets.token_hex(16), title='Stockserialized fixture ' + secrets.token_hex(4),
            description='Fictional topology fixture', price='3.00', regular_price='5.00',
            start_local=(now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M'),
            end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='1',
            eligibility='Fixture student ID', terms='Synthetic test only', dietary='', menu_item='')
        publishes = parallel([lambda: merchant.call('save_offer', **post) for _ in range(50)])
        codes = {row.get('code') for row in publishes if row.get('ok')}
        check(all(row['ok'] for row in publishes) and len(codes) == 1,
              '50same-key simultaneous publication retries produce one offer ID')
        offer_id = codes.pop()
        check(int(rows("SELECT COUNT(*) FROM anchors WHERE arch_type='Offer' AND props->'archetype'->>'title'=:title", dict(title=post['title']))[0][0]) == 1,
              'independent database observer confirms one published offer')
        claims = parallel([lambda student=student: student.call('claim_offer', offer_id=offer_id) for student in students])
        winners = [(index, row) for index, row in enumerate(claims) if row.get('ok')]
        check(len(winners) == 1, '50distinct simultaneous students have one last-unit winner')
        winner_index, claim = winners[0]
        check(int(rows("SELECT COUNT(*) FROM anchors WHERE arch_type='ClaimedAs' AND src=CAST(:id AS uuid)", dict(id=str(UUID(offer_id))))[0][0]) == 1,
              'one durable claim edge for the one-unit offer')
        check(public.call('get_offer', offer_id=offer_id)['remaining'] == 0, 'public stock is sold out after one claim')
        redemptions = parallel([lambda: merchant.call('redeem_claim', qr_payload=claim['qr_payload']) for _ in range(50)])
        check(sum(bool(row.get('ok')) for row in redemptions) == 1, '50simultaneous redemptions produce one success')
        persisted = durable(claim['claim_id']).props['archetype']
        check(persisted['status'] == 'redeemed' and persisted['redeemed_ts'] > 0,
              'independent database observer confirms durable redemption')
        if not args.skip_faults:
            verify_actual_faults(workspace, merchant, students[2], public, rows, durable,
                                 restart_both, check, receipt)
        if args.require_hold_cap:
            cap_offers = []
            for index in range(8):
                cap_post = dict(post, create_key=secrets.token_hex(16), quantity='8',
                               title=post['title'] + ' hold-cap ' + str(index))
                saved = merchant.call('save_offer', **cap_post)
                check(saved.get('ok'), 'created a separate disposable global-hold-cap offer')
                cap_offers.append(saved['code'])
            cap_claims = parallel([lambda oid=oid: students[1].call('claim_offer', offer_id=oid)
                                   for oid in cap_offers])
            active_holds = [(oid, row) for oid, row in zip(cap_offers, cap_claims) if row.get('ok')]
            check(len(active_holds) == 2, 'simultaneous same-actor claims across8offers permit exactly2active holds')
            retried = students[1].call('claim_offer', offer_id=active_holds[0][0])
            check(retried.get('ok') and retried['claim_id'] == active_holds[0][1]['claim_id'],
                  'a live held-claim retry keeps its original claim within global cap')
            live_count = rows("SELECT COUNT(*) FROM anchors WHERE arch_type='Redemption' AND props->'archetype'->>'actor_id'=:actor AND props->'archetype'->>'status'='claimed'", dict(actor=UUID(identities[1]['root_id']).hex))
            check(int(live_count[0][0]) == 2, 'independent database observer confirms2active same-actor holds')
            check(students[1].call('cancel_claim', offer_id=active_holds[0][0])['ok'],
                  'cancelling one held claim releases one global slot')
            third = next(oid for oid, row in zip(cap_offers, cap_claims) if not row.get('ok'))
            check(students[1].call('claim_offer', offer_id=third)['ok'],
                  'a distinct offer can use the newly released global slot')
        stop_process(active_gateway)
        active_gateway = None
        stop_process(active_backend)
        active_backend = None
        start_backend()
        start_gateway()
        check(students[winner_index].call('get_offer', offer_id=offer_id)['my_status'] == 'redeemed',
              'claim and redemption survive backend plus gateway restart')
        check(students[0].call('taste_choices')['completed'] and students[0].call('taste_choices')['favorites'] == [],
              'taste and favorite parity survive restart')
        check(not merchant.call('redeem_claim', qr_payload=claim['qr_payload'])['ok'],
              'redemption stays single-use after restart')
        check(merchant.call('save_offer', **post)['code'] == offer_id,
              'publication key retains original offer after restart')
        with urllib.request.urlopen(gateway + '/healthz', timeout=30) as health:
            check(json.load(health).get('ready') is True, 'serialized readiness remains meaningful after restart')
        receipt['verdict'] = 'BOUNDED_SERIALIZED_APP_RACES_PASS_NOT_HOSTING_CERTIFIED'
    except BaseException as error:
        receipt['failure_type'], receipt['failure'] = type(error).__name__, str(error)
        receipt['verdict'] = 'BLOCKED'
        raise
    finally:
        for process in processes:
            stop_process(process)
        runtime.stop()
        receipt['cleanup'] = dict(owned_api_gateway_groups_stopped=True, private_postgres_stopped=True)
        (workspace / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
        evidence = ROOT / 'docs/review/stock-topology/serialized-app.json'
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(receipt, indent=2) + '\n')
        print('Retained private full-app fixture:', workspace, flush=True)


if __name__ == '__main__':
    main()
