"""Hosted backup round trip: snapshot a real PostgreSQL, encrypt, restore, compare."""
import base64
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('hosted_backup_tool', ROOT / 'scripts' / 'hosted-backup.py')
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
from services import hosted_backup

PG_BIN = next((p for p in (Path('/usr/lib/postgresql/16/bin'), Path('/usr/lib/postgresql/17/bin'), Path('/usr/lib/postgresql/18/bin'))
               if (p / 'initdb').exists()), None)


def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@unittest.skipUnless(PG_BIN and shutil.which('psql') and shutil.which('gpg'), 'needs PostgreSQL, psql and gpg')
class HostedBackupRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.data, self.sock, self.port = base / 'pg', base / 'sock', _free_port()
        self.sock.mkdir()
        user = {} if os.geteuid() != 0 else {'user': 'nobody'}
        if user:
            for path in (base, self.data.parent, self.sock):
                os.chmod(path, 0o777)
        def pg(*args):
            prefix = ['runuser', '-u', 'nobody', '--'] if user else []
            # pg_ctl's server inherits output pipes; never capture them.
            subprocess.run(prefix + list(args), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        self.pg = pg
        pg(str(PG_BIN / 'initdb'), '-D', str(self.data), '-U', 'jac', '--auth=trust', '-E', 'UTF8')
        pg(str(PG_BIN / 'pg_ctl'), '-D', str(self.data), '-l', str(base / 'pg.log'), '-o', f'-k {self.sock} -p {self.port} -c listen_addresses=', '-w', 'start')
        self.psql_base = ['psql', '-h', str(self.sock), '-p', str(self.port), '-U', 'jac']
        for db in ('source', 'target'):
            subprocess.run(self.psql_base + ['-d', 'postgres', '-c', f'CREATE DATABASE {db}'], check=True, capture_output=True)
        self.sql('source', '''
            CREATE SCHEMA app;
            CREATE SEQUENCE app.counter;
            CREATE TABLE app.anchors (id uuid PRIMARY KEY, kind text NOT NULL, body jsonb, raw bytea,
                seen timestamptz DEFAULT now(), n bigint DEFAULT nextval('app.counter'), tags text[]);
            CREATE TABLE app.edges (src uuid REFERENCES app.anchors(id), dst uuid REFERENCES app.anchors(id), w double precision,
                UNIQUE (src, dst));
            CREATE INDEX edges_dst ON app.edges (dst);
            INSERT INTO app.anchors (id, kind, body, raw, tags) VALUES
              ('00000000-0000-0000-0000-000000000001', 'Restaurant', '{"name": "It''s Cafe", "n": 1}', '\\x00ff10', ARRAY['a','b c']),
              ('00000000-0000-0000-0000-000000000002', 'Offer', NULL, NULL, NULL);
            INSERT INTO app.edges VALUES ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002', 0.5);
        ''')
        self.home = base / 'home'
        self.env = patch.dict(os.environ, {'MLOCAL_BACKUP_HOME': str(self.home)})
        self.env.start()
        tool.HOME, tool.CONFIG, tool.TOKEN, tool.PASSPHRASE = self.home, self.home / 'config.json', self.home / 'token', self.home / 'passphrase'

    def tearDown(self):
        self.env.stop()
        self.pg(str(PG_BIN / 'pg_ctl'), '-D', str(self.data), '-m', 'immediate', 'stop')
        self.tmp.cleanup()

    def sql(self, db, text):
        return subprocess.run(self.psql_base + ['-d', db, '-v', 'ON_ERROR_STOP=1', '-qAt', '-c', text],
                              check=True, capture_output=True, text=True).stdout

    def connect(self, db):
        from jaclang.data.pgload import connect
        return connect('jac', port=self.port, unix_socket_dir=str(self.sock), database=db)

    def graph(self, db):
        conn = self.connect(db)
        try:
            return hosted_backup._graph(conn)
        finally:
            conn.close()

    def test_round_trip_restores_rows_constraints_indexes_and_sequences(self):
        self.sql('source', "SELECT nextval('app.counter')")
        before = self.graph('source')
        private_dir = Path(self.tmp.name) / 'private'
        private_dir.mkdir()
        (private_dir / 'code.key').write_bytes(b'k' * 32)
        with sqlite3.connect(private_dir / 'onboarding.sqlite3') as db:
            db.execute('CREATE TABLE accounts (actor TEXT, email TEXT)')
            db.execute("INSERT INTO accounts VALUES ('a', 'owner@fixture.test')")
        with patch.dict(os.environ, {'MLOCAL_ONBOARDING_DIR': str(private_dir)}):
            private = hosted_backup._private()
        body = {'format': tool.FORMAT, 'created_at': 1.0, 'graph': before, 'private': private, 'photos': []}
        text = json.dumps(body, separators=(',', ':'), sort_keys=True)
        document = json.dumps({'sha256': hashlib.sha256(text.encode()).hexdigest(), 'backup': body}).encode()
        tool.setup(type('A', (), {'url': 'https://host.fixture.test', 'backup_dir': str(self.home / 'backups'), 'keep_days': 14, 'show_token': False})())
        sealed = self.home / 'backups' / 'b.json.gpg'
        sealed.write_bytes(tool.encrypt(document))
        self.assertNotIn(b'owner@fixture.test', sealed.read_bytes())
        restored_private = Path(self.tmp.name) / 'restored'
        tool.restore(type('A', (), {'file': str(sealed), 'psql': ' '.join(self.psql_base + ['-d', 'target']),
                                    'private_dir': str(restored_private), 'photos_dir': None})())
        after = self.graph('target')
        for a, b in zip(before['tables'], after['tables']):
            self.assertEqual((a['schema'], a['table'], a['sha256'], a['row_count']), (b['schema'], b['table'], b['sha256'], b['row_count']))
            self.assertEqual(sorted(c['definition'] for c in a['constraints']), sorted(c['definition'] for c in b['constraints']))
            self.assertEqual(sorted(i['definition'] for i in a['indexes']), sorted(i['definition'] for i in b['indexes']))
        self.assertEqual(len(before['tables']), len(after['tables']))
        self.assertEqual(before['sequences'], after['sequences'])
        self.assertEqual((restored_private / 'code.key').read_bytes(), b'k' * 32)
        with sqlite3.connect(restored_private / 'onboarding.sqlite3') as db:
            self.assertEqual(db.execute('SELECT email FROM accounts').fetchone()[0], 'owner@fixture.test')

    def test_tampered_backups_are_refused(self):
        body = {'format': tool.FORMAT, 'created_at': 1.0, 'graph': self.graph('source'),
                'private': [{'name': 'code.key', 'bytes': 32, 'sha256': hashlib.sha256(b'k' * 32).hexdigest(), 'base64': base64.b64encode(b'k' * 32).decode()}],
                'photos': []}
        text = json.dumps(body, separators=(',', ':'), sort_keys=True)
        outer = {'sha256': hashlib.sha256(text.encode()).hexdigest(), 'backup': body}
        tool.check(json.loads(json.dumps(outer)))
        broken = json.loads(json.dumps(outer))
        broken['backup']['graph']['tables'][0]['rows'].append('{}')
        with self.assertRaises(tool.BackupError):
            tool.check(broken)
        missing_key = json.loads(json.dumps(outer))
        missing_key['backup']['private'] = []
        text = json.dumps(missing_key['backup'], separators=(',', ':'), sort_keys=True)
        missing_key['sha256'] = hashlib.sha256(text.encode()).hexdigest()
        with self.assertRaises(tool.BackupError):
            tool.check(missing_key)


class TokenTests(unittest.TestCase):
    def test_token_needs_forty_characters_and_an_exact_match(self):
        with patch.dict(os.environ, {'MLOCAL_BACKUP_TOKEN': 'x' * 39}):
            self.assertFalse(hosted_backup.token_accepted('x' * 39))
        with patch.dict(os.environ, {'MLOCAL_BACKUP_TOKEN': 'y' * 40}):
            self.assertTrue(hosted_backup.token_accepted('y' * 40))
            self.assertFalse(hosted_backup.token_accepted('y' * 41))
            self.assertFalse(hosted_backup.token_accepted(None))


if __name__ == '__main__':
    unittest.main()
