"""Operator-pulled backup of a hosted deployment that offers no shell.

JacHammer gives no database or volume access, so the app itself produces one
coordinated snapshot when the operator's machine asks for it with
MLOCAL_BACKUP_TOKEN (at least 40 characters; unset means backups are off):

* every application table in the graph database, as row_to_json text taken in
  one REPEATABLE READ, READ ONLY transaction on a separate connection, plus the
  table, constraint, index and sequence definitions needed to recreate them;
* the private onboarding store (SQLite online-backup copies), the original
  onboarding key, the review-notice file and the photo-ownership registry;
* uploaded photos.

The app serves one request at a time, so nothing writes while the snapshot is
taken. The snapshot is sent once over HTTPS and never written to disk on the
host. It contains account emails, sign-in secrets and the onboarding key: the
operator machine encrypts it on arrival (scripts/backup-pull.sh).
"""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

FORMAT = 'm-local-hosted-backup-v1'
MIN_TOKEN_LENGTH = 40
MIN_INTERVAL_SECONDS = 300
MAX_PHOTO_BYTES = 200 * 1024 * 1024
PRIVATE_FILES = ('onboarding.sqlite3', 'photo-ownership.sqlite3', 'code.key', 'review-notices.json')
_state = {'last': 0.0}
_lock = threading.Lock()


class BackupRefused(Exception):
    pass


def token_accepted(token):
    expected = os.environ.get('MLOCAL_BACKUP_TOKEN', '')
    if len(expected) < MIN_TOKEN_LENGTH or not isinstance(token, str):
        return False
    return hmac.compare_digest(token.encode(), expected.encode())


def _app_root():
    return Path(__file__).resolve().parents[1]


def _private_dir():
    return Path(os.environ.get('MLOCAL_ONBOARDING_DIR', str(_app_root() / '.jac/onboarding'))).resolve()


def _conninfo():
    from jaclang import JacRuntime as Jac
    store = Jac.get_context().mem.store
    info = getattr(store, 'conninfo', None)
    if info is None:
        raise BackupRefused('The graph database is not a PostgreSQL store.')
    return info


def _connect():
    from jaclang.data.pgload import connect
    info = _conninfo()
    return connect(info.user, host=(info.host or None), port=info.port, unix_socket_dir=info.unix_socket_dir,
                   database=info.database, password=(info.password or None), timeout=120,
                   startup_params={'application_name': 'm-local-backup'})


def _q(name):
    return '"' + str(name).replace('"', '""') + '"'


def _graph(conn):
    conn.run('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
    try:
        tables = conn.run(
            "SELECT n.nspname, c.relname, c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
            "AND n.nspname NOT LIKE 'pg_toast%' AND NOT c.relispartition ORDER BY 1, 2")
        out = []
        for schema, table, oid in tables:
            columns = conn.run(
                'SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, pg_get_expr(d.adbin, d.adrelid) '
                'FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum '
                f'WHERE a.attrelid = {int(oid)} AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum')
            constraints = conn.run(
                'SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint '
                f"WHERE conrelid = {int(oid)} ORDER BY contype = 'f', conname")
            indexes = conn.run(
                'SELECT i.relname, pg_get_indexdef(i.oid) FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid '
                f'WHERE x.indrelid = {int(oid)} AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = x.indexrelid) '
                'ORDER BY 1')
            rows = [r[0] for r in conn.run(f'SELECT row_to_json(t)::text FROM {_q(schema)}.{_q(table)} t')]
            digest = hashlib.sha256('\n'.join(rows).encode()).hexdigest()
            out.append({'schema': schema, 'table': table,
                        'columns': [{'name': c[0], 'type': c[1], 'not_null': bool(c[2]), 'default': c[3]} for c in columns],
                        'constraints': [{'name': c[0], 'definition': c[1]} for c in constraints],
                        'indexes': [{'name': i[0], 'definition': i[1]} for i in indexes],
                        'rows': rows, 'row_count': len(rows), 'sha256': digest})
        sequences = [{'schema': s[0], 'name': s[1], 'last_value': s[2]} for s in conn.run(
            "SELECT schemaname, sequencename, last_value FROM pg_sequences WHERE schemaname NOT IN ('pg_catalog', 'information_schema')")]
        extensions = [e[0] for e in conn.run("SELECT extname FROM pg_extension WHERE extname != 'plpgsql' ORDER BY 1")]
        schemas = [s[0] for s in conn.run(
            "SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'public') "
            "AND nspname NOT LIKE 'pg_%' ORDER BY 1")]
        version = conn.run('SHOW server_version')[0][0]
        return {'server_version': version, 'schemas': schemas, 'extensions': extensions,
                'tables': out, 'sequences': sequences}
    finally:
        conn.run('ROLLBACK')


def _sqlite_copy(path):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / path.name
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15) as source, sqlite3.connect(target) as copy:
            source.backup(copy)
        copy_check = sqlite3.connect(target)
        try:
            if copy_check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise BackupRefused(f'{path.name} failed its integrity check.')
        finally:
            copy_check.close()
        return target.read_bytes()


def _file(name, data):
    return {'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'base64': base64.b64encode(data).decode()}


def _private():
    directory = _private_dir()
    files = []
    for name in PRIVATE_FILES:
        path = directory / name
        if not path.is_file():
            continue
        data = _sqlite_copy(path) if name.endswith('.sqlite3') else path.read_bytes()
        files.append(_file(name, data))
    if not any(f['name'] == 'code.key' and f['bytes'] == 32 for f in files):
        raise BackupRefused('The original onboarding key is missing; refusing an incomplete backup.')
    return files


def _photos():
    directory = _app_root() / 'assets' / 'photos'
    files, total = [], 0
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.is_symlink() or path.name.startswith('.'):
                continue
            data = path.read_bytes()
            total += len(data)
            if total > MAX_PHOTO_BYTES:
                raise BackupRefused('Uploaded photos exceed the backup size limit; back them up separately.')
            files.append(_file(path.name, data))
    return files


def snapshot(token, clock=time.time):
    """Return the backup as one JSON string, or raise BackupRefused."""
    if not token_accepted(token):
        raise BackupRefused('Backups are not enabled, or this backup token is wrong.')
    with _lock:
        now = clock()
        if now - _state['last'] < MIN_INTERVAL_SECONDS:
            raise BackupRefused('A backup was taken in the last five minutes; try again later.')
        _state['last'] = now
    started = time.monotonic()
    conn = _connect()
    try:
        graph = _graph(conn)
    finally:
        conn.close()
    body = {'format': FORMAT, 'created_at': now, 'source_revision': _revision(),
            'entry_path': str(_app_root() / 'main.jac'), 'graph': graph,
            'private': _private(), 'photos': _photos()}
    body['seconds'] = round(time.monotonic() - started, 3)
    text = json.dumps(body, separators=(',', ':'), sort_keys=True)
    return json.dumps({'sha256': hashlib.sha256(text.encode()).hexdigest(), 'backup': body}, separators=(',', ':'), sort_keys=True)


def _revision():
    path = _app_root() / '.jachammer-source-revision'
    try:
        return path.read_text().strip()[:64]
    except OSError:
        return ''
