"""CLI policy regressions using disposable Git inventories, never app stores."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPORTER = Path(os.environ.get("MLOCAL_COMPOSITION_TEST_REPORTER",
                              Path(__file__).resolve().parents[2] / "scripts/check-jac-share.py"))


class SourceCompositionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="source-composition-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Disposable fixture")
        self.git("config", "user.email", "fixture@example.test")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root)

    def commit(self, files):
        for name, contents in files.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Disposable inventory")
        return self.git("rev-parse", "HEAD").decode().strip()

    def report(self, revision="HEAD"):
        # Official jacpython requires explicit Python execution, not a filename
        # that its launcher may interpret as a Jac entry point.
        runner = "import runpy,sys; path=sys.argv.pop(1); runpy.run_path(path,run_name='__main__')"
        return subprocess.run([sys.executable, "-c", runner, str(REPORTER), "--ref", revision],
                              cwd=self.root, capture_output=True, text=True, timeout=30)

    def test_low_jac_share_is_informational(self):
        jac = b"with entry { }\n"
        python = b"# disposable test tooling\n" * 100
        self.commit({"app.jac": jac, "tests/tooling.py": python})
        result = self.report()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["policy"], "informational")
        self.assertLess(report["jac_percent"], 40)
        self.assertEqual(report["language_bytes"], {"Jac": len(jac), "Python": len(python)})
        self.assertNotIn("required_percent", report)

    def test_accounting_uses_selected_git_blobs_and_keeps_tools(self):
        files = {"app.jac": b"with entry { }\n", "tests/check.py": b"# test\n",
                 "scripts/run.sh": b"#!/bin/sh\n", "client/ui.jsx": b"// client\n",
                 "client/ui.ts": b"// types\n", "client/generated.d.ts": b"ignored\n",
                 "README.md": b"ignored documentation\n"}
        revision = self.commit(files)
        self.commit({"app.jac": b"with entry { print('later commit'); }\n",
                     "tests/later.py": b"# later inventory\n"})
        (self.root / "app.jac").write_bytes(b"uncommitted checkout bytes\n" * 100)
        result = self.report(revision)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        expected = {"Jac": len(files["app.jac"]), "Python": len(files["tests/check.py"]),
                    "Shell": len(files["scripts/run.sh"]), "JavaScript": len(files["client/ui.jsx"]),
                    "TypeScript": len(files["client/ui.ts"])}
        self.assertEqual(report["revision"], revision)
        self.assertEqual(report["language_bytes"], expected)
        self.assertEqual(report["total_bytes"], sum(expected.values()))

    def test_no_counted_source_is_a_zero_share_report(self):
        self.commit({"README.md": b"fixture\n"})
        result = self.report()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["language_bytes"], {})
        self.assertEqual(report["total_bytes"], 0)
        self.assertEqual(report["jac_percent"], 0)

    def test_invalid_revision_fails_without_an_inventory_report(self):
        self.commit({"app.jac": b"with entry { }\n"})
        result = self.report("refs/heads/not-a-real-fixture-branch")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
