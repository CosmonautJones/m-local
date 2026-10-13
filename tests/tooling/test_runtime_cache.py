import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class RuntimeCacheTests(unittest.TestCase):
    def setUp(self):
        project = Path(__file__).resolve().parents[2]
        self.temp = tempfile.TemporaryDirectory(prefix="runtime-cache-", dir=project.parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        (self.app / "scripts").mkdir(parents=True)
        shutil.copyfile(project / "scripts/runtime.sh", self.app / "scripts/runtime.sh")
        (self.app / ".jac-version").write_text("0.37.23\n")
        self.jac = self.root / "jac"
        self.jac.write_text("#!/usr/bin/env bash\necho 'jac 0.37.23 linux'\n")
        self.jac.chmod(0o700)

    def run_runtime(self, cache):
        env = dict(os.environ, JAC_BIN=str(self.jac), JAC_CACHE_HOME=str(cache))
        return subprocess.run(["bash", "-c", "source scripts/runtime.sh"],
            cwd=self.app, env=env, capture_output=True, text=True)

    def test_external_cache_allowed(self):
        result = self.run_runtime(self.root / "cache")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_application_root_rejected(self):
        result = self.run_runtime(self.app)
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside the application", result.stderr)

    def test_nested_relative_cache_rejected(self):
        result = self.run_runtime("cache/runtime")
        self.assertEqual(result.returncode, 2)

    def test_symlink_into_application_rejected(self):
        (self.app / "cache").mkdir()
        link = self.root / "cache-link"
        link.symlink_to(self.app / "cache", target_is_directory=True)
        result = self.run_runtime(link)
        self.assertEqual(result.returncode, 2)

    def test_case_alias_into_application_rejected(self):
        alias = self.app.with_name("APP")
        if not alias.exists() or not alias.samefile(self.app):
            self.skipTest("Filesystem is case-sensitive")
        result = self.run_runtime(alias / "cache")
        self.assertEqual(result.returncode, 2)
