import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "sync_source", Path(__file__).resolve().parents[2] / "scripts/sync-phone-source.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SourceSyncTests(unittest.TestCase):
    def _make_directory_link(self, link: Path, destination: Path) -> None:
        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(destination)],
                    capture_output=True,
                    text=True,
                )
                if result.returncode:
                    self.skipTest(f"directory junctions unavailable: {result.stderr.strip()}")
            else:
                link.symlink_to(destination, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"directory links unavailable: {error}")

    def test_uploaded_photos_survive_source_sync_and_source_photo_attempt_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "source", Path(folder) / "runtime"
            for root in (source, target):
                (root / "services").mkdir(parents=True)
                (root / "client").mkdir()
            (source / "main.jac").write_text("source")
            (source / "assets/brand").mkdir(parents=True)
            (source / "assets/brand/logo.png").write_text("new brand")
            (source / "assets/photos").mkdir(parents=True)
            (source / "assets/photos/source-attempt.jpg").write_text("source attempt")
            (target / "assets/brand").mkdir(parents=True)
            (target / "assets/brand/stale.png").write_text("old brand")
            (target / "assets/photos").mkdir(parents=True)
            (target / "assets/photos/uploaded.jpg").write_text("uploaded")

            module.sync(source, target)

            self.assertFalse((target / "assets/brand/stale.png").exists())
            self.assertEqual((target / "assets/brand/logo.png").read_text(), "new brand")
            self.assertEqual((target / "assets/photos/uploaded.jpg").read_text(), "uploaded")
            self.assertFalse((target / "assets/photos/source-attempt.jpg").exists())

    def test_uploaded_photos_survive_when_source_has_no_assets_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "source", Path(folder) / "runtime"
            for root in (source, target):
                (root / "services").mkdir(parents=True)
                (root / "client").mkdir()
            (source / "main.jac").write_text("source")
            (target / "assets/brand").mkdir(parents=True)
            (target / "assets/brand/stale.png").write_text("old brand")
            (target / "assets/photos").mkdir(parents=True)
            (target / "assets/photos/uploaded.jpg").write_text("uploaded")

            module.sync(source, target)

            self.assertFalse((target / "assets/brand/stale.png").exists())
            self.assertEqual((target / "assets/photos/uploaded.jpg").read_text(), "uploaded")

    def test_removed_sources_disappear_but_private_data_survives(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "source", Path(folder) / "runtime"
            for root in (source, target):
                (root / "services").mkdir(parents=True)
                (root / "client").mkdir()
            (source / "main.jac").write_text("source")
            (source / "services/current.jac").write_text("new code")
            (target / "services/removed.jac").write_text("old code")
            (target / ".jac").mkdir()
            (target / ".jac/accounts.json").write_text("private accounts")
            module.sync(source, target)
            self.assertFalse((target / "services/removed.jac").exists())
            self.assertEqual((target / "services/current.jac").read_text(), "new code")
            self.assertEqual((target / ".jac/accounts.json").read_text(), "private accounts")

    def test_symlink_source_is_rejected_before_mutating_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "source", Path(folder) / "runtime"
            for root in (source, target):
                (root / "services").mkdir(parents=True)
                (root / "client").mkdir()
            (source / "main.jac").write_text("source")
            (source / "services/escape.jac").symlink_to(Path(folder) / "private.txt")
            (target / "services/current.jac").write_text("keep live code")
            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((target / "services/current.jac").read_text(), "keep live code")

    def test_photo_symlink_is_rejected_before_mutating_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "source", Path(folder) / "runtime"
            for root in (source, target):
                (root / "services").mkdir(parents=True)
                (root / "client").mkdir()
            (source / "main.jac").write_text("source")
            (target / "services/current.jac").write_text("keep live code")
            mounted = Path(folder) / "mounted-photos"
            mounted.mkdir()
            try:
                (target / "assets").mkdir()
                (target / "assets/photos").symlink_to(mounted, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((target / "services/current.jac").read_text(), "keep live code")

    def test_source_root_link_is_rejected_before_mutating_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root, target = Path(folder), Path(folder) / "runtime"
            real_source, source = root / "real-source", root / "source-link"
            (real_source / "services").mkdir(parents=True)
            (real_source / "client").mkdir()
            (real_source / "main.jac").write_text("source")
            (target / "services").mkdir(parents=True)
            (target / "client").mkdir()
            (target / "services/current.jac").write_text("keep live code")
            try:
                source.symlink_to(real_source, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((target / "services/current.jac").read_text(), "keep live code")

    def test_target_root_link_is_rejected_before_mutating_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root, source = Path(folder), Path(folder) / "source"
            real_target, target = root / "real-runtime", root / "runtime-link"
            (source / "services").mkdir(parents=True)
            (source / "client").mkdir()
            (source / "main.jac").write_text("source")
            (real_target / "services").mkdir(parents=True)
            (real_target / "client").mkdir()
            (real_target / "services/current.jac").write_text("keep live code")
            try:
                target.symlink_to(real_target, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((real_target / "services/current.jac").read_text(), "keep live code")

    def test_source_parent_link_is_rejected_before_mutating_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root, target = Path(folder), Path(folder) / "runtime"
            real_parent, parent_link = root / "real-source-parent", root / "source-parent-link"
            real_source, source = real_parent / "checkout", parent_link / "checkout"
            (real_source / "services").mkdir(parents=True)
            (real_source / "client").mkdir()
            (real_source / "main.jac").write_text("source")
            (real_source / "services/current.jac").write_text("external source")
            (target / "services").mkdir(parents=True)
            (target / "client").mkdir()
            (target / "services/current.jac").write_text("keep live code")
            self._make_directory_link(parent_link, real_parent)

            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((target / "services/current.jac").read_text(), "keep live code")

    def test_target_parent_link_is_rejected_before_mutating_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root, source = Path(folder), Path(folder) / "source"
            real_parent, parent_link = root / "real-runtime-parent", root / "runtime-parent-link"
            real_target, target = real_parent / "runtime", parent_link / "runtime"
            (source / "services").mkdir(parents=True)
            (source / "client").mkdir()
            (source / "main.jac").write_text("source")
            (real_target / "services").mkdir(parents=True)
            (real_target / "client").mkdir()
            (real_target / "services/current.jac").write_text("keep external code")
            self._make_directory_link(parent_link, real_parent)

            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((real_target / "services/current.jac").read_text(), "keep external code")

    def test_source_nested_in_target_is_rejected_before_mutating_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root, target = Path(folder), Path(folder) / "runtime"
            source = target / "client"
            (source / "services").mkdir(parents=True)
            (source / "client").mkdir()
            (source / "main.jac").write_text("source root")
            (source / "services/current.jac").write_text("keep source code")

            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((source / "main.jac").read_text(), "source root")
            self.assertEqual((source / "services/current.jac").read_text(), "keep source code")

    def test_target_nested_in_source_is_rejected_before_mutating_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / "source", root / "source/client"
            (source / "services").mkdir(parents=True)
            (source / "client").mkdir()
            (source / "main.jac").write_text("source root")
            (source / "services/current.jac").write_text("keep source code")

            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((source / "main.jac").read_text(), "source root")
            self.assertEqual((source / "services/current.jac").read_text(), "keep source code")

    @unittest.skipUnless(sys.platform != "win32", "POSIX symlink and parent traversal regression")
    def test_source_parent_symlink_dotdot_is_rejected_before_mutating_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root, target = Path(folder), Path(folder) / "runtime"
            external_parent = root / "external-source-parent"
            linked_dir = external_parent / "linked-dir"
            parent_link = root / "source-parent-link"
            real_source, source = external_parent / "source", parent_link / ".." / "source"
            (real_source / "services").mkdir(parents=True)
            (real_source / "client").mkdir()
            (real_source / "main.jac").write_text("external source")
            (real_source / "services/current.jac").write_text("keep external source")
            (target / "services").mkdir(parents=True)
            (target / "client").mkdir()
            (target / "services/current.jac").write_text("keep live code")
            linked_dir.mkdir(parents=True, exist_ok=True)
            self._make_directory_link(parent_link, linked_dir)

            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((target / "services/current.jac").read_text(), "keep live code")

    @unittest.skipUnless(sys.platform != "win32", "POSIX symlink and parent traversal regression")
    def test_target_parent_symlink_dotdot_is_rejected_before_mutating_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root, source = Path(folder), Path(folder) / "source"
            external_parent = root / "external-target-parent"
            linked_dir = external_parent / "linked-dir"
            parent_link = root / "target-parent-link"
            real_target, target = external_parent / "runtime", parent_link / ".." / "runtime"
            (source / "services").mkdir(parents=True)
            (source / "client").mkdir()
            (source / "main.jac").write_text("source")
            (real_target / "services").mkdir(parents=True)
            (real_target / "client").mkdir()
            (real_target / "services/current.jac").write_text("keep external runtime")
            linked_dir.mkdir(parents=True, exist_ok=True)
            self._make_directory_link(parent_link, linked_dir)

            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((real_target / "services/current.jac").read_text(), "keep external runtime")

    @unittest.skipUnless(sys.platform == "win32", "Windows junction regression")
    def test_brand_junction_is_rejected_before_external_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            root, source, target = Path(folder), Path(folder) / "source", Path(folder) / "runtime"
            external = root / "external-brand"
            (source / "services").mkdir(parents=True)
            (source / "client").mkdir()
            (source / "assets/brand").mkdir(parents=True)
            (source / "main.jac").write_text("source")
            (source / "assets/brand/new.png").write_text("new brand")
            (target / "services").mkdir(parents=True)
            (target / "client").mkdir()
            (target / "services/current.jac").write_text("keep live code")
            external.mkdir()
            (external / "old.png").write_text("keep external")
            (target / "assets").mkdir()
            self._make_directory_link(target / "assets/brand", external)

            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((external / "old.png").read_text(), "keep external")
            self.assertEqual((target / "services/current.jac").read_text(), "keep live code")

    @unittest.skipUnless(sys.platform == "win32", "Windows junction regression")
    def test_nested_photo_junction_is_rejected_before_external_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            root, source, target = Path(folder), Path(folder) / "source", Path(folder) / "runtime"
            external = root / "external-photos"
            (source / "services").mkdir(parents=True)
            (source / "client").mkdir()
            (source / "main.jac").write_text("source")
            (target / "services").mkdir(parents=True)
            (target / "client").mkdir()
            (target / "services/current.jac").write_text("keep live code")
            external.mkdir()
            (external / "uploaded.jpg").write_text("keep external")
            (target / "assets/photos").mkdir(parents=True)
            self._make_directory_link(target / "assets/photos/album", external)

            with self.assertRaises(ValueError):
                module.sync(source, target)
            self.assertEqual((external / "uploaded.jpg").read_text(), "keep external")
            self.assertEqual((target / "services/current.jac").read_text(), "keep live code")


if __name__ == "__main__":
    unittest.main()
