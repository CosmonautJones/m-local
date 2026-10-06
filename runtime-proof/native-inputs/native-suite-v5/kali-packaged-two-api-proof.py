"""Real authenticated two-process proof with independent mutation lock files.

Both APIs use one canonical source path and one disposable PostgreSQL database.
Private identities are cloned only after fixture setup, so this is graph/OCC
evidence, not proof of cross-host private-state replication or production capacity.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import math
import hashlib
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
from zoneinfo import ZoneInfo
import urllib.error
import urllib.request

from jaclang.data.pgembed import PgRuntime

source = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local/work/m-local')
fork = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork')
package = Path(os.environ['MLOCAL_CANDIDATE_PACKAGE']).resolve()
assert package.parent == Path('/var/tmp') and package.name.startswith('m-local-runtime-package-')
assert not fork.exists() and not (package / 'stage').exists()
packaged = json.loads((package / 'result.json').read_text())
binding_file = Path(os.environ['MLOCAL_PACKAGE_BINDING_RECEIPT'])
assert hashlib.sha256(binding_file.read_bytes()).hexdigest() == os.environ['MLOCAL_PACKAGE_BINDING_SHA256']
binding = json.loads(binding_file.read_text())
assert binding['status'] == 'passed' and binding['runtime_patch_sha256'] == 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
assert binding['candidate_binary_sha256'] == packaged['candidate_binary_sha256'] == hashlib.sha256((package / 'jac').read_bytes()).hexdigest()
assert binding['package_metadata_sha256'] == hashlib.sha256((package / 'result.json').read_bytes()).hexdigest()
for name in ('stage-path-classification.json', 'final-payload-path-classification.json'):
    assert hashlib.sha256((package / name).read_bytes()).hexdigest() == binding['file_hashes'][name]
    classified = json.loads((package / name).read_text())
    assert classified['status'] == 'passed' and classified['errors'] == [] and classified['sealed_manifest_sha256'] == binding['sealed_manifest_sha256']
os.umask(0o077)
directory = Path(os.environ['MLOCAL_GATE_CHILD_WORKSPACE'])
assert directory.parent == Path('/var/tmp') and directory.name.startswith('m-local-two-api-')
assert len(directory.name) == len('m-local-two-api-') + 8
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
assert '[dev]' not in (app / 'jac.toml').read_text()
unknown_commit = os.environ.get('MLOCAL_PROBE_UNKNOWN_COMMIT') == '1'
student_count = int(os.environ.get('MLOCAL_PROBE_CONCURRENT_ATTEMPTS', '2'))
assert student_count in (2, 50)
if unknown_commit:
    hook = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local/work/http-commit-fault.py')
    shutil.copyfile(hook, app / 'fault_probe.py')
    main_source = (app / 'main.jac').read_text()
    assert main_source.startswith('"""')
    doc_end = main_source.index('"""', 3) + 3
    (app / 'main.jac').write_text(main_source[:doc_end] + '\nimport fault_probe;\n' + main_source[doc_end:])
    os.environ['MLOCAL_COMMIT_FAULT_RECEIPT'] = str(app / '.jac/commit-fault.json')
sys.path.insert(0, str(app))
sys.path.insert(0, str(app / 'tests/integration'))
from services.email_codes import CodeStore, business_revision
from qr_http import Api

os.umask(0o077)
with socket.socket() as pg_probe:
    pg_probe.bind(('127.0.0.1', 0))
    pg_port = pg_probe.getsockname()[1]
runtime = PgRuntime(data_dir=str(directory / 'pg'), database='two_api_proof', tcp=True, port=pg_port)
def interrupted(signum, frame):
    raise SystemExit(128 + signum)

signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
owned = []
active = {}
checks = []
jac = str(package / 'jac')
ports = (8254, 8255)
private = [app / '.jac' / ('onboarding-' + name) for name in ('a', 'b')]

def require(value, label):
    assert value, label
    checks.append(label)
    print('PASS ' + label, flush=True)

def stop(process):
    if process.poll() is None:
        assert os.getpgid(process.pid) == process.pid
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)

def serve(index, connection):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', ports[index]))
    env = dict(os.environ, MLOCAL_ONBOARDING_DIR=str(private[index]),
               MLOCAL_DEMO_MODE='0', MLOCAL_MERCHANT_OWNERS='{}', MLOCAL_DEMO_STUDENTS='[]')
    if unknown_commit:
        env['MLOCAL_COMMIT_FAULT_RECEIPT'] = str(app / '.jac/commit-fault.json')
    env['JAC_DB_URL'] = ('postgresql://' + quote(connection.user, safe='') + ':' +
        quote(connection.password, safe='') + '@127.0.0.1:' + str(connection.port) + '/' + connection.database)
    generation = len([path for path in directory.glob('api-' + str(index) + '*.log')])
    log = (directory / ('api-' + str(index) + '-' + str(generation) + '.log')).open('w')
    process = subprocess.Popen([jac, 'run', '--no-dev', '--no-client', '--host', '127.0.0.1', '--port', str(ports[index])],
        cwd=app, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    owned.append(process)
    active[index] = process
    return process

def ready(index):
    api = Api('http://127.0.0.1:' + str(ports[index]))
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if active[index].poll() is not None:
            raise RuntimeError('Disposable API exited; private log retained in its workspace')
        try:
            api.call('current_session')
            return api
        except Exception:
            time.sleep(1)
    raise TimeoutError('Disposable API did not become ready')

def parallel(functions):
    barrier = threading.Barrier(len(functions))
    def run(fn):
        barrier.wait(timeout=10)
        begin = time.monotonic()
        return fn(), time.monotonic() - begin
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return [future.result() for future in [pool.submit(run, fn) for fn in functions]]

def source_digest(root):
    paths = [root / '.jac-version', root / 'jac.toml']
    for name in ('services', 'client'):
        paths.extend(path for path in (root / name).rglob('*') if path.is_file() and
            path.suffix in ('.jac', '.py', '.mjs', '.js', '.jsx', '.css') and not path.name.endswith(('.test.jac', '.test.mjs', '.test.js')))
    paths.extend(path for path in root.glob('*.jac') if path.is_file() and not path.name.endswith('.test.jac'))
    paths.extend(path for path in (root / 'data').rglob('*') if path.is_file())
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        digest.update(path.read_bytes().replace(b'\r\n', b'\n') + b'\0')
    return digest.hexdigest()

import jaclang
from jaclang.server.session import Session
import jaclang.server.session as session_module
assert Path(session_module.__file__).resolve().is_relative_to(Path(os.environ['JAC_CACHE_HOME']).resolve())
assert all(Path(value).resolve().is_relative_to(Path(os.environ['JAC_CACHE_HOME']).resolve()) for value in jaclang.__path__)
result = {'scope': __doc__.strip(), 'status': 'running', 'checks': checks,
          'executed_proof_sha256': hashlib.sha256((directory / 'executed-proof.py').read_bytes()).hexdigest(),
          'simultaneous_claim_and_redemption_attempts': student_count,
          'disposable_postgres_port': pg_port,
          'original_production_source_digest_sha256': source_digest(source),
          'served_fixture_source_digest_sha256': source_digest(app),
          'candidate_binary_sha256': hashlib.sha256((package / 'jac').read_bytes()).hexdigest(),
          'runtime_module_file': jaclang.__file__, 'session_debug_filename': Session.commit.__code__.co_filename,
          'session_declaring_module_file': session_module.__file__,
          'session_debug_filename_scope': 'Historical code debug label; actual declaring module and SDK roots are bound to the fresh package cache',
          'development_source_and_build_stage_unavailable': True,
          'package_input_verification_sha256': os.environ['MLOCAL_PACKAGE_BINDING_SHA256'],
          'runtime_patch_sha256': packaged['runtime_patch_sha256'], 'runtime_base_revision': packaged['runtime_base']}
if unknown_commit:
    result['test_only_instrumentation'] = 'main.jac imports fault_probe.py in the disposable app only; PgStore acknowledgement lost after real COMMIT'
    result['test_only_hook_sha256'] = hashlib.sha256(hook.read_bytes()).hexdigest()
assert Path(jaclang.__file__).is_relative_to(Path(os.environ['JAC_CACHE_HOME']))
try:
    assert source_digest(source) == '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42'
    print('Retained two-API workspace:', directory, flush=True)
    info = runtime.ensure()
    subprocess.run([jac, 'install'], cwd=app, check=True, stdout=(directory / 'install.log').open('w'), stderr=subprocess.STDOUT)
    serve(0, info)
    anonymous = ready(0)
    state = CodeStore(private[0])
    run = secrets.token_hex(4)
    def verify(kind, suffix):
        codes = []
        value = 'ta' + run + suffix + ('@example.test' if kind == 'business' else '')
        challenge = state.request(value, kind, 'Two API fixture', lambda _email, code: codes.append(code))
        verified = anonymous.call('verify_email_code', challenge=challenge['challenge'], code=codes[0])
        require(verified['ok'] and verified.get('token'), kind + ' ' + suffix + ' verifies through native HTTP auth')
        return verified['token']
    owner_token = verify('business', 'owner')
    other_owner_token = verify('business', 'otherowner')
    suffixes = ('a', 'b') if student_count == 2 else tuple('s' + str(index).zfill(2) for index in range(student_count))
    tokens = [verify('student', suffix) for suffix in suffixes]
    owner = Api(anonymous.origin, owner_token)
    actor = owner.call('current_session')['actor_id']
    fields = dict(name='Two API Cafe ' + run, cuisine='Cafe', description='Synthetic concurrency fixture',
        address='123 Fictional Street', website='', menu_text='', menu_url='', image_url='', confirmed=True)
    require(owner.call('save_business_draft', **fields)['status'] == 'pending_review', 'fixture requires business approval')
    env = dict(os.environ, MLOCAL_ONBOARDING_DIR=str(private[0]))
    subprocess.run(['bash', 'scripts/review-business.sh', 'approve', '--actor', actor, '--by', 'Fixture operator',
        '--note', 'Fictional concurrency fixture', '--submission', business_revision(state.draft(actor))],
        cwd=app, env=env, check=True, stdout=(directory / 'approval.log').open('w'), stderr=subprocess.STDOUT)
    require(owner.call('save_business_draft', **fields)['status'] == 'active', 'approved fixture activates')
    other_owner = Api(anonymous.origin, other_owner_token)
    other_actor = other_owner.call('current_session')['actor_id']
    other_fields = dict(fields, name='Other Two API Cafe ' + run, address='456 Fictional Street')
    require(other_owner.call('save_business_draft', **other_fields)['status'] == 'pending_review', 'second owner needs approval')
    subprocess.run(['bash', 'scripts/review-business.sh', 'approve', '--actor', other_actor, '--by', 'Fixture operator',
        '--note', 'Fictional independent owner', '--submission', business_revision(state.draft(other_actor))],
        cwd=app, env=env, check=True, stdout=(directory / 'other-approval.log').open('w'), stderr=subprocess.STDOUT)
    require(other_owner.call('save_business_draft', **other_fields)['status'] == 'active', 'second owner activates separately')
    # Quiesced private-state copy establishes equal initial authority only.
    # The files and locks are distinct thereafter; no write replication is claimed.
    private[1].mkdir(parents=True)
    with sqlite3.connect(state.path) as original, sqlite3.connect(private[1] / state.path.name) as copied:
        original.backup(copied)
    shutil.copy2(private[0] / 'code.key', private[1] / 'code.key')
    serve(1, info)
    second = ready(1)
    owners = [Api(api.origin, owner_token) for api in (anonymous, second)]
    students = [Api((anonymous, second)[index % 2].origin, token) for index, token in enumerate(tokens)]
    require(all(client.call('current_session')['role'] == 'merchant' for client in owners), 'both APIs accept the same approved merchant')
    require(all(client.call('current_session')['role'] == 'student' for client in students), 'separate APIs accept distinct student principals')
    now = datetime.now(ZoneInfo('America/Detroit'))
    fields = dict(offer_id='', create_key=secrets.token_hex(16), title='Two API last unit ' + run, description='Fictional offer', price='3', regular_price='5',
        start_local=(now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M'),
        end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='1', eligibility='Valid U-M ID',
        terms='One per student', dietary='', menu_item='')
    same = dict(fields, create_key=secrets.token_hex(16), title='Concurrent same publish ' + run, quantity='2')
    attempts = parallel([lambda client=client: client.call('save_offer', **same) for client in owners])
    require(all(row[0]['ok'] for row in attempts) and len({row[0]['code'] for row in attempts}) == 1,
            'concurrent same-key same-body publishes return one offer identity')
    require(len([item for item in owners[0].call('merchant_portal')['offers'] if item['title'] == same['title']]) == 1,
            'concurrent same-key publish persists exactly one offer')
    formatted = owners[1].call('save_offer', **dict(same, price='3.00', quantity='02', start_local=same['start_local'].replace(' ', 'T')))
    require(formatted['ok'] and formatted['code'] == attempts[0][0]['code'], 'equivalent money quantity and time formatting retries the original publish')
    conflict = dict(fields, create_key=secrets.token_hex(16), title='Concurrent payload A ' + run)
    variants = [conflict, dict(conflict, title='Concurrent payload B ' + run)]
    attempts = parallel([lambda client=client, body=body: client.call('save_offer', **body) for client, body in zip(owners, variants)])
    require(sum(bool(row[0]['ok']) for row in attempts) == 1,
            'concurrent same-key different-body publishes have one winner')
    require(all(row[0]['ok'] or 'already published with different details' in row[0]['message'] for row in attempts),
            'different-body loser receives an explicit edit instruction')
    scoped = dict(fields, create_key=secrets.token_hex(16), title='Owner-scoped key ' + run)
    attempts = parallel([lambda: owners[0].call('save_offer', **scoped),
                         lambda: Api(second.origin, other_owner_token).call('save_offer', **scoped)])
    require(all(row[0]['ok'] for row in attempts) and len({row[0]['code'] for row in attempts}) == 2,
            'different approved owners can use the same key for their separate offers')
    saved = owners[0].call('save_offer', **fields)
    require(saved['ok'], 'first API publishes a one-unit offer')
    offer_id = saved['code']
    require(all(client.call('get_offer', offer_id=offer_id)['id'] == offer_id for client in students), 'both APIs read the same graph offer')
    attempts = parallel([lambda client=client: client.call('claim_offer', offer_id=offer_id) for client in students])
    claims = [row[0] for row in attempts]
    result['claim_results'] = [{'ok': bool(row['ok']), 'message': row['message']} for row in claims]
    result['claim_latency_seconds'] = [row[1] for row in attempts]
    require(sum(bool(row['ok']) for row in claims) == 1, 'independent-lock last-unit claims have exactly one winner')
    require(all(row['ok'] or row['message'] == 'This offer is sold out right now.' for row in claims), 'losing claim is an expected business refusal')
    winner = next(index for index, row in enumerate(claims) if row['ok'])
    claim = claims[winner]
    retry = Api(second.origin if winner % 2 == 0 else anonymous.origin, tokens[winner]).call('claim_offer', offer_id=offer_id)
    require(retry['ok'] and retry['claim_id'] == claim['claim_id'] and retry['qr_payload'] == claim['qr_payload'], 'claim retry through other API returns the original claim')
    stop(active[1])
    serve(1, info)
    ready(1)
    recovered = Api(second.origin, tokens[winner]).call('claim_offer', offer_id=offer_id)
    require(recovered['ok'] and recovered['claim_id'] == claim['claim_id'] and recovered['qr_payload'] == claim['qr_payload'], 'API restart preserves the original held claim and QR')
    attempts = parallel([lambda client=owners[index % 2]: client.call('redeem_claim', qr_payload=claim['qr_payload']) for index in range(student_count)])
    result['redeem_results'] = [{'ok': bool(row[0]['ok']), 'message': row[0]['message']} for row in attempts]
    result['redeem_latency_seconds'] = [row[1] for row in attempts]
    require(sum(bool(row[0]['ok']) for row in attempts) == 1, 'independent-lock redemptions have exactly one winner')
    require(all(row[0]['ok'] or row[0]['message'] == 'This claim was already redeemed.' for row in attempts), 'losing redemption is an expected business refusal')
    require(all(client.call('get_offer', offer_id=offer_id)['remaining'] == 0 for client in students), 'both API reads converge on exhausted stock')
    require(not owners[0].call('redeem_claim', qr_payload=claim['qr_payload'])['ok'], 'repeated redemption remains rejected')
    stop(active[0])
    serve(0, info)
    ready(0)
    require(not owners[0].call('redeem_claim', qr_payload=claim['qr_payload'])['ok'], 'API restart preserves redemption refusal')
    if os.environ.get('MLOCAL_PROBE_LOST_CREATE_RESPONSE') == '1':
        create = dict(fields, create_key=secrets.token_hex(16), title='Lost create response ' + run)
        body = json.dumps(create).encode()
        request = (b'POST /function/save_offer HTTP/1.1\r\nHost: 127.0.0.1\r\n' +
            b'Content-Type: application/json\r\nAuthorization: Bearer ' + owner_token.encode() +
            b'\r\nContent-Length: ' + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)
        with socket.create_connection(('127.0.0.1', ports[0]), timeout=30) as transport:
            transport.sendall(request)
            deadline = time.monotonic() + 30
            accepted = []
            while time.monotonic() < deadline:
                accepted = [item for item in owners[1].call('merchant_portal')['offers'] if item['title'] == create['title']]
                if accepted:
                    break
                time.sleep(0.05)
            require(len(accepted) == 1, 'first publish commits while the client discards its response')
            # Deliberately close without receiving any response bytes.
        retry = owners[1].call('save_offer', **create)
        published = [item for item in owners[0].call('merchant_portal')['offers'] if item['title'] == create['title']]
        result['lost_create_response_offer_count'] = len(published)
        require(retry['ok'] and retry['code'] == accepted[0]['id'] and len(published) == 1,
                'retry after discarded publish response returns the original offer without duplication')
        for index in range(2):
            stop(active[index])
            serve(index, info)
            ready(index)
        restarted = owners[0].call('save_offer', **create)
        require(restarted['ok'] and restarted['code'] == accepted[0]['id'],
                'publish retry after both API restarts retains the original offer identity')
    if unknown_commit:
        create = dict(fields, create_key=secrets.token_hex(16), title='Unknown commit HTTP fixture ' + run)
        request = urllib.request.Request(owners[0].origin + '/function/save_offer', json.dumps(create).encode(),
            {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + owner_token}, method='POST')
        try:
            urllib.request.urlopen(request, timeout=60)
            raise AssertionError('Lost COMMIT acknowledgement must surface uncertainty')
        except urllib.error.HTTPError as error:
            envelope = json.loads(error.read())
            result['uncertain_http_response'] = {'status': error.code, 'body': envelope}
            require(error.code == 503 and 'COMMIT_UNCERTAIN' in json.dumps(envelope).upper(),
                    'accepted COMMIT with lost acknowledgement returns HTTP 503 commit_uncertain')
        fault = json.loads((app / '.jac/commit-fault.json').read_text())
        require(fault['real_commit_completed'] and fault['acknowledgements_discarded'] == 1,
                'test hook discarded exactly one acknowledgement after a real COMMIT')
        committed = [item for item in owners[1].call('merchant_portal')['offers'] if item['title'] == create['title']]
        require(len(committed) == 1, 'uncertain HTTP publish persists exactly one offer')
        retry = owners[1].call('save_offer', **create)
        require(retry['ok'] and retry['code'] == committed[0]['id'], 'publish key reconciles uncertain commit through the other API')
        require(len([item for item in owners[0].call('merchant_portal')['offers'] if item['title'] == create['title']]) == 1,
                'uncertain commit reconciliation does not create a duplicate offer')
        result['intentional_http_503_count'] = 1
    for index in range(2):
        log = '\n'.join(path.read_text() for path in directory.glob('api-' + str(index) + '*.log'))
        expected_503 = 1 if unknown_commit and index == 0 else 0
        require('Traceback (most recent call last)' not in log and ' 500 ' not in log and log.count(' 503 ') == expected_503,
                'API ' + str(index) + ' has no unexpected tracebacks or 5xx responses')
    result['correctness_status'] = 'passed'
    result['mutation_latency'] = {name: {label: sorted(result[name + '_latency_seconds'])[math.ceil(student_count * fraction) - 1]
        for label, fraction in (('p95_seconds', .95), ('p99_seconds', .99))} for name in ('claim', 'redeem')}
    target_met = all(row['p95_seconds'] <= 2 and row['p99_seconds'] <= 5 for row in result['mutation_latency'].values())
    result['status'] = 'passed' if target_met else 'failed_latency_target'
except BaseException as error:
    result['status'] = 'failed'
    result['error'] = type(error).__name__ + ': ' + str(error)
    raise
finally:
    for process in owned:
        stop(process)
    runtime.stop()
    result['owned_api_processes_stopped'] = all(process.poll() is not None for process in owned)
    result['owned_api_process_ids'] = [process.pid for process in owned]
    result['postgres_stopped'] = not runtime.is_running()
    result['runtime_source_override'] = None
    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


raise SystemExit(0 if result['status'] == 'passed' and result['owned_api_processes_stopped'] and result['postgres_stopped'] else 1)
