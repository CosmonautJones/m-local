"""Real PostgreSQL/source-runtime initialization proof, not sealed release acceptance."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
import ast
import hashlib
import json
import marshal
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.request

from jaclang.data.pgembed import PgRuntime
from jaclang.data.pgwire import PgWireError
from jaclang.data.store import ConnInfo, PgStore, TxnIsolation
from jaclang.server.identity.identity_storage import PgIdentityStorage, IdentityStorage, IdentityTakenError
from jaclang.server.identity.user_manager import SYSTEM_USER, UserManager
from jaclang.runtime.constants import Constants

directory = Path(os.environ['MLOCAL_IDENTITY_PROOF_WORKSPACE'])
fork = Path(os.environ['JAC_DEV_SOURCE']).parent
assert directory.parent == Path('/var/tmp') and directory.name.startswith('m-local-identity-bootstrap-proof-v4-')
assert directory.is_mount() and directory.stat().st_uid == 65534 and directory.stat().st_mode & 0o777 == 0o700
method_file = Path(PgIdentityStorage.ensure_indexes.__code__.co_filename).resolve()
assert method_file.is_relative_to(fork)
method_source_sha256 = hashlib.sha256(method_file.read_bytes()).hexdigest()
assert method_source_sha256 == '46856b750bb693fed472e2f75dc0b11878a6344845aaeb04924f4632f2125063'
assert any(isinstance(value, str) and 'pg_advisory_xact_lock' in value and 'jac:identity_schema' in value
    for value in PgIdentityStorage.ensure_indexes.__code__.co_consts)
loaded_methods = {}
for label, method, relative in (
    ('store_run', PgStore._run, 'jac/jaclang/data/impl/store.impl.jac'),
    ('store_main', PgStore._main, 'jac/jaclang/data/impl/store.impl.jac'),
    ('store_begin', PgStore.begin, 'jac/jaclang/data/impl/store.impl.jac'),
    ('store_commit', PgStore.commit, 'jac/jaclang/data/impl/store.impl.jac'),
    ('store_rollback', PgStore.rollback, 'jac/jaclang/data/impl/store.impl.jac'),
    ('store_discard', PgStore._discard_main, 'jac/jaclang/data/impl/store.impl.jac'),
    ('identity_insert', PgIdentityStorage._store_user, 'jac/jaclang/server/identity/impl/identity_storage.pg.impl.jac'),
    ('identity_create', IdentityStorage.create_user, 'jac/jaclang/server/identity/impl/identity_storage.impl.jac'),
    ('internal_ensure', UserManager.ensure_internal_user, 'jac/jaclang/server/identity/impl/user_manager.impl.jac'),
):
    path = Path(method.__code__.co_filename).resolve()
    assert path == fork / relative
    loaded_methods[label] = dict(file=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        loaded_code_sha256=hashlib.sha256(marshal.dumps(method.__code__)).hexdigest())
assert 'Pinned database connection was replaced' in PgStore._run.__code__.co_consts
assert any(isinstance(v,str) and 'jac:identity_bootstrap' in v and 'pg_advisory_lock' in v
    for v in UserManager.ensure_internal_user.__code__.co_consts)
app = directory / 'app' 
production = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local/work/m-local')
app.mkdir(mode=0o700)
for name in ('main.jac', 'theme.jac', 'jac.toml', '.jac-version'):
    shutil.copyfile(production / name, app / name)
for name in ('services', 'client', 'data', 'scripts'):
    shutil.copytree(production / name, app / name, ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(production / 'assets/brand', app / 'assets/brand')
digest_helper = Path('/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local/work/export-emergency-checkpoint.py')
assert hashlib.sha256(digest_helper.read_bytes()).hexdigest() == 'e73a01554b5b3fccb66b4544773b7dc74928c7d7ce7dbb1fcc60bf3c9f26caf4'
digest_node = next(node for node in ast.parse(digest_helper.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == 'digest')
digest_scope = dict(Path=Path, hashlib=hashlib)
exec(compile(ast.fix_missing_locations(ast.Module(body=[digest_node], type_ignores=[])), str(digest_helper), 'exec'), digest_scope)
app_digest = digest_scope['digest'](app)
assert app_digest == '71f73c9482f65ae41ca9521650f22bf5d226bc535c39379ef16ddce465341f42'
private = app / '.jac/identity-proof-private'
with socket.socket() as probe:
    probe.bind(('127.0.0.1', 0))
    pg_port = probe.getsockname()[1]
runtime = PgRuntime(data_dir=str(directory / 'pg'), database='identity_start', tcp=True, port=pg_port)
owned = []
stores = []
checks = []
result = dict(status='running', scope=__doc__, workspace=str(directory), runtime_patch_sha256=os.environ['MLOCAL_IDENTITY_PATCH_SHA256'],
    implementation_file=str(method_file), executed_proof_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    implementation_source_sha256=method_source_sha256,
    implementation_loaded_code_sha256=hashlib.sha256(marshal.dumps(PgIdentityStorage.ensure_indexes.__code__)).hexdigest(),
    loaded_identity_method_has_transaction_advisory_lock=True, loaded_methods=loaded_methods, graph_identity_atomicity=False,
    production_source_digest_sha256=app_digest,
    digest_helper_sha256=hashlib.sha256(digest_helper.read_bytes()).hexdigest(),
    copied_app_digest_verified_before_api_start=True,
    api_readiness_timeout_seconds=1200,
    checks=checks, actual_smtp=False, sealed_package=False)

def require(condition, label):
    assert condition, label
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

def store_for(info, database):
    store = PgStore(conninfo=ConnInfo(host='127.0.0.1', port=info.port, user=info.user,
        password=info.password, database=database), auto_schema=False)
    stores.append(store)
    return store

def identity_indexes(store):
    return store.rows("SELECT indexname FROM pg_indexes WHERE schemaname=current_schema() AND tablename IN ('identity_users','identity_lookups','sso_lookups') ORDER BY indexname", {})

def identity_tables(store):
    return store.rows("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename IN ('identity_users','identity_lookups','sso_lookups')", {})

def start_api(index, info):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    env = dict(os.environ, MLOCAL_ONBOARDING_DIR=str(private), MLOCAL_DEMO_MODE='0',
        MLOCAL_MERCHANT_OWNERS='{}', MLOCAL_DEMO_STUDENTS='[]')
    env['JAC_DB_URL'] = 'postgresql://' + quote(info.user, safe='') + ':' + quote(info.password, safe='') + '@127.0.0.1:' + str(info.port) + '/' + info.database
    log_path = directory / ('api-' + str(index) + '-' + str(len(owned)) + '.log')
    with log_path.open('w') as log:
        process = subprocess.Popen([os.environ['JAC_BIN'], 'run', '--no-dev', '--no-client', '--host', '127.0.0.1', '--port', str(port)],
            cwd=app, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    owned.append(process)
    return process, port, log_path

def ready(row):
    process, port, _ = row
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        assert process.poll() is None, 'Concurrent source API exited during startup'
        try:
            request = urllib.request.Request('http://127.0.0.1:' + str(port) + '/function/current_session', b'{}', {'Content-Type':'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=3) as response:
                envelope = json.load(response)
            assert envelope['ok'] and not envelope['data']['result']['authenticated']
            return
        except Exception:
            time.sleep(.5)
    raise TimeoutError('Concurrent source API readiness timed out')

try:
    print('Retained identity source proof: ' + str(directory), flush=True)
    info = runtime.ensure()
    admin = store_for(info, info.database)
    require(identity_tables(admin) == [], 'new database starts with no identity tables')
    with (directory / 'install.log').open('w') as log:
        subprocess.run([os.environ['JAC_BIN'], 'install'], cwd=app, env=os.environ,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
    for phase in ('concurrent-empty-database-start', 'concurrent-initialized-database-restart'):
        pair = [start_api(index, info) for index in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(ready, pair))
        require(all(row[0].poll() is None for row in pair), phase + ': both APIs are ready')
        indexes = identity_indexes(admin)
        require([row[0] for row in indexes] == ['identity_lookups_pkey','identity_users_pkey','idx_identity_lookups_user','sso_lookups_pkey'], phase + ': exactly four expected identity indexes')
        builtin_users = admin.rows("SELECT doc->>'role',doc->'identities'->0->>'value_normalized',jsonb_array_length(doc->'identities') FROM identity_users ORDER BY doc->>'role'", {})
        require(builtin_users == [('system', SYSTEM_USER, 1), ('user', Constants.GUEST.value, 1)], phase + ': exactly the two runtime built-in identities; no fixture accounts')
        lookup_counts = admin.rows("SELECT count(*),count(DISTINCT user_id) FROM identity_lookups", {})[0]
        orphan_count = admin.rows("SELECT count(*) FROM identity_users t WHERE NOT EXISTS (SELECT 1 FROM identity_lookups l WHERE l.user_id=t.user_id)", {})[0][0]
        require(lookup_counts == (2,2) and orphan_count == 0, phase + ': exactly one lookup owner per builtin; zero orphan identity docs')
        for process, _, _ in pair:
            stop(process)
        for _, _, log_path in pair:
            text = log_path.read_text()
            require('Traceback (most recent call last)' not in text and 'Error executing' not in text, phase + ': startup log has no runtime failure')

    original_rows = PgStore.rows
    admin.rows('CREATE DATABASE identity_rollback', {})
    target = store_for(info, 'identity_rollback')
    seen = []
    def failing_rows(store, sql, params):
        if store is target and 'CREATE ' in sql:
            seen.append(sql)
            if len(seen) == 3:
                raise RuntimeError('Disposable third DDL failure')
        return original_rows(store, sql, params)
    PgStore.rows = failing_rows
    try:
        try:
            PgIdentityStorage(store=target)
            raise AssertionError('DDL fault was swallowed')
        except RuntimeError as error:
            require(str(error) == 'Disposable third DDL failure', 'third DDL fault propagates')
    finally:
        PgStore.rows = original_rows
    require(not target.in_txn() and identity_tables(target) == [], 'failed DDL rolls back every preceding table')
    require(target.rows("SELECT pg_try_advisory_lock(hashtext('jac:identity_schema'))", {})[0][0], 'DDL rollback releases migration lock')
    target.rows("SELECT pg_advisory_unlock(hashtext('jac:identity_schema'))", {})
    PgIdentityStorage(store=target)
    require(len(identity_indexes(target)) == 4, 'clean retry after DDL rollback succeeds')

    admin.rows('CREATE DATABASE identity_timeout', {})
    blocked = store_for(info, 'identity_timeout')
    holder = store_for(info, 'identity_timeout')
    holder.rows("SELECT pg_advisory_lock(hashtext('jac:identity_schema'))", {})
    started = time.monotonic()
    try:
        try:
            PgIdentityStorage(store=blocked)
            raise AssertionError('Contended lock did not time out')
        except PgWireError as error:
            state = next(arg['C'] for arg in error.args if isinstance(arg, dict) and 'C' in arg)
            require(state == '55P03', 'configured lock timeout propagates55P03')
    finally:
        holder.rows("SELECT pg_advisory_unlock(hashtext('jac:identity_schema'))", {})
    result['observed_lock_timeout_seconds'] = time.monotonic() - started
    require(9 <= result['observed_lock_timeout_seconds'] <= 15 and not blocked.in_txn() and identity_tables(blocked) == [], 'ten-second lock timeout is bounded and leaves no identity DDL')
    PgIdentityStorage(store=blocked)
    require(len(identity_indexes(blocked)) == 4, 'startup succeeds after competing lock releases')

    admin.rows('CREATE DATABASE identity_ack_lost', {})
    uncertain = store_for(info, 'identity_ack_lost')
    original_commit = PgStore.commit
    accepted = []
    def lost_ack(store):
        original_commit(store)
        if store is uncertain:
            accepted.append(True)
            raise PgWireError({'C':'08006','M':'Disposable acknowledgement lost after real identity DDL COMMIT'})
    PgStore.commit = lost_ack
    try:
        try:
            PgIdentityStorage(store=uncertain)
            raise AssertionError('Lost acknowledgement was swallowed')
        except PgWireError:
            require(accepted == [True], 'exactly one real identity DDL COMMIT acknowledgement is discarded')
    finally:
        PgStore.commit = original_commit
    recovered = store_for(info, 'identity_ack_lost')
    require(len(identity_indexes(recovered)) == 4, 'accepted uncertain identity DDL remains committed')
    PgIdentityStorage(store=recovered)
    require(len(identity_indexes(recovered)) == 4, 'next startup safely repeats all IF NOT EXISTS DDL')

    admin.rows('CREATE DATABASE identity_nested', {})
    nested = store_for(info, 'identity_nested')
    nested.begin(TxnIsolation.READ_COMMITTED)
    try:
        try:
            PgIdentityStorage(store=nested)
            raise AssertionError('Caller transaction was not rejected')
        except RuntimeError as error:
            require('requires its own transaction' in str(error) and nested.in_txn(), 'initializer preserves an existing caller transaction')
    finally:
        nested.rollback()
    require(identity_tables(nested) == [], 'existing caller transaction receives no identity DDL')
    identity = PgIdentityStorage(store=admin)
    manager = object.__new__(UserManager)
    manager._identity_storage = identity
    manager.base_path = str(app)
    manager.provision_unknown_users = False
    peer = store_for(info, info.database)
    def lock_available():
        available = peer.rows("SELECT pg_try_advisory_lock(hashtext('jac:identity_bootstrap'))", {})[0][0]
        if available:
            peer.rows("SELECT pg_advisory_unlock(hashtext('jac:identity_bootstrap'))", {})
        return available
    def row_counts():
        return admin.rows('SELECT (SELECT count(*) FROM identity_users),(SELECT count(*) FROM identity_lookups)', {})[0]
    def fixture(user_id, value):
        return dict(user_id=user_id, status='active', identities=[dict(type='username',value_raw=value,value_normalized=value,verified=True)], credentials=[],root_id=None,role='user')
    existing_guest = manager.find_user_by_identity(Constants.GUEST.value)
    original_timeout = admin.rows('SHOW lock_timeout', {})[0][0]
    before_counts = row_counts()
    require(manager.ensure_internal_user(Constants.GUEST.value,'public-proof-sentinel')['user_id'] == existing_guest['user_id'], 'existing builtin provisioning returns the same principal')
    require(row_counts() == before_counts and lock_available() and admin._pinned_conn is None,
        'existing builtin retry creates no documents and releases pin and session lock')

    peer.rows("SELECT pg_advisory_lock(hashtext('jac:identity_bootstrap'))", {})
    started = time.monotonic()
    try:
        try:
            manager.ensure_internal_user(Constants.GUEST.value,'public-proof-sentinel')
            raise AssertionError('Bootstrap contention was swallowed')
        except PgWireError as error:
            require(any(isinstance(arg,dict) and arg.get('C')=='55P03' for arg in error.args), 'bootstrap lock timeout propagates55P03')
    finally:
        peer.rows("SELECT pg_advisory_unlock(hashtext('jac:identity_bootstrap'))", {})
    result['observed_bootstrap_lock_timeout_seconds'] = time.monotonic()-started
    require(9 <= result['observed_bootstrap_lock_timeout_seconds'] <= 15 and not admin.in_txn()
        and admin._pinned_conn is None and admin.rows('SHOW lock_timeout', {})[0][0] == original_timeout,
        'bootstrap timeout restores transaction state and prior timeout')
    require(manager.ensure_internal_user(Constants.GUEST.value,'public-proof-sentinel')['user_id'] == existing_guest['user_id'] and lock_available(),
        'same store retries successfully after bootstrap contention')

    # Reentrant guest lookup models the shared-root helper's call back into ensure_internal_user.
    original_find = UserManager.find_user_by_identity
    nested_calls = []
    def nested_find(current, value):
        if current is manager and not nested_calls:
            nested_calls.append(True)
            found = manager.ensure_internal_user(Constants.GUEST.value,'public-proof-sentinel')
            require(found['user_id'] == existing_guest['user_id'] and not lock_available(),
                'nested guest provisioning keeps the outer session lock held')
        return original_find(current,value)
    UserManager.find_user_by_identity = nested_find
    try:
        manager.ensure_internal_user(Constants.GUEST.value,'public-proof-sentinel')
    finally:
        UserManager.find_user_by_identity = original_find
    require(len(nested_calls)==1 and lock_available() and admin._pinned_conn is None,
        'nested guest provisioning returns without deadlock and balances lock and pin')

    # A real active transaction must survive rejection before Root save/commit.
    before_roots = admin.rows('SELECT count(*) FROM anchors', {})[0][0]
    admin.begin(TxnIsolation.READ_COMMITTED)
    admin.rows("INSERT INTO kv_state(key,value) VALUES ('identity-caller-sentinel','held')", {})
    try:
        for operation in (lambda: identity.create_user([dict(type='username',value='proof-caller')],{}),
                          lambda: manager.ensure_internal_user('proof-caller','public-proof-sentinel'),
                          lambda: identity._store_user(fixture('proof-caller-id','proof-caller'))):
            try:
                operation()
                raise AssertionError('Caller transaction accepted')
            except RuntimeError as error:
                require('requires its own transaction' in str(error) and admin.in_txn(), 'identity entry point rejects and preserves caller transaction')
        require(admin.rows('SELECT count(*) FROM anchors', {})[0][0] == before_roots,
            'rejected caller transaction creates no graph root')
    finally:
        admin.rollback()
    require(admin.rows("SELECT count(*) FROM kv_state WHERE key='identity-caller-sentinel'", {})[0][0] == 0,
        'caller sentinel remains rollbackable after identity rejection')

    before_counts = row_counts()
    original_rows = PgStore.rows
    def dml_failure(store, sql, params):
        if store is admin and 'INSERT INTO identity_lookups' in sql:
            raise RuntimeError('Disposable identity lookup DML failure')
        return original_rows(store,sql,params)
    PgStore.rows = dml_failure
    try:
        try:
            identity._store_user(fixture('proof-fault-id','proof-fault'))
            raise AssertionError('DML error swallowed')
        except RuntimeError as error:
            require(str(error)=='Disposable identity lookup DML failure', 'identity lookup DML error propagates')
    finally:
        PgStore.rows = original_rows
    require(row_counts()==before_counts and not admin.in_txn() and admin._pinned_conn is None,
        'lookup DML failure rolls back its preceding identity document and clears pin')
    try:
        identity._store_user(fixture('proof-conflict-id', Constants.GUEST.value))
        raise AssertionError('Lookup conflict swallowed')
    except IdentityTakenError:
        require(row_counts()==before_counts, 'real normalized lookup23505 maps to IdentityTakenError after whole-write rollback')
    duplicate = fixture(existing_guest['user_id'],'proof-unexpected-pkey')
    try:
        identity._store_user(duplicate)
        raise AssertionError('User primary key conflict swallowed')
    except PgWireError as error:
        require(any(isinstance(arg,dict) and arg.get('n')=='identity_users_pkey' for arg in error.args),
            'unexpected user primary-key23505 remains PgWireError')

    # Replace the main connection inside the protected lookup. No unprotected statement may execute.
    old_connection = admin._main()
    replacement_connection = peer._main()
    def replaced_find(current,value):
        if current is manager:
            admin._conn = replacement_connection
        return original_find(current,value)
    UserManager.find_user_by_identity = replaced_find
    try:
        try:
            manager.ensure_internal_user(Constants.GUEST.value,'public-proof-sentinel')
            raise AssertionError('Connection replacement accepted')
        except RuntimeError as error:
            require(str(error)=='Pinned database connection was replaced', 'protected lookup aborts immediately on connection replacement')
    finally:
        UserManager.find_user_by_identity = original_find
        if admin._conn is replacement_connection:
            admin._conn = None
    require(getattr(old_connection,'_closed',False) and peer._conn is replacement_connection and peer.rows('SELECT 1',{}) == [(1,)],
        'retirement closes only old pinned connection and preserves replacement')
    require(admin._pinned_conn is None and lock_available(), 'connection replacement releases bootstrap lock and pin')

    # Accept SQL COMMIT, then discard its acknowledgement. No rollback/replay is permitted.
    original_commit = PgStore.commit
    accepted = []
    ack_doc = fixture('proof-accepted-commit-id','proof-accepted-commit')
    def sql_lost_ack(store):
        original_commit(store)
        if store is admin:
            accepted.append(True)
            raise PgWireError({'C':'08006','M':'Disposable acknowledgement lost after real identity SQL COMMIT'})
    PgStore.commit = sql_lost_ack
    try:
        try:
            identity._store_user(ack_doc)
            raise AssertionError('SQL commit uncertainty swallowed')
        except PgWireError:
            require(accepted==[True] and admin._conn is None and not admin.in_txn(),
                'one real identity SQL COMMIT acknowledgement is discarded and connection retired')
    finally:
        PgStore.commit = original_commit
    committed = manager.find_user_by_identity('proof-accepted-commit')
    before_counts = row_counts()
    require(committed['user_id']=='proof-accepted-commit-id' and manager.ensure_internal_user('proof-accepted-commit','public-proof-sentinel')['user_id']==committed['user_id'],
        'retry after lost SQL acknowledgement resolves the same committed principal')
    require(row_counts()==before_counts and lock_available() and admin._pinned_conn is None,
        'lost SQL acknowledgement retry duplicates no identity and releases bootstrap lock')
    # Exercise a real SQL insert failure while the bootstrap lock is held.
    original_create_internal = UserManager.create_internal_user
    before_counts = row_counts()
    def fixture_create(current, username, password, role='user'):
        identity._store_user(fixture('proof-locked-dml-id',username))
        return dict(user_id='proof-locked-dml-id')
    UserManager.create_internal_user = fixture_create
    PgStore.rows = dml_failure
    try:
        try:
            manager.ensure_internal_user('proof-locked-dml','public-proof-sentinel')
            raise AssertionError('Locked DML error swallowed')
        except RuntimeError as error:
            require(str(error)=='Disposable identity lookup DML failure', 'real lookup DML error escapes locked provisioning')
    finally:
        UserManager.create_internal_user = original_create_internal
        PgStore.rows = original_rows
    require(row_counts()==before_counts and lock_available() and not admin.in_txn() and admin._pinned_conn is None,
        'locked DML failure rolls back identity rows and releases bootstrap lock and pin')

    # Force connection replacement immediately before the SQL COMMIT boundary.
    old_connection = admin._main()
    replacement_connection = peer._main()
    def replace_before_commit(store):
        if store is admin:
            admin._conn = replacement_connection
            admin._in_txn = False
            admin._isolation = None
        return original_commit(store)
    PgStore.commit = replace_before_commit
    try:
        try:
            identity._store_user(fixture('proof-replaced-commit-id','proof-replaced-commit'))
            raise AssertionError('Replaced commit connection accepted')
        except RuntimeError as error:
            require(str(error)=='Pinned database connection was replaced', 'SQL COMMIT aborts before execution on a replacement connection')
    finally:
        PgStore.commit = original_commit
        if admin._conn is replacement_connection:
            admin._conn = None
    require(getattr(old_connection,'_closed',False) and peer.rows('SELECT 1',{}) == [(1,)] and row_counts()==before_counts
        and not admin.in_txn() and admin._pinned_conn is None,
        'replaced SQL COMMIT retires old uncommitted write and preserves peer connection')

    before_counts = row_counts()
    upgraded = manager.ensure_internal_user('proof-accepted-commit','public-proof-sentinel',role='system')
    require(upgraded['user_id']=='proof-accepted-commit-id' and manager.get_user_role(upgraded['user_id'])=='system',
        'existing internal principal retains its identity during role upgrade')
    require(row_counts()==before_counts and lock_available() and admin._pinned_conn is None,
        'role upgrade adds no identity document and balances bootstrap lock and pin')
    result['remaining_limits'] = ['Graph root is committed before identity SQL; graph-commit lost acknowledgement and orphan-root recovery remain unverified',
        'Reentrant guest-helper callback modeled in source process; full nested shared-root browser workflow remains separate',
        'No migration or automatic cleanup of pre-existing duplicate identities', 'Source proof is not sealed package or sustained capacity acceptance']
    result['status'] = 'passed' 
except BaseException as error:
    result.update(status='failed', error_type=type(error).__name__, error=str(error))
    raise
finally:
    for process in owned:
        stop(process)
    for store in stores:
        store.close()
    runtime.stop()
    result.update(owned_processes_stopped=all(process.poll() is not None for process in owned),
        postgres_stopped=not runtime.is_running(), owned_process_ids=[process.pid for process in owned])
    (directory / 'child-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status':result['status'],'checks':len(checks)}), flush=True)
