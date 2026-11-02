import importlib.util
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("jachammer_stage", ROOT / "scripts" / "jachammer-stage.py")
stage_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage_module)


class TransformTests(unittest.TestCase):
    def setUp(self):
        self.original = (ROOT / "jac.toml").read_bytes().decode("utf-8")
        self.staged = tomllib.loads(stage_module.transform(self.original))
        self.before = tomllib.loads(self.original)

    def test_entry_and_kind_move_to_the_explicit_app(self):
        self.assertNotIn("entry-point", self.staged["project"])
        self.assertNotIn("kind", self.staged["project"])
        app = self.staged["apps"]["m-local"]
        self.assertEqual(app["entry-point"], self.before["project"]["entry-point"])
        self.assertEqual(app["kind"], self.before["project"]["kind"])

    def test_single_serialized_replica_without_autoscaling_or_overlap(self):
        scale = self.staged["apps"]["m-local"]["scale"]
        self.assertEqual((scale["replicas"], scale["workers"], scale["threads"]), (1, 1, 1))
        self.assertFalse(scale["hpa"]["enabled"])
        rolling = scale["deployment_overlay"]["spec"]["strategy"]["rollingUpdate"]
        self.assertEqual(rolling, {"maxSurge": 0, "maxUnavailable": 1})

    def test_private_state_and_photos_are_on_persistent_volumes(self):
        volumes = {v["name"]: v for v in self.staged["scale"]["gateway"]["shared_volumes"]}
        self.assertEqual(volumes["mlocal-state"]["mount_path"], "/srv/m-local")
        self.assertEqual(volumes["mlocal-photos"]["mount_path"], "/app/assets/photos")
        for volume in volumes.values():
            self.assertEqual(volume["apps"], ["m-local"])
            self.assertEqual(volume["access_mode"], "ReadWriteOnce")

    def test_python_pins_move_to_pypi_unchanged(self):
        self.assertEqual(self.staged["dependencies"]["pypi"], {
            k: v for k, v in self.before["dependencies"].items() if isinstance(v, str)})
        self.assertEqual(self.staged["dependencies"]["npm"], self.before["dependencies"]["npm"])
        self.assertFalse([k for k, v in self.staged["dependencies"].items() if isinstance(v, str)])

    def test_everything_else_is_preserved(self):
        for key in ("serve", "jachammer", "byllm", "jacpack"):
            self.assertEqual(self.staged.get(key), self.before.get(key))
        self.assertEqual(self.staged["project"]["jac-version"], self.before["project"]["jac-version"])
        self.assertFalse(self.staged["scale"]["admin"]["enabled"])

    def test_only_the_intended_lines_change_and_endings_are_kept(self):
        staged = stage_module.transform(self.original)
        block = "".join(line + "\n" for line in stage_module.APP_BLOCK)
        self.assertIn(block, staged)
        expected = [line for line in self.original.splitlines(keepends=True)
                    if line.strip().replace(" ", "") not in ('entry-point="main"', 'kind="web-app"')]
        expected = [line.replace("[dependencies]", "[dependencies.pypi]", 1) if line.strip() == "[dependencies]" else line
                    for line in expected]
        self.assertEqual(staged.replace(block, "", 1), "".join(expected))

    def test_refuses_an_already_transformed_file(self):
        with self.assertRaises(stage_module.StageError):
            stage_module.transform(stage_module.transform(self.original))

    def test_refuses_an_unexpected_layout(self):
        with self.assertRaises(stage_module.StageError):
            stage_module.transform(self.original.replace('entry-point = "main"', 'entry-point = "app"'))


class StageTests(unittest.TestCase):
    def test_stages_only_tracked_runtime_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            def git(*args):
                subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
            git("init", "-q")
            git("config", "user.email", "t@example.test")
            git("config", "user.name", "t")
            (repo / "jac.toml").write_bytes((ROOT / "jac.toml").read_bytes())
            (repo / "main.jac").write_text("with entry {}\n")
            for rel in ("docs/big.mp4", "tests/t.py", "services/a.jac"):
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text("x")
            git("add", ".")
            git("commit", "-q", "-m", "init")
            (repo / ".jac").mkdir()
            (repo / ".jac" / "code.key").write_bytes(b"private")
            (repo / "untracked.txt").write_text("nope")
            target = Path(tmp) / "out"
            stage_module.stage(repo, target)
            staged = sorted(str(p.relative_to(target)) for p in target.rglob("*") if p.is_file())
            self.assertEqual(staged, [".jachammer-source-revision", "jac.toml", "main.jac", "services/a.jac"])
            self.assertIn("apps", tomllib.loads((target / "jac.toml").read_text()))

    def test_refuses_uncommitted_tracked_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.email", "t@example.test"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.name", "t"], check=True)
            (repo / "jac.toml").write_bytes((ROOT / "jac.toml").read_bytes())
            subprocess.run(["git", "-C", tmp, "add", "."], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", "init"], check=True)
            (repo / "jac.toml").write_text("changed")
            with self.assertRaises(stage_module.StageError):
                stage_module.stage(repo, repo / "out")


if __name__ == "__main__":
    unittest.main()
