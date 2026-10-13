"""The offline fixture must refuse shared persistence before importing Jac."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("release_sample_fixture", Path(__file__).with_name("release_sample_fixture.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class SampleFixtureGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="m-local-release-browser.guard-", dir="/var/tmp")
        self.workspace = Path(self.temporary.name)
        self.app, self.cache = self.workspace / "app", self.workspace / "cache"
        self.app.mkdir(mode=0o700)
        self.cache.mkdir(mode=0o700)
        (self.app / '.jac').mkdir(mode=0o700)
        self.onboarding = self.app / '.jac/onboarding'
        self.environment = {"MLOCAL_RELEASE_BROWSER_FIXTURE": "1", "JAC_CACHE_HOME": str(self.cache),
                            "MLOCAL_ONBOARDING_DIR": str(self.onboarding)}

    def tearDown(self):
        self.temporary.cleanup()

    def refused(self, environment):
        original_import = __import__
        def guarded_import(name, *args, **kwargs):
            if name.startswith("jaclang"):
                raise AssertionError("Jac imported before refusing unsafe persistence")
            return original_import(name, *args, **kwargs)
        with patch.object(fixture.Path, "cwd", return_value=self.app), patch.dict(os.environ, environment, clear=True), patch("builtins.__import__", guarded_import):
            with self.assertRaisesRegex(RuntimeError, "Sample fixture refuses"):
                fixture.main()

    def test_missing_cache_refused_before_jac_import(self):
        self.refused({"MLOCAL_RELEASE_BROWSER_FIXTURE": "1"})

    def test_wrong_cache_refused_before_jac_import(self):
        self.refused(dict(self.environment, JAC_CACHE_HOME=str(Path.home() / ".cache/m-local")))

    def test_symlink_cache_refused_before_jac_import(self):
        alias = self.workspace / "cache-alias"
        alias.symlink_to(self.cache, target_is_directory=True)
        self.refused(dict(self.environment, JAC_CACHE_HOME=str(alias)))

    def test_non_private_cache_refused_before_jac_import(self):
        self.cache.chmod(0o755)
        self.refused(self.environment)

    def test_non_private_workspace_refused_before_jac_import(self):
        self.workspace.chmod(0o755)
        self.refused(self.environment)

    def test_foreign_directory_owner_refused_before_jac_import(self):
        with patch.object(fixture.os, "geteuid", return_value=os.geteuid() + 1):
            self.refused(self.environment)

    def test_external_persistence_overrides_refused_before_jac_import(self):
        for name in ("JAC_DB_URL", "JAC_DATA_PATH", "JAC_DEV_SOURCE", "JACPATH"):
            with self.subTest(name=name):
                self.refused(dict(self.environment, **{name: "unsafe-test-override"}))

    def test_explicit_owned_private_cache_accepted_without_jac_import(self):
        with patch.object(fixture.Path, "cwd", return_value=self.app), patch.dict(os.environ, self.environment, clear=True):
            self.assertEqual(fixture.validate_fixture_store(), self.app)

    def test_wrong_or_missing_onboarding_directory_refused_before_jac_import(self):
        for value in ('', str(self.workspace / 'external-onboarding'), 'relative-onboarding'):
            with self.subTest(value=value):
                self.refused(dict(self.environment, MLOCAL_ONBOARDING_DIR=value))

    def test_symlink_onboarding_store_refused_before_jac_import(self):
        other = self.workspace / 'external-onboarding'
        other.mkdir(mode=0o700)
        self.onboarding.symlink_to(other, target_is_directory=True)
        self.refused(self.environment)
        self.assertEqual(list(other.iterdir()), [])

    def test_symlink_onboarding_database_refused_without_external_writes(self):
        self.onboarding.mkdir(mode=0o700)
        other = self.workspace / 'external-database'
        other.write_bytes(b'untouched fixture database')
        (self.onboarding / 'onboarding.sqlite3').symlink_to(other)
        self.refused(self.environment)
        self.assertEqual(other.read_bytes(), b'untouched fixture database')

    def test_missing_private_store_is_initialized_at_the_declared_owned_path(self):
        from services.email_codes import CodeStore
        with patch.object(fixture.Path, 'cwd', return_value=self.app), patch.dict(os.environ, self.environment, clear=True):
            state = fixture.initialize_fixture_onboarding(CodeStore)
            self.assertEqual(state.directory, self.onboarding)
            self.assertEqual(len((self.onboarding / 'code.key').read_bytes()), 32)
            with state.transaction() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0], 0)

    def test_existing_private_store_keeps_key_account_and_suspension_history(self):
        from services.email_codes import CodeStore, business_revision
        with patch.object(fixture.Path, 'cwd', return_value=self.app), patch.dict(os.environ, self.environment, clear=True):
            state = CodeStore(self.onboarding)
            actor = 'a' * 32
            state.remember_account(actor, 'owner@example.test', 'business', 'Fixture Owner')
            fields = {'name': 'Fixture Cafe', 'address': '123 Test St'}
            state.save_draft(actor, fields)
            state.approve_business(actor, 'Fixture reviewer', 'Fictional authority', business_revision(fields))
            state.reserve_business(actor)
            state.activate_business(actor, fields)
            state.change_business_status(actor, 'suspended', 'Fixture operator', 'Fixture complaint', 0, '1' * 32)
            key, account = state.key, state.account(actor)
            status, events = state.business_status(actor), state.business_status_events(actor)
            initialized = fixture.initialize_fixture_onboarding(CodeStore)
            self.assertEqual(initialized.key, key)
            self.assertEqual(initialized.account(actor), account)
            self.assertEqual(initialized.business_status(actor), status)
            self.assertEqual(initialized.business_status_events(actor), events)


if __name__ == "__main__":
    unittest.main()
