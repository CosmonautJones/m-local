"""Private merchant authority is issued only to verified business accounts."""
import concurrent.futures
from contextlib import closing
import fcntl
import os
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from services.email_codes import CodeStore, business_revision
from services import email_codes
from services import onboarding_support as onboarding


class BusinessActivationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        environment = patch.dict('os.environ', {'MLOCAL_ONBOARDING_DIR': directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.state = CodeStore(self.directory)
        self.owner = 'a' * 32
        self.other = 'b' * 32
        self.student = 'c' * 32
        for actor, kind in ((self.owner, 'business'), (self.other, 'business'), (self.student, 'student')):
            self.state.remember_account(actor, actor + '@example.test', kind, 'Fixture')
        self.fields = {'name': 'Test Cafe', 'address': '123 Test St', 'menu_text': 'Soup $5'}

    def approve(self, actor):
        onboarding.persist_draft(actor, self.fields)
        self.state.approve_business(actor, 'Fixture reviewer', 'Confirmed authority with fixture business', business_revision(self.state.draft(actor)))

    def test_authority_read_does_not_wait_for_an_uncommitted_writer(self):
        self.approve(self.owner)
        prepared = onboarding.prepare_business_activation(self.owner, self.fields)
        onboarding.finish_business_activation(self.owner, prepared)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with self.state.transaction() as db:
                db.execute('UPDATE business_owners SET active=0 WHERE actor=?', (self.owner,))
                future = pool.submit(email_codes.registered_business_owner, prepared['slug'])
                self.assertEqual(future.result(timeout=1), self.owner)
        self.assertEqual(email_codes.registered_business_owner(prepared['slug']), '')

    def test_authority_read_observes_committed_revocation_and_identity_damage(self):
        self.approve(self.owner)
        prepared = onboarding.prepare_business_activation(self.owner, self.fields)
        onboarding.finish_business_activation(self.owner, prepared)
        self.assertEqual(email_codes.registered_business_owner(prepared['slug']), self.owner)
        with self.state.transaction() as db:
            db.execute('UPDATE business_owners SET active=0 WHERE actor=?', (self.owner,))
        self.assertEqual(email_codes.registered_business_owner(prepared['slug']), '')
        with self.state.transaction() as db:
            db.execute('UPDATE business_owners SET active=1 WHERE actor=?', (self.owner,))
            db.execute('UPDATE business_approvals SET body=? WHERE actor=?', ('{}', self.owner))
        self.assertEqual(email_codes.registered_business_owner(prepared['slug']), '')

    def test_authority_read_fails_closed_without_recreating_private_files(self):
        self.approve(self.owner)
        prepared = onboarding.prepare_business_activation(self.owner, self.fields)
        onboarding.finish_business_activation(self.owner, prepared)
        key = self.directory / 'code.key'
        key.write_bytes(b'broken')
        self.assertEqual(email_codes.registered_business_owner(prepared['slug']), '')
        key.unlink()
        self.assertEqual(email_codes.registered_business_owner(prepared['slug']), '')
        self.assertFalse(key.exists())
        key.write_bytes(self.state.key)
        self.state.path.rename(self.directory / 'saved.sqlite3')
        self.assertEqual(email_codes.registered_business_owner(prepared['slug']), '')
        self.assertFalse(self.state.path.exists())

    def test_verified_business_cannot_activate_without_operator_approval(self):
        fields = {**self.fields, 'status': 'approved', 'approved': True}
        with self.assertRaisesRegex(ValueError, 'approval'):
            onboarding.prepare_business_activation(self.owner, fields)
        with self.assertRaisesRegex(ValueError, 'approval'):
            onboarding.finish_business_activation(self.owner, fields)
        self.assertEqual(self.state.business_owner('business-' + self.owner), '')

    def test_legacy_approval_schema_requires_migration_and_identity_review(self):
        self.approve(self.owner)
        prepared = onboarding.prepare_business_activation(self.owner, self.fields)
        onboarding.finish_business_activation(self.owner, prepared)
        with self.state.transaction() as db:
            db.execute('ALTER TABLE business_approvals DROP COLUMN body')
        self.assertEqual(email_codes.registered_business_owner(prepared['slug']), '')
        with self.state.transaction() as db:
            self.assertNotIn('body', [row['name'] for row in db.execute('PRAGMA table_info(business_approvals)')])
        migrated = email_codes.existing_store()
        with migrated.transaction() as db:
            self.assertIn('body', [row['name'] for row in db.execute('PRAGMA table_info(business_approvals)')])
        self.assertEqual(email_codes.registered_business_owner(prepared['slug']), '')
        self.assertFalse(migrated.approval_covers(self.owner, self.fields))
        self.approve(self.owner)
        self.assertEqual(email_codes.registered_business_owner(prepared['slug']), self.owner)

    def test_operator_review_refuses_missing_or_wrong_private_state(self):
        missing = self.directory / 'missing'
        with patch.dict('os.environ', {'MLOCAL_ONBOARDING_DIR': str(missing)}):
            with self.assertRaisesRegex(ValueError, 'existing deployment'):
                email_codes.existing_store()
        self.assertFalse(missing.exists())
        key = self.directory / 'code.key'
        key.unlink()
        with self.assertRaisesRegex(ValueError, 'original key'):
            email_codes.existing_store()
        self.assertFalse(key.exists())
        key.write_bytes(b'broken')
        with self.assertRaises(ValueError):
            email_codes.existing_store()
        self.assertEqual(key.read_bytes(), b'broken')
        key.write_bytes(self.state.key)
        self.state.path.rename(self.directory / 'saved.sqlite3')
        with self.assertRaises(ValueError):
            email_codes.existing_store()
        self.assertFalse(self.state.path.exists())
        db = sqlite3.connect(self.state.path)
        db.execute('CREATE TABLE unrelated (value TEXT)')
        db.close()
        with self.assertRaisesRegex(ValueError, 'existing deployment'):
            email_codes.existing_store()
        with closing(sqlite3.connect(self.state.path)) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [('unrelated',)])

    def test_operator_review_refuses_named_tables_with_missing_columns_without_mutation(self):
        schemas = {
            'accounts': 'actor TEXT PRIMARY KEY, email TEXT UNIQUE, kind TEXT, name TEXT',
            'business_owners': 'actor TEXT PRIMARY KEY, slug TEXT UNIQUE NOT NULL, active INTEGER NOT NULL DEFAULT 0',
            'drafts': 'actor TEXT PRIMARY KEY, body TEXT, updated REAL',
        }
        for damaged in schemas:
            with self.subTest(table=damaged):
                directory = self.directory / ('wrong-' + damaged)
                directory.mkdir()
                key = directory / 'code.key'
                key.write_bytes(self.state.key)
                database = directory / 'onboarding.sqlite3'
                with closing(sqlite3.connect(database)) as db:
                    for table, columns in schemas.items():
                        db.execute('CREATE TABLE ' + table + ' (' + ('unrelated TEXT' if table == damaged else columns) + ')')
                before = database.read_bytes()
                with patch.dict('os.environ', {'MLOCAL_ONBOARDING_DIR': str(directory)}):
                    with self.assertRaisesRegex(ValueError, 'existing deployment'):
                        email_codes.existing_store()
                self.assertEqual(database.read_bytes(), before)
                self.assertEqual(key.read_bytes(), self.state.key)

    def test_operator_review_normalizes_migration_errors(self):
        for error in (sqlite3.OperationalError('database is locked'), PermissionError('read only')):
            with self.subTest(error=type(error).__name__):
                with patch.object(email_codes, 'CodeStore', side_effect=error):
                    with self.assertRaisesRegex(ValueError, 'could not open or migrate'):
                        email_codes.existing_store()
        for error in (OSError('path unavailable'), RuntimeError('symlink loop')):
            with self.subTest(path_error=type(error).__name__):
                with patch.object(email_codes.Path, 'resolve', side_effect=error):
                    with self.assertRaisesRegex(ValueError, 'existing deployment'):
                        email_codes.existing_store()

    def test_operator_command_reports_post_migration_storage_errors_without_success_or_traceback(self):
        onboarding.persist_draft(self.owner, self.fields)
        submission = business_revision(self.state.draft(self.owner))
        with self.state.transaction() as db:
            db.execute('DROP TABLE business_approvals')
            db.execute('CREATE TABLE business_approvals (body TEXT)')
        project = Path(__file__).resolve().parents[2]
        for command in ('list', 'approve'):
            with self.subTest(command=command):
                arguments = [] if command == 'list' else ['--actor', self.owner, '--by', 'Fixture reviewer',
                    '--note', 'Verified fictional business', '--submission', submission]
                result = subprocess.run(['bash', 'scripts/review-business.sh', command, *arguments],
                    cwd=project, env=dict(os.environ), capture_output=True, text=True, timeout=120)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Business review could not read or update the private store.', result.stderr)
                self.assertNotIn('Traceback', result.stdout + result.stderr)
                self.assertNotIn('Business approved.', result.stdout)

    def test_reserved_registry_slot_has_no_authority_until_graph_activation_finishes(self):
        self.approve(self.owner)
        prepared = onboarding.prepare_business_activation(self.owner, self.fields)
        self.assertEqual(prepared['slug'], 'business-' + self.owner)
        self.assertEqual(self.state.business_owner(prepared['slug']), '')
        self.assertEqual(self.state.draft(self.owner)['status'], 'pending_review')
        active = onboarding.finish_business_activation(self.owner, prepared)
        self.assertEqual(active['status'], 'active')
        self.assertEqual(self.state.business_owner(prepared['slug']), self.owner)
        self.assertEqual(self.state.draft(self.owner)['menu_text'], 'Soup $5')

    def test_repeated_and_concurrent_reservation_converges_on_one_private_identity(self):
        self.approve(self.owner)
        def reserve(_):
            return onboarding.prepare_business_activation(self.owner, self.fields)['slug']
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            slugs = list(pool.map(reserve, range(12)))
        self.assertEqual(set(slugs), {'business-' + self.owner})
        raw = onboarding.prepare_business_activation(self.owner, self.fields)
        onboarding.finish_business_activation(self.owner, raw)
        with self.assertRaisesRegex(ValueError, 'approval'):
            onboarding.prepare_business_activation(self.owner, {**self.fields, 'name': 'Renamed Cafe'})
        onboarding.persist_draft(self.owner, {**self.fields, 'name': 'Renamed Cafe'})
        self.state.approve_business(self.owner, 'Fixture reviewer', 'Reviewed new business name', business_revision(self.state.draft(self.owner)))
        renamed = onboarding.prepare_business_activation(self.owner, {**self.fields, 'name': 'Renamed Cafe'})
        onboarding.finish_business_activation(self.owner, renamed)
        reopened = CodeStore(self.directory)
        self.assertEqual(reopened.business_owner(raw['slug']), self.owner)
        self.assertEqual(reopened.draft(self.owner)['name'], 'Renamed Cafe')

    def test_client_cannot_choose_another_business_slug_actor_or_status(self):
        self.approve(self.owner)
        raw = onboarding.prepare_business_activation(self.owner, {
            **self.fields, 'slug': 'arbor-leaf-kitchen', 'actor': self.other,
            'owner_actor_id': self.other, 'status': 'admin',
        })
        active = onboarding.finish_business_activation(self.owner, raw)
        self.assertEqual(raw['slug'], 'business-' + self.owner)
        self.assertEqual(self.state.business_owner('arbor-leaf-kitchen'), '')
        self.assertEqual(self.state.business_owner('business-' + self.other), '')
        self.assertNotIn('owner_actor_id', active)
        self.assertNotIn('actor', self.state.draft(self.owner))
        self.assertEqual(self.state.account(self.owner)['kind'], 'business')

    def test_same_business_name_does_not_merge_accounts_or_grant_other_owner_access(self):
        for actor in (self.owner, self.other):
            self.approve(actor)
            raw = onboarding.prepare_business_activation(actor, self.fields)
            onboarding.finish_business_activation(actor, raw)
        self.assertEqual(self.state.business_owner('business-' + self.owner), self.owner)
        self.assertEqual(self.state.business_owner('business-' + self.other), self.other)

    def test_guest_student_unverified_and_malformed_actor_cannot_reserve_or_activate(self):
        for actor in ('', self.student, 'd' * 32, 'not-an-actor'):
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                onboarding.prepare_business_activation(actor, self.fields)
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                onboarding.finish_business_activation(actor, self.fields)

    def test_invalid_profile_cannot_change_active_profile_or_create_authority(self):
        self.approve(self.owner)
        raw = onboarding.prepare_business_activation(self.owner, self.fields)
        onboarding.finish_business_activation(self.owner, raw)
        with self.assertRaises(ValueError):
            onboarding.prepare_business_activation(self.owner, {**self.fields, 'name': ''})
        self.assertEqual(self.state.draft(self.owner)['name'], 'Test Cafe')
        with self.assertRaises(ValueError):
            onboarding.prepare_business_activation(self.other, {**self.fields, 'address': ''})
        self.assertEqual(self.state.business_owner('business-' + self.other), '')

    def test_reading_legacy_pending_profile_never_activates_it(self):
        self.state.save_draft(self.owner, {**self.fields, 'status': 'pending_review'})
        self.assertEqual(onboarding.read_draft(self.owner)['status'], 'pending_review')
        self.assertEqual(self.state.business_owner('business-' + self.owner), '')
        with self.assertRaisesRegex(ValueError, 'approval'):
            onboarding.prepare_business_activation(self.owner, self.fields)
        self.approve(self.owner)
        raw = onboarding.prepare_business_activation(self.owner, self.fields)
        onboarding.finish_business_activation(self.owner, raw)
        self.assertEqual(onboarding.read_draft(self.owner)['status'], 'active')

    def test_activation_fields_fit_the_merchant_editor_and_reject_control_characters(self):
        for field, value in (
            ('name', 'N' * 121), ('cuisine', 'C' * 81), ('address', 'A' * 241),
            ('name', 'Bad\x00name'), ('cuisine', 'Bad\x7fcuisine'),
            ('address', 'Bad\x1faddress'), ('description', 'Bad\x00description'),
        ):
            with self.subTest(field=field, value=repr(value)), self.assertRaises(ValueError):
                onboarding.prepare_business_activation(self.owner, {**self.fields, field: value})
        self.assertEqual(self.state.draft(self.owner), {})
        self.assertEqual(self.state.business_owner('business-' + self.owner), '')

    def test_approval_survives_reopen_and_keeps_original_audit_on_retry(self):
        self.approve(self.owner)
        reopened = CodeStore(self.directory)
        self.assertTrue(reopened.business_approved(self.owner))
        reopened.approve_business(self.owner, 'Other reviewer', 'Retry after interrupted activation', business_revision(reopened.draft(self.owner)))
        with reopened.transaction() as db:
            row = db.execute('SELECT reviewer,note FROM business_approvals WHERE actor=?', (self.owner,)).fetchone()
        self.assertEqual(row['reviewer'], 'Fixture reviewer')
        self.assertEqual(row['note'], 'Confirmed authority with fixture business')
        self.assertFalse(reopened.business_approved(self.other))

    def test_old_active_registry_does_not_bypass_new_approval_policy(self):
        slug = self.state.reserve_business(self.owner)
        with self.state.transaction() as db:
            db.execute('UPDATE business_owners SET active=1 WHERE actor=?', (self.owner,))
        self.assertEqual(self.state.business_owner(slug), '')
        self.assertFalse(self.state.business_approved(self.owner))

    def test_review_requires_business_submission_and_auditable_reason(self):
        for actor in (self.student, self.other, 'not-an-actor'):
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                self.state.approve_business(actor, 'Reviewer', 'Checked authority', '')
        onboarding.persist_draft(self.owner, self.fields)
        for reviewer, note in (('', 'Checked authority'), ('Reviewer', ''), ('Reviewer', 'Bad\x00note')):
            with self.subTest(reviewer=reviewer, note=note), self.assertRaises(ValueError):
                self.state.approve_business(self.owner, reviewer, note, business_revision(self.state.draft(self.owner)))
        self.assertFalse(self.state.business_approved(self.owner))

    def test_changed_submission_cannot_be_approved_using_old_review_revision(self):
        onboarding.persist_draft(self.owner, self.fields)
        revision = business_revision(self.state.draft(self.owner))
        onboarding.persist_draft(self.owner, {**self.fields, 'address': '456 Changed Street'})
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.state.approve_business(self.owner, 'Reviewer', 'Checked old address', revision)
        self.assertFalse(self.state.business_approved(self.owner))

    def test_review_inventory_includes_old_active_owner_without_private_draft(self):
        slug = self.state.reserve_business(self.owner)
        with self.state.transaction() as db:
            db.execute('UPDATE business_owners SET active=1 WHERE actor=?', (self.owner,))
            db.execute('INSERT INTO business_approvals (actor,reviewer,note,approved) VALUES (?,?,?,?)',
                       (self.owner, 'Old reviewer', 'Pre-snapshot approval', 1))
        pending = self.state.pending_businesses()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['actor'], self.owner)
        self.assertEqual(pending[0]['slug'], slug)
        self.assertTrue(pending[0]['needs_submission'])
        self.assertEqual(pending[0]['profile'], {})
        self.assertFalse(self.state.business_approved(self.owner))
        with self.assertRaisesRegex(ValueError, 'submitted'):
            self.state.approve_business(self.owner, 'Reviewer', 'Checked authority', pending[0]['submission'])
        self.approve(self.owner)
        self.assertEqual(self.state.pending_businesses(), [])
        self.assertEqual(self.state.business_owner(slug), self.owner)

    def test_identity_review_history_keeps_original_snapshot_after_later_edits(self):
        import json
        self.approve(self.owner)
        first = self.state.draft(self.owner)
        onboarding.persist_draft(self.owner, {**self.fields, 'name': 'New Cafe'})
        self.state.approve_business(self.owner, 'Second reviewer', 'Confirmed changed name',
                                    business_revision(self.state.draft(self.owner)))
        onboarding.persist_draft(self.owner, {**self.fields, 'name': 'New Cafe', 'menu_text': 'Soup $7'})
        with self.state.transaction() as db:
            rows = db.execute('SELECT reviewer,body FROM business_reviews WHERE actor=? ORDER BY id',
                              (self.owner,)).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(json.loads(rows[0]['body']), first)
        self.assertEqual(json.loads(rows[1]['body'])['name'], 'New Cafe')
        self.assertEqual(json.loads(rows[1]['body'])['menu_text'], 'Soup $5')

    def test_concurrent_edit_and_review_never_approve_the_unreviewed_submission(self):
        onboarding.persist_draft(self.owner, self.fields)
        revision = business_revision(self.state.draft(self.owner))
        def review():
            try:
                self.state.approve_business(self.owner, 'Reviewer', 'Checked original identity', revision)
            except ValueError as error:
                self.assertIn('changed', str(error))
        def edit():
            onboarding.persist_draft(self.owner, {**self.fields, 'address': '456 Changed Street'})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(review), pool.submit(edit)]
            for future in futures:
                future.result()
        self.assertFalse(self.state.approval_covers(self.owner, self.state.draft(self.owner)))
        approved = self.state.approved_profile(self.owner)
        self.assertIn(approved.get('address'), (None, '123 Test St'))

    def test_damaged_private_approval_fails_closed_and_stays_in_review_inventory(self):
        self.approve(self.owner)
        raw = onboarding.prepare_business_activation(self.owner, self.fields)
        onboarding.finish_business_activation(self.owner, raw)
        for damaged in ('broken json', 'null', '[]', '"text"', '{"name":1,"address":true}'):
            with self.subTest(damaged=damaged):
                with self.state.transaction() as db:
                    db.execute('UPDATE business_approvals SET body=? WHERE actor=?', (damaged, self.owner))
                self.assertFalse(self.state.business_approved(self.owner))
                self.assertEqual(self.state.business_owner(raw['slug']), '')
                self.assertEqual(self.state.pending_businesses()[0]['actor'], self.owner)
        with self.state.transaction() as db:
            db.execute('UPDATE drafts SET body=? WHERE actor=?', ('broken json', self.owner))
        self.assertEqual(self.state.draft(self.owner), {})
        self.assertTrue(self.state.pending_businesses()[0]['needs_submission'])
        with self.assertRaisesRegex(ValueError, 'complete'):
            self.state.approve_business(self.owner, 'Reviewer', 'Checked damaged entry', '')

    def test_wrong_kind_old_owner_is_in_inventory_and_cannot_gain_authority(self):
        with self.state.transaction() as db:
            db.execute('INSERT INTO business_owners (actor,slug,active) VALUES (?,?,1)',
                       (self.student, 'business-' + self.student))
        pending = self.state.pending_businesses()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['actor'], self.student)
        self.assertTrue(pending[0]['needs_submission'])
        self.assertEqual(self.state.business_owner('business-' + self.student), '')

    def test_damaged_existing_draft_cannot_silently_skip_routine_intent(self):
        self.state.save_draft(self.owner, self.fields)
        for damaged in ('broken json', 'null', '[]', '{}', '{"name":1,"address":true}'):
            with self.subTest(damaged=damaged):
                with self.state.transaction() as db:
                    db.execute('UPDATE drafts SET body=? WHERE actor=?', (damaged, self.owner))
                with self.assertRaisesRegex(ValueError, 'recovery'):
                    self.state.update_business_details(self.owner, 'Bakery', 'Changed')

    def test_noncanonical_legacy_identity_is_visible_in_migration_inventory(self):
        import json
        self.approve(self.owner)
        prepared = onboarding.prepare_business_activation(self.owner, self.fields)
        onboarding.finish_business_activation(self.owner, prepared)
        legacy = {'name': ' Test Cafe ', 'address': ' 123 Test St '}
        with self.state.transaction() as db:
            db.execute('UPDATE drafts SET body=? WHERE actor=?', (json.dumps(legacy), self.owner))
            db.execute('UPDATE business_approvals SET body=? WHERE actor=?', (json.dumps(legacy), self.owner))
        pending = self.state.pending_businesses()
        self.assertEqual(len(pending), 1)
        self.assertTrue(pending[0]['needs_submission'])
        self.assertEqual(self.state.business_owner(prepared['slug']), '')

    def test_control_corrupted_legacy_identity_requires_recovery(self):
        import json
        for character in ('\x00', '\x1f', '\x7f', '\x85'):
            with self.subTest(character=repr(character)):
                self.approve(self.owner)
                legacy = dict(self.fields, name='Fixture' + character + 'Cafe')
                with self.state.transaction() as db:
                    db.execute('UPDATE drafts SET body=? WHERE actor=?', (json.dumps(legacy), self.owner))
                    db.execute('UPDATE business_approvals SET body=? WHERE actor=?', (json.dumps(legacy), self.owner))
                pending = self.state.pending_businesses()
                self.assertEqual(len(pending), 1)
                self.assertTrue(pending[0]['needs_submission'])
                self.assertFalse(self.state.approval_covers(self.owner, legacy))

    def test_identity_review_waits_for_the_app_mutation_lock(self):
        self.state.save_draft(self.owner, self.fields)
        lock_path = self.directory / 'mutations.lock'
        waiting = threading.Event()
        original_flock = fcntl.flock
        def observed_flock(fd, operation):
            if operation == fcntl.LOCK_EX:
                waiting.set()
            return original_flock(fd, operation)
        with patch.dict('os.environ', {'TMPDIR': str(self.directory / 'private-tmp')}):
            self.assertEqual(Path(email_codes.mutation_lock_path()), lock_path)
            with lock_path.open('wb') as lock:
                original_flock(lock.fileno(), fcntl.LOCK_EX)
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    with patch('fcntl.flock', side_effect=observed_flock):
                        future = pool.submit(self.state.approve_business, self.owner, 'Reviewer', 'Checked identity', business_revision(self.state.draft(self.owner)))
                        try:
                            self.assertTrue(waiting.wait(2), 'review must request the same lock')
                            self.assertFalse(future.done(), 'review must not change identity during activation')
                        finally:
                            original_flock(lock.fileno(), fcntl.LOCK_UN)
                        future.result(timeout=2)
        self.assertTrue(self.state.business_approved(self.owner))


if __name__ == '__main__':
    unittest.main()
