"""An inbox challenge is not authority to remove or relink native identities."""
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from pathlib import Path

from services.email_codes import CodeStore
from services.onboarding_support import finish_account


class PreservedUsers:
    def __init__(self, user):
        self.user = user
        self.deleted = []
        self.created = []
        self.tokens = []

    def find_user_by_identity(self, email):
        return self.user

    def delete_user(self, user_id):
        self.deleted.append(user_id)
        return {"error": "fixture refuses destructive repair"}

    def create_user_with_identities(self, **params):
        self.created.append(params)
        raise AssertionError("Collision must not create a replacement identity")

    def create_jwt_token(self, user_id):
        self.tokens.append(user_id)
        return 'fixture-runtime-token'


class IdentityPreservationTests(unittest.TestCase):
    def test_unverified_native_identity_without_onboarding_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            state = CodeStore(Path(directory))
            user = {'user_id': 'legitimate-native', 'root_id': 'a' * 32,
                    'role': 'user', 'status': 'active', 'profile': {},
                    'identities': [{'type': 'email', 'value_normalized': 'fixture@umich.edu', 'verified': False}]}
            users = PreservedUsers(user)
            key = state.key
            proof = dict(email='fixture@umich.edu', kind='student', name='Inbox owner')
            def attempt(_):
                with self.assertRaisesRegex(ValueError, 'original sign-in|host'):
                    finish_account(proof, users, state)
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(attempt, range(8)))
            self.assertEqual(users.deleted, [], 'Missing onboarding must never authorize native deletion')
            self.assertEqual(users.created, [])
            self.assertEqual(users.tokens, [])
            self.assertEqual(state.key, key)
            self.assertEqual(state.account('a' * 32), {})

    def test_foreign_sso_admin_suspended_and_provisioned_accounts_are_preserved(self):
        variants = [
            dict(role='admin'), dict(status='suspended'),
            dict(profile={'sso': 'external-identity'}), dict(profile={'mlocal_provision': 'unknown-marker'}),
            dict(identities=[{'type': 'oidc', 'value_normalized': 'fixture@umich.edu', 'verified': True}]),
        ]
        with tempfile.TemporaryDirectory() as directory:
            state = CodeStore(Path(directory))
            for variant in variants:
                user = {'user_id': 'preserved', 'root_id': 'a' * 32, 'role': 'user', 'status': 'active',
                        'identities': [{'type': 'email', 'value_normalized': 'fixture@umich.edu', 'verified': False}],
                        **variant}
                users = PreservedUsers(user)
                with self.subTest(variant=variant), self.assertRaises(ValueError):
                    finish_account(dict(email='fixture@umich.edu', kind='student', name='New'), users, state)
                self.assertEqual(users.deleted, [])
                self.assertEqual(users.created, [])


if __name__ == '__main__':
    unittest.main()
