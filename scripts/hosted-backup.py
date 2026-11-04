#!/usr/bin/env python3
"""Pull, verify, encrypt and restore M-Local hosted backups on the operator's machine.

    python3 scripts/hosted-backup.py setup --url https://<host>          # once
    python3 scripts/hosted-backup.py pull                                 # daily (scheduled)
    python3 scripts/hosted-backup.py verify <file.json.gpg>
    python3 scripts/hosted-backup.py restore <file.json.gpg> --psql "<psql command>" \\
        [--private-dir DIR] [--photos-dir DIR]

`setup` writes ~/.mlocal-backup/config.json (URL, backup directory), a random
backup token and a random encryption passphrase, all mode 0600. Put the token
on the host once: `jachammer env add MLOCAL_BACKUP_TOKEN=<token> --name ...`
(it is printed only by `setup --show-token`). Keep the passphrase somewhere
safe as well: without it the backups cannot be read.

`pull` asks the host for one snapshot, verifies every checksum, encrypts it
with gpg (AES-256) before anything is written to the backup folder, and deletes
encrypted copies older than the retention period (14 days by default). The
plaintext exists only in memory.

`restore` decrypts, verifies and loads the graph into an empty PostgreSQL
database through psql (tables, rows, constraints, indexes, sequences), and
writes the private onboarding files and photos into the given directories.
"""
import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get('MLOCAL_BACKUP_HOME', Path.home() / '.mlocal-backup'))
CONFIG = HOME / 'config.json'
TOKEN = HOME / 'token'
PASSPHRASE = HOME / 'passphrase'
FORMAT = 'm-local-hosted-backup-v1'


class BackupError(Exception):
    pass


def _write_secret(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value)


def _config():
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        raise BackupError(f'No backup configuration at {CONFIG}; run setup first.') from None


def setup(args):
    url = args.url.rstrip('/')
    if not url.startswith('https://') and not url.startswith('http://127.0.0.1'):
        raise BackupError('Pass the https origin of the deployment.')
    folder = Path(args.backup_dir).expanduser() if args.backup_dir else HOME / 'backups'
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_secret(CONFIG, json.dumps({'url': url, 'backup_dir': str(folder), 'keep_days': args.keep_days}, indent=2))
    if not TOKEN.exists():
        _write_secret(TOKEN, secrets.token_urlsafe(48))
    if not PASSPHRASE.exists():
        _write_secret(PASSPHRASE, secrets.token_urlsafe(48))
    print(f'Configured {url}; backups go to {folder}, kept {args.keep_days} days.')
    if args.show_token:
        print('MLOCAL_BACKUP_TOKEN=' + TOKEN.read_text().strip())
    else:
        print('Run setup again with --show-token to print the host token once.')
    return 0


def check(outer):
    """Verify a decoded backup document; return its body."""
    if not isinstance(outer, dict) or 'backup' not in outer:
        raise BackupError('Not an M-Local backup document.')
    body = outer['backup']
    text = json.dumps(body, separators=(',', ':'), sort_keys=True)
    if hashlib.sha256(text.encode()).hexdigest() != outer.get('sha256'):
        raise BackupError('The backup checksum does not match; it is incomplete or altered.')
    if body.get('format') != FORMAT:
        raise BackupError(f'Unsupported backup format {body.get("format")!r}.')
    for table in body['graph']['tables']:
        if len(table['rows']) != table['row_count'] or hashlib.sha256('\n'.join(table['rows']).encode()).hexdigest() != table['sha256']:
            raise BackupError(f'Table {table["schema"]}.{table["table"]} failed its checksum.')
    for item in body['private'] + body['photos']:
        if hashlib.sha256(base64.b64decode(item['base64'])).hexdigest() != item['sha256']:
            raise BackupError(f'File {item["name"]} failed its checksum.')
    if not any(f['name'] == 'code.key' and f['bytes'] == 32 for f in body['private']):
        raise BackupError('The onboarding key is missing from this backup.')
    return body


def summary(body):
    tables = body['graph']['tables']
    rows = sum(t['row_count'] for t in tables)
    photo_bytes = sum(p['bytes'] for p in body['photos'])
    when = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(body['created_at']))
    return (f'{when}: {len(tables)} tables, {rows} rows, {len(body["private"])} private files, '
            f'{len(body["photos"])} photos ({photo_bytes // 1024} KB), revision {body.get("source_revision") or "unknown"}')


def _gpg(arguments, data):
    result = subprocess.run(['gpg', '--batch', '--yes', '--quiet', '--pinentry-mode', 'loopback',
                             '--passphrase-file', str(PASSPHRASE), *arguments], input=data, capture_output=True)
    if result.returncode != 0:
        raise BackupError('gpg failed: ' + result.stderr.decode(errors='replace').strip()[:300])
    return result.stdout


def encrypt(data):
    return _gpg(['--symmetric', '--cipher-algo', 'AES256', '--s2k-digest-algo', 'SHA512', '--output', '-'], data)


def decrypt(path):
    return _gpg(['--decrypt', '--output', '-', str(path)], b'')


def pull(args):
    config = _config()
    token = TOKEN.read_text().strip()
    request = urllib.request.Request(config['url'] + '/function/download_backup', json.dumps({'token': token}).encode(),
                                     {'Content-Type': 'application/json', 'Accept-Encoding': 'identity'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise BackupError(f'Could not reach the host: {error}') from None
    result = (payload.get('data') or {}).get('result') or {}
    if not payload.get('ok') or not result.get('ok'):
        raise BackupError('The host refused the backup: ' + str(result.get('message') or payload.get('error')))
    raw = result['backup'].encode()
    body = check(json.loads(raw))
    folder = Path(config['backup_dir'])
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = time.strftime('m-local-%Y%m%d-%H%M%S.json.gpg', time.localtime(body['created_at']))
    target = folder / name
    sealed = encrypt(raw)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(sealed)
    # Prove the stored copy decrypts to the same verified document before pruning.
    if hashlib.sha256(decrypt(target)).hexdigest() != hashlib.sha256(raw).hexdigest():
        raise BackupError('The encrypted copy did not read back identically; keeping older backups.')
    removed = prune(folder, int(config.get('keep_days', 14)))
    line = f'Saved {target.name} — {summary(body)}; removed {removed} old backup(s).'
    print(line)
    with open(HOME / 'backup.log', 'a') as log:
        log.write(time.strftime('%Y-%m-%dT%H:%M:%S ') + line + '\n')
    return 0


def prune(folder, keep_days):
    cutoff = time.time() - keep_days * 86400
    backups = sorted(folder.glob('m-local-*.json.gpg'))
    removed = 0
    for path in backups[:-1]:  # never remove the newest copy
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def verify(args):
    body = check(json.loads(decrypt(Path(args.file))))
    print('OK ' + summary(body))
    return 0


def _literal(text):
    return "'" + text.replace("'", "''") + "'"


def _ident(name):
    return '"' + str(name).replace('"', '""') + '"'


def restore_sql(body):
    """SQL that recreates the graph database in an empty PostgreSQL."""
    graph = body['graph']
    out = ['BEGIN;', 'SET client_min_messages = warning;']
    for schema in graph['schemas']:
        out.append(f'CREATE SCHEMA IF NOT EXISTS {_ident(schema)};')
    for extension in graph['extensions']:
        out.append(f'CREATE EXTENSION IF NOT EXISTS {_ident(extension)};')
    for sequence in graph['sequences']:
        out.append(f'CREATE SEQUENCE IF NOT EXISTS {_ident(sequence["schema"])}.{_ident(sequence["name"])};')
    for table in graph['tables']:
        name = f'{_ident(table["schema"])}.{_ident(table["table"])}'
        columns = []
        for column in table['columns']:
            text = f'{_ident(column["name"])} {column["type"]}'
            if column['default'] is not None:
                text += f' DEFAULT {column["default"]}'
            if column['not_null']:
                text += ' NOT NULL'
            columns.append(text)
        out.append(f'CREATE TABLE {name} ({", ".join(columns)});')
        for row in table['rows']:
            out.append(f'INSERT INTO {name} SELECT * FROM json_populate_record(NULL::{name}, {_literal(row)}::json);')
    for foreign in (False, True):
        for table in graph['tables']:
            name = f'{_ident(table["schema"])}.{_ident(table["table"])}'
            for constraint in table['constraints']:
                if constraint['definition'].startswith('FOREIGN KEY') == foreign:
                    out.append(f'ALTER TABLE {name} ADD CONSTRAINT {_ident(constraint["name"])} {constraint["definition"]};')
    for table in graph['tables']:
        for index in table['indexes']:
            out.append(index['definition'] + ';')
    for sequence in graph['sequences']:
        if sequence['last_value'] is not None:
            out.append(f"SELECT setval({_literal(_ident(sequence['schema']) + '.' + _ident(sequence['name']))}, {int(sequence['last_value'])});")
    out.append('COMMIT;')
    return '\n'.join(out) + '\n'


def _write_files(items, directory, mode):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for item in items:
        name = Path(item['name']).name
        if name != item['name'] or name.startswith('.'):
            raise BackupError(f'Refusing an unexpected file name {item["name"]!r}.')
        target = directory / name
        if target.exists():
            raise BackupError(f'{target} already exists; restore into an empty directory.')
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(base64.b64decode(item['base64']))


def restore(args):
    body = check(json.loads(decrypt(Path(args.file))))
    if args.psql:
        with tempfile.NamedTemporaryFile('w', suffix='.sql', delete=False) as script:
            script.write(restore_sql(body))
        try:
            os.chmod(script.name, 0o600)
            command = args.psql.split() + ['-v', 'ON_ERROR_STOP=1', '-q', '-f', script.name]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                raise BackupError('psql failed: ' + result.stderr.strip()[:500])
        finally:
            os.unlink(script.name)
        print(f'Graph restored: {len(body["graph"]["tables"])} tables.')
    if args.private_dir:
        _write_files(body['private'], Path(args.private_dir), 0o600)
        print(f'Private files written to {args.private_dir}.')
    if args.photos_dir:
        _write_files(body['photos'], Path(args.photos_dir), 0o644)
        print(f'Photos written to {args.photos_dir}.')
    print('Restored ' + summary(body))
    print('Boot the same source revision at the original entry path: ' + body.get('entry_path', ''))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('setup')
    s.add_argument('--url', required=True)
    s.add_argument('--backup-dir')
    s.add_argument('--keep-days', type=int, default=14)
    s.add_argument('--show-token', action='store_true')
    sub.add_parser('pull')
    v = sub.add_parser('verify')
    v.add_argument('file')
    r = sub.add_parser('restore')
    r.add_argument('file')
    r.add_argument('--psql', help='psql command line for an EMPTY target database, e.g. "psql -h /tmp -p 5544 -d restore"')
    r.add_argument('--private-dir')
    r.add_argument('--photos-dir')
    args = parser.parse_args(argv)
    try:
        return {'setup': setup, 'pull': pull, 'verify': verify, 'restore': restore}[args.command](args)
    except BackupError as error:
        print(f'hosted-backup: {error}', file=sys.stderr)
        with open(HOME / 'backup.log', 'a') if HOME.exists() else open(os.devnull, 'w') as log:
            log.write(time.strftime('%Y-%m-%dT%H:%M:%S ') + 'FAILED ' + str(error) + '\n')
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
