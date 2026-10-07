"""External store/source overrides must be refused before a native subprocess."""
import importlib.util
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("release_experience_preflight", Path(__file__).with_name("release_experience_live.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class ReleaseExperiencePreflightTests(unittest.TestCase):
    def test_external_overrides_refused_before_runtime_subprocess(self):
        browser = ModuleType("playwright.sync_api")
        browser.sync_playwright, browser.expect = None, None
        arguments = ["release_experience_live.py", "--source", str(fixture.ROOT),
                     "--gateway-repo", str(fixture.ROOT), "--gateway-ref", "fixture-test",
                     "--evidence", "/var/tmp/unused-refused-browser-evidence"]
        for name in ("JAC_DB_URL", "JAC_DATA_PATH", "JAC_DEV_SOURCE", "JACPATH"):
            with self.subTest(name=name), patch.dict(sys.modules, {"playwright.sync_api": browser}), \
                    patch.object(sys, "argv", arguments), \
                    patch.dict(os.environ, {"JAC_BIN": "/var/tmp/unused-runtime", name: "unsafe-test-override"}, clear=True), \
                    patch.object(fixture.subprocess, "check_output", side_effect=AssertionError("Runtime subprocess reached before override refusal")) as runtime:
                with self.assertRaisesRegex(RuntimeError, "without inherited live database/source overrides"):
                    fixture.main()
                runtime.assert_not_called()

    def test_bash_wrapper_refuses_overrides_before_runtime_invocation(self):
        with tempfile.TemporaryDirectory(prefix="m-local-browser-preflight-", dir="/var/tmp") as temporary:
            workspace = Path(temporary)
            source = workspace / "source"
            for relative in ("tests/ui", "scripts"):
                (source / relative).mkdir(parents=True)
            for relative in ("tests/ui/run-release-experience-live.sh", "scripts/runtime.sh", ".jac-version"):
                (source / relative).write_bytes((fixture.ROOT / relative).read_bytes().replace(b"\r\n", b"\n"))
            marker = workspace / "runtime-called"
            runtime = workspace / "forbidden-runtime"
            runtime.write_text("#!/usr/bin/env bash\ntouch '" + str(marker) + "'\nexit 91\n")
            runtime.chmod(0o700)
            for name in ("JAC_DB_URL", "JAC_DATA_PATH", "JAC_DEV_SOURCE", "JACPATH"):
                with self.subTest(name=name):
                    marker.unlink(missing_ok=True)
                    environment = {"PATH": os.environ["PATH"], "HOME": str(workspace),
                                   "JAC_BIN": str(runtime), name: "unsafe-test-override"}
                    result = subprocess.run(["bash", str(source / "tests/ui/run-release-experience-live.sh"),
                        "unused-refused-candidate", str(workspace / "unused-evidence")],
                        env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("without inherited graph/source overrides", result.stderr)
                    self.assertFalse(marker.exists(), "Wrapper invoked a runtime before refusing the inherited override")


if __name__ == "__main__":
    unittest.main()
