"""Private browser diagnostics must not become credential-bearing CI artifacts."""
import ast
import json
from pathlib import Path
import re
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch


class ReleaseExperienceDiagnosticsTests(unittest.TestCase):
    def test_readiness_exports_only_fixed_categories_and_numeric_measurements(self):
        source = Path(__file__).with_name("release_experience_live.py")
        definition = next(node for node in ast.parse(source.read_text()).body
                          if isinstance(node, ast.FunctionDef) and node.name == "readiness_diagnostic_summary")
        namespace = {"json": json}
        exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), "exec"), namespace)
        private = "PRIVATE-IDENTITY-TOKEN-AND-STORE-SENTINEL"
        attempts = [{"label": "gateway-samples-restored", "seconds": 300.5, "attempts": 80,
                     "statuses": {"503": 79, private: 1},
                     "categories": {"client_timeout": 1, private: 1}, "message": private},
                    {"label": private, "attempts": 1, "seconds": 1}]
        probe = {"gateway_stopped_before_native_probe": True, "native_health": {"status": 200, "ready": True, "seconds": .2, "body": private},
                 "native_feed": {"status": 200, "ok": True, "shape_valid": True, "seconds": 7.5, "body": private}}
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "gateway-samples-restored.log").write_text("\n".join([
                json.dumps({"kind": "mlocal_ingress_failure", "code": "UPSTREAM_DEADLINE", "route": "readiness", "status": 503, "message": private}),
                json.dumps({"kind": "mlocal_ingress_failure", "code": private, "route": "readiness", "status": 503}),
                private]))
            exported = namespace["readiness_diagnostic_summary"](workspace, attempts, probe)
        self.assertNotIn(private, json.dumps(exported))
        self.assertEqual(exported["attempts"][0]["statuses"], {"503": 79})
        self.assertEqual(exported["attempts"][0]["categories"], {"client_timeout": 1})
        self.assertEqual(exported["gateway_events"]["gateway-samples-restored"], {"UPSTREAM_DEADLINE": 1})
        self.assertTrue(exported["post_failure"]["gateway_stopped_before_native_probe"])
        self.assertEqual(exported["post_failure"]["native_feed"], {"status": 200, "seconds": 7.5, "ok": True, "shape_valid": True})

    def test_private_messages_and_credentials_are_not_exported(self):
        source = Path(__file__).with_name("release_experience_live.py")
        definition = next(node for node in ast.parse(source.read_text()).body
                          if isinstance(node, ast.FunctionDef) and node.name == "qr_diagnostic_summary")
        namespace = {"json": json, "re": re, "subprocess": subprocess}
        exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), "exec"), namespace)
        private = "PRIVATE-QR-AND-NATIVE-TOKEN-SENTINEL"
        merchant = {"state_text": "No readable claim QR was found. " + private,
                    "errors": [private], "csp": [private], "merchant_visibility": private,
                    "student_visibility": "visible",
                    "resolve": [{"status": 200, "ok": private, "message": private}],
                    "assets": [{"path": "/static/assets/index-fixture.js", "status": 200,
                                "content_type": "text/javascript " + private},
                               {"path": "/private/" + private + ".js", "status": 403,
                                "content_type": private}]}
        with tempfile.TemporaryDirectory() as directory, patch.dict("sys.modules", {"PIL": types.SimpleNamespace(Image=None)}):
            exported = namespace["qr_diagnostic_summary"](Path(directory), merchant)
        self.assertNotIn(private, json.dumps(exported))
        self.assertEqual(exported["state_category"], "image_decode_failed")
        self.assertEqual(exported["resolve"], [{"status": 200, "ok": None}])
        self.assertEqual(exported["assets"], [{"path": "/static/assets/index-fixture.js", "status": 200, "javascript": True}])


if __name__ == "__main__":
    unittest.main()
