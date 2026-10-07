"""Coordinated restore rehearsal for a disposable local HTTP application.

The fixture starts from the real approval/photo HTTP journey, adds two real
student claims and a second approved merchant, then quiesces every owned
writer before copying the matching PostgreSQL cluster and private SQLite/key/
photo state. It restores the same canonical source path and verifies the
graph, native identity, onboarding, JWT, claim snapshots, redemption state,
photo bytes and photo ownership across restore and a later restart.

This is a private loopback rehearsal. It does not prove a fresh host, sealed
relocation, public deployment, SMTP delivery, or RPO/RTO.
"""
from datetime import datetime, timedelta
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
PORT = 8252
REQUIRED_JAC = '0.37.23'
PRIVATE_LOG_HINT = ''
PHOTO_PAYLOAD = 'data:image/jpeg;base64,' + (
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAQDAwQDAwQEBAQFBQQFBwsHBwYGBw4KCggLEA4RERAOEA8SFBoWEhMYEw8QFh8XGBsbHR0dERYgIh8cIhocHRz/2wBDAQUFBQcGBw0HBw0cEhASHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBz/wAARCAAwAEADASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCegKsmIAAAAAAAAAAAAAAAAAAAAAD/2Q=='
)


class Api:
    def __init__(self, origin, token=''):
        self.origin = origin
        self.token = token

    def call(self, endpoint, **params):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        request = urllib.request.Request(self.origin + '/function/' + endpoint,
            json.dumps(params).encode(), headers, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                envelope = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403, 404):
                return {'ok': False, 'http_status': error.code}
            raise RuntimeError(endpoint + ' returned an unexpected HTTP status') from None
        if not envelope.get('ok'):
            return {'ok': False}
        return envelope.get('data', {}).get('result', {})


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    path.chmod(0o700)
    assert not path.is_symlink() and path.stat().st_mode & 0o777 == 0o700


def private_file(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def assert_no_symlinks(root):
    assert not root.is_symlink()
    assert all(not path.is_symlink() for path in root.rglob('*'))


def copy_tree(source, destination, *, skip_private=False):
    assert source.is_dir() and not source.is_symlink()
    destination.mkdir(mode=0o755, parents=True, exist_ok=False)
    for path in source.rglob('*'):
        relative = path.relative_to(source)
        if any(part == '__pycache__' or part.startswith('.env') for part in relative.parts):
            continue
        if skip_private and ('.jac' in relative.parts or 'venv' in relative.parts or '.venv' in relative.parts
                             or relative.parts[:2] == ('assets', 'photos')):
            continue
        target = destination / relative
        if path.is_symlink():
            raise AssertionError('source tree contains an unexpected symlink')
        if path.is_dir():
            target.mkdir(mode=path.stat().st_mode & 0o777, parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            data = path.read_bytes()
            if path.suffix == '.sh':
                data = data.replace(b'\r\n', b'\n')
            target.write_bytes(data)
            target.chmod(path.stat().st_mode & 0o777)
    assert_no_symlinks(destination)


def copy_application(source, destination):
    assert destination.is_dir() and not destination.is_symlink()
    destination.chmod(0o700)
    for name in ('main.jac', 'theme.jac', 'jac.toml', '.jac-version'):
        path = source / name
        assert path.is_file() and not path.is_symlink()
        target = destination / name
        target.write_bytes(path.read_bytes())
        target.chmod(path.stat().st_mode & 0o777)
    for name in ('services', 'client', 'data', 'scripts', 'tests'):
        copy_tree(source / name, destination / name)
    copy_tree(source / 'assets/brand', destination / 'assets/brand')


def input_manifest(root):
    names = ['main.jac', 'theme.jac', 'jac.toml', '.jac-version']
    names.extend(str(path.relative_to(root)).replace('\\', '/')
                 for name in ('services', 'client', 'data', 'scripts', 'tests')
                 for path in sorted((root / name).rglob('*')) if path.is_file())
    names.extend('assets/brand/' + str(path.relative_to(root / 'assets/brand')).replace('\\', '/')
                 for path in sorted((root / 'assets/brand').rglob('*')) if path.is_file())
    return {name: digest(root / name) for name in sorted(names)}


def stable_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sqlite_backup(source, destination):
    assert source.is_file() and not source.is_symlink()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    source_db = sqlite3.connect(source)
    target_db = sqlite3.connect(destination)
    try:
        source_db.backup(target_db)
        target_db.commit()
    finally:
        target_db.close()
        source_db.close()
    destination.chmod(0o600)


def process_group_alive(process):
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def scrub_environment(jac, cache, onboarding):
    environment = dict(os.environ)
    for key in list(environment):
        if re.search(r'(smtp|mail|sendgrid|resend|postmark|mailgun|ses)', key, re.IGNORECASE):
            environment.pop(key)
    for key in ('JAC_DB_URL', 'JAC_DEV_SOURCE', 'MLOCAL_IMPORT_MODEL', 'OPENAI_API_KEY', 'RESEND_API_KEY'):
        environment.pop(key, None)
    environment.update(
        JAC_BIN=str(jac), JAC_CACHE_HOME=str(cache), JAC_NO_DEV_SOURCE='1',
        PYTHONUNBUFFERED='1', MLOCAL_DEMO_MODE='0', MLOCAL_MERCHANT_OWNERS='{}',
        MLOCAL_DEMO_STUDENTS='[]', MLOCAL_ONBOARDING_DIR=str(onboarding),
        MLOCAL_IMPORT_MODEL='', PYTHONDONTWRITEBYTECODE='1',
        TMPDIR=str(cache / 'tmp'), NO_PROXY='127.0.0.1,localhost,::1', no_proxy='127.0.0.1,localhost,::1')
    assert 'JAC_DB_URL' not in environment and not any(re.search(r'(smtp|mail|sendgrid|resend|postmark|mailgun|ses)', key, re.IGNORECASE) for key in environment)
    return environment


def postgres_identity(environment, cache, runtime=None):
    print('RUN PostgreSQL distribution identity', flush=True)
    configured = Path(environment['JAC_PG_DIST']).resolve() if environment.get('JAC_PG_DIST') else None
    selected = []
    if runtime is not None:
        bin_dir = Path(runtime._bin_dir or runtime._resolve_binaries()).resolve()
        if bin_dir.name != 'bin' or not (bin_dir / 'postgres').is_file():
            raise RuntimeError('Selected PostgreSQL binary directory is unavailable')
        selected.append(bin_dir.parent)
    selected = list(dict.fromkeys(selected))
    if configured is not None:
        if selected and any(path != configured for path in selected):
            raise RuntimeError('JAC_PG_DIST disagrees with the running private PostgreSQL distribution')
        selected.append(configured)
    if not selected:
        selected = [path.parent.parent for path in (cache / 'pg/dist').rglob('postgres')
                    if path.is_file() and path.parent.name == 'bin']
    selected = list(dict.fromkeys(selected))
    if len(selected) != 1:
        raise RuntimeError('Could not resolve exactly one running private PostgreSQL distribution')
    distribution = selected[0]
    binary = distribution / 'bin/postgres'
    if distribution.is_symlink() or not distribution.is_dir() or binary.is_symlink() or not binary.is_file():
        raise RuntimeError('Selected PostgreSQL distribution does not contain a regular binary')
    files = {}
    for path in sorted(distribution.rglob('*')):
        if path.is_symlink():
            target = path.resolve()
            if not target.is_relative_to(distribution) or not target.is_file():
                raise RuntimeError('PostgreSQL distribution contains an unsafe symlink')
            files[str(path.relative_to(distribution)).replace('\\', '/')] = dict(
                link_text=os.readlink(path), target_relative=str(target.relative_to(distribution)).replace('\\', '/'),
                target_sha256=digest(target))
        elif path.is_file():
            files[str(path.relative_to(distribution)).replace('\\', '/')] = dict(file_sha256=digest(path))
    version = subprocess.check_output([str(binary), '--version'], text=True, stderr=subprocess.STDOUT,
                                      timeout=30).strip()
    return dict(distribution_root=str(distribution), binary_path=str(binary), version=version,
                binary_sha256=digest(binary), distribution_sha256=hashlib.sha256(stable_json(files)).hexdigest())


def stop_process(process):
    if process is None:
        return
    process.poll()
    if process_group_alive(process):
        os.killpg(process.pid, signal.SIGTERM)
        deadline = time.monotonic() + 15
        while process_group_alive(process) and time.monotonic() < deadline:
            process.poll()
            time.sleep(.1)
        if process_group_alive(process):
            os.killpg(process.pid, signal.SIGKILL)
            deadline = time.monotonic() + 15
            while process_group_alive(process) and time.monotonic() < deadline:
                process.poll()
                time.sleep(.1)
    if process.poll() is None:
        process.wait(timeout=15)
    assert not process_group_alive(process), 'owned process group remained after cleanup'


def run_logged(label, command, cwd, environment, log_path, timeout):
    print('RUN ' + label, flush=True)
    log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_path.touch(mode=0o600, exist_ok=True)
    log_path.chmod(0o600)
    process = None
    try:
        with log_path.open('ab') as log:
            process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            result = process.wait(timeout=timeout)
        if result:
            raise RuntimeError(label + ' failed')
    finally:
        if process is not None:
            stop_process(process)


def port_available():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', PORT))


def start_server(candidate, jac, environment, log_path, owned):
    port_available()
    log_path.touch(mode=0o600, exist_ok=True)
    log_path.chmod(0o600)
    with log_path.open('ab') as log:
        process = subprocess.Popen([str(jac), 'run', '--no-dev', '--no-client', '--host', '127.0.0.1', '--port', str(PORT)],
            cwd=candidate, env=environment, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True)
    owned.append(process)
    api = Api('http://127.0.0.1:' + str(PORT))
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('owned API exited during startup')
        try:
            if api.call('current_session').get('ok') is not False:
                return process, api
        except (OSError, RuntimeError, urllib.error.URLError):
            pass
        time.sleep(.5)
    raise TimeoutError('owned API did not become ready')


def check(condition, label, checks):
    if not condition:
        print('FAIL check: ' + label, flush=True)
        raise AssertionError(label)
    checks.append(label)
    print('PASS ' + label, flush=True)


def fetch_photo(api, url):
    with urllib.request.urlopen(api.origin + url, timeout=30) as response:
        data = response.read()
        assert response.headers.get_content_type() == 'image/jpeg'
    return data


def verify_code(state, anonymous, value, kind, name, api, checks):
    codes = []
    challenge = state.request(value, kind, name, lambda _email, code: codes.append(code))
    result = anonymous.call('verify_email_code', challenge=challenge['challenge'], code=codes[0])
    check(result.get('ok') and result.get('token'), kind + ' verifies through real HTTP without SMTP', checks)
    client = Api(api.origin, result['token'])
    session = client.call('current_session')
    check(session.get('authenticated') and session.get('email_verified') and session.get('role') == kind,
          kind + ' native identity and JWT session survives HTTP verification', checks)
    return client, session


def approve(candidate, state, actor, log_path, environment, checks):
    from services.email_codes import business_revision
    run_logged('local operator approval', ['bash', 'scripts/review-business.sh', 'approve', '--actor', actor,
        '--by', 'Recovery fixture operator', '--note', 'Confirmed disposable recovery authority',
        '--submission', business_revision(state.draft(actor))], candidate, environment, log_path, 180)
    check(state.business_approved(actor), 'operator approval is present in onboarding SQLite', checks)


def offer_fields(now, title, *, price='5', terms='Original recovery terms', eligibility='Recovery student ID'):
    return dict(offer_id='', create_key='recovery-' + hashlib.sha256((title + str(now)).encode()).hexdigest()[:32],
        title=title, description='Disposable restore offer', price=price, regular_price='7',
        start_local=(now - timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M'),
        end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='2',
        eligibility=eligibility, terms=terms, dietary='', menu_item='')


def main():
    global PRIVATE_LOG_HINT
    print('RUN coordinated recovery fixture', flush=True)
    if Path.cwd().resolve() != ROOT:
        raise RuntimeError('Run from the repository source root')
    if os.environ.get('JAC_DB_URL'):
        raise RuntimeError('External JAC_DB_URL is forbidden')
    if tomllib.loads((ROOT / 'jac.toml').read_text())['project']['jac-version'] != REQUIRED_JAC:
        raise RuntimeError('Repository Jac pin is not 0.37.23')
    jac = Path(os.environ.get('JAC_BIN', '')).resolve()
    if not jac.is_file() or jac.is_symlink():
        raise RuntimeError('Pinned Jac binary is unavailable')
    version = subprocess.check_output([str(jac), '--version'], text=True, stderr=subprocess.STDOUT, timeout=30).strip()
    if not version.startswith('jac ' + REQUIRED_JAC + ' '):
        raise RuntimeError('Pinned Jac version does not match 0.37.23')
    parent = Path(tempfile.mkdtemp(prefix='m-local-recovery.', dir='/var/tmp'))
    parent.chmod(0o700)
    private = parent / 'private'
    cache = parent / 'cache'
    private_dir(private)
    private_dir(cache)
    private_dir(cache / 'tmp')
    candidate = Path(tempfile.mkdtemp(prefix='m-local-release-approval.', dir='/var/tmp'))
    candidate.chmod(0o700)
    if candidate.parent != Path('/var/tmp') or not candidate.name.startswith('m-local-release-approval.'):
        raise RuntimeError('Candidate path is outside the fixed private /var/tmp namespace')
    release_copy = private / 'controlled-release-source'
    source_preserved = private / 'candidate-source-preserved'
    restored_source = private / 'candidate-source-restored'
    pg_preserved = private / 'pg-main-preserved'
    pg_cold = private / 'pg-main-cold-copy'
    logs = private / 'logs'
    private_dir(logs)
    PRIVATE_LOG_HINT = str(logs)
    onboarding = candidate / '.jac/onboarding'
    environment = scrub_environment(jac, cache, onboarding)
    os.environ.clear()
    os.environ.update(environment)
    source_manifest = None
    private_receipt = private / 'recovery-private.json'
    owned = []
    pg_path = (cache / 'pg/main').resolve()
    canonical_candidate = candidate.resolve()
    checks = []
    started = time.monotonic()
    github_sha = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch(r'[0-9a-fA-F]{7,64}', github_sha):
        github_sha = ''
    try:
        check(not cache.resolve().is_relative_to(candidate.resolve()), 'private cache is outside candidate source', checks)
        check(not any(candidate.iterdir()) and candidate.stat().st_mode & 0o777 == 0o700,
              'fresh candidate source is empty and private before mutation', checks)
        copy_application(ROOT, candidate)
        source_manifest = input_manifest(candidate)
        check(source_manifest == input_manifest(candidate), 'controlled application input manifest is stable', checks)
        source_manifest_sha = hashlib.sha256(stable_json(source_manifest)).hexdigest()
        private_file(private / 'source-input-manifest.json', stable_json(source_manifest) + b'\n')
        check(digest(candidate / '.jac-version') == digest(ROOT / '.jac-version'), 'pinned runtime source input copied', checks)
        session_module = __import__('jaclang.server.session', fromlist=['project_db_name', 'shared_pg_data_dir'])
        canonical_entry = (candidate / 'main.jac').resolve()
        source_project_db_name = session_module.project_db_name(str(candidate), str(canonical_entry))
        check(canonical_entry == canonical_candidate / 'main.jac' and canonical_entry.is_file() and
              not canonical_entry.is_symlink() and source_project_db_name,
              'canonical main.jac entry and runtime project database are bound', checks)
        environment['MLOCAL_ONBOARDING_DIR'] = str(onboarding)
        run_logged('Jac dependency installation', [str(jac), 'install'], candidate, environment, logs / 'install.log', 300)
        pg_module = __import__('jaclang.data.pgembed', fromlist=['PgRuntime'])
        process, anonymous = start_server(candidate, jac, environment, logs / 'api-initial.log', owned)
        running_pg = pg_module.PgRuntime(data_dir=str(pg_path), database='postgres')
        check(running_pg.is_running(), 'private embedded PostgreSQL is running for binary identity capture', checks)
        pg_identity_before = postgres_identity(environment, cache, running_pg)
        check(not Path(pg_identity_before['distribution_root']).is_relative_to(candidate) and
              Path(pg_identity_before['distribution_root']) != pg_path,
              'resolved PostgreSQL distribution is independent of source and data paths', checks)
        environment['JAC_PG_DIST'] = pg_identity_before['distribution_root']
        os.environ['JAC_PG_DIST'] = environment['JAC_PG_DIST']
        approval_code = 'import runpy,sys; sys.path.insert(0,"tests/integration"); runpy.run_path("tests/integration/business_approval_http.py",run_name="__main__")'
        approval_restart_code = 'import runpy,sys; sys.path.insert(0,"tests/integration"); sys.argv=["business_approval_http.py","--verify-restart"]; runpy.run_path("tests/integration/business_approval_http.py",run_name="__main__")'
        run_logged('business approval/photo fixture', ['bash', str(candidate / 'scripts/python.sh'), '-c', approval_code],
                   candidate, environment, logs / 'business-approval.log', 600)
        approval = json.loads((candidate / '.jac/approval-http.json').read_text())
        check((candidate / '.jac/approval-http.json').stat().st_mode & 0o777 == 0o600,
              'approval fixture receipt is private', checks)
        owner = Api(anonymous.origin, approval['token'])
        business_photo_bytes = fetch_photo(owner, approval['photo'])
        business_photo_sha = hashlib.sha256(business_photo_bytes).hexdigest()
        check(len(business_photo_bytes) > 100 and business_photo_bytes.startswith(b'\xff\xd8'),
              'approved business JPEG is fetched through HTTP', checks)
        sys.path.insert(0, str(candidate))
        state = __import__('services.email_codes', fromlist=['CodeStore']).CodeStore(onboarding)
        run = hashlib.sha256(os.urandom(16)).hexdigest()[:10]
        student_a, student_a_session = verify_code(state, anonymous, 'recovery' + run + 'a', 'student', 'Recovery Student A', anonymous, checks)
        student_b, student_b_session = verify_code(state, anonymous, 'recovery' + run + 'b', 'student', 'Recovery Student B', anonymous, checks)
        second, second_session = verify_code(state, anonymous, 'recovery' + run + 'm@example.test', 'business', 'Recovery Foreign Merchant', anonymous, checks)
        second_actor = second_session['actor_id']
        second_draft = dict(name='Recovery Foreign Merchant ' + run, cuisine='Cafe', description='Synthetic second authority',
            address='456 Recovery Street', website='', menu_text='Soup $5', menu_url='', image_url='', confirmed=True)
        saved = second.call('save_business_draft', **second_draft)
        check(saved.get('ok') and saved.get('status') == 'pending_review', 'second synthetic business submits for review', checks)
        approve(candidate, state, second_actor, logs / 'second-approval.log', environment, checks)
        check(second.call('save_business_draft', **second_draft).get('status') == 'active',
              'second approved merchant activates over HTTP', checks)
        blue = Api(anonymous.origin, approval['token']).call('upload_business_photo', payload=PHOTO_PAYLOAD)
        check(blue.get('ok') and blue['url'].startswith('/static/photos/'), 'owner uploads a second owned JPEG', checks)
        offer_photo = blue['url']
        check(approval['photo'] != offer_photo, 'business and offer photos have distinct URLs', checks)
        offer_photo_sha = hashlib.sha256(fetch_photo(owner, offer_photo)).hexdigest()
        check(business_photo_sha != offer_photo_sha, 'business and offer JPEG bytes are distinct', checks)
        now = datetime.now(ZoneInfo('America/Detroit'))
        fields = offer_fields(now, 'Recovery held lunch ' + run)
        created = owner.call('save_offer', **fields)
        check(created.get('ok'), 'dedicated two-unit offer is published', checks)
        offer_id = created['code']
        fields['offer_id'] = offer_id
        check(owner.call('save_offer', **fields, image_url=offer_photo).get('ok'), 'owner attaches its second JPEG to the offer', checks)
        claim_a = student_a.call('claim_offer', offer_id=offer_id)
        claim_b = student_b.call('claim_offer', offer_id=offer_id)
        check(claim_a.get('ok') and claim_b.get('ok'), 'two student claims are held in the real graph', checks)
        qr_a, qr_b = claim_a['qr_payload'], claim_b['qr_payload']
        original = owner.call('resolve_claim', qr_payload=qr_a)
        check(original.get('ok') and original['price_cents'] == 500, 'merchant resolves the original claim snapshot', checks)
        check(owner.call('redeem_claim', qr_payload=qr_b).get('ok'), 'one claim redeems before backup', checks)
        portal = owner.call('merchant_portal')
        row = next(item for item in portal['offers'] if item['id'] == offer_id)
        changed = dict(offer_id=offer_id, title=row['title'], description=row['description'], price='9', regular_price='12',
            start_local=row['start_input'], end_local=row['end_input'], quantity='2', eligibility='Future eligibility',
            terms='Future terms after hold', dietary='', menu_item='', image_url=offer_photo)
        check(owner.call('save_offer', **changed).get('ok'), 'current offer price and terms change after claims', checks)
        held = student_a.call('get_offer', offer_id=offer_id)
        check(held['my_price_cents'] == 500 and held['my_terms'] == original['terms'] and
              held['my_eligibility'] == original['eligibility'] and held['my_expires_ts'] == original['expires_ts'],
              'held claim keeps original price terms eligibility and expiry', checks)
        check(not student_b.call('resolve_claim', qr_payload=qr_a).get('ok'), 'other student cannot inspect another QR', checks)
        check(not second.call('resolve_claim', qr_payload=qr_a).get('ok'), 'second merchant cannot inspect another business QR', checks)
        foreign = offer_fields(now, 'Foreign image denial ' + run)
        foreign_created = second.call('save_offer', **foreign)
        check(foreign_created.get('ok'), 'second merchant publishes its own control offer', checks)
        foreign['offer_id'] = foreign_created['code']
        check(not second.call('save_offer', **foreign, image_url=offer_photo).get('ok'),
              'second merchant cannot reference the first merchant photo', checks)
        protected = dict(owner_token=approval['token'], second_token=second.token,
            student_a_token=student_a.token, student_b_token=student_b.token,
            owner_actor=approval['actor'], second_actor=second_actor,
            student_a_actor=student_a_session['actor_id'], student_b_actor=student_b_session['actor_id'],
            base_offer=approval['offer'], offer=offer_id, foreign_offer=foreign['offer_id'], qr_a=qr_a, qr_b=qr_b,
            claim_a=claim_a['claim_id'], claim_b=claim_b['claim_id'],
            business_photo=approval['photo'], offer_photo=offer_photo, create_key=fields['create_key'],
            original_claim={key: original[key] for key in ('title_snapshot', 'price_cents', 'terms', 'eligibility', 'expires_ts')},
            business_photo_sha256=business_photo_sha, offer_photo_sha256=offer_photo_sha)
        private_file(private_receipt, stable_json(protected) + b'\n')
        check(private_receipt.stat().st_mode & 0o777 == 0o600, 'recovery receipt with tokens and QR values is private', checks)
        approval_receipt_backup = private / 'approval-http.json'
        private_file(approval_receipt_backup, stable_json(approval) + b'\n')
        check(approval_receipt_backup.stat().st_mode & 0o777 == 0o600,
              'approval fixture receipt is retained privately for restore verification', checks)
        stop_process(process)
        check(not process_group_alive(process), 'initial owned API process group is gone before backup', checks)
        owned.remove(process)
        pg_path = Path(session_module.shared_pg_data_dir()).resolve()
        check(pg_path == (cache / 'pg/main').resolve(), 'embedded PostgreSQL is inside the private cache', checks)
        pg = pg_module.PgRuntime(data_dir=str(pg_path), database='postgres')
        check(pg.is_running(), 'private embedded PostgreSQL is running before quiesced backup', checks)
        pg.stop()
        check(not pg.is_running() and not (pg_path / 'postmaster.pid').exists(),
              'all owned PostgreSQL writers are stopped before copy', checks)
        assert_no_symlinks(pg_path)
        pg_version = (pg_path / 'PG_VERSION').read_text().strip()
        check(pg_identity_before['version'].split()[-1].split('.')[0] == pg_version,
              'embedded PostgreSQL cluster major version matches selected binary', checks)
        shutil.copytree(pg_path, pg_cold, symlinks=False)
        assert_no_symlinks(pg_cold)
        check(pg_cold.is_dir() and (pg_cold / 'PG_VERSION').read_text().strip() == pg_version,
              'cold physical PostgreSQL cluster copy retained at the matching version', checks)
        copy_tree(candidate, release_copy, skip_private=True)
        onboarding_backup = private / 'onboarding.sqlite3'
        photo_backup = private / 'photo-ownership.sqlite3'
        sqlite_backup(onboarding / 'onboarding.sqlite3', onboarding_backup)
        sqlite_backup(onboarding / 'photo-ownership.sqlite3', photo_backup)
        code_key_backup = private / 'code.key'
        jwt_backup = private / 'jwt_secret'
        shutil.copy2(onboarding / 'code.key', code_key_backup)
        shutil.copy2(candidate / '.jac/data/jwt_secret', jwt_backup)
        code_key_backup.chmod(0o600); jwt_backup.chmod(0o600)
        check(code_key_backup.stat().st_mode & 0o777 == 0o600 and jwt_backup.stat().st_mode & 0o777 == 0o600,
              'code.key and jwt_secret backups are private', checks)
        photo_backup_dir = private / 'photos'
        copy_tree(candidate / 'assets/photos', photo_backup_dir)
        photo_inventory = {str(path.relative_to(photo_backup_dir)): digest(path) for path in photo_backup_dir.rglob('*') if path.is_file()}
        check(set(photo_inventory) == {path.name for path in (candidate / 'assets/photos').iterdir() if path.is_file()},
              'all uploaded JPEGs are retained in one private photo inventory', checks)
        check(photo_inventory and all(name.lower().endswith('.jpg') for name in photo_inventory),
              'private photo inventory contains JPEGs only', checks)
        check(all(path.stat().st_mode & 0o777 == 0o644 for path in photo_backup_dir.rglob('*.jpg')),
              'uploaded JPEGs are retained in the private backup', checks)
        backup_meta = dict(onboarding_sha256=digest(onboarding_backup), photo_ownership_sha256=digest(photo_backup),
            code_key_sha256=digest(code_key_backup), jwt_secret_sha256=digest(jwt_backup), pg_cold_copy=str(pg_cold),
            photo_files={str(path.relative_to(photo_backup_dir)): digest(path) for path in photo_backup_dir.rglob('*.jpg')},
            approval_receipt_sha256=digest(approval_receipt_backup),
            canonical_entry=str(canonical_entry), project_db_name=source_project_db_name,
            postgres_identity_before=pg_identity_before)
        private_file(private / 'backup-manifest.json', stable_json(backup_meta) + b'\n')
        private_receipt.write_bytes(stable_json({**protected, **backup_meta}) + b'\n')
        private_receipt.chmod(0o600)
        source_preserved.parent.mkdir(mode=0o700, exist_ok=True)
        candidate.rename(source_preserved)
        pg_preserved.parent.mkdir(mode=0o700, exist_ok=True)
        pg_path.rename(pg_preserved)
        copy_tree(release_copy, restored_source)
        restored_source.rename(candidate)
        candidate.chmod(0o700)
        pg_path.parent.mkdir(mode=0o700, exist_ok=True)
        shutil.copytree(pg_cold, pg_path, symlinks=False)
        assert_no_symlinks(pg_path)
        pg_identity_after = postgres_identity(environment, cache)
        check(pg_identity_after == pg_identity_before,
              'restored PostgreSQL binary version, binary SHA and distribution identity match', checks)
        restore_onboarding = candidate / '.jac/onboarding'
        restore_onboarding.mkdir(mode=0o700, parents=True)
        restore_data = candidate / '.jac/data'
        restore_data.mkdir(mode=0o700, parents=True)
        sqlite_backup(onboarding_backup, restore_onboarding / 'onboarding.sqlite3')
        sqlite_backup(photo_backup, restore_onboarding / 'photo-ownership.sqlite3')
        shutil.copy2(code_key_backup, restore_onboarding / 'code.key')
        shutil.copy2(jwt_backup, restore_data / 'jwt_secret')
        shutil.copy2(approval_receipt_backup, candidate / '.jac/approval-http.json')
        (restore_onboarding / 'code.key').chmod(0o600); (restore_data / 'jwt_secret').chmod(0o600)
        (candidate / '.jac/approval-http.json').chmod(0o600)
        shutil.copytree(photo_backup_dir, candidate / 'assets/photos', symlinks=False)
        assert input_manifest(candidate) == source_manifest
        assert_no_symlinks(candidate)
        check(digest(restore_onboarding / 'onboarding.sqlite3') == digest(onboarding_backup) and
              digest(restore_onboarding / 'photo-ownership.sqlite3') == digest(photo_backup) and
              digest(restore_onboarding / 'code.key') == digest(code_key_backup) and
              digest(restore_data / 'jwt_secret') == digest(jwt_backup),
              'restored onboarding, photo ownership, code key and JWT secret bytes match backups', checks)
        check(source_preserved.is_dir() and candidate.is_dir() and
              candidate.resolve() == canonical_candidate and
              source_preserved.stat().st_ino != candidate.stat().st_ino and
              pg_preserved.is_dir() and pg_path.is_dir() and pg_preserved.stat().st_ino != pg_path.stat().st_ino,
              'restored source and PostgreSQL paths are fresh copies with originals retained', checks)
        check((restore_onboarding / 'onboarding.sqlite3').stat().st_ino != onboarding_backup.stat().st_ino and
              (restore_onboarding / 'photo-ownership.sqlite3').stat().st_ino != photo_backup.stat().st_ino,
              'restored SQLite databases are fresh online-backup copies', checks)
        restored_inventory = {str(path.relative_to(candidate / 'assets/photos')): digest(path)
                              for path in (candidate / 'assets/photos').rglob('*') if path.is_file()}
        check(restored_inventory == photo_inventory, 'restored photo inventory matches every backed-up JPEG', checks)
        check(input_manifest(candidate) == source_manifest, 'controlled source manifest matches before restore start', checks)
        restored_entry = (candidate / 'main.jac').resolve()
        restored_project_db_name = session_module.project_db_name(str(candidate), str(restored_entry))
        check(restored_entry == canonical_entry and restored_entry.is_file() and not restored_entry.is_symlink() and
              restored_project_db_name == source_project_db_name,
              'restored canonical main.jac and runtime project database are unchanged', checks)
        environment['MLOCAL_ONBOARDING_DIR'] = str(restore_onboarding)
        run_logged('Jac dependency reinstallation after restore', [str(jac), 'install'], candidate, environment,
                   logs / 'install-restored.log', 300)
        process, recovered_api = start_server(candidate, jac, environment, logs / 'api-restored.log', owned)
        run_logged('approval restart fixture', ['bash', str(candidate / 'scripts/python.sh'), '-c', approval_restart_code],
                   candidate, environment, logs / 'approval-restored.log', 300)
        restored_owner = Api(recovered_api.origin, protected['owner_token'])
        restored_second = Api(recovered_api.origin, protected['second_token'])
        restored_a = Api(recovered_api.origin, protected['student_a_token'])
        restored_b = Api(recovered_api.origin, protected['student_b_token'])
        check(restored_owner.call('current_session').get('role') == 'merchant', 'restored native identity and JWT authority agree', checks)
        check(all(client.call('current_session').get('actor_id') == protected[key] for client, key in (
            (restored_owner, 'owner_actor'), (restored_second, 'second_actor'),
            (restored_a, 'student_a_actor'), (restored_b, 'student_b_actor'))),
            'all four original native actor identities survive restore', checks)
        check(restored_owner.call('get_business_profile').get('name') == approval['name'], 'reviewed business identity survives restore', checks)
        restored_offer = restored_a.call('get_offer', offer_id=protected['offer'])
        restored_redeemed = restored_b.call('get_offer', offer_id=protected['offer'])
        check(restored_offer.get('my_status') == 'claimed' and restored_redeemed.get('my_status') == 'redeemed',
              'held and redeemed claim states survive restore', checks)
        check(restored_offer.get('my_claim_id') == protected['claim_a'] and
              restored_redeemed.get('my_claim_id') == protected['claim_b'] and
              restored_offer.get('my_qr_payload') == protected['qr_a'] and
              restored_offer.get('my_title') == protected['original_claim']['title_snapshot'],
              'original claim identities held QR and title snapshot survive restore', checks)
        check(restored_offer.get('image_url') == protected['business_photo'] and
              restored_offer.get('offer_image_url') == protected['offer_photo'],
              'distinct business and offer photo associations survive before any restored edit', checks)
        check(restored_offer.get('my_price_cents') == 500 and restored_offer.get('my_terms') == protected['original_claim']['terms'] and
              restored_offer.get('my_eligibility') == protected['original_claim']['eligibility'] and
              restored_offer.get('my_expires_ts') == protected['original_claim']['expires_ts'] and restored_offer.get('price') == 9,
              'claim snapshots and changed current offer survive restore', checks)
        check(hashlib.sha256(fetch_photo(restored_owner, protected['business_photo'])).hexdigest() == business_photo_sha and
              hashlib.sha256(fetch_photo(restored_owner, protected['offer_photo'])).hexdigest() == offer_photo_sha,
              'uploaded JPEG bytes survive restore over HTTP', checks)
        current = next(item for item in restored_owner.call('merchant_portal')['offers'] if item['id'] == protected['offer'])
        own_reselect = dict(offer_id=protected['offer'], title=current['title'], description=current['description'], price='9', regular_price='12',
            start_local=current['start_input'], end_local=current['end_input'], quantity='2', eligibility='Future eligibility',
            terms='Future terms after hold', dietary='', menu_item='', image_url=protected['offer_photo'])
        check(restored_owner.call('save_offer', **own_reselect).get('ok'), 'owner can reselect its restored uploaded photo', checks)
        foreign_current = next(item for item in restored_second.call('merchant_portal')['offers'] if item['id'] == protected['foreign_offer'])
        foreign_reselect = dict(offer_id=protected['foreign_offer'], title=foreign_current['title'], description=foreign_current['description'], price='5', regular_price='7',
            start_local=foreign_current['start_input'], end_local=foreign_current['end_input'], quantity='2', eligibility='Recovery student ID',
            terms='Original recovery terms', dietary='', menu_item='', image_url=protected['offer_photo'])
        check(not restored_second.call('save_offer', **foreign_reselect).get('ok'), 'foreign merchant remains unable to reference restored photo', checks)
        check(not restored_owner.call('redeem_claim', qr_payload=protected['qr_b']).get('ok'), 'restored redeemed QR refuses a second redemption', checks)
        check(restored_owner.call('redeem_claim', qr_payload=protected['qr_a']).get('ok'), 'restored held QR redeems exactly once', checks)
        check(not restored_b.call('resolve_claim', qr_payload=protected['qr_a']).get('ok') and
              not restored_second.call('resolve_claim', qr_payload=protected['qr_a']).get('ok'),
              'other student and merchant cannot inspect restored QR', checks)
        stop_process(process)
        check(not process_group_alive(process), 'restored API process group is gone before restart', checks)
        owned.remove(process)
        process, restarted_api = start_server(candidate, jac, environment, logs / 'api-restarted.log', owned)
        run_logged('approval second restart fixture', ['bash', str(candidate / 'scripts/python.sh'), '-c', approval_restart_code],
                   candidate, environment, logs / 'approval-restarted.log', 300)
        restarted_owner = Api(restarted_api.origin, protected['owner_token'])
        restarted_a = Api(restarted_api.origin, protected['student_a_token'])
        restarted_b = Api(restarted_api.origin, protected['student_b_token'])
        restarted_offer = restarted_a.call('get_offer', offer_id=protected['offer'])
        check(restarted_offer.get('image_url') == protected['business_photo'] and
              restarted_offer.get('offer_image_url') == protected['offer_photo'],
              'restart preserves distinct business and offer photo associations', checks)
        check(restarted_owner.call('current_session').get('role') == 'merchant' and
              restarted_a.call('get_offer', offer_id=protected['offer']).get('my_status') == 'redeemed' and
              restarted_b.call('get_offer', offer_id=protected['offer']).get('my_status') == 'redeemed',
              'both redeemed states survive a subsequent restart', checks)
        check(not restarted_owner.call('redeem_claim', qr_payload=protected['qr_a']).get('ok') and
              not restarted_owner.call('redeem_claim', qr_payload=protected['qr_b']).get('ok'),
              'restart preserves single-use QR refusal', checks)
        check(hashlib.sha256(fetch_photo(restarted_owner, protected['business_photo'])).hexdigest() == business_photo_sha and
              hashlib.sha256(fetch_photo(restarted_owner, protected['offer_photo'])).hexdigest() == offer_photo_sha,
              'restart preserves photo bytes and ownership-backed serving', checks)
        stop_process(process)
        check(not process_group_alive(process), 'restarted API process group is gone after verification', checks)
        owned.remove(process)
        pg_final = pg_module.PgRuntime(data_dir=str(pg_path), database='postgres')
        if pg_final.is_running():
            pg_final.stop()
        check(not pg_final.is_running() and not (pg_path / 'postmaster.pid').exists(),
              'all owned PostgreSQL processes stop after restart verification', checks)
        summary = dict(status='passed', checks=len(checks), elapsed_seconds=round(time.monotonic() - started, 3),
            runtime_version=version, runtime_bin_sha256=digest(jac), source_input_manifest_sha256=source_manifest_sha,
            postgres_version=pg_identity_before['version'], postgres_binary_sha256=pg_identity_before['binary_sha256'],
            postgres_distribution_sha256=pg_identity_before['distribution_sha256'],
            github_sha=github_sha, restore_success=True, restart_success=True, actual_smtp=False,
            canonical_source_entry_path_preserved=True,
            physical_copy_scope='cold physical PostgreSQL cluster copy; matching Jac/runtime version only',
            private_state_scope='onboarding.sqlite3/photo-ownership.sqlite3 via sqlite3.Connection.backup; code.key/jwt_secret/JPEGs copied',
            release_acceptance=False)
        print(json.dumps(summary), flush=True)
    finally:
        for process in reversed(owned):
            stop_process(process)
        if pg_path and pg_path.exists():
            pg = __import__('jaclang.data.pgembed', fromlist=['PgRuntime']).PgRuntime(data_dir=str(pg_path), database='postgres')
            if pg.is_running():
                pg.stop()
        owned.clear()


if __name__ == '__main__':
    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    try:
        main()
    except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError, ValueError, KeyError, TypeError,
            AssertionError, sqlite3.Error) as error:
        # Keep failure output useful without exposing private logs, tokens or raw server output.
        sys.stderr.write('FAIL recovery fixture: ' + type(error).__name__ + '; private recovery logs: ' +
                         (PRIVATE_LOG_HINT or '/var/tmp/m-local-recovery.*') + '\n')
        raise SystemExit(1) from error
