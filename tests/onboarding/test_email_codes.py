import concurrent.futures
import json
import secrets
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from services.email_codes import CodeStore, account_email


class EmailCodeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.now = 1000
        self.sent = []
        self.store = CodeStore(Path(self.directory.name), clock=lambda: self.now)

    def tearDown(self):
        self.directory.cleanup()

    def send(self, email, code):
        self.sent.append((email, code))

    def request(self, value='fixture', kind='student'):
        return self.store.request(value, kind, 'Fixture Person', self.send)

    def test_student_address_is_built_server_side(self):
        self.assertEqual(account_email('  AbC123 ', 'student'), 'abc123@umich.edu')
        for value in ('person@gmail.com', 'a@umich.edu', 'a+tag', 'a\nBcc:x', '', 'äbc'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                account_email(value, 'student')
        self.assertEqual(account_email('Owner@Example.com', 'business'), 'owner@example.com')
        with self.assertRaises(ValueError):
            account_email('owner@example.com', 'admin')

    def test_no_account_or_code_leak_before_verified(self):
        result = self.request()
        code = self.sent[0][1]
        self.assertEqual(self.sent[0][0], 'fixture@umich.edu')
        self.assertRegex(code, r'^\d{6}$')
        self.assertNotIn(code, json.dumps(result))
        self.assertNotIn(code.encode(), (Path(self.directory.name) / 'onboarding.sqlite3').read_bytes())
        verified = self.store.consume(result['challenge'], code)
        self.assertEqual(verified['email'], 'fixture@umich.edu')
        self.assertEqual(verified['kind'], 'student')
        with self.assertRaises(ValueError):
            self.store.consume(result['challenge'], code)

    def test_expiry_and_wrong_attempt_limit(self):
        result = self.request()
        wrong = '000000' if self.sent[0][1] != '000000' else '000001'
        for _ in range(5):
            with self.assertRaises(ValueError):
                self.store.consume(result['challenge'], wrong)
        with self.assertRaises(ValueError):
            self.store.consume(result['challenge'], self.sent[0][1])
        self.now += 61
        result = self.request()
        self.now += 601
        with self.assertRaises(ValueError):
            self.store.consume(result['challenge'], self.sent[-1][1])

    def test_resend_cooldown_new_code_and_hourly_limit(self):
        first = self.request()
        old_code = self.sent[-1][1]
        with self.assertRaises(ValueError):
            self.request()
        for _ in range(4):
            self.now += 61
            self.request()
        with self.assertRaises(ValueError):
            self.store.consume(first['challenge'], old_code)
        self.now += 61
        with self.assertRaises(ValueError):
            self.request()

    def test_used_code_allows_a_fresh_request_right_away_within_the_hourly_limit(self):
        for _ in range(5):
            sent = self.request()
            self.assertEqual(self.store.consume(sent['challenge'], self.sent[-1][1])['email'], 'fixture@umich.edu')
            self.now += 1
        self.assertEqual(len(self.sent), 5)
        with self.assertRaises(ValueError) as refused:
            self.request()
        self.assertIn('Too many code requests', str(refused.exception))
        self.assertEqual(len(self.sent), 5)

    def test_unused_code_still_blocks_a_second_request_for_a_minute(self):
        first = self.request()
        with self.assertRaises(ValueError):
            self.store.consume(first['challenge'], '000000' if self.sent[-1][1] != '000000' else '111111')
        self.now += 30
        with self.assertRaises(ValueError) as refused:
            self.request()
        self.assertIn('wait 60 seconds', str(refused.exception))
        self.assertEqual(len(self.sent), 1)

    def test_delivery_failure_never_creates_a_usable_challenge(self):
        def failed(email, code):
            raise OSError('private provider diagnostic')
        with self.assertRaisesRegex(ValueError, 'could not send'):
            self.store.request('fixture', 'student', 'Name', failed)
        self.assertEqual(self.store.pending_count(), 0)

    def test_concurrent_consumption_has_exactly_one_winner(self):
        result = self.request()
        def attempt(_):
            try:
                return self.store.consume(result['challenge'], self.sent[0][1])['email']
            except ValueError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, range(8)))
        self.assertEqual(outcomes.count('fixture@umich.edu'), 1)

    def test_concurrent_cold_start_never_observes_a_partial_sign_in_key(self):
        started, release = threading.Event(), threading.Event()
        generation_lock = threading.Lock()
        first_generation = True
        original = secrets.token_bytes
        def generate(size):
            nonlocal first_generation
            with generation_lock:
                wait = first_generation
                first_generation = False
            if wait:
                started.set()
                if not release.wait(10):
                    raise TimeoutError('Key generation fixture was not released')
            return original(size)
        with tempfile.TemporaryDirectory() as directory, patch('services.email_codes.secrets.token_bytes', generate):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(CodeStore, Path(directory))
                self.assertTrue(started.wait(10))
                second = pool.submit(CodeStore, Path(directory))
                try:
                    ready = second.result(timeout=10)
                finally:
                    release.set()
                resumed = first.result(timeout=10)
                self.assertEqual(len(ready.key), 32)
                self.assertEqual(ready.key, resumed.key)
                self.assertEqual((Path(directory) / 'code.key').read_bytes(), ready.key)
                self.assertEqual(list(Path(directory).glob('.code-key-*')), [])


if __name__ == '__main__':
    unittest.main()
