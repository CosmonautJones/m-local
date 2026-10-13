"""Recovery readback rejects lost suspension history without repeating transitions."""
import contextlib
import copy
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


source = Path(__file__).resolve().parents[1] / 'integration' / 'recovery_http.py'
spec = importlib.util.spec_from_file_location('recovery_fixture', source)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryApprovalContractTests(unittest.TestCase):
    def setUp(self):
        self.approval = dict(actor='owner', student_actor='student', token='owner-token',
            student_token='student-token', offer='original-offer', name='Fixture Cafe', photo='/fixture.jpg',
            business_status=dict(actor='owner', status='active', revision=2),
            business_events=[dict(status='suspended', revision=1, note='Complaint'),
                             dict(status='active', revision=2, note='Reviewed resolution')],
            held=dict(my_claim_id='original-claim', my_title='Saved lunch', my_price_cents=500,
                      my_terms='Original terms', my_eligibility='Original ID', my_expires_ts=1000))
        self.status = copy.deepcopy(self.approval['business_status'])
        self.events = copy.deepcopy(self.approval['business_events'])
        self.owner_session = dict(actor_id='owner', role='merchant', merchant_paused=False)
        self.history = {**self.approval['held'], 'my_status': 'redeemed', 'my_qr_payload': ''}
        self.calls = []

    def verify(self):
        fixture = self
        class Client:
            def __init__(self, origin, token=''):
                self.origin, self.token = origin, token

            def call(self, name, **arguments):
                fixture.calls.append((self.token, name))
                if name == 'current_session':
                    return fixture.owner_session if self.token == 'owner-token' else dict(actor_id='student')
                if name == 'get_offer':
                    return fixture.history
                if name == 'get_business_profile':
                    return dict(name='Fixture Cafe', image_url='/fixture.jpg')
                if name == 'merchant_portal':
                    return dict(offers=[dict(id='original-offer', offer_image_url='/fixture.jpg')])
                raise AssertionError('Readback must not repeat mutation: ' + name)

        state = SimpleNamespace(business_status=lambda actor: fixture.status,
            business_status_events=lambda actor: fixture.events, business_approved=lambda actor: True)
        checks = []
        with patch.object(recovery, 'Api', Client), patch.object(recovery, 'fetch_photo', return_value=b'\xff\xd8fixture'), contextlib.redirect_stdout(io.StringIO()):
            recovery.verify_active_approval(SimpleNamespace(origin='fixture'), state, self.approval, checks, 'test')
        return checks

    def test_repeated_restore_and_restart_readback_preserves_audit_and_spent_claim_without_mutation(self):
        before = copy.deepcopy((self.status, self.events, self.history))
        for _ in range(2):
            self.assertEqual(len(self.verify()), 8)
        self.assertEqual((self.status, self.events, self.history), before)
        self.assertTrue(all(name in {'current_session', 'get_offer', 'get_business_profile', 'merchant_portal'}
                            for _, name in self.calls))

    def test_restore_must_retain_explicit_reinstatement_revision(self):
        for status in (dict(actor='owner', status='suspended', revision=1),
                       dict(actor='owner', status='active', revision=3)):
            with self.subTest(status=status):
                self.status = status
                with self.assertRaisesRegex(AssertionError, 'exact suspension'):
                    self.verify()

    def test_restore_must_retain_original_suspension_reason_and_history(self):
        for events in (self.events[1:], [dict(status='suspended', revision=1, note='Changed reason'), self.events[1]]):
            with self.subTest(events=events):
                self.events = events
                with self.assertRaisesRegex(AssertionError, 'exact suspension'):
                    self.verify()

    def test_restore_must_not_remap_merchant_or_leave_operations_paused(self):
        for field, value in (('actor_id', 'replacement'), ('merchant_paused', True), ('role', 'business')):
            with self.subTest(field=field):
                self.owner_session = dict(actor_id='owner', role='merchant', merchant_paused=False)
                self.owner_session[field] = value
                with self.assertRaisesRegex(AssertionError, 'original active merchant'):
                    self.verify()

    def test_restore_must_not_revive_spent_qr_or_change_promised_snapshot(self):
        for field, value in (('my_status', 'claimed'), ('my_qr_payload', 'revived-qr'),
                             ('my_claim_id', 'replacement'), ('my_price_cents', 900),
                             ('my_terms', 'Changed terms'), ('my_expires_ts', 2000)):
            with self.subTest(field=field):
                self.history = {**self.approval['held'], 'my_status': 'redeemed', 'my_qr_payload': ''}
                self.history[field] = value
                with self.assertRaisesRegex(AssertionError, 'spent claim'):
                    self.verify()


if __name__ == '__main__':
    unittest.main()
