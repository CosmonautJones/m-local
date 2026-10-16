"""Opt-in SQL-only proof; requires an explicitly owned disposable PostgreSQL DB."""
import concurrent.futures
import hashlib
import hmac
import io
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
TABLES = (
    'accounts', 'business_approvals', 'business_owners', 'business_reviews',
    'business_status', 'business_status_events', 'codes', 'display_names',
    'drafts', 'imports', 'provisioning', 'sends',
)
ACTOR = 'a' * 32
STUDENT = 'b' * 32
OTHER = 'c' * 32
PHOTO_A = '1' * 32 + '.jpg'
PHOTO_B = '2' * 32 + '.jpg'


def hashes(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob('*')) if p.is_file()}


@unittest.skipUnless(os.environ.get('MLOCAL_AUXILIARY_TEST_DSN'),
                     'requires explicit disposable MLOCAL_AUXILIARY_TEST_DSN')
class PostgresAuxiliaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict
        cls.psycopg, cls.sql = psycopg, sql
        cls.dsn = os.environ['MLOCAL_AUXILIARY_TEST_DSN']
        cls.schema_base = os.environ.get('MLOCAL_AUXILIARY_TEST_SCHEMA', '')
        if any(name in os.environ for name in ('PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE')):
            raise ValueError('Unset inherited libpq redirection before disposable testing')
        try:
            settings = conninfo_to_dict(cls.dsn)
        except Exception:
            raise ValueError('Invalid explicit disposable test DSN') from None
        if (settings.get('host') not in {'127.0.0.1', '::1', 'localhost'}
                or settings.get('hostaddr', '127.0.0.1') not in {'127.0.0.1', '::1'}
                or not settings.get('dbname', '').startswith('mlocal_aux_test_')
                or 'service' in settings
                or not re.fullmatch(r'mlocal_aux_test_[a-z0-9_]{1,24}', cls.schema_base)):
            raise ValueError('Refusing a database/schema outside explicit loopback test ownership')
        temporary = os.environ.get('TMPDIR', '')
        if not temporary or not Path(temporary).is_absolute():
            raise ValueError('Set TMPDIR to the owned X-backed disposable fixture directory')
        sys.path.insert(0, str(ROOT))
        import jaclang  # Register the pinned runtime's unchanged Jac module importer.
        from services.email_codes import CodeStore, business_revision
        from services import postgres_auxiliary
        from PIL import Image
        cls.CodeStore = CodeStore
        cls.business_revision = staticmethod(business_revision)
        cls.module = postgres_auxiliary
        cls.Image = Image
        # Build once through the unchanged business class; each test imports a
        # fresh byte-for-byte copy rather than repeating Jac fixture execution.
        cls.template_temporary = tempfile.TemporaryDirectory(prefix='mlocal-aux-template-', dir=temporary)
        cls.addClassCleanup(cls.template_temporary.cleanup)
        template = cls(methodName='test_import_preserves_all_tables_keys_photos_and_exact_replay')
        template.legacy = Path(cls.template_temporary.name) / 'originals'
        template.legacy.mkdir()
        template.now = time.time()
        template._make_originals()
        cls.template = template
        cls.template_hashes = hashes(template.legacy)

    def connect(self):
        try:
            connection = self.psycopg.connect(self.dsn, connect_timeout=5)
        except self.psycopg.Error:
            raise RuntimeError('Owned PostgreSQL fixture connection unavailable') from None
        actual = connection.execute('SELECT current_database()').fetchone()[0]
        if not actual.startswith('mlocal_aux_test_'):
            connection.close()
            raise ValueError('Refusing a non-fixture PostgreSQL database')
        return connection

    def setUp(self):
        self.schemas = []
        self.temporary = tempfile.TemporaryDirectory(prefix='mlocal-aux-', dir=os.environ['TMPDIR'])
        self.work = Path(self.temporary.name)
        self.legacy = self.work / 'originals'
        shutil.copytree(self.template.legacy, self.legacy)
        self.runtime = self.work / 'runtime'
        self.runtime.mkdir()
        self.now = self.template.now
        self.fields = dict(self.template.fields)
        self.code_key, self.native_key = self.template.code_key, self.template.native_key
        self.jpeg_a, self.jpeg_b = self.template.jpeg_a, self.template.jpeg_b
        self.photos_dir = self.legacy / 'photos'
        self.original_transaction = self.CodeStore.transaction
        self.original_hashes = hashes(self.legacy)
        self.addCleanup(self.finish)
        suffix = uuid4().hex[:12]
        self.schema = self.schema_base + '_' + suffix
        self.native_schema = 'mlocal_aux_test_native_' + suffix
        with self.connect() as connection:
            for schema in (self.schema, self.native_schema):
                connection.execute(self.sql.SQL('CREATE SCHEMA {}').format(self.sql.Identifier(schema)))
                self.schemas.append(schema)
            for table in ('anchors', 'identity_lookups'):
                connection.execute(self.sql.SQL('CREATE TABLE {}.{} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)').format(
                    self.sql.Identifier(self.native_schema), self.sql.Identifier(table)))
                connection.execute(self.sql.SQL('INSERT INTO {}.{} VALUES (%s,%s)').format(
                    self.sql.Identifier(self.native_schema), self.sql.Identifier(table)),
                    ('synthetic-native-sentinel', 'must remain unchanged'))
        self.native_before = self.snapshot(self.native_schema)
        self.backend = self.module.PostgresAuxiliary(self.dsn, self.schema)
        self.backend.initialize()

    def finish(self):
        try:
            self.assertEqual(hashes(self.legacy), self.original_hashes, 'Original fixture bytes changed')
            self.assertEqual(hashes(self.template.legacy), self.template_hashes, 'Fixture template bytes changed')
            self.assertIs(self.CodeStore.transaction, self.original_transaction,
                          'The unchanged CodeStore class was globally patched')
            if hasattr(self, 'native_before'):
                self.assertEqual(self.snapshot(self.native_schema), self.native_before,
                                 'Synthetic native sentinel schema changed')
        finally:
            try:
                with self.connect() as connection:
                    for schema in reversed(self.schemas):
                        if not re.fullmatch(r'mlocal_aux_test_[a-z0-9_]+', schema):
                            raise ValueError('Refusing cleanup outside owned test schemas')
                        connection.execute(self.sql.SQL('DROP SCHEMA {} CASCADE').format(self.sql.Identifier(schema)))
            finally:
                self.temporary.cleanup()

    def jpeg(self, color):
        output = io.BytesIO()
        self.Image.new('RGB', (32, 32), color).save(output, format='JPEG', quality=82)
        return output.getvalue()

    def _make_originals(self):
        self.old = self.CodeStore(self.legacy, clock=lambda: self.now)
        self.old.remember_account(ACTOR, 'owner@example.test', 'business', 'Fixture owner')
        self.old.remember_account(STUDENT, 'legacy@umich.edu', 'student', 'Fixture student')
        self.old.remember_account(OTHER, 'other@example.test', 'business', 'Other owner')
        self.old.save_display_name('d' * 32, 'Fixture demo preference')
        self.old.provisioning('pending@example.test', 'business', 'Pending fixture')
        self.fields = {'name': 'Fixture cafe', 'address': '123 Test St',
                       'cuisine': 'Fixture', 'description': 'Synthetic only',
                       'image_url': '/static/photos/' + PHOTO_A, 'menu_text': 'Soup'}
        self.old.save_draft(ACTOR, self.fields)
        self.old.approve_business(ACTOR, 'Fixture reviewer', 'Verified synthetic authority',
                                  self.business_revision(self.fields))
        self.old.reserve_business(ACTOR)
        self.old.activate_business(ACTOR, self.fields)
        self.old.change_business_status(ACTOR, 'suspended', 'Fixture reviewer', 'Fixture suspension', 0, '0' * 29 + '101')
        self.old.change_business_status(ACTOR, 'active', 'Fixture reviewer', 'Fixture reinstatement', 1, '0' * 29 + '102')
        self.old.reserve_import(ACTOR)
        self.old.request('legacy', 'student', 'Fixture student', lambda email, code: None)
        with self.old.transaction() as database:
            database.execute('UPDATE business_reviews SET id=41')
        self.code_key = (self.legacy / 'code.key').read_bytes()
        self.native_key = b'fixture-original-native-jwt-signing-material'
        (self.legacy / 'jwt_secret').write_bytes(self.native_key)
        self.photos_dir = self.legacy / 'photos'
        self.photos_dir.mkdir()
        self.jpeg_a, self.jpeg_b = self.jpeg('red'), self.jpeg('blue')
        with sqlite3.connect(self.legacy / 'photo-ownership.sqlite3') as database:
            database.execute('CREATE TABLE photos (filename TEXT PRIMARY KEY, actor TEXT NOT NULL, digest TEXT NOT NULL, bytes INTEGER NOT NULL, created REAL NOT NULL, UNIQUE(actor,digest))')
            for filename, actor, data in ((PHOTO_A, ACTOR, self.jpeg_a), (PHOTO_B, OTHER, self.jpeg_b)):
                (self.photos_dir / filename).write_bytes(data)
                database.execute('INSERT INTO photos VALUES (?,?,?,?,?)',
                                 (filename, actor, hashlib.sha256(data).hexdigest(), len(data), self.now))

    def import_from(self, original=None):
        original = original or self.legacy
        return self.backend.import_legacy(original / 'onboarding.sqlite3',
                                          original / 'photo-ownership.sqlite3', original / 'photos',
                                          original / 'code.key', original / 'jwt_secret')

    def state(self):
        state = self.backend.code_store(self.CodeStore, self.runtime, clock=lambda: self.now)
        self.assertIs(type(state), self.CodeStore)
        self.assertEqual(state.key, self.code_key)
        self.assertFalse((self.runtime / 'onboarding.sqlite3').exists())
        return state

    def snapshot(self, schema):
        with self.connect() as connection:
            names = connection.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename', (schema,)).fetchall()
            return {name: sorted(repr(tuple(row)) for row in connection.execute(
                self.sql.SQL('SELECT * FROM {}.{}').format(self.sql.Identifier(schema), self.sql.Identifier(name))))
                    for (name,) in names}

    def rows(self, table, columns='*'):
        with self.connect() as connection:
            query = self.sql.SQL('SELECT {} FROM {}.{}').format(
                self.sql.SQL(columns), self.sql.Identifier(self.schema), self.sql.Identifier(table))
            return connection.execute(query).fetchall()

    def key_cells(self):
        """Independent SQL BYTEA readback, without depending on the key table name."""
        found = []
        with self.connect() as connection:
            columns = connection.execute(
                "SELECT table_name,column_name FROM information_schema.columns "
                "WHERE table_schema=%s AND data_type='bytea' AND table_name!='photos'",
                (self.schema,)).fetchall()
            for table, column in columns:
                query = self.sql.SQL('SELECT {} FROM {}.{} WHERE {} IN (%s,%s)').format(
                    self.sql.Identifier(column), self.sql.Identifier(self.schema),
                    self.sql.Identifier(table), self.sql.Identifier(column))
                for (value,) in connection.execute(query, (self.code_key, self.native_key)):
                    found.append((table, column, bytes(value)))
        return found

    def parallel(self, count, action):
        barrier = threading.Barrier(count, timeout=15)
        def invoke(index):
            barrier.wait()
            return action(index)
        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
            return list(pool.map(invoke, range(count)))

    def test_import_preserves_all_tables_keys_photos_and_exact_replay(self):
        receipt = self.import_from()
        self.assertRegex(receipt['digest'], r'^[0-9a-f]{64}$')
        self.assertIsInstance(receipt['summary'], dict)
        with sqlite3.connect(self.legacy / 'onboarding.sqlite3') as original:
            for table in TABLES:
                with self.subTest(table=table):
                    expected = sorted(repr(tuple(row)) for row in original.execute('SELECT * FROM ' + table))
                    self.assertEqual(sorted(repr(tuple(row)) for row in self.rows(table)), expected)
                    self.assertTrue(expected, 'Each legacy application table must be represented')
        self.assertEqual(self.backend.signing_material(), {'code_key': self.code_key, 'native_key': self.native_key})
        self.assertCountEqual([value for table, column, value in self.key_cells()],
                              [self.code_key, self.native_key])
        self.assertEqual(self.state().digest('fixture-challenge', '123456'),
                         hmac.new(self.code_key, b'fixture-challenge:123456', hashlib.sha256).hexdigest())
        photos = self.rows('photos', "filename,actor,digest,bytes,created,content")
        self.assertEqual({row[0] for row in photos}, {PHOTO_A, PHOTO_B})
        with sqlite3.connect(self.legacy / 'photo-ownership.sqlite3') as original:
            metadata = {row[0]: tuple(row) for row in original.execute('SELECT filename,actor,digest,bytes,created FROM photos')}
        for filename, actor, digest, length, created, content in photos:
            self.assertEqual((filename, actor, digest, length, created), metadata[filename])
            expected = (self.photos_dir / filename).read_bytes()
            self.assertEqual(bytes(content), expected)
            self.assertEqual((digest, length, created), (hashlib.sha256(expected).hexdigest(), len(expected), self.now))
        before = self.snapshot(self.schema)
        replay = self.import_from()
        self.assertEqual((replay['digest'], replay['summary']), (receipt['digest'], receipt['summary']))
        self.assertEqual(self.snapshot(self.schema), before)

    def test_conflicting_import_does_not_replace_any_state(self):
        self.import_from()
        before = self.snapshot(self.schema)
        variant = self.work / 'conflicting-originals'
        shutil.copytree(self.legacy, variant)
        (variant / 'code.key').write_bytes(b'x' * 32)
        variant_before = hashes(variant)
        with self.assertRaises((ValueError, RuntimeError)):
            self.import_from(variant)
        self.assertEqual(self.snapshot(self.schema), before)
        self.assertEqual(hashes(variant), variant_before)

    def test_incomplete_legacy_suspension_audit_is_refused_atomically(self):
        variant = self.work / 'incomplete-originals'
        shutil.copytree(self.legacy, variant)
        with sqlite3.connect(variant / 'onboarding.sqlite3') as database:
            database.execute('DROP TABLE business_status_events')
        variant_before, target_before = hashes(variant), self.snapshot(self.schema)
        with self.assertRaises((ValueError, RuntimeError)):
            self.import_from(variant)
        self.assertEqual(self.snapshot(self.schema), target_before)
        self.assertEqual(hashes(variant), variant_before)

    def test_source_status_latest_audit_mismatch_is_refused_atomically(self):
        variant = self.work / 'inconsistent-originals'
        shutil.copytree(self.legacy, variant)
        with sqlite3.connect(variant / 'onboarding.sqlite3') as database:
            database.execute('UPDATE business_status SET revision=revision+1')
        variant_before, target_before = hashes(variant), self.snapshot(self.schema)
        with self.assertRaises((ValueError, RuntimeError)):
            self.import_from(variant)
        self.assertEqual(self.snapshot(self.schema), target_before)
        self.assertEqual(hashes(variant), variant_before)

    def test_incompatible_source_and_established_target_versions_refuse_without_mutation(self):
        variant = self.work / 'unsupported-version-originals'
        shutil.copytree(self.legacy, variant)
        with sqlite3.connect(variant / 'onboarding.sqlite3') as database:
            database.execute('PRAGMA user_version=2')
        variant_before, target_before = hashes(variant), self.snapshot(self.schema)
        with self.assertRaises((ValueError, RuntimeError)):
            self.import_from(variant)
        self.assertEqual(hashes(variant), variant_before)
        self.assertEqual(self.snapshot(self.schema), target_before)

        self.import_from()
        for column in ('schema_version', 'legacy_version'):
            with self.subTest(target_version_column=column):
                with self.connect() as connection:
                    connection.execute(self.sql.SQL('UPDATE {}.auxiliary_state SET {}=2 WHERE id=1').format(
                        self.sql.Identifier(self.schema), self.sql.Identifier(column)))
                before = self.snapshot(self.schema)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.backend.initialize()
                self.assertEqual(self.snapshot(self.schema), before)
                with self.assertRaises((ValueError, RuntimeError)):
                    with self.backend.transaction():
                        self.fail('An incompatible established schema admitted a transaction')
                self.assertEqual(self.snapshot(self.schema), before)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.import_from()
                self.assertEqual(self.snapshot(self.schema), before)
                with self.connect() as connection:
                    connection.execute(self.sql.SQL('UPDATE {}.auxiliary_state SET {}=1 WHERE id=1').format(
                        self.sql.Identifier(self.schema), self.sql.Identifier(column)))

    def test_exact_import_replay_refuses_target_business_divergence(self):
        self.import_from()
        self.state().save_draft(ACTOR, {**self.fields, 'description': 'A later legitimate fixture write'})
        before = self.snapshot(self.schema)
        with self.assertRaises((ValueError, RuntimeError)):
            self.import_from()
        self.assertEqual(self.snapshot(self.schema), before)

    def test_exact_import_replay_refuses_target_key_divergence(self):
        self.import_from()
        cells = [cell for cell in self.key_cells() if cell[2] == self.code_key]
        self.assertEqual(len(cells), 1, 'Original code key must have one independently readable BYTEA value')
        table, column, value = cells[0]
        changed = bytes([value[0] ^ 1]) + value[1:]
        with self.connect() as connection:
            connection.execute(self.sql.SQL('UPDATE {}.{} SET {}=%s WHERE {}=%s').format(
                self.sql.Identifier(self.schema), self.sql.Identifier(table),
                self.sql.Identifier(column), self.sql.Identifier(column)), (changed, value))
        before = self.snapshot(self.schema)
        with self.assertRaises((ValueError, RuntimeError)):
            self.import_from()
        self.assertEqual(self.snapshot(self.schema), before)

    def test_exact_import_replay_refuses_target_photo_divergence(self):
        self.import_from()
        changed = self.jpeg('purple')
        with self.connect() as connection:
            connection.execute(self.sql.SQL('UPDATE {}.photos SET content=%s,digest=%s,bytes=%s WHERE filename=%s').format(
                self.sql.Identifier(self.schema)),
                (changed, hashlib.sha256(changed).hexdigest(), len(changed), PHOTO_A))
        before = self.snapshot(self.schema)
        with self.assertRaises((ValueError, RuntimeError)):
            self.import_from()
        self.assertEqual(self.snapshot(self.schema), before)

    def test_transaction_rows_rowcount_and_failure_rollback(self):
        self.import_from()
        with self.backend.transaction() as database:
            row = database.execute('SELECT actor,email,kind,name FROM accounts WHERE actor=?', (ACTOR,)).fetchone()
            self.assertEqual(row[0], row['actor'])
            self.assertEqual(dict(row)['email'], 'owner@example.test')
            self.assertEqual(len(database.execute('SELECT actor FROM accounts').fetchall()), 3)
            self.assertEqual(database.execute('UPDATE accounts SET name=? WHERE actor=?', ('Updated', ACTOR)).rowcount, 1)
            self.assertEqual(database.execute('UPDATE accounts SET name=? WHERE actor=?', ('Absent', 'f' * 32)).rowcount, 0)
        before = self.snapshot(self.schema)
        with self.assertRaisesRegex(ValueError, 'fixture rollback'):
            with self.backend.transaction() as database:
                database.execute('UPDATE accounts SET name=? WHERE actor=?', ('Abandoned', ACTOR))
                raise ValueError('fixture rollback')
        self.assertEqual(self.snapshot(self.schema), before)
        self.assertEqual(self.state().account(ACTOR)['name'], 'Updated')

    def test_actual_codestore_eight_way_otp_consumption_has_one_winner(self):
        self.import_from()
        sent = []
        result = self.state().request('freshfixture', 'student', 'Fixture', lambda email, code: sent.append(code))
        def consume(_):
            try:
                return self.state().consume(result['challenge'], sent[0])['email']
            except ValueError:
                return None
        self.assertEqual(self.parallel(8, consume).count('freshfixture@umich.edu'), 1)

    def test_actual_codestore_failed_delivery_and_attempt_expiry_limits(self):
        self.import_from()
        state, baseline = self.state(), self.state().pending_count()
        def failed(email, code):
            raise OSError('synthetic SMTP sink failure')
        with self.assertRaisesRegex(ValueError, 'could not send'):
            state.request('failedfixture', 'student', 'Fixture', failed)
        self.assertEqual(state.pending_count(), baseline)
        self.assertEqual(len(self.rows('sends')), 2, 'Failed delivery must retain its reservation')
        sent = []
        result = state.request('attemptfixture', 'student', 'Fixture', lambda email, code: sent.append(code))
        wrong = '000000' if sent[0] != '000000' else '111111'
        for _ in range(5):
            with self.assertRaises(ValueError):
                state.consume(result['challenge'], wrong)
        with self.assertRaises(ValueError):
            state.consume(result['challenge'], sent[0])
        self.now += 61
        result = state.request('attemptfixture', 'student', 'Fixture', lambda email, code: sent.append(code))
        self.now += 601
        with self.assertRaises(ValueError):
            state.consume(result['challenge'], sent[-1])

    def test_actual_codestore_hourly_and_daily_quota_races_do_not_overshoot(self):
        self.import_from()
        for name, count, age, ceiling in (('hourly', 59, 0, 60), ('daily', 299, 7200, 300)):
            with self.subTest(quota=name):
                with self.backend.transaction() as database:
                    database.execute('DELETE FROM sends')
                    database.execute('DELETE FROM codes')
                    for index in range(count):
                        database.execute('INSERT INTO sends VALUES (?,?)', (f'seed{index}@example.test', self.now - age))
                delivered = []
                def request(index):
                    try:
                        self.state().request(f'{name}fixture{index}', 'student', 'Fixture', lambda email, code: delivered.append(email))
                        return True
                    except ValueError:
                        return False
                self.assertEqual(self.parallel(2, request).count(True), 1)
                self.assertEqual(len(delivered), 1)
                self.assertEqual(len(self.rows('sends')), ceiling)

    def test_actual_codestore_provisioning_approval_and_review_sequence(self):
        self.import_from()
        state = self.state()
        first = state.provisioning('fresh-owner@example.test', 'business', 'Original name')
        self.assertEqual(state.provisioning('fresh-owner@example.test', 'student', 'Changed name'), first)
        state.remember_account('e' * 32, 'fresh-owner@example.test', 'business', 'Original name')
        self.assertEqual(state.provisioning('fresh-owner@example.test'), {})
        self.assertEqual(state.reserve_business(ACTOR), 'business-' + ACTOR)
        changed = {**self.fields, 'name': 'Reviewed fixture name'}
        state.save_draft(ACTOR, changed)
        with self.assertRaises(ValueError):
            state.approve_business(ACTOR, 'Fixture reviewer', 'Stale submission', self.business_revision(self.fields))
        revision = self.business_revision(changed)
        state.approve_business(ACTOR, 'Fixture reviewer', 'Fresh fixture review', revision)
        state.approve_business(ACTOR, 'Fixture reviewer', 'Exact identity retry', revision)
        reviews = self.rows('business_reviews')
        self.assertEqual(len(reviews), 2)
        self.assertGreater(max(row[0] for row in reviews), 41)
        self.assertEqual(state.activate_business(ACTOR, changed)['name'], changed['name'])

    def test_actual_codestore_suspension_exact_retry_and_stale_commands(self):
        self.import_from()
        command = '0' * 29 + '201'
        def suspend(_):
            return self.state().change_business_status(ACTOR, 'suspended', 'Fixture reviewer', 'New fixture complaint', 2, command)
        results = self.parallel(8, suspend)
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.state().business_status_events(ACTOR)), 3)
        self.state().change_business_status(ACTOR, 'active', 'Fixture reviewer', 'Fixture resolved', 3, '0' * 29 + '202')
        self.assertEqual(suspend(0), results[0])
        self.assertEqual(self.state().business_status(ACTOR)['revision'], 4)
        with self.assertRaises(ValueError):
            self.state().change_business_status(ACTOR, 'active', 'Fixture reviewer', 'Changed command payload', 2, command)
        with self.assertRaises(ValueError):
            self.state().change_business_status(ACTOR, 'suspended', 'Fixture reviewer', 'Stale revision', 3, '0' * 29 + '203')

    def test_missing_established_audit_fails_closed_without_recreation(self):
        self.import_from()
        with self.connect() as connection:
            connection.execute(self.sql.SQL('DROP TABLE {}.business_status_events').format(self.sql.Identifier(self.schema)))
        before = self.snapshot(self.schema)
        with self.assertRaises((ValueError, RuntimeError)):
            self.state().business_status(ACTOR)
        with self.assertRaises((ValueError, RuntimeError)):
            self.backend.initialize()
        with self.assertRaises((ValueError, RuntimeError)):
            self.import_from()
        self.assertEqual(self.snapshot(self.schema), before)

    def test_target_status_latest_audit_mismatch_fails_closed(self):
        self.import_from()
        with self.connect() as connection:
            connection.execute(self.sql.SQL('UPDATE {}.business_status SET revision=revision+1').format(
                self.sql.Identifier(self.schema)))
        before = self.snapshot(self.schema)
        with self.assertRaises((ValueError, RuntimeError)):
            self.state().business_status(ACTOR)
        with self.assertRaises((ValueError, RuntimeError)):
            self.backend.initialize()
        with self.assertRaises((ValueError, RuntimeError)):
            self.import_from()
        self.assertEqual(self.snapshot(self.schema), before)

    def test_photo_defaults_dedup_ownership_and_reopen_retry(self):
        self.import_from()
        self.assertEqual((self.module.PHOTO_MAX_BYTES, self.module.PHOTO_ACTOR_MAX_BYTES,
                          self.module.PHOTO_TOTAL_MAX_BYTES, self.module.PHOTO_DAILY_LIMIT),
                         (8 * 1024 * 1024, 32 * 1024 * 1024, 512 * 1024 * 1024, 30))
        jpeg = self.jpeg('green')
        filename = self.backend.photo_save(ACTOR, '3' * 32 + '.jpg', jpeg, self.now)
        self.assertEqual(filename, '3' * 32 + '.jpg')
        reopened = self.module.PostgresAuxiliary(self.dsn, self.schema)
        # Simulate loss of the successful caller result, not COMMIT wire acknowledgement loss.
        self.assertEqual(reopened.photo_save(ACTOR, '4' * 32 + '.jpg', jpeg, self.now + 1), filename)
        self.assertTrue(reopened.photo_owned(filename, ACTOR))
        self.assertFalse(reopened.photo_owned(filename, OTHER))
        self.assertFalse(reopened.photo_owned('../' + filename, ACTOR))
        self.assertEqual(reopened.photo_save(OTHER, '5' * 32 + '.jpg', jpeg, self.now), '5' * 32 + '.jpg')
        self.assertEqual(len(self.rows('photos')), 4)
        with patch.object(self.module, 'PHOTO_DAILY_LIMIT', 0):
            self.assertEqual(reopened.photo_save(ACTOR, '7' * 32 + '.jpg', jpeg, self.now + 1), filename,
                             'An exact deduplication retry must precede new-upload quota checks')
        with self.assertRaises((ValueError, RuntimeError)):
            reopened.photo_save(ACTOR, '6' * 32 + '.jpg', b'x' * (8 * 1024 * 1024 + 1), self.now)

    def test_photo_filename_collision_and_cache_path_inputs_are_refused(self):
        self.import_from()
        before = self.snapshot(self.schema)
        for actor, filename in ((OTHER, PHOTO_A), (ACTOR, PHOTO_A),
                                (ACTOR, '../escape.jpg'), (ACTOR, '/tmp/escape.jpg'),
                                (ACTOR, 'A' * 32 + '.jpg'), (ACTOR, '3' * 32 + '.png')):
            with self.subTest(actor=actor, filename=filename), self.assertRaises((ValueError, RuntimeError)):
                self.backend.photo_save(actor, filename, self.jpeg('green'), self.now)
        self.assertEqual(self.snapshot(self.schema), before)

    def test_photo_dedup_refuses_inconsistent_existing_bytes(self):
        self.import_from()
        with self.connect() as connection:
            # Same length permits a length CHECK while breaking the preserved digest.
            connection.execute(self.sql.SQL('UPDATE {}.photos SET content=set_byte(content,0,0) WHERE filename=%s').format(
                self.sql.Identifier(self.schema)), (PHOTO_A,))
        before = self.snapshot(self.schema)
        with self.assertRaises((ValueError, RuntimeError)):
            self.backend.photo_save(ACTOR, '3' * 32 + '.jpg', self.jpeg_a, self.now)
        self.assertEqual(self.snapshot(self.schema), before)

    def photo_quota_race(self, constant):
        self.import_from()
        candidates = (self.jpeg('green'), self.jpeg('yellow'))
        existing = self.rows('photos', 'actor,bytes,created')
        allowance = max(map(len, candidates))
        boundary = {'PHOTO_ACTOR_MAX_BYTES': sum(row[1] for row in existing if row[0] == ACTOR) + allowance,
                    'PHOTO_TOTAL_MAX_BYTES': sum(row[1] for row in existing) + allowance,
                    'PHOTO_DAILY_LIMIT': sum(row[0] == ACTOR for row in existing) + 1}[constant]
        def save(index):
            try:
                return self.backend.photo_save(ACTOR, str(index + 3) * 32 + '.jpg', candidates[index], self.now)
            except ValueError:
                return None
        with patch.object(self.module, constant, boundary):
            self.assertEqual(sum(value is not None for value in self.parallel(2, save)), 1)
        rows = self.rows('photos', 'actor,bytes,content')
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(length == len(content) for actor, length, content in rows))

    def test_photo_actor_byte_quota_race(self):
        self.photo_quota_race('PHOTO_ACTOR_MAX_BYTES')

    def test_photo_global_byte_quota_race(self):
        self.photo_quota_race('PHOTO_TOTAL_MAX_BYTES')

    def test_photo_daily_quota_race(self):
        self.photo_quota_race('PHOTO_DAILY_LIMIT')

    def test_photo_insert_failure_rolls_back_and_cache_reconstructs(self):
        self.import_from()
        before = self.snapshot(self.schema)
        with self.connect() as connection:
            connection.execute(self.sql.SQL("CREATE FUNCTION {}.reject_photo() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic photo write failure'; END $$").format(self.sql.Identifier(self.schema)))
            connection.execute(self.sql.SQL('CREATE TRIGGER reject_photo BEFORE INSERT ON {}.photos FOR EACH ROW EXECUTE FUNCTION {}.reject_photo()').format(self.sql.Identifier(self.schema), self.sql.Identifier(self.schema)))
        with self.assertRaises((ValueError, RuntimeError, self.psycopg.Error)):
            self.backend.photo_save(ACTOR, '3' * 32 + '.jpg', self.jpeg('green'), self.now)
        self.assertEqual(self.snapshot(self.schema), before)
        with self.connect() as connection:
            connection.execute(self.sql.SQL('DROP TRIGGER reject_photo ON {}.photos').format(self.sql.Identifier(self.schema)))
        self.backend.photo_save(ACTOR, '3' * 32 + '.jpg', self.jpeg('green'), self.now)
        cache = self.work / 'cache'
        self.backend.materialize_photos(cache)
        expected = {filename: hashlib.sha256(bytes(content)).hexdigest()
                    for filename, content in self.rows('photos', 'filename,content')}
        self.assertEqual(hashes(cache), expected)
        retained = self.snapshot(self.schema)
        shutil.rmtree(cache)
        self.module.PostgresAuxiliary(self.dsn, self.schema).materialize_photos(cache)
        self.assertEqual(hashes(cache), expected)
        self.assertEqual(self.snapshot(self.schema), retained)

    def test_late_import_sql_failure_rolls_back_all_staged_state(self):
        before = self.snapshot(self.schema)
        def sequences():
            with self.connect() as connection:
                names = connection.execute('SELECT sequencename FROM pg_sequences WHERE schemaname=%s ORDER BY sequencename', (self.schema,)).fetchall()
                return {name: connection.execute(self.sql.SQL('SELECT last_value,is_called FROM {}.{}').format(
                    self.sql.Identifier(self.schema), self.sql.Identifier(name))).fetchone() for (name,) in names}
        sequences_before = sequences()
        with self.connect() as connection:
            connection.execute(self.sql.SQL("""
                CREATE FUNCTION {schema}.reject_late_import() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF (SELECT COUNT(*) FROM {schema}.accounts) != 3
                       OR (SELECT COUNT(*) FROM {schema}.signing_material) != 2
                       OR (SELECT COUNT(*) FROM {schema}.photos) != 2 THEN
                        RAISE EXCEPTION 'late trigger did not observe staged fixture rows';
                    END IF;
                    RAISE EXCEPTION 'synthetic late import rollback' USING ERRCODE='PZ001';
                END $$
            """).format(schema=self.sql.Identifier(self.schema)))
            connection.execute(self.sql.SQL('CREATE TRIGGER reject_late_import BEFORE UPDATE OF import_digest ON {}.auxiliary_state FOR EACH ROW EXECUTE FUNCTION {}.reject_late_import()').format(
                self.sql.Identifier(self.schema), self.sql.Identifier(self.schema)))
        with self.assertRaises(self.psycopg.Error) as refused:
            self.import_from()
        self.assertEqual(refused.exception.sqlstate, 'PZ001', 'Failure must follow all staged onboarding/key/photo writes')
        self.assertEqual(self.snapshot(self.schema), before)
        self.assertEqual(sequences(), sequences_before, 'Failed import changed a preserved sequence')
        self.assertEqual(hashes(self.legacy), self.original_hashes)

    def test_independent_sql_row_lock_blocks_another_backend_transaction(self):
        self.import_from()
        before = self.snapshot(self.schema)
        locker = self.connect()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        entered, started = threading.Event(), threading.Event()
        other = self.module.PostgresAuxiliary(self.dsn, self.schema)
        locker.execute(self.sql.SQL('SELECT id FROM {}.auxiliary_state WHERE id=1 FOR UPDATE').format(
            self.sql.Identifier(self.schema)))
        locker_pid = locker.info.backend_pid
        def attempt():
            started.set()
            with other.transaction() as database:
                entered.set()
                return database.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
        pending = pool.submit(attempt)
        observed = False
        try:
            self.assertTrue(started.wait(2), 'Independent backend worker did not start')
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with self.connect() as observer:
                    observed = bool(observer.execute(
                        "SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                        "AND wait_event_type='Lock' AND %s=ANY(pg_blocking_pids(pid))",
                        (locker_pid,)).fetchone())
                if observed:
                    break
                time.sleep(0.02)
            self.assertTrue(observed, 'PostgreSQL did not observe the independent row-lock wait')
            self.assertFalse(entered.is_set(), 'Auxiliary transaction bypassed the database row lock')
        finally:
            locker.rollback()
            locker.close()
            try:
                self.assertEqual(pending.result(timeout=10), 3)
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
        self.assertTrue(entered.is_set())
        self.assertEqual(self.snapshot(self.schema), before)

    def test_materialization_refuses_originals_and_every_nonempty_cache_before_writes(self):
        self.import_from()
        other_cache = self.work / 'nonempty-cache'
        other_cache.mkdir()
        (other_cache / ('9' * 32 + '.jpg')).write_bytes(self.jpeg('purple'))
        def stats(directory):
            # Reading files can update atime; compare the mutation-relevant stat fields.
            result = {}
            for path in (directory, *sorted(directory.rglob('*'))):
                value = path.lstat()
                result[str(path.relative_to(directory))] = (
                    value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
                    value.st_ino, value.st_dev, value.st_nlink)
            return result
        target_before = self.snapshot(self.schema)
        for directory in (self.photos_dir, other_cache):
            with self.subTest(directory=directory.name):
                bytes_before, stat_before = hashes(directory), stats(directory)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.backend.materialize_photos(directory)
                self.assertEqual(hashes(directory), bytes_before)
                self.assertEqual(stats(directory), stat_before)
        self.assertEqual(self.snapshot(self.schema), target_before)

    def test_header_verified_but_truncated_jpeg_is_refused_without_mutation(self):
        truncated = None
        for trim in range(2, min(64, len(self.jpeg_a))):
            candidate = self.jpeg_a[:-trim]
            try:
                with self.Image.open(io.BytesIO(candidate)) as image:
                    image.verify()
            except (OSError, ValueError):
                continue
            try:
                with patch('PIL.ImageFile.LOAD_TRUNCATED_IMAGES', False):
                    with self.Image.open(io.BytesIO(candidate)) as image:
                        image.load()
            except OSError:
                truncated = candidate
                break
        self.assertIsNotNone(truncated, 'Fixture must pass header verification but fail pixel decoding')
        variant = self.work / 'truncated-photo-originals'
        shutil.copytree(self.legacy, variant)
        (variant / 'photos' / PHOTO_A).write_bytes(truncated)
        with sqlite3.connect(variant / 'photo-ownership.sqlite3') as database:
            database.execute('UPDATE photos SET digest=?,bytes=? WHERE filename=?',
                             (hashlib.sha256(truncated).hexdigest(), len(truncated), PHOTO_A))
        variant_before, before = hashes(variant), self.snapshot(self.schema)
        with self.assertRaises((ValueError, RuntimeError)):
            self.import_from(variant)
        self.assertEqual(hashes(variant), variant_before)
        self.assertEqual(self.snapshot(self.schema), before)
        self.import_from()
        before = self.snapshot(self.schema)
        with self.assertRaises((ValueError, RuntimeError)):
            self.backend.photo_save(ACTOR, '3' * 32 + '.jpg', truncated, self.now)
        self.assertEqual(self.snapshot(self.schema), before)

    def _authority_sqlite_copy(self, *, contradictory=False, preserve=True):
        directory = self.work / 'configured-sqlite'
        shutil.copytree(self.legacy, directory)
        if contradictory:
            with sqlite3.connect(directory / 'onboarding.sqlite3') as database:
                database.execute("UPDATE accounts SET kind='student',name='Stale SQLite identity' WHERE actor=?", (ACTOR,))
                database.execute('UPDATE business_owners SET active=0 WHERE actor=?', (ACTOR,))
                database.execute('DELETE FROM business_approvals WHERE actor=?', (ACTOR,))
        before = hashes(directory)
        if preserve:
            self.addCleanup(lambda: self.assertEqual(hashes(directory), before,
                                                     'Selected PostgreSQL authority changed configured SQLite/key/photo bytes'))
        else:
            # Default SQLite startup may reassert its existing schema version.
            retained = {name: digest for name, digest in before.items() if name != 'onboarding.sqlite3'}
            self.addCleanup(lambda: self.assertEqual(
                {name: digest for name, digest in hashes(directory).items() if name != 'onboarding.sqlite3'}, retained))
        return directory

    def _authority_environment(self, directory, **changes):
        return {'MLOCAL_ENV': 'development', 'MLOCAL_ONBOARDING_BACKEND': 'postgres-proof',
                'MLOCAL_ONBOARDING_DIR': str(directory), 'MLOCAL_MERCHANT_OWNERS': '{}',
                'MLOCAL_AUXILIARY_TEST_DSN': self.dsn, 'MLOCAL_AUXILIARY_TEST_SCHEMA': self.schema,
                'JAC_DB_URL': self.dsn, **changes}

    def _authority_calls(self):
        from services import email_codes, qr_auth, onboarding_support
        slug = 'business-' + ACTOR
        return (
            ('store', lambda: email_codes.store().account(ACTOR)),
            ('existing_store', lambda: email_codes.existing_store().account(ACTOR)),
            ('registered_owner', lambda: email_codes.registered_business_owner(slug)),
            ('noncanonical_owner', lambda: email_codes.registered_business_owner('fixture-configured')),
            ('merchant_status', lambda: email_codes.merchant_operations_allowed(ACTOR)),
            ('qr_owner', lambda: qr_auth.merchant_owner(slug)),
            ('qr_operations', lambda: qr_auth.merchant_operations_enabled(slug)),
            ('qr_visibility', lambda: qr_auth.listing_visible(slug, 'business_signup')),
            ('qr_noncanonical_owner', lambda: qr_auth.merchant_owner('fixture-configured')),
            ('qr_noncanonical_operations', lambda: qr_auth.merchant_operations_enabled('fixture-configured')),
            ('activation', lambda: onboarding_support.prepare_business_activation(ACTOR, {**self.fields, 'image_url': ''})),
        )

    def _authority_refuses(self, directory):
        for name, invoke in self._authority_calls():
            with self.subTest(api=name):
                with self.assertRaises(ValueError) as caught:
                    invoke()
                message = str(caught.exception)
                for secret in (self.dsn, str(directory), self.code_key.hex(), str(self.code_key),
                               self.native_key.decode(), 'fixture-driver-secret'):
                    self.assertNotIn(secret, message)
                self.assertRegex(message.lower(), r'backend|authority|proof')

    def test_authority_unset_and_sqlite_keep_existing_default_behavior(self):
        from services import email_codes, qr_auth
        directory = self._authority_sqlite_copy(preserve=False)
        for selector in (None, 'sqlite'):
            with self.subTest(selector=selector), patch.dict(os.environ, self._authority_environment(directory)):
                if selector is None:
                    os.environ.pop('MLOCAL_ONBOARDING_BACKEND', None)
                else:
                    os.environ['MLOCAL_ONBOARDING_BACKEND'] = selector
                self.assertEqual(email_codes.store().account(ACTOR)['kind'], 'business')
                self.assertEqual(email_codes.existing_store().key, self.code_key)
                self.assertEqual(email_codes.registered_business_owner('business-' + ACTOR), ACTOR)
                self.assertTrue(email_codes.merchant_operations_allowed(ACTOR))
                self.assertEqual(qr_auth.merchant_owner('business-' + ACTOR), ACTOR)

    def test_authority_postgres_state_overrides_contradictory_sqlite(self):
        from services import email_codes, qr_auth, onboarding_support
        self.import_from()
        directory = self._authority_sqlite_copy(contradictory=True)
        before = self.snapshot(self.schema)
        with patch.dict(os.environ, self._authority_environment(directory)):
            for factory in (email_codes.store, email_codes.existing_store):
                with self.subTest(factory=factory.__name__):
                    state = factory()
                    self.assertEqual(state.account(ACTOR), {'email': 'owner@example.test', 'kind': 'business', 'name': 'Fixture owner'})
                    self.assertEqual(state.key, self.code_key)
            self.assertEqual(email_codes.registered_business_owner('business-' + ACTOR), ACTOR)
            self.assertTrue(email_codes.merchant_operations_allowed(ACTOR))
            self.assertEqual(qr_auth.merchant_owner('business-' + ACTOR), ACTOR)
            self.assertTrue(qr_auth.merchant_operations_enabled('business-' + ACTOR))
            self.assertTrue(qr_auth.listing_visible('business-' + ACTOR, 'business_signup'))
            result = onboarding_support.prepare_business_activation(ACTOR, {**self.fields, 'image_url': ''})
            self.assertEqual((result['slug'], result['status']), ('business-' + ACTOR, 'draft'))
        self.assertEqual(self.snapshot(self.schema), before)

    def test_authority_postgres_reads_do_not_require_accessible_sqlite(self):
        from services import email_codes, qr_auth, onboarding_support
        self.import_from()
        directory = self.work / 'absent-sqlite'
        before = self.snapshot(self.schema)
        with patch.dict(os.environ, self._authority_environment(directory)), \
                patch.object(sqlite3, 'connect', side_effect=AssertionError('Unexpected SQLite authority access')):
            self.assertEqual(email_codes.store().account(ACTOR)['kind'], 'business')
            self.assertEqual(email_codes.existing_store().key, self.code_key)
            self.assertEqual(email_codes.registered_business_owner('business-' + ACTOR), ACTOR)
            self.assertTrue(email_codes.merchant_operations_allowed(ACTOR))
            self.assertEqual(qr_auth.merchant_owner('business-' + ACTOR), ACTOR)
            self.assertTrue(qr_auth.merchant_operations_enabled('business-' + ACTOR))
            self.assertEqual(onboarding_support.prepare_business_activation(ACTOR, {**self.fields, 'image_url': ''})['slug'], 'business-' + ACTOR)
        self.assertFalse(directory.exists(), 'SQL authority selection created replacement local state')
        self.assertEqual(self.snapshot(self.schema), before)

    def test_authority_sql_suspension_overrides_stale_sqlite_active_status(self):
        from services import email_codes, qr_auth, onboarding_support
        self.import_from()
        directory = self._authority_sqlite_copy()
        self.state().change_business_status(ACTOR, 'suspended', 'Fixture reviewer', 'SQL authority suspension', 2, '0' * 29 + '301')
        before = self.snapshot(self.schema)
        with patch.dict(os.environ, self._authority_environment(directory)):
            self.assertFalse(email_codes.merchant_operations_allowed(ACTOR))
            self.assertEqual(email_codes.store().business_status(ACTOR)['status'], 'suspended')
            self.assertEqual(email_codes.existing_store().business_status(ACTOR)['revision'], 3)
            self.assertEqual(qr_auth.merchant_owner('business-' + ACTOR), ACTOR, 'Suspension must preserve ownership')
            self.assertFalse(qr_auth.merchant_operations_enabled('business-' + ACTOR))
            self.assertFalse(qr_auth.listing_visible('business-' + ACTOR, 'business_signup'))
            with self.assertRaises(ValueError):
                onboarding_support.prepare_business_activation(ACTOR, {**self.fields, 'image_url': ''})
        self.assertEqual(self.snapshot(self.schema), before)

    def test_authority_sql_revocation_returns_genuine_no_owner_without_sqlite_fallback(self):
        from services import email_codes, qr_auth
        self.import_from()
        directory = self._authority_sqlite_copy()
        changes = (
            ('inactive', "UPDATE business_owners SET active=0 WHERE actor=%s", "UPDATE business_owners SET active=1 WHERE actor=%s"),
            ('account_kind', "UPDATE accounts SET kind='student' WHERE actor=%s", "UPDATE accounts SET kind='business' WHERE actor=%s"),
            ('approval_identity', "UPDATE business_approvals SET body='{{}}' WHERE actor=%s", None),
        )
        for label, damage, restore in changes:
            with self.connect() as connection:
                connection.execute(self.sql.SQL(damage.replace('business_owners', '{}.business_owners').replace('accounts', '{}.accounts').replace('business_approvals', '{}.business_approvals')).format(self.sql.Identifier(self.schema)), (ACTOR,))
            before = self.snapshot(self.schema)
            with self.subTest(reason=label), patch.dict(os.environ, self._authority_environment(directory)):
                self.assertEqual(email_codes.registered_business_owner('business-' + ACTOR), '')
                self.assertEqual(qr_auth.merchant_owner('business-' + ACTOR), '')
                self.assertFalse(qr_auth.merchant_operations_enabled('business-' + ACTOR))
                self.assertEqual(email_codes.registered_business_owner('business-' + OTHER), '')
            self.assertEqual(self.snapshot(self.schema), before)
            if restore is not None:
                with self.connect() as connection:
                    connection.execute(self.sql.SQL(restore.replace('business_owners', '{}.business_owners').replace('accounts', '{}.accounts')).format(self.sql.Identifier(self.schema)), (ACTOR,))

    def test_authority_configured_owner_precedence_is_preserved(self):
        import json
        from services import email_codes, qr_auth
        self.import_from()
        directory = self._authority_sqlite_copy()
        for configured, slug, owner in (
                ({'fixture-configured': ACTOR}, 'fixture-configured', ACTOR),
                ({'fixture-configured': ACTOR}, 'business-' + ACTOR, ''),
                ({'business-' + ACTOR: OTHER}, 'business-' + ACTOR, ''),
                ({'business-' + ACTOR: ACTOR}, 'business-' + ACTOR, ACTOR)):
            with self.subTest(slug=slug, expected_owner=owner), patch.dict(os.environ, self._authority_environment(
                    directory, MLOCAL_MERCHANT_OWNERS=json.dumps(configured))):
                self.assertEqual(qr_auth.merchant_owner(slug), owner)
        # A malformed stored slug must not gain self-service authority merely
        # because its row still has an approved business account and active flag.
        with self.connect() as connection:
            connection.execute(self.sql.SQL('UPDATE {}.business_owners SET slug=%s WHERE actor=%s').format(
                self.sql.Identifier(self.schema)), ('fixture-noncanonical', ACTOR))
        before = self.snapshot(self.schema)
        with patch.dict(os.environ, self._authority_environment(directory)):
            self.assertEqual(email_codes.registered_business_owner('fixture-noncanonical'), '')
            self.assertEqual(qr_auth.merchant_owner('fixture-noncanonical'), '')
            self.assertTrue(qr_auth.merchant_operations_enabled('fixture-noncanonical'))
            self.assertFalse(qr_auth.listing_visible('fixture-noncanonical', 'business_signup'))
        self.assertEqual(self.snapshot(self.schema), before)

    def test_authority_first_activation_uses_stored_status_without_prior_owner_requirement(self):
        from services import email_codes, onboarding_support
        self.import_from()
        directory = self._authority_sqlite_copy(contradictory=True)
        with self.connect() as connection:
            connection.execute(self.sql.SQL('DELETE FROM {}.business_owners WHERE actor=%s').format(self.sql.Identifier(self.schema)), (ACTOR,))
            connection.execute(self.sql.SQL('DELETE FROM {}.business_status_events WHERE actor=%s').format(self.sql.Identifier(self.schema)), (ACTOR,))
            connection.execute(self.sql.SQL('DELETE FROM {}.business_status WHERE actor=%s').format(self.sql.Identifier(self.schema)), (ACTOR,))
        with patch.dict(os.environ, self._authority_environment(directory)):
            self.assertEqual(email_codes.registered_business_owner('business-' + ACTOR), '')
            self.assertTrue(email_codes.merchant_operations_allowed(ACTOR))
            result = onboarding_support.prepare_business_activation(ACTOR, {**self.fields, 'image_url': ''})
            self.assertEqual((result['slug'], result['status']), ('business-' + ACTOR, 'draft'))
        self.assertEqual(self.rows('business_owners', 'actor,slug,active'), [(ACTOR, 'business-' + ACTOR, 0)])
        self.assertEqual(self.rows('business_status'), [])
        self.assertEqual(self.rows('business_status_events'), [])

    def test_authority_unknown_selector_incomplete_config_and_production_fail_stop(self):
        self.import_from()
        directory = self._authority_sqlite_copy()
        before = self.snapshot(self.schema)
        for changes in ({'MLOCAL_ONBOARDING_BACKEND': 'unknown-proof'}, {'MLOCAL_ONBOARDING_BACKEND': ''},
                        {'MLOCAL_AUXILIARY_TEST_DSN': ''}, {'MLOCAL_AUXILIARY_TEST_SCHEMA': ''},
                        {'MLOCAL_ENV': 'production'}, {'MLOCAL_ENV': ' Production '}):
            with self.subTest(settings=tuple(changes)), patch.dict(os.environ, self._authority_environment(directory, **changes)):
                self._authority_refuses(directory)
            self.assertEqual(self.snapshot(self.schema), before)

    def test_authority_unavailable_schema_audit_versions_and_keys_fail_stop_without_repair(self):
        self.import_from()
        directory = self._authority_sqlite_copy()
        cases = ('missing_schema', 'uninitialized', 'schema_version', 'legacy_version',
                 'missing_audit', 'partial_audit', 'revision_mismatch', 'missing_keys')
        for index, kind in enumerate(cases):
            schema = self.schema + '_bad' + str(index)
            if kind != 'missing_schema':
                with self.connect() as connection:
                    connection.execute(self.sql.SQL('CREATE SCHEMA {}').format(self.sql.Identifier(schema)))
                self.schemas.append(schema)
                if kind != 'uninitialized':
                    target = self.module.PostgresAuxiliary(self.dsn, schema)
                    target.initialize()
                    target.import_legacy(self.legacy / 'onboarding.sqlite3', self.legacy / 'photo-ownership.sqlite3',
                                         self.photos_dir, self.legacy / 'code.key', self.legacy / 'jwt_secret')
                    statement = {
                        'schema_version': 'UPDATE {}.auxiliary_state SET schema_version=2',
                        'legacy_version': 'UPDATE {}.auxiliary_state SET legacy_version=2',
                        'missing_audit': 'DROP TABLE {}.business_status_events',
                        'partial_audit': 'DELETE FROM {}.business_status_events WHERE revision=1',
                        'revision_mismatch': 'UPDATE {}.business_status SET revision=revision+1',
                        'missing_keys': 'DELETE FROM {}.signing_material',
                    }[kind]
                    with self.connect() as connection:
                        connection.execute(self.sql.SQL(statement).format(self.sql.Identifier(schema)))
            before = self.snapshot(schema)
            with self.subTest(unavailable=kind), patch.dict(os.environ, self._authority_environment(
                    directory, MLOCAL_AUXILIARY_TEST_SCHEMA=schema)):
                self._authority_refuses(directory)
            self.assertEqual(self.snapshot(schema), before, 'Authority selection repaired or replaced unavailable state')
            if kind == 'missing_schema':
                with self.connect() as connection:
                    self.assertIsNone(connection.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (schema,)).fetchone())

    def test_authority_driver_failure_is_sanitized_and_never_falls_back_to_sqlite(self):
        from services import email_codes
        self.import_from()
        directory = self._authority_sqlite_copy()
        before = self.snapshot(self.schema)
        failure = self.psycopg.OperationalError('fixture-driver-secret ' + self.dsn)
        with patch.dict(os.environ, self._authority_environment(directory)), patch.object(
                self.psycopg, 'connect', side_effect=failure):
            self._authority_refuses(directory)
        # Admission can succeed before a later connection fails. The returned
        # real CodeStore must retain the same fail-stop/error-redaction boundary.
        with patch.dict(os.environ, self._authority_environment(directory)):
            for factory in (email_codes.store, email_codes.existing_store):
                state = factory()
                self.assertEqual(state.account(ACTOR)['kind'], 'business')
                def read_transaction():
                    with state.transaction() as database:
                        return database.execute('SELECT actor FROM accounts WHERE actor=?', (ACTOR,)).fetchone()
                with patch.object(self.psycopg, 'connect', side_effect=failure):
                    for operation, invoke in (('account', lambda: state.account(ACTOR)),
                                              ('transaction', read_transaction)):
                        with self.subTest(factory=factory.__name__, operation=operation):
                            with self.assertRaises(ValueError) as caught:
                                invoke()
                            message = str(caught.exception)
                            self.assertRegex(message.lower(), r'backend|authority|proof')
                            for secret in (self.dsn, str(directory), 'fixture-driver-secret'):
                                self.assertNotIn(secret, message)
        self.assertEqual(self.snapshot(self.schema), before)

    def test_authority_native_startup_refuses_proof_before_nonproduction_or_filesystem_checks(self):
        from services import production_guard
        directory = self._authority_sqlite_copy()
        native_root = self.work / 'uncreated-native-app'
        before = hashes(self.work)
        for selector in ('postgres-proof', 'unknown-proof', ''):
            for environment in ('development', 'production'):
                settings = self._authority_environment(directory, MLOCAL_ENV=environment,
                                                       MLOCAL_ONBOARDING_BACKEND=selector)
                with self.subTest(selector=selector, environment=environment), patch.object(
                        production_guard.tempfile, 'NamedTemporaryFile', side_effect=AssertionError('Unexpected filesystem write probe')):
                    with self.assertRaises(production_guard.ProductionConfigError) as caught:
                        production_guard.enforce_production_config(settings, native_root)
                    self.assertIn('MLOCAL_ONBOARDING_BACKEND', str(caught.exception))
                    self.assertNotIn(self.dsn, str(caught.exception))
                    self.assertNotIn(str(directory), str(caught.exception))
                self.assertEqual(hashes(self.work), before)
        self.assertFalse(native_root.exists())

    def test_authority_media_paths_refuse_proof_before_filesystem_mutation(self):
        import base64
        from services import media_upload
        directory = self._authority_sqlite_copy()
        before = hashes(self.work)
        payload = 'data:image/jpeg;base64,' + base64.b64encode(self.jpeg_a).decode()
        actions = (('directory', media_upload.photo_directory), ('registry', media_upload.photo_registry),
                   ('save_bytes', lambda: media_upload.save_image_bytes(self.jpeg_a, ACTOR)),
                   ('save_payload', lambda: media_upload.save_photo(payload, ACTOR)),
                   ('owned_photo', lambda: media_upload.owned_photo('/static/photos/' + PHOTO_A, ACTOR)))
        for selector in ('postgres-proof', 'unknown-proof', ''):
            with patch.dict(os.environ, self._authority_environment(
                    directory, MLOCAL_ONBOARDING_BACKEND=selector)), patch.object(
                    Path, 'mkdir', side_effect=AssertionError('Unexpected media filesystem mutation')):
                for name, invoke in actions:
                    with self.subTest(selector=selector, api=name):
                        with self.assertRaises(ValueError) as caught:
                            invoke()
                        self.assertRegex(str(caught.exception).lower(), r'backend|authority|proof')
            self.assertEqual(hashes(self.work), before)


    def _photo_reference_local(self):
        directory = self.work / 'stale-photo-reference'
        shutil.copytree(self.legacy, directory)
        with sqlite3.connect(directory / 'photo-ownership.sqlite3') as database:
            database.execute('UPDATE photos SET actor=? WHERE filename=?', (OTHER, PHOTO_A))
        (directory / 'photos' / PHOTO_A).write_bytes(self.jpeg_b)
        before = hashes(directory)
        self.addCleanup(lambda: self.assertEqual(hashes(directory), before,
                                                 'Photo reference changed preserved local stores/keys/JPEGs'))
        return directory

    def test_photo_reference_sql_owner_overrides_stale_local_owner_and_bytes(self):
        from services import media_upload, photo_reference
        self.import_from()
        directory = self._photo_reference_local()
        before = self.snapshot(self.schema)
        url = '/static/photos/' + PHOTO_A
        with patch.dict(os.environ, self._authority_environment(directory)):
            for repeat in range(2):
                self.assertEqual(media_upload.owned_photo(url, ACTOR), url)
                self.assertEqual(photo_reference.image_reference(url, ACTOR), url)
        self.assertEqual(self.snapshot(self.schema), before)

    def test_photo_reference_sql_needs_no_local_file_registry_or_symlink_target(self):
        from services import media_upload, photo_reference
        self.import_from()
        directory = self.work / 'missing-photo-private'
        app = self.work / 'disposable-photo-app'
        photos = app / 'assets/photos'
        photos.mkdir(parents=True)
        link = photos / PHOTO_A
        target_before = hashes(self.legacy)
        before = self.snapshot(self.schema)
        with patch.dict(os.environ, self._authority_environment(directory)), \
                patch.object(media_upload, '__file__', str(app / 'services/media_upload.py')), \
                patch.object(media_upload, 'photo_directory', side_effect=AssertionError('Unexpected local photo lookup')), \
                patch.object(media_upload, 'photo_registry', side_effect=AssertionError('Unexpected local registry lookup')), \
                patch.object(sqlite3, 'connect', side_effect=AssertionError('Unexpected SQLite authority access')):
            url = '/static/photos/' + PHOTO_A
            self.assertFalse(link.exists())
            self.assertEqual(media_upload.owned_photo(url, ACTOR), url)
            self.assertEqual(photo_reference.image_reference(url, ACTOR), url)
            link.symlink_to(self.photos_dir / PHOTO_A)
            link_before = (os.readlink(link), link.lstat().st_mtime_ns)
            self.assertEqual(media_upload.owned_photo(url, ACTOR), url)
            self.assertEqual(photo_reference.image_reference(url, ACTOR), url)
        self.assertFalse(directory.exists())
        self.assertEqual((os.readlink(link), link.lstat().st_mtime_ns), link_before)
        self.assertEqual(hashes(self.legacy), target_before)
        self.assertEqual(self.snapshot(self.schema), before)

    def test_photo_reference_sql_denies_foreign_missing_and_invalid_urls(self):
        from services import media_upload, photo_reference
        self.import_from()
        directory = self._photo_reference_local()
        before = self.snapshot(self.schema)
        cases = ((OTHER, '/static/photos/' + PHOTO_A), (STUDENT, '/static/photos/' + PHOTO_A),
                 (ACTOR, '/static/photos/' + '0' * 32 + '.jpg'),
                 (ACTOR, '/static/photos/../' + PHOTO_A),
                 (ACTOR, '/static/photos/' + 'A' * 32 + '.jpg'),
                 (ACTOR, '/static/photos/' + PHOTO_A + '?owner=' + ACTOR))
        with patch.dict(os.environ, self._authority_environment(directory)), \
                patch.object(media_upload, 'photo_directory', side_effect=AssertionError('Unexpected fallback to local files')), \
                patch.object(media_upload, 'photo_registry', side_effect=AssertionError('Unexpected fallback to SQLite')):
            for actor, url in cases:
                with self.subTest(actor=actor, url=url):
                    with self.assertRaises(ValueError):
                        media_upload.owned_photo(url, actor)
                    with self.assertRaises(ValueError):
                        photo_reference.image_reference(url, actor)
            with self.assertRaises(ValueError):
                media_upload.owned_photo('/static/photos/' + PHOTO_A, '')
        self.assertEqual(self.snapshot(self.schema), before)

    def test_photo_reference_actual_activation_keeps_sql_photo_and_authority(self):
        from services import email_codes, onboarding_support
        self.import_from()
        directory = self._photo_reference_local()
        preserved = {table: self.rows(table) for table in ('photos', 'signing_material', 'accounts',
                     'business_approvals', 'business_reviews', 'business_status', 'business_status_events')}
        url = '/static/photos/' + PHOTO_A
        raw = {**self.fields, 'image_url': url, 'slug': 'untrusted', 'actor': OTHER, 'status': 'untrusted'}
        with patch.dict(os.environ, self._authority_environment(directory)):
            for repeat in range(2):
                prepared = onboarding_support.prepare_business_activation(ACTOR, raw)
                self.assertEqual((prepared['slug'], prepared['image_url']), ('business-' + ACTOR, url))
                finished = onboarding_support.finish_business_activation(ACTOR, prepared)
                self.assertEqual((finished['image_url'], finished['status']), (url, 'active'))
                self.assertNotIn('actor', finished)
                self.assertNotIn('slug', finished)
                self.assertEqual(email_codes.store().draft(ACTOR)['image_url'], url)
                self.assertEqual(email_codes.registered_business_owner('business-' + ACTOR), ACTOR)
                self.assertTrue(email_codes.merchant_operations_allowed(ACTOR))
        self.assertEqual(self.rows('business_owners', 'actor,slug,active'), [(ACTOR, 'business-' + ACTOR, 1)])
        for table, rows in preserved.items():
            self.assertEqual(self.rows(table), rows)

    def test_photo_reference_bad_sql_bytes_keys_audit_or_version_refuse_without_repair(self):
        from services import media_upload, photo_reference
        self.import_from()
        directory = self._photo_reference_local()
        url = '/static/photos/' + PHOTO_A
        for index, kind in enumerate(('digest', 'jpeg', 'native_key', 'audit', 'version')):
            schema = self.schema + '_photo' + str(index)
            with self.connect() as connection:
                connection.execute(self.sql.SQL('CREATE SCHEMA {}').format(self.sql.Identifier(schema)))
            self.schemas.append(schema)
            backend = self.module.PostgresAuxiliary(self.dsn, schema)
            backend.initialize()
            backend.import_legacy(self.legacy / 'onboarding.sqlite3', self.legacy / 'photo-ownership.sqlite3',
                                  self.photos_dir, self.legacy / 'code.key', self.legacy / 'jwt_secret')
            with self.connect() as connection:
                if kind == 'digest':
                    connection.execute(self.sql.SQL('UPDATE {}.photos SET digest=%s WHERE filename=%s').format(
                        self.sql.Identifier(schema)), ('0' * 64, PHOTO_A))
                elif kind == 'jpeg':
                    data = b'x' * len(self.jpeg_a)
                    connection.execute(self.sql.SQL('UPDATE {}.photos SET content=%s,digest=%s WHERE filename=%s').format(
                        self.sql.Identifier(schema)), (data, hashlib.sha256(data).hexdigest(), PHOTO_A))
                elif kind == 'native_key':
                    connection.execute(self.sql.SQL("DELETE FROM {}.signing_material WHERE name='native_key'").format(self.sql.Identifier(schema)))
                elif kind == 'audit':
                    connection.execute(self.sql.SQL('DELETE FROM {}.business_status_events WHERE revision=1').format(self.sql.Identifier(schema)))
                else:
                    connection.execute(self.sql.SQL('UPDATE {}.auxiliary_state SET schema_version=2').format(self.sql.Identifier(schema)))
            before = self.snapshot(schema)
            with self.subTest(damaged=kind), patch.dict(os.environ, self._authority_environment(
                    directory, MLOCAL_AUXILIARY_TEST_SCHEMA=schema)):
                for invoke in (lambda: media_upload.owned_photo(url, ACTOR),
                               lambda: photo_reference.image_reference(url, ACTOR)):
                    with self.assertRaises(ValueError) as caught:
                        invoke()
                    self.assertRegex(str(caught.exception).lower(), r'authority|backend|proof')
                    self.assertNotIn(self.dsn, str(caught.exception))
            self.assertEqual(self.snapshot(schema), before)

    def test_photo_reference_outage_unknown_and_production_fail_stop(self):
        from services import media_upload, photo_reference, onboarding_support
        self.import_from()
        directory = self._photo_reference_local()
        before = self.snapshot(self.schema)
        url = '/static/photos/' + PHOTO_A
        calls = (lambda: media_upload.owned_photo(url, ACTOR),
                 lambda: photo_reference.image_reference(url, ACTOR),
                 lambda: onboarding_support.prepare_business_activation(ACTOR, self.fields),
                 lambda: onboarding_support.finish_business_activation(ACTOR, self.fields))
        for changes in ({'MLOCAL_ONBOARDING_BACKEND': 'unknown'}, {'MLOCAL_ONBOARDING_BACKEND': ''},
                        {'MLOCAL_ENV': 'production'}, {'MLOCAL_AUXILIARY_TEST_SCHEMA': ''}):
            with self.subTest(settings=tuple(changes)), patch.dict(os.environ, self._authority_environment(directory, **changes)):
                for invoke in calls:
                    with self.assertRaises(ValueError) as caught:
                        invoke()
                    self.assertNotIn(self.dsn, str(caught.exception))
        with patch.dict(os.environ, self._authority_environment(directory)), patch.object(
                self.psycopg, 'connect', side_effect=self.psycopg.OperationalError('fixture-driver-secret ' + self.dsn)):
            for invoke in calls:
                with self.assertRaises(ValueError) as caught:
                    invoke()
                self.assertNotIn('fixture-driver-secret', str(caught.exception))
                self.assertNotIn(self.dsn, str(caught.exception))
        self.assertEqual(self.snapshot(self.schema), before)



    def _native_key_fixture(self, raw=None):
        import json
        root = self.work / ('native-key-proof-' + uuid4().hex[:8])
        base, home = root / 'app', root / 'original-native'
        base.mkdir(parents=True)
        signing = home / '.jac/data'
        signing.mkdir(parents=True)
        raw = self.native_key if raw is None else raw
        (signing / 'jwt_secret').write_bytes(raw)
        entry = base / 'identity-probe.py'
        entry.write_text('# Fixed canonical synthetic auth/identity context.\n')
        original = hashes(home)
        self.addCleanup(lambda: self.assertEqual(hashes(home), original, 'Original native key fixture changed'))
        # This anchor is recorded before importing or selecting SQL material.
        expected = hashlib.sha256((signing / 'jwt_secret').read_bytes()).hexdigest()
        descriptor = {'synthetic_disposable_only': True, 'fixture_root': str(root),
                      'base': str(base), 'entry': str(entry), 'original_home': str(home),
                      'packet': str(root / 'private-issued-tokens.json'), 'dsn': self.dsn,
                      'schema': self.schema, 'expected_raw_sha256': expected}
        with os.fdopen(os.open(root / 'original-key-fingerprint.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump({'raw_sha256': expected}, stream)
        return descriptor

    def _native_key_run(self, fixture, phase, selection='postgres-proof', expected_exit=0, **changes):
        import json, signal, subprocess
        request = {**fixture, 'phase': phase, 'selection': selection, **changes}
        path = Path(fixture['fixture_root']) / ('request-' + uuid4().hex + '.json')
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump(request, stream)
        program = ('import os,runpy,sys; '
                   'sys.path.insert(0,os.environ["MLOCAL_AUXILIARY_DRIVER_SITE"]); '
                   'sys.path.insert(0,sys.argv.pop(1)); script=sys.argv.pop(1); '
                   'runpy.run_path(script,run_name="__main__")')
        environment = dict(os.environ)
        # Poison only harmless synthetic signing overrides; the child must scrub
        # them before loading official settings. No foreign database is supplied.
        environment['JAC_SERVE_AUTH_SECRET'] = 'synthetic-inherited-wrong-signing-setting'
        environment['JAC_SERVE_AUTH_ALGORITHM'] = 'HS512'
        child = subprocess.Popen([sys.executable, '-c', program, str(ROOT),
                                  str(ROOT / 'tests/integration/native_key_probe.py'), str(path)],
                                 cwd=fixture['base'], env=environment, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            stdout, stderr = child.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate(timeout=5)
            self.fail('Owned synthetic key probe exceeded its deadline')
        self.assertEqual(child.wait(timeout=5), child.returncode)
        with self.assertRaises(ProcessLookupError):
            os.killpg(child.pid, 0)
        try:
            result = json.loads(stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            self.fail('Owned key probe did not return redacted structured evidence')
        if child.returncode != expected_exit:
            print('native-key probe diagnostic: ' + json.dumps({k: result.get(k) for k in
                  ('phase', 'stage', 'status', 'error_class', 'line')}, sort_keys=True))
        self.assertEqual(child.returncode, expected_exit, 'Owned key probe status differs from expected phase result')
        # Boolean-only diagnostics never format private fixture values or output.
        private_values = [self.dsn, self.native_key.decode(),
                          (Path(fixture['original_home']) / '.jac/data/jwt_secret').read_text()]
        packet = Path(fixture['packet'])
        if packet.exists():
            private_values.extend(row['token'] for row in json.loads(packet.read_text()))
        self.assertFalse(any(value and value in output for value in private_values
                             for output in (stdout, stderr)), 'Private fixture value appeared in probe output')
        base = Path(fixture['base'])
        self.assertFalse(list(base.rglob('jwt_secret*')), 'Native probe minted a fallback signing file')
        self.assertFalse(list(base.rglob('*.sqlite*')), 'Native probe created an alternate SQLite store')
        return result

    def test_native_key_real_identities_and_issued_tokens_survive_restart_and_selection(self):
        import json
        fixture = self._native_key_fixture()
        first = self._native_key_run(fixture, 'seed', selection='sqlite')
        self.assertTrue(first['token_issuance'] and first['actual_session_pgstore'])
        packet = Path(fixture['packet'])
        token_bytes = packet.read_bytes()
        private = json.loads(token_bytes)
        self.assertEqual(len(private), 2)
        self.assertEqual([row['user']['identities'][1]['verified'] for row in private], [True, False])
        native = self.snapshot('public')
        self.assertTrue(native['identity_users'] and native['anchors'])
        # Import only after the original fingerprint and real baseline tokens exist.
        self.import_from()
        auxiliary = self.snapshot(self.schema)
        pids = {first['pid']}
        for phase, selection in (('verify', 'sqlite'), ('verify', 'postgres-proof'),
                                 ('verify-wrong-secret', 'postgres-proof'), ('verify', 'sqlite')):
            outcome = self._native_key_run(fixture, phase, selection=selection)
            self.assertEqual(outcome['original_tokens_verified'], 2)
            self.assertFalse(outcome['token_issuance'])
            self.assertEqual((outcome['canonical_base'], outcome['canonical_entry']),
                             (fixture['base'], fixture['entry']))
            if selection == 'postgres-proof':
                self.assertTrue(outcome['sql_nonblank_env'])
            self.assertNotIn(outcome['pid'], pids)
            pids.add(outcome['pid'])
            self.assertTrue(packet.read_bytes() == token_bytes, 'Previously issued tokens were replaced')
            self.assertEqual(self.snapshot('public'), native, 'Native identity/root rows changed during validation')
            self.assertEqual(self.snapshot(self.schema), auxiliary)
        self.assertEqual(self.backend.signing_material()['native_key'], self.native_key)

    def test_native_key_original_fingerprint_and_malformed_material_refuse_before_fallback(self):
        import runpy
        fixture = self._native_key_fixture()
        self.import_from()
        native = self.snapshot('public')
        for kind in ('wrong', 'missing_native', 'missing_code'):
            with self.connect() as connection:
                if kind == 'wrong':
                    connection.execute(self.sql.SQL("UPDATE {}.signing_material SET material=%s WHERE name='native_key'").format(self.sql.Identifier(self.schema)),
                                       (b'synthetic-different-valid-length-native-key',))
                else:
                    name = 'native_key' if kind == 'missing_native' else 'code_key'
                    connection.execute(self.sql.SQL('DELETE FROM {}.signing_material WHERE name=%s').format(self.sql.Identifier(self.schema)), (name,))
            before = self.snapshot(self.schema)
            with self.subTest(sql_damage=kind):
                result = self._native_key_run(fixture, 'admit', expected_exit=1)
                self.assertEqual(result['stage'], 'admission')
                self.assertEqual(self.snapshot(self.schema), before)
                self.assertEqual(self.snapshot('public'), native)
            with self.connect() as connection:
                for name, material in (('native_key', self.native_key), ('code_key', self.code_key)):
                    connection.execute(self.sql.SQL('INSERT INTO {}.signing_material(name,material) VALUES (%s,%s) ON CONFLICT(name) DO UPDATE SET material=excluded.material').format(self.sql.Identifier(self.schema)), (name, material))
        probe = runpy.run_path(str(ROOT / 'tests/integration/native_key_probe.py'), run_name='native_key_contract')
        derive = probe['effective_key']
        bad = (b'', b'   \t\n', b'short', b'supersecretkey_for_testing_only!', b'\xffsynthetic-invalid-utf8',
               b'synthetic-native-key-with-embedded\x00nul-only', b'synthetic-native-key-with-embedded\nline-break',
               b'synthetic-native-key-with-embedded\rcarriage-return')
        for raw in bad:
            with self.subTest(material_class=bad.index(raw)):
                with self.assertRaises(ValueError) as caught:
                    derive(raw, hashlib.sha256(raw).hexdigest())
                self.assertRegex(str(caught.exception).lower(), 'key|signing|material')
        for expected in ('', 'x' * 64, '0' * 64, None):
            with self.subTest(anchor=type(expected).__name__):
                with self.assertRaises(ValueError):
                    derive(self.native_key, expected)
        self.assertEqual(self.snapshot('public'), native)

    def test_native_key_effective_text_matches_official_file_and_environment_resolution(self):
        variants = (b' \t' + self.native_key + b'\r\n',
                    ('\u2003' + self.native_key.decode() + '\u2003').encode())
        native = self.snapshot('public')
        for index, raw in enumerate(variants):
            fixture = self._native_key_fixture(raw)
            legacy = self.work / ('native-key-variant-' + str(index))
            shutil.copytree(self.legacy, legacy)
            (legacy / 'jwt_secret').write_bytes(raw)
            preserved = hashes(legacy)
            self.addCleanup(lambda directory=legacy, before=preserved: self.assertEqual(hashes(directory), before))
            schema = self.schema + '_key' + str(index)
            with self.connect() as connection:
                connection.execute(self.sql.SQL('CREATE SCHEMA {}').format(self.sql.Identifier(schema)))
            self.schemas.append(schema)
            backend = self.module.PostgresAuxiliary(self.dsn, schema)
            backend.initialize()
            backend.import_legacy(legacy / 'onboarding.sqlite3', legacy / 'photo-ownership.sqlite3',
                                  legacy / 'photos', legacy / 'code.key', legacy / 'jwt_secret')
            fixture['schema'] = schema
            before = self.snapshot(schema)
            file_result = self._native_key_run(fixture, 'resolve', selection='sqlite')
            sql_result = self._native_key_run(fixture, 'resolve')
            self.assertEqual(file_result['effective_sha256'], sql_result['effective_sha256'])
            self.assertTrue(sql_result['sql_nonblank_env'])
            self.assertEqual(backend.signing_material()['native_key'], raw)
            self.assertEqual(self.snapshot(schema), before)
            self.assertEqual(self.snapshot('public'), native)

    def test_native_key_invalid_selection_and_outage_never_initialize_native_identity(self):
        fixture = self._native_key_fixture()
        self.import_from()
        native, auxiliary = self.snapshot('public'), self.snapshot(self.schema)
        cases = ({'selection': 'unknown'}, {'selection': ''}, {'environment': 'production'},
                 {'schema': ''}, {'dsn': ''},
                 {'dsn': self.psycopg.conninfo.make_conninfo(self.dsn, port=1)})
        for changes in cases:
            with self.subTest(configuration=tuple(changes)):
                result = self._native_key_run(fixture, 'admit', expected_exit=1, **changes)
                self.assertEqual(result['stage'], 'admission')
                self.assertEqual(self.snapshot('public'), native)
                self.assertEqual(self.snapshot(self.schema), auxiliary)


if __name__ == '__main__':
    unittest.main(verbosity=2)
