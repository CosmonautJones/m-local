import ast
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit


source = Path(__file__).parents[1] / "ui" / "release_experience_live.py"
definition = next(node for node in ast.parse(source.read_text()).body
                  if isinstance(node, ast.FunctionDef) and node.name == "scanner_chunk")
namespace = {"re": re, "urlsplit": urlsplit}
exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), "exec"), namespace)
scanner_chunk = namespace["scanner_chunk"]


class ReleaseExperienceAssetTests(unittest.TestCase):
    def test_recognizes_current_and_legacy_scanner_chunks(self):
        for prefix in ("/assets/", "/static/assets/", "/static/assets/assets/"):
            for name in ("esm-Dn3JhgMT.js", "index-D8Cg41Nt.js"):
                with self.subTest(prefix=prefix, name=name):
                    self.assertTrue(scanner_chunk("https://fixture.invalid" + prefix + name))
        self.assertTrue(scanner_chunk("https://fixture.invalid/static/assets/esm-Dn3JhgMT.js?v=1"))

    def test_does_not_count_unrelated_javascript_or_non_bundle_paths(self):
        for path in ("/static/client.js", "/client.Dn3JhgMT.js", "/assets/app-Dn3JhgMT.js",
                     "/assets/unrelated.js", "/assets/esm-.js", "/assets/esm-Dn3JhgMT.js.map",
                     "/assets/esm-Dn3JhgMT.css", "/private/esm-Dn3JhgMT.js",
                     "/assets/nested/assets/esm-Dn3JhgMT.js", "/assets/../esm-Dn3JhgMT.js"):
            with self.subTest(path=path):
                self.assertFalse(scanner_chunk("https://fixture.invalid" + path))


if __name__ == "__main__":
    unittest.main()
