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
