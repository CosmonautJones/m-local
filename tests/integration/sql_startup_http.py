"""Additional real-HTTP checks for the owned package fixture, never a launcher."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import urllib.request
from zoneinfo import ZoneInfo


@contextmanager
def client_libraries(tools):
    """Scope the extracted libpq to existing backup/restore client subprocesses."""
    previous = os.environ.get('LD_LIBRARY_PATH')
    os.environ['LD_LIBRARY_PATH'] = str(tools / 'usr/lib/x86_64-linux-gnu')
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop('LD_LIBRARY_PATH', None)
        else:
            os.environ['LD_LIBRARY_PATH'] = previous


def installed_driver(app, environment, workspace, check):
    """Fail as an assertion before starting PostgreSQL if normal deps lack SQL."""
    program = '''import json,sys
from pathlib import Path
import psycopg
from psycopg import pq
root=Path.cwd()/".jac/venv"
module=Path(psycopg.__file__).resolve()
assert Path(sys.prefix).resolve()==root.resolve()
assert module.is_relative_to((root/"lib").resolve())
assert psycopg.__version__=="3.3.6" and pq.__impl__=="binary"
print(json.dumps({"version":psycopg.__version__,"implementation":pq.__impl__,
                  "relative_module":str(module.relative_to(root.resolve()))}))
'''
    result = subprocess.run([str(app / '.jac/venv/bin/python'), '-c', program], cwd=app,
                            env=environment, capture_output=True, timeout=30)
    if result.returncode:
        (workspace / 'installed-driver-refusal.log').write_bytes(result.stdout + result.stderr)
    check(result.returncode == 0,
          'restored app normal offline venv contains pinned psycopg 3.3.6 binary implementation')
    return json.loads(result.stdout)


def postgres18_tools(package, tools, workspace, environment, command, check, receipt):
    """Use the existing official fetcher for the server and matching PG18 clients."""
    environment.update(JAC_PG_VERSION='18', JAC_TOOLCHAIN_DIR=str(workspace / 'runtime-cache/toolchains'),
                       TMPDIR=str(workspace / 'pg-tmp'))
    environment.pop('JAC_PG_DIST', None)
    Path(environment['TMPDIR']).mkdir(mode=0o700)
    output = workspace / 'pg18-distribution.json'
    program = '''import hashlib,json,os,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True)
os.chdir(root)
from jaclang.project.config import JacConfig,set_config
set_config(JacConfig(project_root=root))
from jaclang.data.pgembed import PgRuntime
runtime=PgRuntime(data_dir=str(root/"fetch-only-unused"),database="mlocal_aux_test_package_original")
bin_dir=Path(runtime.fetch_dist()).resolve(strict=True)
assert bin_dir.is_relative_to(Path(os.environ["JAC_CACHE_HOME"]).resolve())
tools={}
for name in ("postgres","initdb","pg_ctl"):
    executable=bin_dir/name
    version=subprocess.check_output([str(executable),"--version"],text=True,timeout=10).strip()
    assert int(version.split()[-1].split(".")[0])==18
    tools[name]={"version":version,"sha256":hashlib.sha256(executable.read_bytes()).hexdigest()}
Path(sys.argv[2]).write_text(json.dumps({"bin":str(bin_dir),"tools":tools}))
'''
    command(str(package / 'runtime/jacpython'), '-c', program, str(workspace), str(output))
    distribution = json.loads(output.read_text())
    server_bin = Path(distribution['bin'])
    client_bin = tools / 'usr/lib/postgresql/18/bin'
    clients = {}
    for name in ('createdb', 'pg_dump', 'pg_restore'):
        executable = client_bin / name
        check(executable.is_file(), 'package fixture has matching PostgreSQL18 client ' + name)
        version = command(str(executable), '--version').decode().strip()
        match = re.search(r'\b(\d+)\.\d+', version)
        check(match is not None and int(match[1]) == 18,
              'package fixture verifies PostgreSQL18 client version ' + name)
        clients[name] = dict(version=version, sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
    environment.update(JAC_PG_DIST=str(server_bin.parent),
                       PATH=str(client_bin) + ':' + str(server_bin) + ':' + environment['PATH'])
    receipt['pg18_distribution'] = dict(server=distribution['tools'], clients=clients)
    return server_bin


# Private stdin/stdout carries only this fixture's requests/results. Public
# evidence receives labels/counts; never rows, keys, credentials or connection text.
_OBSERVER = r'''
import hashlib,json,sys,time,uuid
from pathlib import Path
import psycopg
from psycopg import sql
def encode(value):
    if isinstance(value,(bytes,bytearray,memoryview)):
        return {"bytea":bytes(value).hex()}
    return str(value)
def decode(value):
    return bytes.fromhex(value["bytea"]) if set(value)=={"bytea"} else value
request=json.loads(sys.stdin.read(),object_hook=decode)
dsn,schema=request["dsn"],request["schema"]
assert schema.startswith("mlocal_aux_test_")
with psycopg.connect(dsn,connect_timeout=5,options="-c statement_timeout=15000 -c lock_timeout=5000") as c:
    assert c.info.dbname.startswith("mlocal_aux_test_")
    c.execute("SET LOCAL search_path TO pg_catalog")
    action=request["action"]
    if action=="import":
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    elif action=="snapshot":
        relations=c.execute("SELECT n.nspname,c.relname,c.relkind,c.relpersistence,c.relispartition,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' ORDER BY 1,2").fetchall()
        rows=[]
        for namespace,name,kind,*_ in relations:
            if kind in ("r","S"):
                values=c.execute(sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(namespace),sql.Identifier(name))).fetchall()
                rows.append((namespace,name,sorted(json.dumps(row,default=encode,sort_keys=True) for row in values)))
        definitions=[]
        for query in (
            "SELECT n.nspname,r.relname,a.attnum,a.attname,a.atttypid,a.atttypmod,a.attcollation,a.attnotnull,a.attidentity,a.attgenerated,a.attisdropped,pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a JOIN pg_class r ON r.oid=a.attrelid JOIN pg_namespace n ON n.oid=r.relnamespace LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' AND a.attnum>0 ORDER BY 1,2,3",
            "SELECT n.nspname,c.conrelid,c.conname,c.contype,c.condeferrable,c.condeferred,c.convalidated,c.conenforced,pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' ORDER BY 1,2,3",
            "SELECT n.nspname,c.relname,pg_get_indexdef(i.indexrelid),i.indisvalid,i.indisready FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' ORDER BY 1,2",
            "SELECT n.nspname,c.relname,s.seqstart,s.seqincrement,s.seqmin,s.seqmax,s.seqcache,s.seqcycle FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' ORDER BY 1,2",
            "SELECT n.nspname,p.proname,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' ORDER BY 1,2,p.oid",
        ):
            definitions.append(c.execute(query).fetchall())
        result={"state_sha256":hashlib.sha256(json.dumps((relations,rows,definitions),default=encode,sort_keys=True).encode()).hexdigest(),"server_version_num":c.info.server_version}
    elif action=="status":
        c.execute(sql.SQL("SET LOCAL search_path TO {},pg_catalog").format(sql.Identifier(schema)))
        c.execute("SELECT id FROM auxiliary_state WHERE id=1 FOR UPDATE")
        actor,status=request["actor"],request["status"]
        previous=c.execute("SELECT revision FROM business_status WHERE actor=%s",(actor,)).fetchone()[0]
        body={"actor":actor,"status":status,"reviewer":"Fixture operator","note":"Stopped disposable SQL authority witness","expected_revision":previous}
        digest=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        c.execute("UPDATE business_status SET status=%s,revision=%s WHERE actor=%s",(status,previous+1,actor))
        c.execute("INSERT INTO business_status_events VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,actor,status,previous,previous+1,body["reviewer"],body["note"],time.time(),digest))
        result={"status":status}
    elif action in ("extra_photo","admit"):
        result={}
    elif action=="sql":
        c.execute(sql.SQL("SET LOCAL search_path TO {},pg_catalog").format(sql.Identifier(schema)))
        result=[]
        for query,params in request["statements"]:
            cursor=c.execute(query,params)
            result.append(cursor.fetchall() if cursor.description else [])
    else:
        raise AssertionError("Unknown owned observer action")
if action=="import":
    from services.postgres_auxiliary import PostgresAuxiliary
    backend=PostgresAuxiliary(dsn,schema)
    backend.initialize()
    backend.import_legacy(*(Path(request[name]) for name in ("onboarding","registry","photos","code_key","native_key")))
    result={"imported":True}
elif action in ("extra_photo","admit"):
    from services.postgres_auxiliary import PostgresAuxiliary
    backend=PostgresAuxiliary(dsn,schema)
    if action=="extra_photo":
        backend.photo_save(request["actor"],request["filename"],request["content"],time.time())
    backend.signing_material()
    result={"healthy":backend.photo_owned(request["filename"],request["actor"])}
print(json.dumps(result,default=encode,sort_keys=True))
'''


def run_sql_startup_checks(f):
    """Reuse the existing fixture's launcher/process/HTTP/assertion callbacks."""
    app, workspace, onboarding = f['app'], f['workspace'], f['onboarding']
    check, config, environment = f['check'], f['config'], f['environment']
    schema = 'mlocal_aux_test_package_startup'
    dsn = environment['JAC_DB_URL']
    native_key, code_key = app / '.jac/data/jwt_secret', onboarding / 'code.key'
    cache, originals = app / 'assets/photos', workspace / 'retained-sql-original-photos'
    root_python = f['root_python']
    check(root_python.is_file(), 'SQL fixture uses an independent normal root project venv observer')
    cache.rename(originals)
    cache.mkdir(mode=0o700)
    original_paths = [onboarding / name for name in ('onboarding.sqlite3','photo-ownership.sqlite3','code.key')]
    original_paths += [native_key, *sorted(originals.iterdir())]

    def fingerprint(paths):
        result = []
        for path in paths:
            if not path.exists() and not path.is_symlink():
                result.append((str(path), 'missing', None, None))
                continue
            stat = path.lstat()
            metadata = (stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size, stat.st_mtime_ns)
            if path.is_symlink():
                kind, content = 'link', os.readlink(path)
            elif path.is_file():
                kind, content = 'file', hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                kind, content = 'directory', None
            result.append((str(path), kind, content, metadata))
        return result

    preserved = fingerprint(original_paths)
    photo_bytes = (originals / f['photo']['url'].rsplit('/', 1)[-1]).read_bytes()
    original_native_bytes, original_code_bytes = native_key.read_bytes(), code_key.read_bytes()
    def encoded(value):
        if isinstance(value, bytes):
            return {'bytea': value.hex()}
        raise TypeError('Unsupported fixture request value')
    def decoded(value):
        return bytes.fromhex(value['bytea']) if set(value) == {'bytea'} else value
    def observe(action, target_dsn=None, **values):
        request = dict(dsn=target_dsn or dsn, schema=schema, action=action, **values)
        result = subprocess.run([str(root_python), '-c', _OBSERVER], cwd=app, env=environment,
                                input=json.dumps(request, default=encoded).encode(), capture_output=True, timeout=90)
        if result.returncode:
            (workspace / ('sql-observer-' + secrets.token_hex(4) + '.log')).write_bytes(result.stdout + result.stderr)
        check(result.returncode == 0, 'independent SQL observer completes owned ' + action)
        return json.loads(result.stdout, object_hook=decoded)
    def sql(*statements):
        return observe('sql', statements=statements)
    observe('import', onboarding=str(onboarding / 'onboarding.sqlite3'), registry=str(onboarding / 'photo-ownership.sqlite3'),
            photos=str(originals), code_key=str(code_key), native_key=str(native_key))
    # A second real SQL-owned photo makes missing-one-file a nonempty partial
    # cache, distinct from the supported fresh/empty-cache reconstruction path.
    extra_photo = secrets.token_hex(16) + '.jpg'
    check(observe('extra_photo', actor=f['student_actor'], filename=extra_photo, content=photo_bytes)['healthy'],
          'SQL fixture establishes two real photo rows for partial-cache admission')
    check(observe('snapshot')['server_version_num'] // 10000 == 18, 'actual integrated native and auxiliary database is PostgreSQL18')
    check(fingerprint(original_paths) == preserved, 'SQL fixture import preserves all original SQLite key and photo bytes')
    local = dict(environment, MLOCAL_ENV='disposable', MLOCAL_ONBOARDING_BACKEND='postgres-local',
                 MLOCAL_AUXILIARY_TEST_DSN=dsn, MLOCAL_AUXILIARY_TEST_SCHEMA=schema)
    for name in ('JAC_SERVE_AUTH_SECRET', 'JAC_SERVE_AUTH_ALGORITHM', 'JAC_SV_SIBLING'):
        local.pop(name, None)
    launch_args = ['bash', str(app / 'scripts/release-run.sh'), '--package', str(f['package']),
                   '--config', str(f['config_file']), '--evidence', str(f['evidence_file']), '--disposable-sql']

    def ports():
        config.update(backend_port=f['next_port'](), gateway_port=f['next_port']())
        f['config_file'].write_text(json.dumps(config))
    def stopped(process, label):
        f['stop_process'](process)
        check(not f['process_group_alive'](process) and f['closed'](config['backend_port']) and f['closed'](config['gateway_port']),
              label + ' stops the entire owned group and both listeners')
    def launch(label):
        ports()
        process = f['start'](launch_args, local, label)
        try:
            gateway = f['ready'](process, 'http://127.0.0.1:' + str(config['gateway_port']), gateway=True)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            stopped(process, label)
            check(False, label + ' actual guarded SQL launcher reaches native and gateway readiness')
        check(True, label + ' actual guarded SQL launcher reaches native and gateway readiness')
        native_origin = 'http://127.0.0.1:' + str(config['backend_port'])
        for role in ('student', 'merchant', 'historical'):
            api = f['Api'](gateway.origin, f[role + '_token'])
            check(api.call('current_session').get('actor_id') == f[role + '_actor'], label + ' preserves original ' + role + ' token and native root actor')
        for role in ('student', 'merchant'):
            api = f['Api'](gateway.origin, f[role + '_token'])
            check(api.call('get_account_profile').get('display_name') == 'Preserved SQL ' + role + ' profile',
                  label + ' reads the original ' + role + ' authenticated saved profile')
        for role, claim in (('student', f['original_claim']), ('historical', f['historical_claim'])):
            detail = f['Api'](gateway.origin, f[role + '_token']).call('get_offer', offer_id=f['original_offer']['code'])
            check(detail.get('my_claim_id') == claim['claim_id'] and detail.get('my_status') == 'redeemed'
                  and detail.get('my_qr_payload') == '' and detail.get('my_terms') == 'Original package terms',
                  label + ' loads the original ' + role + ' private native graph claim and immutable snapshot')
        merchant = f['Api'](gateway.origin, f['merchant_token'])
        check(any(row['id'] == f['original_offer']['code'] for row in merchant.call('merchant_portal')['offers']),
              label + ' retains original merchant offer ownership through SQL authority')
        for origin, path_label in ((native_origin, 'native'), (gateway.origin, 'gateway')):
            with urllib.request.urlopen(origin + f['photo']['url'], timeout=15) as response:
                check(response.status == 200 and response.read() == photo_bytes and response.headers.get_content_type() == 'image/jpeg',
                      label + ' ' + path_label + ' GET serves exact original JPEG bytes')
            request = urllib.request.Request(origin + f['photo']['url'], method='HEAD')
            with urllib.request.urlopen(request, timeout=15) as response:
                check(response.status == 200 and response.read() == b'' and int(response.headers['Content-Length']) == len(photo_bytes),
                      label + ' ' + path_label + ' HEAD has original length and an empty body')
        before = observe('snapshot')
        before_cache = fingerprint([cache, *sorted(cache.iterdir())])
        check(merchant.call('upload_business_photo', payload=f['photo_payload']).get('ok') is False,
              label + ' explicitly refuses SQL mode photo uploads')
        check(observe('snapshot') == before and fingerprint([cache, *sorted(cache.iterdir())]) == before_cache and fingerprint(original_paths) == preserved,
              label + ' refused upload preserves SQL original SQLite keys photos and delivery cache')
        return process, gateway, merchant

    process, gateway, merchant = launch('sql-original-startup')
    fields = dict(f['fields'], description='Actual SQL draft authority marker')
    check(merchant.call('save_business_draft', **fields).get('status') == 'active', 'SQL native HTTP saves an approved business draft')
    draft = sql(('SELECT body FROM drafts WHERE actor=%s', [f['merchant_actor']]))[0][0][0]
    check(json.loads(draft).get('description') == fields['description'] and fingerprint(original_paths) == preserved,
          'SQL native draft RPC changes actual PostgreSQL without local SQLite fallback')
    now = datetime.now(ZoneInfo('America/Detroit'))
    offer = merchant.call('save_offer', offer_id='', create_key=secrets.token_hex(16), title='Disposable SQL authority offer',
        description='Integrated authority fixture', price='3.00', regular_price='5.00',
        start_local=(now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M'),
        end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='3', eligibility='Fixture student', terms='SQL authority terms', dietary='', menu_item='')
    check(offer.get('ok'), 'SQL owner publishes through real application HTTP')
    student = f['Api'](gateway.origin, f['student_token'])
    held = student.call('claim_offer', offer_id=offer['code'])
    check(held.get('ok') and merchant.call('resolve_claim', qr_payload=held['qr_payload']).get('ok'),
          'actual SQL owner resolves a real original-token student QR')
    stopped(process, 'sql-original-startup')
    observe('status', actor=f['merchant_actor'], status='suspended')
    process, gateway, merchant = launch('sql-normal-restart')
    check(merchant.call('current_session').get('merchant_paused') is True and not merchant.call('resolve_claim', qr_payload=held['qr_payload']).get('ok'),
          'normal SQL restart obeys SQL suspension despite preserved active SQLite authority')
    stopped(process, 'sql-normal-restart')
    observe('status', actor=f['merchant_actor'], status='active')
    # Remove only files materialized by this fixture, never original photo inputs.
    check(cache.resolve() == (app / 'assets/photos').resolve() and cache.is_dir() and not cache.is_symlink(),
          'SQL cache removal is bounded to the exact owned canonical delivery directory')
    expected_cache = {row[0] for row in sql(('SELECT filename FROM photos', []))[0]}
    check({p.name for p in cache.iterdir()} == expected_cache and all(p.is_file() and not p.is_symlink() for p in cache.iterdir()),
          'SQL cache removal refuses unknown entries')
    for path in cache.iterdir():
        path.unlink()
    process, gateway, merchant = launch('sql-cache-rebuild-restart')
    check(merchant.call('resolve_claim', qr_payload=held['qr_payload']).get('ok'), 'reconstructed SQL cache restart preserves the prior held QR and owner')
    stopped(process, 'sql-cache-rebuild-restart')

    def refused(label, changes=None, use_flag=True):
        ports()
        env = dict(local)
        for name, value in (changes or {}).items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value
        original_dsn = dsn.replace('_restored', '_original')
        before = (observe('snapshot'), observe('snapshot', target_dsn=original_dsn))
        before_files = fingerprint(original_paths)
        cache_paths = sorted(cache.rglob('*'))
        cache_files = fingerprint([cache, *cache_paths])
        process = f['start'](launch_args if use_flag else launch_args[:-1], env, 'sql-refusal-' + label)
        try:
            code = process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            stopped(process, 'sql-refusal-' + label)
            check(False, 'SQL startup ' + label + ' fails closed within its deadline')
        check(code != 0 and not f['process_group_alive'](process) and f['closed'](config['backend_port']) and f['closed'](config['gateway_port']),
              'SQL startup ' + label + ' refuses without native or gateway listeners')
        check((observe('snapshot'), observe('snapshot', target_dsn=original_dsn)) == before and fingerprint(original_paths) == before_files
              and sorted(cache.rglob('*')) == cache_paths and fingerprint([cache, *cache_paths]) == cache_files,
              'SQL startup ' + label + ' preserves native public SQL originals and cache without fallback or repair')
        diagnostic = (workspace / ('sql-refusal-' + label + '.log')).read_bytes()
        private = [dsn.encode(), original_native_bytes.strip(), original_code_bytes.hex().encode()]
        private += [f[name + '_token'].encode() for name in ('student','merchant','historical')]
        private += [env[name].encode() for name in ('JAC_DB_URL','MLOCAL_AUXILIARY_TEST_DSN','JAC_SERVE_AUTH_SECRET') if env.get(name)]
        check(not any(value and value in diagnostic for value in private), 'SQL startup ' + label + ' keeps private diagnostics out of its launcher output')

    for label, changes in (
        ('missing-dsn', {'MLOCAL_AUXILIARY_TEST_DSN': None}),
        ('missing-schema-config', {'MLOCAL_AUXILIARY_TEST_SCHEMA': None}),
        ('missing-schema', {'MLOCAL_AUXILIARY_TEST_SCHEMA': schema + '_absent'}),
        ('different-native-database', {'MLOCAL_AUXILIARY_TEST_DSN': dsn.replace('_restored', '_original')}),
        ('production-requested', {'MLOCAL_ENV': 'production'}),
        ('wrong-configured-key', {'JAC_SERVE_AUTH_SECRET': 'DISPOSABLE_WRONG_ORIGINAL_KEY_' + 'x' * 32}),
    ):
        refused(label, changes)
    refused('explicit-flag-required', use_flag=False)
    original_evidence = f['evidence_file'].read_bytes()
    evidence = json.loads(original_evidence)
    evidence['disposable_fixture_only'] = False
    f['evidence_file'].write_text(json.dumps(evidence))
    try:
        refused('fixture-evidence-required')
    finally:
        f['evidence_file'].write_bytes(original_evidence)
    # Real invalid SQL state, restored explicitly only after refusal preservation.
    for name in ('native_key', 'code_key'):
        material = sql(('SELECT material FROM signing_material WHERE name=%s', [name]))[0][0][0]
        sql(('UPDATE signing_material SET material=%s WHERE name=%s', [b'x' * 32, name]))
        try:
            refused('wrong-' + name)
        finally:
            sql(('UPDATE signing_material SET material=%s WHERE name=%s', [material, name]))
    material = sql(('DELETE FROM signing_material WHERE name=%s RETURNING material', ['native_key']))[0][0][0]
    try:
        refused('missing-native-key')
    finally:
        sql(('INSERT INTO signing_material VALUES (%s,%s)', ['native_key', material]))
    sql(('UPDATE business_status SET revision=revision+1 WHERE actor=%s', [f['merchant_actor']]))
    try:
        refused('incomplete-suspension-audit')
    finally:
        sql(('UPDATE business_status SET revision=revision-1 WHERE actor=%s', [f['merchant_actor']]))
    sql(('ALTER TABLE business_owners ALTER COLUMN active SET DEFAULT 1', []))
    try:
        refused('incompatible-schema')
    finally:
        sql(('ALTER TABLE business_owners ALTER COLUMN active SET DEFAULT 0', []))
    content = sql(('SELECT digest,bytes,content FROM photos WHERE filename=%s', [f['photo']['url'].rsplit('/',1)[-1]]))[0][0]
    bad = b'not a JPEG'
    sql(('UPDATE photos SET digest=%s,bytes=%s,content=%s WHERE filename=%s', [hashlib.sha256(bad).hexdigest(), len(bad), bad, f['photo']['url'].rsplit('/',1)[-1]]))
    try:
        refused('corrupt-owned-photo')
    finally:
        sql(('UPDATE photos SET digest=%s,bytes=%s,content=%s WHERE filename=%s', [*content, f['photo']['url'].rsplit('/',1)[-1]]))
    unrelated = cache / 'unknown.txt'
    unrelated.write_bytes(b'owned negative cache witness')
    try:
        refused('unknown-nonempty-cache')
    finally:
        unrelated.unlink()
    target = cache / f['photo']['url'].rsplit('/',1)[-1]
    target.write_bytes(b'corrupt cached bytes')
    try:
        refused('corrupt-cache')
    finally:
        target.write_bytes(photo_bytes)
    partial = workspace / 'retained-partial-cache-photo'
    target.rename(partial)
    try:
        refused('partial-nonempty-cache')
    finally:
        partial.rename(target)
    for name, kind in (('.photo-interrupted', 'file'), ('unexpected-directory', 'directory'), ('unexpected-link', 'link')):
        extra = cache / name
        if kind == 'directory':
            extra.mkdir()
        elif kind == 'link':
            extra.symlink_to(originals / f['photo']['url'].rsplit('/',1)[-1])
        else:
            extra.write_bytes(b'owned interrupted-cache marker')
        try:
            refused('cache-' + kind)
        finally:
            extra.rmdir() if kind == 'directory' else extra.unlink()
    original_key_hold = workspace / 'retained-missing-native-key'
    native_key.rename(original_key_hold)
    try:
        refused('missing-original-native-file')
    finally:
        original_key_hold.rename(native_key)
    hidden = workspace / 'retained-application-driver'
    driver = next((app / '.jac/venv/lib').glob('python*/site-packages/psycopg'))
    driver.rename(hidden)
    try:
        refused('missing-installed-driver')
    finally:
        hidden.rename(driver)
    unavailable = dsn.replace(':' + str(environment['PGPORT']) + '/', ':' + str(f['next_port']()) + '/')
    refused('database-outage', {'JAC_DB_URL': unavailable, 'MLOCAL_AUXILIARY_TEST_DSN': unavailable})
    check(observe('admit', filename=f['photo']['url'].rsplit('/',1)[-1], actor=f['merchant_actor'])['healthy'],
          'all SQL startup negative fixtures restore a healthy original authority')
    check(fingerprint(original_paths) == preserved, 'complete SQL startup and refusal matrix preserves every original SQLite key and photo byte')
    f['receipt']['sql_startup_scope'] = dict(canonical_entry_unchanged=True, original_tokens_reused=True,
        startup_only=True, ongoing_sql_readiness_certified=False, uploads_supported=False,
        cache_reconstructed_after_stop=True, interrupted_cache_construction_certified=False,
        fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
