"""Separate-process onboarding proof for one shared local directory.

Run with the pinned jacpython on Linux. Sender callbacks are disposable sinks;
this does not test SMTP, HTTP, graph identity, or independent host replication.
"""
import hashlib
import multiprocessing
import queue
import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from services.email_codes import CodeStore


def worker(directory, operation, data, start, results):
    try:
        start.wait(timeout=15)
        store = CodeStore(Path(directory), clock=lambda: data.get('now', 1000))
        if operation == 'cold':
            result = {'key_hash': hashlib.sha256(store.key).hexdigest()}
        elif operation == 'request':
            sent = []
            try:
                store.request(data['value'], 'business', 'Process fixture',
                              lambda _email, _code: sent.append(True))
                result = {'accepted': True, 'delivered': len(sent)}
            except ValueError:
                result = {'accepted': False, 'delivered': len(sent)}
        elif operation == 'consume':
            try:
                verified = store.consume(data['challenge'], data['code'])
                result = {'accepted': verified['email'] == data['email']}
            except ValueError:
                result = {'accepted': False}
        elif operation == 'save':
            store.remember_account(data['actor'], data['email'], 'business', 'Process fixture')
            store.save_draft(data['actor'], data['body'])
            result = {'saved': True}
        elif operation == 'read':
            result = {'account_matches': store.account(data['actor'])['email'] == data['email'],
                      'draft_matches': store.draft(data['actor']) == data['body']}
        else:
            raise AssertionError('Unknown fixture operation')
        results.put(result)
    except Exception as error:
        # No challenge, code, email, database content or provider error is logged.
        results.put({'failed': type(error).__name__})


class SharedOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.context = multiprocessing.get_context('fork')
        self.temporary = tempfile.TemporaryDirectory(prefix='m-local-onboarding-process-')
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def processes(self, operation, rows, directory=None):
        results = self.context.Queue()
        start = self.context.Barrier(len(rows) + 1)
        children = [self.context.Process(target=worker,
            args=(str(directory or self.directory), operation, row, start, results)) for row in rows]
        deadline = time.monotonic() + 45
        try:
            for child in children:
                child.start()
            start.wait(timeout=15)
            received = []
            for _ in children:
                try:
                    received.append(results.get(timeout=max(.01, deadline - time.monotonic())))
                except queue.Empty:
                    self.fail('A fixture process did not report within its deadline')
            for child in children:
                child.join(timeout=max(.01, deadline - time.monotonic()))
                self.assertFalse(child.is_alive(), 'A fixture process did not stop')
                self.assertEqual(child.exitcode, 0)
            self.assertFalse(any('failed' in row for row in received),
                             'A fixture process raised an unexpected exception')
            return received
        finally:
            for child in children:
                if child.pid is not None and child.is_alive():
                    child.terminate()
            for child in children:
                if child.pid is not None:
                    child.join(timeout=5)
                    if child.is_alive():
                        child.kill()
                        child.join(timeout=5)
                    self.assertFalse(child.is_alive(), 'Owned fixture process cleanup failed')
                    child.close()
            results.close()
            results.join_thread()

    def counts(self):
        with closing(sqlite3.connect(self.directory / 'onboarding.sqlite3')) as db:
            return tuple(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                         for table in ('sends', 'codes', 'accounts', 'drafts'))

    def test_concurrent_cold_processes_publish_one_complete_key_and_readable_state(self):
        rows = self.processes('cold', [{} for _ in range(8)])
        key = (self.directory / 'code.key').read_bytes()
        self.assertEqual(len(key), 32)
        self.assertEqual({row['key_hash'] for row in rows}, {hashlib.sha256(key).hexdigest()})
        self.assertEqual(list(self.directory.glob('.code-key-*')), [])
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    def test_code_requested_in_one_process_is_consumed_once_across_eight(self):
        store = CodeStore(self.directory, clock=lambda: 1000)
        codes = []
        sent = store.request('owner@example.test', 'business', 'Process fixture',
                             lambda _email, code: codes.append(code))
        data = {'challenge': sent['challenge'], 'code': codes[0], 'email': 'owner@example.test'}
        rows = self.processes('consume', [data for _ in range(8)])
        self.assertEqual(sum(row['accepted'] for row in rows), 1)
        self.assertEqual(self.counts()[:2], (1, 0))
        with self.assertRaises(ValueError):
            CodeStore(self.directory, clock=lambda: 1000).consume(sent['challenge'], codes[0])

    def test_concurrent_resends_share_one_cooldown_and_one_delivery(self):
        rows = self.processes('request', [{'value': 'owner@example.test'} for _ in range(8)])
        self.assertEqual(sum(row['accepted'] for row in rows), 1)
        self.assertEqual(sum(row['delivered'] for row in rows), 1)
        self.assertEqual(self.counts()[:2], (1, 1))

    def test_hourly_sender_budget_is_shared_across_processes(self):
        store = CodeStore(self.directory, clock=lambda: 1000)
        for index in range(58):
            store.request(f'prefill{index}@example.test', 'business', 'Process fixture',
                          lambda _email, _code: None)
        rows = self.processes('request', [{'value': f'contender{index}@example.test'} for index in range(8)])
        self.assertEqual(sum(row['accepted'] for row in rows), 2)
        self.assertEqual(sum(row['delivered'] for row in rows), 2)
        self.assertEqual(self.counts()[:2], (60, 60))

    def test_used_codes_still_share_the_per_email_hourly_budget(self):
        store = CodeStore(self.directory, clock=lambda: 1000)
        for _ in range(4):
            codes = []
            sent = store.request('owner@example.test', 'business', 'Process fixture',
                                 lambda _email, code: codes.append(code))
            store.consume(sent['challenge'], codes[0])
        rows = self.processes('request', [{'value': 'owner@example.test'} for _ in range(8)])
        self.assertEqual(sum(row['accepted'] for row in rows), 1)
        self.assertEqual(self.counts()[:2], (5, 1))
        with self.assertRaisesRegex(ValueError, 'Too many code requests'):
            CodeStore(self.directory, clock=lambda: 1061).request(
                'owner@example.test', 'business', 'Process fixture', lambda _email, _code: None)

    def test_account_and_draft_written_by_a_process_survive_its_replacement(self):
        data = {'actor': '11111111111111111111111111111111', 'email': 'owner@example.test',
                'body': {'name': 'Fictional Cafe', 'address': '123 Fixture Street'}}
        self.assertEqual(self.processes('save', [data]), [{'saved': True}])
        self.assertEqual(self.processes('read', [data]),
                         [{'account_matches': True, 'draft_matches': True}])
        self.assertEqual(self.counts()[2:], (1, 1))

    def test_copied_directories_do_not_share_new_challenges(self):
        store = CodeStore(self.directory, clock=lambda: 1000)
        replica = self.directory / 'copied-replica'
        replica.mkdir(mode=0o700)
        shutil.copyfile(self.directory / 'code.key', replica / 'code.key')
        (replica / 'code.key').chmod(0o600)
        with closing(sqlite3.connect(store.path)) as original, closing(sqlite3.connect(replica / 'onboarding.sqlite3')) as copied:
            original.backup(copied)
        (replica / 'onboarding.sqlite3').chmod(0o600)
        self.assertEqual((replica / 'code.key').read_bytes(), store.key)
        self.assertNotEqual((replica / 'onboarding.sqlite3').stat().st_ino, store.path.stat().st_ino)
        codes = []
        sent = store.request('owner@example.test', 'business', 'Process fixture',
                             lambda _email, code: codes.append(code))
        data = {'challenge': sent['challenge'], 'code': codes[0], 'email': 'owner@example.test'}
        rows = self.processes('consume', [data], replica)
        self.assertEqual(rows, [{'accepted': False}])
        self.assertEqual(self.counts()[:2], (1, 1))
        self.assertEqual(self.processes('consume', [data]), [{'accepted': True}])


if __name__ == '__main__':
    unittest.main()
