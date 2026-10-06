"""Local sustained native API benchmark; no SMTP or public ingress.

Two API processes share one disposable PostgreSQL and private directory on this
host.250 virtual authenticated API clients are not250 rendering browser clients.
The fixture helper is removed and APIs restarted before measurements.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.request

from jaclang.data.pgembed import PgRuntime
import jaclang

task = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local')
source = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local/work/m-local')
package = Path(os.environ['MLOCAL_CANDIDATE_PACKAGE']).resolve()
assert package.parent == Path('/var/tmp') and package.name.startswith('m-local-runtime-package-')
metadata = json.loads((package / 'result.json').read_text())
assert hashlib.sha256((package / 'jac').read_bytes()).hexdigest() == metadata['candidate_binary_sha256']
assert metadata['inherited_python_and_dependencies_byte_matched']
assert metadata['runtime_patch_sha256'] == 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
assert not Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork').exists() and not (package / 'stage').exists()
binding_file = Path(os.environ['MLOCAL_PACKAGE_BINDING_RECEIPT'])
assert hashlib.sha256(binding_file.read_bytes()).hexdigest() == os.environ['MLOCAL_PACKAGE_BINDING_SHA256']
binding = json.loads(binding_file.read_text())
assert binding['status'] == 'passed' and binding['candidate_binary_sha256'] == metadata['candidate_binary_sha256']
assert binding['runtime_patch_sha256'] == metadata['runtime_patch_sha256']
assert binding['package_metadata_sha256'] == hashlib.sha256((package / 'result.json').read_bytes()).hexdigest()
for name in ('stage-path-classification.json', 'final-payload-path-classification.json'):
    assert hashlib.sha256((package / name).read_bytes()).hexdigest() == binding['file_hashes'][name]
    classified = json.loads((package / name).read_text())
    assert classified['status'] == 'passed' and classified['errors'] == [] and classified['sealed_manifest_sha256'] == binding['sealed_manifest_sha256']
http_file = Path(os.environ['MLOCAL_CAPACITY_HTTP_RECEIPT'])
http = json.loads(http_file.read_text())
assert http['status'] == 'passed' and http['candidate_binary_sha256'] == metadata['candidate_binary_sha256']
assert http['package_input_verification_sha256'] == os.environ['MLOCAL_PACKAGE_BINDING_SHA256']
assert http['runtime_patch_sha256'] == metadata['runtime_patch_sha256']
assert http['executed_proof_sha256'] == hashlib.sha256((task / 'work/identity-runtime-v3/kali-packaged-two-api-proof.py').read_bytes()).hexdigest()
assert http['production_source_digest_sha256'] == '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42'
assert Path(jaclang.__file__).is_relative_to(Path(os.environ['JAC_CACHE_HOME']))
os.umask(0o077)
directory = Path(os.environ['MLOCAL_GATE_CHILD_WORKSPACE'])
assert directory.parent == Path('/var/tmp') and directory.name.startswith('m-local-capacity-')
assert len(directory.name) == len('m-local-capacity-') + 8
assert directory.is_mount() and not directory.is_symlink() and not any(directory.iterdir())
assert directory.stat().st_dev == Path('/var/tmp/m-local-build-e-drive-v2-01a1050e').stat().st_dev
assert directory.stat().st_uid == 65534 and directory.stat().st_mode & 0o777 == 0o700
scratch = Path(os.environ['TMPDIR'])
assert scratch.parent == Path(os.environ['MLOCAL_GATE_WORKSPACE_RECEIPT']).parent
assert scratch.stat().st_dev == directory.stat().st_dev and scratch.stat().st_uid == 65534
assert not scratch.is_symlink() and scratch.stat().st_mode & 0o777 == 0o700
shutil.copyfile(__file__, directory / 'executed-proof.py')
marker = Path(os.environ['MLOCAL_GATE_WORKSPACE_RECEIPT'])
assert marker.parent.parent == Path('/var/tmp') and marker.parent.name.startswith('m-local-kali-native-')
marker_pending = marker.with_suffix('.tmp')
marker_pending.write_text(json.dumps({'workspace': str(directory)}) + '\n')
marker_pending.replace(marker)
app = directory / 'app'
def copy_application(source, destination):
    def copy_tree(source_root, destination_root):
        for path in source_root.rglob('*'):
            relative = path.relative_to(source_root)
            if any(part == '__pycache__' or part == '.jac' or part.startswith('.env') for part in relative.parts):
                continue
            target = destination_root / relative
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                content = path.read_bytes()
                target.write_bytes(content.replace(b'\r\n', b'\n') if path.suffix == '.sh' else content)
                target.chmod(path.stat().st_mode & 0o777)
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('main.jac', 'theme.jac', 'jac.toml', '.jac-version'):
        path = source / name
        assert path.is_file()
        target = destination / name
        target.write_bytes(path.read_bytes())
        target.chmod(path.stat().st_mode & 0o777)
    for name in ('services', 'client', 'data', 'tests', 'scripts'):
        copy_tree(source / name, destination / name)
    copy_tree(source / 'assets/brand', destination / 'assets/brand')

copy_application(source, app)
sys.path.insert(0, str(app))
from services.email_codes import CodeStore, business_revision

private = app / '.jac/onboarding-shared'
helper = app / 'capacity_fixture.jac'
shutil.copyfile(task / 'work/capacity-fixture.jac', helper)
original_main = (app / 'main.jac').read_bytes()
text = original_main.decode()
assert text.startswith('"""') and '[dev]' not in (app / 'jac.toml').read_text()
doc_end = text.index('"""', 3) + 3
addition = '\nimport from capacity_fixture { seed_capacity_history }\ndef:protect capacity_history(actors: list[str]) -> dict[str, any] { return seed_capacity_history(actors); }\n'
(app / 'main.jac').write_text(text[:doc_end] + addition + text[doc_end:])
with socket.socket() as pg_probe:
    pg_probe.bind(('127.0.0.1', 0))
    pg_port = pg_probe.getsockname()[1]
runtime = PgRuntime(data_dir=str(directory / 'pg'), database='regional_capacity', tcp=True, port=pg_port)
owned = []
active = {}
ports = (8256, 8257)
measurements = []
pending = set()
resource_samples = []
sampler_stop = threading.Event()
sampler = None
sampler_errors = []
resource_abort = []
pg_pid = None
workload = ('home_feed',) * 8 + ('current_session',) * 5 + ('get_offer',) * 4 + ('get_business_profile',) * 2 + ('merchant_insights',)
result = {'status': 'running', 'scope': __doc__.strip(), 'workspace': str(directory),
          'disposable_postgres_port': pg_port,
          'candidate_binary_sha256': metadata['candidate_binary_sha256'], 'runtime_patch_sha256': metadata['runtime_patch_sha256'],
          'package_input_verification_sha256': os.environ['MLOCAL_PACKAGE_BINDING_SHA256'],
          'prior_http_receipt_sha256': hashlib.sha256(http_file.read_bytes()).hexdigest(),
          'executed_proof_sha256': hashlib.sha256((directory / 'executed-proof.py').read_bytes()).hexdigest(),
          'fixture_helper_sha256': hashlib.sha256(helper.read_bytes()).hexdigest(),
          'test_duration_seconds': 900, 'requested_requests_per_second': 20, 'virtual_api_clients': 250,
          'dataset': {'accounts': 500, 'merchants': 30, 'active_offers': 120, 'history_claims': 10000, 'history_days': 365},
          'private_state_topology': 'Same-host shared SQLite/key directory; no cross-host replication or failover proof',
          'authentication_fixture_scope': 'Delivered challenges injected into this disposable CodeStore; native OTP consumption, principal binding and JWT verification remain real. No SMTP/send-quota or public-ingress proof.',
          'workload_scope': 'Read-only synthetic hotspot:250 of470 student accounts; all analytics reads target one merchant with10k historical claims. Separate mutation gate required.',
          'runtime_package_receipt': metadata,
          'occ_retry_measurement': 'Not instrumented; PostgreSQL rollback/deadlock/lock-wait samples are not OCC retry counts'}
assert not os.environ.get('JAC_SERVE_MAX_CONNECTIONS'), 'Capacity proof must use the checked-in connection cap'
result['configured_max_connections_per_api'] = tomllib.loads((app / 'jac.toml').read_text())['serve']['limits']['max_connections']
assert result['configured_max_connections_per_api'] == 96

def interrupted(signum, frame):
    raise SystemExit(128 + signum)

signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)

def call(index, token, endpoint, body=None, timeout=30):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request('http://127.0.0.1:' + str(ports[index]) + '/function/' + endpoint,
        json.dumps(body or {}).encode(), headers, method='POST')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        envelope = json.load(response)
    assert envelope.get('ok'), endpoint + ': runtime envelope failed'
    return envelope['data']['result']

def stop(process):
    if process.poll() is None:
        assert os.getpgid(process.pid) == process.pid
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)

def serve(index, info, fixture):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', ports[index]))
    env = dict(os.environ, MLOCAL_ONBOARDING_DIR=str(private), MLOCAL_DEMO_MODE='0',
               MLOCAL_MERCHANT_OWNERS='{}', MLOCAL_DEMO_STUDENTS='[]', MLOCAL_CAPACITY_FIXTURE='1' if fixture else '0')
    env['JAC_DB_URL'] = 'postgresql://' + quote(info.user, safe='') + ':' + quote(info.password, safe='') + '@127.0.0.1:' + str(info.port) + '/' + info.database
    if not fixture:
        env['JAC_CACHE_HOME'] = str(directory / 'measured-runtime-cache')
    log = (directory / ('api-' + str(index) + '-' + str(len(owned)) + '.log')).open('w')
    process = subprocess.Popen([str(package / 'jac'), 'run', '--no-dev', '--no-client', '--host', '127.0.0.1', '--port', str(ports[index])],
        cwd=app, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    owned.append(process)
    active[index] = process
    log.close()

def ready(index):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        assert active[index].poll() is None, 'Owned API exited during startup'
        try:
            call(index, '', 'current_session')
            return
        except Exception:
            time.sleep(1)
    raise TimeoutError('Owned API did not become ready')

def admission_check(index):
    held = []
    try:
        for _ in range(result['configured_max_connections_per_api']):
            connection = socket.create_connection(('127.0.0.1', ports[index]), timeout=3)
            held.append(connection)
            connection.sendall(b'G')
        with socket.create_connection(('127.0.0.1', ports[index]), timeout=3) as overflow:
            overflow.sendall(b'GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            response = b''
            while b'\r\n\r\n' not in response:
                chunk = overflow.recv(4096)
                assert chunk, 'Admission response ended before headers'
                response += chunk
        headers = response.split(b'\r\n\r\n', 1)[0].lower()
        assert headers.startswith(b'http/1.1 503'), 'Connection cap did not return 503'
        assert b'\r\nretry-after: 1' in headers
        return {'api': index, 'held_partial_requests': len(held), 'overflow_status': 503, 'retry_after_seconds': 1}
    finally:
        for connection in held:
            connection.close()

def source_digest(root):
    paths = [root / '.jac-version', root / 'jac.toml']
    for name in ('services', 'client'):
        paths.extend(p for p in (root / name).rglob('*') if p.is_file() and p.suffix in ('.jac', '.py', '.mjs', '.js', '.jsx', '.css') and not p.name.endswith(('.test.jac', '.test.mjs', '.test.js')))
    paths.extend(p for p in root.glob('*.jac') if p.is_file() and not p.name.endswith('.test.jac'))
    paths.extend(p for p in (root / 'data').rglob('*') if p.is_file())
    value = hashlib.sha256()
    for p in sorted(set(paths)):
        value.update(p.relative_to(root).as_posix().encode() + b'\0' + p.read_bytes().replace(b'\r\n', b'\n') + b'\0')
    return value.hexdigest()

def percentile(rows, fraction):
    return sorted(rows)[math.ceil(len(rows) * fraction) - 1] if rows else None

def pg_query(info, query):
    client = Path('/var/tmp/m-local-kali-pg-client-01a1050e/root/usr/lib/postgresql/18/bin/psql')
    assert client.is_file()
    env = dict(os.environ, PGPASSWORD=info.password,
        LD_LIBRARY_PATH='/var/tmp/m-local-kali-pg-client-01a1050e/root/usr/lib/x86_64-linux-gnu')
    output = subprocess.check_output([str(client), '--no-psqlrc', '-h', '127.0.0.1', '-p', str(info.port),
        '-U', info.user, '-d', info.database, '-t', '-A', '-c', query], env=env, stderr=subprocess.PIPE, timeout=10)
    return json.loads(output)

def process_sample():
    assert all(p.poll() is None for p in active.values()), 'An owned measured API exited unexpectedly'
    table = {}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            raw = (p / 'stat').read_text().split(') ', 1)[1].split()
            table[int(p.name)] = {'parent': int(raw[1]), 'cpu_ticks': int(raw[11]) + int(raw[12]),
                                'rss_kib': int(raw[21]) * os.sysconf('SC_PAGE_SIZE') // 1024}
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    roots = {p.pid for p in active.values()}
    roots.add(int((directory / 'pg/postmaster.pid').read_text().splitlines()[0]))
    selected = set(roots)
    while True:
        children = {pid for pid, values in table.items() if values['parent'] in selected}
        if children.issubset(selected):
            break
        selected.update(children)
    return {'cpu_ticks': sum(table[pid]['cpu_ticks'] for pid in selected if pid in table),
            'sum_rss_kib': sum(table[pid]['rss_kib'] for pid in selected if pid in table),
            'api_root_rss_kib': sum(table[p.pid]['rss_kib'] for p in active.values() if p.pid in table),
            'owned_process_count': len(selected)}

def sample_resources(info):
    try:
        while not sampler_stop.is_set():
            row = {'time': time.monotonic(), **process_sample()}
            row['postgres'] = pg_query(info, "SELECT json_build_object('connections', count(*)-1, 'active', count(*) FILTER (WHERE state='active')-1, 'lock_waiters', count(*) FILTER (WHERE wait_event_type='Lock')) FROM pg_stat_activity WHERE datname=current_database() AND backend_type='client backend'")
            resource_samples.append(row)
            if row['sum_rss_kib'] > 8 * 1024 * 1024:
                resource_abort.append('Summed owned API/PostgreSQL tree RSS exceeds8GiB')
                for process in active.values():
                    stop(process)
                sampler_stop.set()
                break
            sampler_stop.wait(5)
    except Exception as error:
        sampler_errors.append(dict(type=type(error).__name__, message=str(error)))
        sampler_stop.set()

try:
    compatibility = Path(os.environ['MLOCAL_CAPACITY_COMPATIBILITY_RECEIPT'])
    verified_compatibility = json.loads(compatibility.read_text())
    assert verified_compatibility['status'] == 'passed' and verified_compatibility['binary_sha256'] == result['candidate_binary_sha256']
    assert http['compatibility_receipt_sha256'] == hashlib.sha256(compatibility.read_bytes()).hexdigest()
    assert verified_compatibility['source_digest_sha256'] == '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42'
    result['compatibility_receipt_sha256'] = hashlib.sha256(compatibility.read_bytes()).hexdigest()
    print('Retained capacity workspace: ' + str(directory), flush=True)
    result['source_baseline_digest_sha256'] = source_digest(source)
    assert result['source_baseline_digest_sha256'] == '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42'
    info = runtime.ensure()
    pg_pid = int((directory / 'pg/postmaster.pid').read_text().splitlines()[0])
    result['statistics_client_preflight'] = pg_query(info, "SELECT json_build_object('ready',true)")
    assert result['statistics_client_preflight']['ready']
    result['postgres_connection_settings'] = pg_query(info, "SELECT json_build_object('max_connections',current_setting('max_connections')::int,'superuser_reserved_connections',current_setting('superuser_reserved_connections')::int,'reserved_connections',current_setting('reserved_connections')::int,'fixture_role_is_superuser',(SELECT rolsuper FROM pg_roles WHERE rolname=current_user))")
    settings = result['postgres_connection_settings']
    result['database_connection_budget'] = {'normal_client_limit': settings['max_connections'] - settings['superuser_reserved_connections'] - settings['reserved_connections'],
        'sampler_connections': 1, 'api_instances': 2, 'combined_transport_connection_cap': 2 * result['configured_max_connections_per_api'],
        'scope': 'Transport caps are not database pool budgets; observed fixture usage is not proof of production role, reserved-access or other-service headroom'}
    subprocess.run([str(package / 'jac'), 'install'], cwd=app, check=True, stdout=(directory / 'install.log').open('w'), stderr=subprocess.STDOUT)
    for index in range(2):
        serve(index, info, True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(ready, range(2)))
    state = CodeStore(private)
    run = secrets.token_hex(4)
    owners = []
    actors = []
    students = []
    offers = []
    now = datetime.now(ZoneInfo('America/Detroit'))
    for n in range(500):
        kind = 'business' if n < 30 else 'student'
        value = 'cap' + run + str(n) + ('@example.test' if kind == 'business' else '')
        challenge = secrets.token_urlsafe(32)
        code = f'{secrets.randbelow(1000000):06d}'
        email = value if kind == 'business' else value + '@umich.edu'
        with state.transaction() as db:
            db.execute('INSERT INTO codes VALUES (?,?,?,?,?,?,0,1)',
                (challenge, email, kind, 'Capacity fixture', state.digest(challenge, code), time.time() + 600))
        account = call(n % 2, '', 'verify_email_code', {'challenge': challenge, 'code': code})
        assert account['ok'] and account.get('token')
        token = account['token']
        actor = call(n % 2, token, 'current_session')['actor_id']
        actors.append(actor)
        if kind == 'business':
            owners.append(token)
            fields = dict(name='Capacity business ' + run + ' ' + str(n), cuisine='Cafe', description='Synthetic benchmark',
                address=str(n + 1) + ' Fictional Street', website='', menu_text='', menu_url='', image_url='', confirmed=True)
            assert call(n % 2, token, 'save_business_draft', fields)['status'] == 'pending_review'
            env = dict(os.environ, MLOCAL_ONBOARDING_DIR=str(private))
            subprocess.run(['bash', 'scripts/review-business.sh', 'approve', '--actor', actor, '--by', 'Capacity fixture operator',
                '--note', 'Fictional benchmark only', '--submission', business_revision(state.draft(actor))],
                cwd=app, env=env, check=True, stdout=(directory / ('approval-' + str(n) + '.log')).open('w'), stderr=subprocess.STDOUT)
            assert call(n % 2, token, 'save_business_draft', fields)['status'] == 'active'
            for k in range(4):
                saved = call(n % 2, token, 'save_offer', dict(offer_id='', create_key=secrets.token_hex(16), title='Capacity offer ' + str(n) + '-' + str(k),
                    description='Synthetic capacity only', price='3', regular_price='5',
                    start_local=(now-timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M'), end_local=(now+timedelta(hours=4)).strftime('%Y-%m-%d %H:%M'),
                    quantity='100', eligibility='Synthetic fixture', terms='Synthetic fixture', dietary='', menu_item=''))
                assert saved['ok']
                offers.append(saved['code'])
        else:
            students.append(token)
        if (n + 1) % 50 == 0:
            print('Prepared ' + str(n + 1) + ' synthetic accounts', flush=True)
    assert len(set(actors)) == 500 and len(offers) == 120
    seeded = call(0, owners[0], 'capacity_history', {'actors': actors[30:]}, timeout=600)
    assert seeded['ok'] and seeded['history'] == 10000 and seeded['public_businesses'] == 30
    for process in active.values():
        stop(process)
    (app / 'main.jac').write_bytes(original_main)
    assert helper.parent.resolve() == app.resolve()
    helper.unlink()
    assert source_digest(app) == source_digest(source)
    cache = (app / '.jac/cache').resolve()
    assert cache.is_relative_to(app.resolve()) and cache.name == 'cache'
    if cache.exists():
        cache.rename(directory / 'fixture-app-cache')
    result['fixture_app_cache_removed_before_measurement'] = True
    result['production_source_digest_sha256'] = source_digest(app)
    result['helper_removed_before_measured_restart'] = True
    for index in range(2):
        serve(index, info, False)
        ready(index)
    result['admission_checks'] = [admission_check(index) for index in range(2)]
    for index in range(2):
        ready(index)
    assert len(call(0, students[0], 'list_offers', timeout=120)) == 120
    analytics = call(0, owners[0], 'merchant_insights', {'days': 365}, timeout=120)
    assert analytics['ok'] and analytics['totals']['claims'] == 10000 and len(analytics['frames']) == 366
    result['dataset_verified'] = True
    assert source_digest(app) == verified_compatibility['source_digest_sha256']
    warmups = []
    for endpoint, token, body in (
        ('home_feed', students[0], {}), ('current_session', students[0], {}),
        ('get_offer', students[0], {'offer_id': offers[0]}),
        ('get_business_profile', students[0], {'offer_id': offers[0]}),
        ('merchant_insights', owners[0], {'days': 365}),
    ):
        durations = []
        for _ in range(3):
            begin = time.monotonic()
            call(0, token, endpoint, body, timeout=120)
            durations.append(time.monotonic() - begin)
        warmups.append({'endpoint': endpoint, 'seconds': durations})
    result['serial_warmup_latency'] = warmups
    result['serial_warmup_scope'] = 'Three direct native reads per endpoint before load; not sustained capacity or latency percentiles'
    if any(max(row['seconds']) > 2.5 for row in warmups):
        raise RuntimeError('Serial warmup exceeded the 2.5-second preflight ceiling; sustained load not started')
    db_stats_query = "SELECT json_build_object('commits',xact_commit,'rollbacks',xact_rollback,'deadlocks',deadlocks,'blocks_read',blks_read,'blocks_hit',blks_hit,'rows_returned',tup_returned,'rows_fetched',tup_fetched) FROM pg_stat_database WHERE datname=current_database()"
    result['postgres_before'] = pg_query(info, db_stats_query)
    sampler = threading.Thread(target=sample_resources, args=(info,), daemon=True)
    sampler.start()
    started = time.monotonic()
    def request(n, target):
        client = n % 250
        endpoint = workload[n % 20]
        body = {'offer_id': offers[n % len(offers)]} if endpoint in ('get_offer', 'get_business_profile') else ({'days': 365} if endpoint == 'merchant_insights' else {})
        token = owners[0] if endpoint == 'merchant_insights' else students[client]
        begin = time.monotonic()
        status = 'ok'
        try:
            value = call((n // 20 + n) % 2, token, endpoint, body)
            if endpoint in ('merchant_insights', 'get_business_profile'):
                assert value['ok']
                if endpoint == 'merchant_insights':
                    assert value['totals']['claims'] == 10000 and len(value['frames']) == 366
                else:
                    assert len(value['offers']) == 4
            elif endpoint == 'home_feed':
                assert isinstance(value, dict) and value.get('signed_in') is True and value['total_deals'] == 120
            elif endpoint == 'current_session':
                assert value['role'] == 'student' and value['actor_id'] == actors[30 + client]
            elif endpoint == 'get_offer':
                assert value['id'] == body['offer_id']
        except urllib.error.HTTPError as error:
            status = 'HTTP ' + str(error.code)
        except Exception as error:
            status = type(error).__name__
        end = time.monotonic()
        return {'endpoint': endpoint, 'status': status, 'response_seconds': end - begin,
                'scheduled_latency_seconds': end - target, 'queue_seconds': begin - target,
                'dispatch_seconds': begin - started}
    with ThreadPoolExecutor(max_workers=250) as pool:
        for n in range(18000):
            assert not resource_abort and not sampler_errors, dict(sampler_errors=sampler_errors, resource_abort=resource_abort)
            assert all(p.poll() is None for p in active.values()), 'An owned measured API exited unexpectedly'
            target = started + n / 20
            time.sleep(max(0, target - time.monotonic()))
            done = {future for future in pending if future.done()}
            measurements.extend(future.result() for future in done)
            pending.difference_update(done)
            late = time.monotonic() - target
            if len(pending) >= 250 or late > .05:
                measurements.append({'endpoint': workload[n % 20],
                    'status': 'client capacity exceeded' if len(pending) >= 250 else 'missed schedule slot',
                    'scheduled_latency_seconds': 30.0, 'response_seconds': None, 'queue_seconds': None, 'dispatch_seconds': None})
            else:
                pending.add(pool.submit(request, n, target))
            if n and n % 1200 == 0:
                print('Measured ' + str(n // 20) + ' seconds; completed ' + str(len(measurements)) + ' requests', flush=True)
        measurements.extend(future.result() for future in pending)
        pending.clear()
    result['measurement_elapsed_seconds'] = time.monotonic() - started
    assert result['measurement_elapsed_seconds'] <= 935, 'Sustained load drain exceeded35 seconds'
    assert all(p.poll() is None for p in active.values()), 'An owned measured API exited unexpectedly'
    sampler_stop.set()
    sampler.join(timeout=15)
    assert not sampler.is_alive() and not sampler_errors and not resource_abort
    assert len(resource_samples) >= 170 and resource_samples[-1]['time'] >= started + 885, 'Resource sampling did not cover the sustained measurement'
    result['postgres_after'] = pg_query(info, db_stats_query)
    result['postgres_deadlocks_added'] = result['postgres_after']['deadlocks'] - result['postgres_before']['deadlocks']
    log_checks = []
    for path in sorted(directory.glob('api-*.log')):
        log = re.sub(r'\x1b\[[0-9;]*m', '', path.read_text(errors='replace'))
        failed = bool(re.search(r'Traceback \(most recent call last\)|HTTP/\d\.\d[" ]+5\d\d\b|(?:^|\n)ERROR:', log))
        log_checks.append({'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'no_unexpected_errors': not failed})
    result['api_log_checks'] = log_checks
    errors = sum(row['status'] != 'ok' for row in measurements)
    times = [row['scheduled_latency_seconds'] for row in measurements]
    result['requests'] = {'attempted': 18000, 'completed': len(measurements), 'errors': errors, 'error_fraction': errors / 18000,
        'p95_seconds': percentile(times, .95), 'p99_seconds': percentile(times, .99),
        'network_completed': sum(row['response_seconds'] is not None for row in measurements),
        'rejected_virtual_client_slots': sum(row['response_seconds'] is None for row in measurements),
        'successful_requests_per_second': sum(row['status'] == 'ok' for row in measurements) / result['measurement_elapsed_seconds'],
        'error_kinds': {label: sum(row['status'] == label for row in measurements) for label in sorted({row['status'] for row in measurements if row['status'] != 'ok'})}}
    result['per_endpoint'] = {name: {'count': len(rows), 'errors': sum(row['status'] != 'ok' for row in rows),
        'p95_seconds': percentile([row['scheduled_latency_seconds'] for row in rows], .95),
        'p99_seconds': percentile([row['scheduled_latency_seconds'] for row in rows], .99)}
        for name in sorted({row['endpoint'] for row in measurements}) for rows in [[row for row in measurements if row['endpoint'] == name]]}
    result['resource_samples'] = resource_samples
    result['resource_summary'] = {'peak_api_root_rss_kib': max(row['api_root_rss_kib'] for row in resource_samples),
        'peak_sum_rss_kib': max(row['sum_rss_kib'] for row in resource_samples),
        'peak_postgres_client_connections': max(row['postgres']['connections'] for row in resource_samples),
        'peak_postgres_lock_waiters': max(row['postgres']['lock_waiters'] for row in resource_samples)}
    ticks_per_second = os.sysconf('SC_CLK_TCK')
    cpu_cores = [max(0, b['cpu_ticks'] - a['cpu_ticks']) / ticks_per_second / (b['time'] - a['time']) for a, b in zip(resource_samples, resource_samples[1:])]
    result['database_connection_budget']['observed_normal_client_headroom'] = result['database_connection_budget']['normal_client_limit'] - 1 - result['resource_summary']['peak_postgres_client_connections']
    result['resource_summary']['average_owned_cpu_cores'] = sum(cpu_cores) / len(cpu_cores)
    result['resource_summary']['peak_owned_cpu_cores'] = max(cpu_cores)
    result['resource_summary']['available_affinity_cpu_cores'] = len(os.sched_getaffinity(0))
    result['cpu_scope'] = 'Observed owned process CPU-tick deltas in5s samples; exited child CPU may be omitted; affinity count is not a hosting CPU quota'
    result['rss_scope'] = 'Sum RSS across owned API and PostgreSQL process trees; shared mapped pages can be counted more than once'
    result['latency_scope'] = 'Scheduled time to response includes client queueing, preventing coordinated omission; direct loopback HTTP, no public TLS/network or browser rendering'
    result['scheduler_scope'] = 'Missed ticks over50ms are counted as rejected slots; no catch-up bursts; dispatch timestamps report actual arrival rate'
    samples = directory / 'request-samples.json'
    samples.write_text(json.dumps(measurements) + '\n')
    result['request_samples_sha256'] = hashlib.sha256(samples.read_bytes()).hexdigest()
    result['unexpected_request_errors'] = errors
    per_endpoint_passed = all(row['errors'] == 0 and row['p95_seconds'] <= 1 and row['p99_seconds'] <= 2.5 for row in result['per_endpoint'].values())
    result['status'] = 'passed' if errors == 0 and per_endpoint_passed and result['postgres_deadlocks_added'] == 0 and all(row['no_unexpected_errors'] for row in log_checks) else 'failed_capacity_target'
except BaseException as error:
    result['status'] = 'failed_setup_or_execution'
    result['error'] = type(error).__name__ + ': ' + ('subprocess exit ' + str(error.returncode) if isinstance(error, subprocess.CalledProcessError) else str(error))
    result['resource_guard'] = resource_abort
    result['sampler_errors'] = sampler_errors
    raise
finally:
    sampler_stop.set()
    if sampler is not None:
        sampler.join(timeout=15)
    result['resource_samples'] = resource_samples
    for future in pending:
        if future.done() and not future.cancelled():
            try:
                measurements.append(future.result())
            except Exception as error:
                result.setdefault('drained_future_errors', []).append(type(error).__name__)
    if measurements:
        samples = directory / 'request-samples.json'
        samples.write_text(json.dumps(measurements) + '\n')
        result['request_samples_sha256'] = hashlib.sha256(samples.read_bytes()).hexdigest()
        result['recorded_request_count'] = len(measurements)
        result['recorded_request_error_count'] = sum(row['status'] != 'ok' for row in measurements)
    cleanup_errors = []
    for process in owned:
        try:
            stop(process)
        except Exception as error:
            cleanup_errors.append('API cleanup: ' + type(error).__name__)
    try:
        runtime.stop()
    except Exception as error:
        cleanup_errors.append('PostgreSQL cleanup: ' + type(error).__name__)
    result['owned_processes_stopped'] = all(process.poll() is not None for process in owned)
    result['postgres_stopped'] = pg_pid is None or not (Path('/proc') / str(pg_pid)).exists()
    result['cleanup_errors'] = cleanup_errors
    if cleanup_errors or not result['owned_processes_stopped'] or not result['postgres_stopped']:
        result['status'] = 'failed_cleanup'
    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    Path(os.environ['MLOCAL_CAPACITY_RECEIPT']).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'workspace': str(directory), 'requests': result.get('requests')}), flush=True)
raise SystemExit(0 if result['status'] == 'passed' else 1)
