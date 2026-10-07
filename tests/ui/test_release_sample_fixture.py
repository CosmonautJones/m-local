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
        self.environment = {"MLOCAL_RELEASE_BROWSER_FIXTURE": "1", "JAC_CACHE_HOME": str(self.cache)}

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
        for name in ("JAC_DB_URL", "JAC_DATA_PATH", "JAC_DEV_SOURCE"):
            with self.subTest(name=name):
                self.refused(dict(self.environment, **{name: "unsafe-test-override"}))

    def test_explicit_owned_private_cache_accepted_without_jac_import(self):
        with patch.object(fixture.Path, "cwd", return_value=self.app), patch.dict(os.environ, self.environment, clear=True):
            self.assertEqual(fixture.validate_fixture_store(), self.app)


if __name__ == "__main__":
    unittest.main()
