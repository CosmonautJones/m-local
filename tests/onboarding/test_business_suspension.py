"""Host-only merchant status commands preserve identities and reject stale writes."""
import concurrent.futures
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.email_codes import CodeStore, business_revision
from services import email_codes


class BusinessSuspensionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.fixture_cleanup = directory.cleanup
        self.directory = Path(directory.name)
        environment = patch.dict('os.environ', {'MLOCAL_ONBOARDING_DIR': directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.now = 1000.0
        self.state = CodeStore(self.directory, clock=lambda: self.now)
        self.actor = 'a' * 32
        self.student = 'b' * 32
        self.other = 'c' * 32
        self.fields = {'name': 'Fixture Cafe', 'address': '123 Test St',
            'image_url': '/photos/fixture.png', 'menu_text': 'Soup $5'}
        self.state.remember_account(self.actor, 'owner@example.test', 'business', 'Fixture Owner')
        self.state.remember_account(self.student, 'student@example.test', 'student', 'Fixture Student')
        self.state.remember_account(self.other, 'other@example.test', 'business', 'Other Owner')
        self.state.save_draft(self.actor, self.fields)
        self.state.approve_business(self.actor, 'Fixture Reviewer', 'Verified fixture authority',
            business_revision(self.fields))
        self.slug = self.state.reserve_business(self.actor)
        self.state.activate_business(self.actor, self.fields)

    def change(self, target_status, revision=0, command='1' * 32, **overrides):
        arguments = {'actor': self.actor, 'status': target_status, 'reviewer': 'Fixture Operator',
            'note': 'Confirmed fixture complaint', 'expected_revision': revision, 'command_id': command}
        arguments.update(overrides)
        return self.state.change_business_status(**arguments)

    def snapshot(self):
        with self.state.transaction() as db:
            return {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)]
                for table in ('accounts', 'business_owners', 'business_approvals', 'business_reviews', 'drafts')}

    def test_new_status_is_active_and_changes_are_durable_without_changing_business_data(self):
        before = self.snapshot()
        self.assertEqual(self.state.business_status(self.actor),
            {'actor': self.actor, 'status': 'active', 'revision': 0})
        suspended = self.change('suspended')
        self.assertEqual(suspended['status'], 'suspended')
        self.assertEqual(suspended['revision'], 1)
        self.now += 10
        restored = self.change('active', revision=1, command='2' * 32, note='Complaint resolved')
        self.assertEqual(restored['revision'], 2)
        reopened = CodeStore(self.directory)
        self.assertEqual(reopened.business_status(self.actor),
            {'actor': self.actor, 'status': 'active', 'revision': 2})
        events = reopened.business_status_events(self.actor)
        self.assertEqual([(row['status'], row['revision'], row['at']) for row in events],
            [('suspended', 1, 1000.0), ('active', 2, 1010.0)])
        self.assertEqual(events[0]['reviewer'], 'Fixture Operator')
        self.assertEqual(events[0]['note'], 'Confirmed fixture complaint')
        self.assertEqual(self.snapshot(), before)

    def test_exact_command_retry_keeps_original_event_after_later_state_changes(self):
        first = self.change('suspended')
        self.now += 5
        self.change('active', revision=1, command='2' * 32)
        self.now += 5
        self.change('suspended', revision=2, command='3' * 32)
        self.assertEqual(self.change('suspended'), first)
        self.assertEqual(self.state.business_status(self.actor)['revision'], 3)
        self.assertEqual(len(self.state.business_status_events(self.actor)), 3)

    def test_stale_reinstatement_cannot_override_a_newer_suspension(self):
        self.change('suspended')
        self.change('suspended', revision=1, command='2' * 32, note='New complaint requires review')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.change('active', revision=1, command='3' * 32)
        self.assertEqual(self.state.business_status(self.actor),
            {'actor': self.actor, 'status': 'suspended', 'revision': 2})
        self.assertEqual(len(self.state.business_status_events(self.actor)), 2)

    def test_command_token_cannot_be_reused_for_another_payload(self):
        self.change('suspended')
        for overrides in ({'status': 'active'}, {'note': 'Different complaint'},
            {'reviewer': 'Other Operator'}, {'expected_revision': 1}, {'actor': self.other}):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, 'command'):
                self.change('suspended', **overrides)
        self.assertEqual(len(self.state.business_status_events(self.actor)), 1)

    def test_concurrent_exact_retry_creates_one_event(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.change('suspended'), range(8)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.state.business_status(self.actor)['revision'], 1)
        self.assertEqual(len(self.state.business_status_events(self.actor)), 1)

    def test_competing_commands_with_same_revision_have_one_winner(self):
        def attempt(command):
            try:
                return self.change('suspended', command=command)
            except ValueError as error:
                return str(error)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, [str(value) * 32 for value in range(1, 9)]))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertTrue(all('changed' in result for result in results if isinstance(result, str)))
        self.assertEqual(len(self.state.business_status_events(self.actor)), 1)

    def test_invalid_unapproved_unactivated_and_preprovisioned_accounts_get_no_status(self):
        for actor in ('invalid', 'd' * 32, self.student, self.other):
            with self.subTest(actor=actor):
                with self.assertRaises(ValueError):
                    self.state.business_status(actor)
                with self.assertRaises(ValueError):
                    self.change('suspended', actor=actor)
        self.state.save_draft(self.other, self.fields)
        self.state.approve_business(self.other, 'Fixture Reviewer', 'Verified fixture', business_revision(self.fields))
        self.state.reserve_business(self.other)
        with self.assertRaises(ValueError):
            self.state.business_status(self.other)
        self.assertEqual(self.state.business_status_events(self.actor), [])

    def test_configured_merchant_without_private_account_can_be_suspended_and_reinstated(self):
        actor = 'd' * 32
        with patch.dict('os.environ', {'MLOCAL_MERCHANT_OWNERS': json.dumps({'fixture-cafe': actor})}):
            self.assertEqual(self.state.business_status(actor)['revision'], 0)
            self.change('suspended', actor=actor)
            self.assertFalse(email_codes.merchant_operations_allowed(actor))
            self.change('active', actor=actor, revision=1, command='2' * 32)
            self.assertTrue(email_codes.merchant_operations_allowed(actor))
            self.assertEqual(self.state.account(actor), {})

    def test_suspension_preserves_authority_but_blocks_operations_and_public_listing(self):
        from services import qr_auth
        self.change('suspended')
        self.assertEqual(qr_auth.merchant_owner(self.slug), self.actor)
        self.assertFalse(qr_auth.merchant_operations_enabled(self.slug))
        self.assertFalse(qr_auth.listing_visible(self.slug, 'business_signup'))
        self.assertFalse(email_codes.merchant_operations_allowed(self.actor))
        self.change('active', revision=1, command='2' * 32)
        self.assertTrue(qr_auth.merchant_operations_enabled(self.slug))
        self.assertTrue(qr_auth.listing_visible(self.slug, 'business_signup'))

    def test_identity_activation_or_reapproval_cannot_clear_suspension(self):
        self.change('suspended')
        self.state.approve_business(self.actor, 'Fixture Reviewer', 'Rechecked fixture',
            business_revision(self.state.draft(self.actor)))
        with self.assertRaisesRegex(ValueError, 'suspend|paused'):
            self.state.activate_business(self.actor, self.fields)
        self.assertEqual(self.state.business_status(self.actor)['status'], 'suspended')
        self.assertEqual(len(self.state.business_status_events(self.actor)), 1)

    def test_missing_or_malformed_explicit_status_fails_closed_without_replacement(self):
        self.change('suspended')
        with self.state.transaction() as db:
            db.execute('DELETE FROM business_status WHERE actor=?', (self.actor,))
        self.assertFalse(email_codes.merchant_operations_allowed(self.actor))
        with self.assertRaisesRegex(ValueError, 'recovery'):
            self.state.business_status(self.actor)
        with self.state.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM business_status').fetchone()[0], 0)
        self.assertEqual(len(self.state.business_status_events(self.actor)), 1)

    def test_established_store_missing_both_status_tables_fails_closed_on_read(self):
        self.change('suspended')
        with self.state.transaction() as db:
            db.execute('DROP TABLE business_status')
            db.execute('DROP TABLE business_status_events')
        self.assertFalse(email_codes.merchant_operations_allowed(self.actor))
        with self.state.transaction() as db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('business_status', names)
        self.assertNotIn('business_status_events', names)

    def test_lost_private_directory_cannot_revive_a_suspended_configured_merchant(self):
        from services import qr_auth
        actor = 'd' * 32
        with patch.dict('os.environ', {'MLOCAL_MERCHANT_OWNERS': json.dumps({'fixture-cafe': actor})}):
            self.change('suspended', actor=actor)
            retained = self.directory.with_name(self.directory.name + '-retained')
            self.directory.rename(retained)
            self.addCleanup(lambda: retained.rename(self.directory) if retained.exists() else None)
            self.assertEqual(qr_auth.merchant_owner('fixture-cafe'), actor)
            self.assertFalse(email_codes.merchant_operations_allowed(actor))
            self.assertFalse(qr_auth.merchant_operations_enabled('fixture-cafe'))
            self.assertFalse(qr_auth.listing_visible('fixture-cafe', 'manual'))
            self.assertFalse(self.directory.exists())

    def test_production_store_does_not_recreate_a_lost_private_directory(self):
        self.change('suspended')
        retained = self.directory.with_name(self.directory.name + '-retained')
        self.directory.rename(retained)
        def restore():
            # A failing pre-fix run can create a replacement fixture directory.
            if self.directory.exists():
                self.fixture_cleanup()
            if retained.exists():
                retained.rename(self.directory)
        self.addCleanup(restore)
        with patch.dict('os.environ', {'MLOCAL_ENV': 'production'}):
            with self.assertRaisesRegex(ValueError, 'existing deployment'):
                email_codes.store()
        self.assertFalse(self.directory.exists())
        self.assertFalse(email_codes.merchant_operations_allowed(self.actor))

    def test_established_store_opener_does_not_recreate_missing_status_tables(self):
        self.change('suspended')
        with self.state.transaction() as db:
            db.execute('DROP TABLE business_status')
            db.execute('DROP TABLE business_status_events')
        before = self.state.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'status.*recovery'):
            CodeStore(self.directory)
        self.assertEqual(self.state.path.read_bytes(), before)

    def test_valid_legacy_v0_store_migrates_without_replacing_existing_state(self):
        before = self.snapshot()
        with self.state.transaction() as db:
            db.execute('DROP TABLE business_status')
            db.execute('DROP TABLE business_status_events')
            db.execute('PRAGMA user_version=0')
        self.assertTrue(email_codes.merchant_operations_allowed(self.actor))
        upgraded = CodeStore(self.directory)
        with upgraded.transaction() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertEqual(upgraded.business_status(self.actor),
            {'actor': self.actor, 'status': 'active', 'revision': 0})
        self.assertEqual(upgraded.key, self.state.key)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_operator_payloads_do_not_create_events(self):
        for overrides in ({'reviewer': ''}, {'reviewer': 'bad\noperator'}, {'note': ''},
            {'note': 'bad\nreason'}, {'note': 'x' * 501}, {'expected_revision': -1},
            {'expected_revision': True}, {'command_id': ''}, {'command_id': 'invalid'},
            {'status': 'approved'}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.change('suspended', **overrides)
        self.assertEqual(self.state.business_status_events(self.actor), [])

    def test_storage_failure_rolls_back_both_state_and_event(self):
        import sqlite3
        with self.state.transaction() as db:
            db.execute("CREATE TRIGGER fail_status_event BEFORE INSERT ON business_status_events "
                "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.change('suspended')
        self.assertEqual(self.state.business_status(self.actor)['revision'], 0)
        self.assertEqual(self.state.business_status_events(self.actor), [])

    def test_status_mutation_waits_for_the_shared_app_mutation_lock(self):
        import fcntl
        with (self.directory / 'mutations.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(self.change, 'suspended')
                try:
                    with self.assertRaises(concurrent.futures.TimeoutError):
                        pending.result(timeout=0.1)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                self.assertEqual(pending.result(timeout=5)['revision'], 1)

    def test_host_command_reports_current_status_and_historical_replay_receipts(self):
        project = Path(__file__).resolve().parents[2]
        def run(command, *arguments):
            return subprocess.run(['bash', 'scripts/review-business.sh', command,
                '--actor', self.actor, *arguments], cwd=project, env=dict(os.environ),
                capture_output=True, text=True, timeout=120)
        current = run('status')
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertEqual(json.loads(current.stdout)['revision'], 0)
        details = ['--revision', '0', '--command-id', '1' * 32,
            '--by', 'Fixture Operator', '--note', 'Confirmed fixture complaint']
        suspended = run('suspend', *details)
        self.assertEqual(suspended.returncode, 0, suspended.stderr)
        receipt = json.loads(suspended.stdout)
        self.assertEqual(receipt['revision'], 1)
        self.change('active', revision=1, command='2' * 32)
        replayed = run('suspend', *details)
        self.assertEqual(json.loads(replayed.stdout), receipt)
        audited = run('audit')
        self.assertEqual([row['revision'] for row in json.loads(audited.stdout)], [1, 2])
        stale = run('reinstate', '--revision', '1', '--command-id', '3' * 32,
            '--by', 'Fixture Operator', '--note', 'Complaint resolved')
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn('Business status changed', stale.stderr)
        self.assertNotIn('Traceback', stale.stdout + stale.stderr)
        self.assertEqual(self.state.business_status(self.actor)['revision'], 2)


if __name__ == '__main__':
    unittest.main()
