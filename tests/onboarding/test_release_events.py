"""Private fixed-category operational events; no request or exception content."""
from contextlib import redirect_stderr
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.email_codes import CodeStore


class ReleaseEventTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.now = 100000
        self.store = CodeStore(Path(self.directory.name), clock=lambda: self.now)
        self.enabled = patch.dict(os.environ, {'MLOCAL_DOMAIN_EVENT_LOG': 'stderr'})
        self.enabled.start()

    def tearDown(self):
        self.enabled.stop()
        self.directory.cleanup()

    def observer(self):
        try:
            module = importlib.import_module('services.release_events')
        except ModuleNotFoundError:
            module = None
        self.assertIsNotNone(module, 'the server-only fixed-category observer is missing')
        return module

    def events(self, output):
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        for event in events:
            self.assertEqual(event['kind'], 'mlocal_domain_event')
            self.assertIsInstance(event['time'], (int, float))
        return events

    def seed_attempts(self, hourly, daily):
        with self.store.transaction() as db:
            rows = [('private-fixture@example.test', self.now - 1)] * hourly
            rows += [('private-fixture@example.test', self.now - 3601)] * (daily - hourly)
            db.executemany('INSERT INTO sends VALUES (?,?)', rows)

    def test_actual_delivery_failure_has_fixed_event_and_preserves_unusable_challenge(self):
        output = io.StringIO()
        private = []
        def reject(email, code):
            private.extend([email, code, 'private-smtp-password', 'PRIVATE PROVIDER EXCEPTION'])
            raise OSError('PRIVATE PROVIDER EXCEPTION: private-smtp-password ' + email + ' ' + code)
        with redirect_stderr(output), self.assertRaisesRegex(ValueError, 'could not send'):
            self.store.request('fixture', 'student', 'PRIVATE PERSON', reject)
        self.assertEqual(self.store.pending_count(), 0)
        events = self.events(output)
        self.assertEqual(len(events), 1, 'SMTP failure must be visible despite HTTP-200 friendly errors')
        self.assertEqual(events[0]['code'], 'SMTP_DELIVERY_FAILED')
        self.assertEqual(events[0]['operation'], 'email_delivery')
        self.assertEqual(set(events[0]), {'kind', 'time', 'operation', 'code'})
        for value in [*private, 'PRIVATE PERSON']:
            self.assertNotIn(value, output.getvalue())

    def test_quota_warning_uses_existing_durable_attempt_counts(self):
        self.seed_attempts(47, 239)
        output = io.StringIO()
        with redirect_stderr(output):
            result = self.store.request('newfixture', 'student', 'PRIVATE NAME', lambda email, code: None)
        self.assertTrue(result['ok'])
        events = self.events(output)
        self.assertEqual(len(events), 1, 'crossing 80% headroom must emit an aggregate warning')
        self.assertEqual(events[0]['code'], 'MAIL_QUOTA_NEAR')
        self.assertEqual(events[0]['hourly_attempts'], 48)
        self.assertEqual(events[0]['daily_attempts'], 240)
        self.assertEqual(events[0]['hourly_limit'], 60)
        self.assertEqual(events[0]['daily_limit'], 300)
        self.assertNotIn('private-fixture', output.getvalue())
        self.assertNotIn(result['challenge'], output.getvalue())

    def test_reached_global_quota_event_does_not_change_admission(self):
        self.seed_attempts(60, 300)
        output = io.StringIO()
        with redirect_stderr(output), self.assertRaisesRegex(ValueError, 'busy'):
            self.store.request('newfixture', 'student', 'PRIVATE NAME', lambda email, code: self.fail('quota allowed a send'))
        self.assertEqual(self.store.pending_count(), 0)
        events = self.events(output)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['code'], 'MAIL_QUOTA_REACHED')
        self.assertEqual(events[0]['hourly_attempts'], 60)
        self.assertEqual(events[0]['daily_attempts'], 300)

    def test_operation_failures_are_fixed_categories_and_success_is_silent(self):
        observer = self.observer()
        output = io.StringIO()
        with redirect_stderr(output):
            for operation in ('email_request', 'claim', 'redeem'):
                observer.record_outcome(operation, True)
                observer.record_outcome(operation, False)
        events = self.events(output)
        self.assertEqual([e['operation'] for e in events], ['email_request', 'claim', 'redeem'])
        self.assertTrue(all(e['code'] == 'OPERATION_FAILED' for e in events))
        self.assertTrue(all(set(e) == {'kind', 'time', 'operation', 'code'} for e in events))

    def test_unapproved_operation_and_non_boolean_outcome_cannot_enter_logs(self):
        observer = self.observer()
        output = io.StringIO()
        with redirect_stderr(output):
            observer.record_outcome('PRIVATE EMAIL token=SECRET QR=PRIVATE', False)
            observer.record_outcome('claim', 'PRIVATE ERROR')
            observer.record_outcome('claim', 0)
        self.assertEqual(output.getvalue(), '')

    def test_quota_events_are_bounded_and_invalid_counts_are_silent(self):
        observer = self.observer()
        output = io.StringIO()
        with redirect_stderr(output):
            observer.record_mail_quota(1000000, 1000000000)
            observer.record_mail_quota(-1, 240)
            observer.record_mail_quota(True, 300)
            observer.record_mail_quota('private', 300)
        events = self.events(output)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['hourly_attempts'], 60)
        self.assertEqual(events[0]['daily_attempts'], 300)

    def test_observer_is_disabled_unless_exact_stderr_setting(self):
        observer = self.observer()
        for setting in ('', '1', 'file:PRIVATE', 'STDERR'):
            with self.subTest(setting=setting), patch.dict(os.environ, {'MLOCAL_DOMAIN_EVENT_LOG': setting}):
                output = io.StringIO()
                with redirect_stderr(output):
                    observer.record_outcome('claim', False)
                    observer.record_mail_failure()
                    observer.record_mail_quota(60, 300)
                self.assertEqual(output.getvalue(), '')

    def test_sink_failure_does_not_change_success_or_failure_behavior(self):
        observer = self.observer()
        class BrokenSink:
            def write(self, value):
                raise OSError('PRIVATE SINK FAILURE')
            def flush(self):
                raise OSError('PRIVATE SINK FAILURE')
        with redirect_stderr(BrokenSink()):
            observer.record_outcome('claim', False)
            observer.record_mail_failure()
            observer.record_mail_quota(60, 300)
            success = self.store.request('newfixture', 'student', 'PRIVATE NAME', lambda email, code: None)
            self.assertTrue(success['ok'])
            def failed(email, code):
                raise OSError('PRIVATE SMTP FAILURE')
            with self.assertRaisesRegex(ValueError, 'could not send'):
                self.store.request('secondfixture', 'student', 'PRIVATE NAME', failed)
        self.assertEqual(self.store.pending_count(), 1)


if __name__ == '__main__':
    unittest.main()
