"""Offline release safety checks. All repositories and private state are disposable."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import tarfile
import io
import socket
import time
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_package", ROOT / "deploy/release/package.py")
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class ReleasePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Disposable Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.source / "main.jac").write_text("with entry {}\n")
        (self.source / ".jac-version").write_text("0.37.23\n")
        (self.source / "jac.toml").write_text('[project]\njac-version="0.37.23"\n')
        (self.source / "services").mkdir()
        (self.source / "services/example.py").write_text("VALUE = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.source), *args], text=True).strip()

    def bundle(self):
        destination = self.root / "bundle"
        PACKAGE.create_source_package(self.source, destination)
        return destination

    def config(self, app):
        return {"canonical_entry": str(app / "main.jac"), "durable_root": str(self.root / "state"),
                "onboarding_dir": str(self.root / "state/onboarding"),
                "native_signing_file": str(app / ".jac/data/jwt_secret"),
                "photos_dir": str(app / "assets/photos"), "backend_port": 18200,
                "gateway_port": 18201, "topology": "single-instance-serialized", "replicas": 1}

    def test_git_bound_source_and_tamper_detection(self):
        bundle = self.bundle()
        manifest = PACKAGE.verify_package(bundle)
        self.assertEqual(manifest["source_sha"], self.git("rev-parse", "HEAD"))
        self.assertEqual(manifest["source_tree"], self.git("rev-parse", "HEAD^{tree}"))
        (bundle / "source/main.jac").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "digest"):
            PACKAGE.verify_package(bundle)

    def test_dirty_source_refused_without_touching_wip(self):
        (self.source / "main.jac").write_text("user WIP")
        with self.assertRaisesRegex(ValueError, "uncommitted"):
            self.bundle()
        self.assertEqual((self.source / "main.jac").read_text(), "user WIP")
        self.assertFalse((self.root / "bundle").exists())

    def test_tracked_private_key_refused(self):
        (self.source / "code.key").write_text("do not package")
        self.git("add", "code.key")
        self.git("commit", "-qm", "private fixture")
        with self.assertRaisesRegex(ValueError, "private"):
            self.bundle()

    def test_injected_file_refused(self):
        bundle = self.bundle()
        (bundle / "source/surprise.py").write_text("unexpected")
        with self.assertRaisesRegex(ValueError, "inventory"):
            PACKAGE.verify_package(bundle)

    def test_source_switch_and_rollback_preserve_identity_photos_and_removed_sources(self):
        bundle = self.bundle()
        app = self.root / "canonical"
        (app / ".jac/data").mkdir(parents=True)
        (app / ".jac/data/jwt_secret").write_text("original signing key")
        (app / "assets/photos").mkdir(parents=True)
        (app / "assets/photos/sentinel.jpg").write_bytes(b"original photo")
        (app / "services").mkdir()
        (app / "services/removed.py").write_text("obsolete")
        PACKAGE.install_source(bundle, app)
        self.assertFalse((app / "services/removed.py").exists())
        self.assertEqual((app / ".jac/data/jwt_secret").read_text(), "original signing key")
        self.assertEqual((app / "assets/photos/sentinel.jpg").read_bytes(), b"original photo")
        (self.source / "services/example.py").write_text("VALUE = 2\n")
        self.git("add", ".")
        self.git("commit", "-qm", "next")
        next_bundle = self.root / "next"
        PACKAGE.create_source_package(self.source, next_bundle)
        PACKAGE.install_source(next_bundle, app)
        PACKAGE.install_source(bundle, app)
        self.assertEqual((app / "services/example.py").read_text(), "VALUE = 1\n")
        self.assertEqual((app / ".jac/data/jwt_secret").read_text(), "original signing key")

    def test_data_symlink_refused_before_source_mutation(self):
        bundle = self.bundle()
        app = self.root / "canonical"
        app.mkdir()
        outside = self.root / "private"
        outside.mkdir()
        (outside / "sentinel").write_text("preserve")
        try:
            (app / ".jac").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(ValueError, "symlink"):
            PACKAGE.install_source(bundle, app)
        self.assertEqual((outside / "sentinel").read_text(), "preserve")
        self.assertFalse((app / "main.jac").exists())

    def test_existing_git_checkout_with_dirty_work_is_refused(self):
        bundle = self.bundle()
        (self.source / "main.jac").write_text("uncommitted human change")
        with self.assertRaisesRegex(ValueError, "uncommitted"):
            PACKAGE.install_source(bundle, self.source)
        self.assertEqual((self.source / "main.jac").read_text(), "uncommitted human change")

    def test_private_backup_online_sqlite_and_keys_and_fresh_restore(self):
        app = self.root / "canonical"
        config = self.config(app)
        onboarding = Path(config["onboarding_dir"])
        onboarding.mkdir(parents=True)
        for name in ("onboarding.sqlite3", "photo-ownership.sqlite3"):
            with sqlite3.connect(onboarding / name) as db:
                db.execute("CREATE TABLE sentinel(value TEXT)")
                db.execute("INSERT INTO sentinel VALUES('preserve')")
        (onboarding / "code.key").write_bytes(b"original code key")
        signing = Path(config["native_signing_file"])
        signing.parent.mkdir(parents=True)
        signing.write_bytes(b"original JWT key")
        photos = Path(config["photos_dir"])
        photos.mkdir(parents=True)
        (photos / "sentinel.jpg").write_bytes(b"photo bytes")
        backup = self.root / "backup"
        PACKAGE.backup_private_state(config, backup)
        receipt = PACKAGE.verify_backup(backup)
        self.assertEqual(receipt["sqlite"]["onboarding.sqlite3"]["sentinel"], 1)
        new_app = self.root / "restored"
        restored = self.config(new_app)
        restored["onboarding_dir"] = str(self.root / "new-onboarding")
        PACKAGE.restore_private_state(backup, restored)
        self.assertEqual(Path(restored["native_signing_file"]).read_bytes(), b"original JWT key")
        self.assertEqual((Path(restored["onboarding_dir"]) / "code.key").read_bytes(), b"original code key")
        self.assertEqual((Path(restored["photos_dir"]) / "sentinel.jpg").read_bytes(), b"photo bytes")

    def test_restore_never_overwrites_existing_identity(self):
        app = self.root / "canonical"
        config = self.config(app)
        onboarding = Path(config["onboarding_dir"])
        onboarding.mkdir(parents=True)
        (onboarding / "code.key").write_bytes(b"legitimate existing identity")
        with self.assertRaisesRegex(ValueError, "existing"):
            PACKAGE.restore_private_state(self.root / "nonexistent", config)
        self.assertEqual((onboarding / "code.key").read_bytes(), b"legitimate existing identity")

    def test_topology_evidence_missing_fails_closed(self):
        bundle = self.bundle()
        app = self.root / "canonical"
        with self.assertRaisesRegex(ValueError, "runtime safety"):
            PACKAGE.require_launch_evidence(self.config(app), PACKAGE.verify_package(bundle), {})

    def test_canonical_path_mismatch_refused(self):
        config = self.config(self.root / "canonical")
        config["canonical_entry"] = str(self.root / "canonical/other.jac")
        with self.assertRaisesRegex(ValueError, "canonical"):
            PACKAGE.validate_config(config)

    def test_secret_values_never_in_inventory(self):
        config = self.config(self.root / "canonical")
        onboarding = Path(config["onboarding_dir"])
        onboarding.mkdir(parents=True)
        (onboarding / "code.key").write_bytes(b"SECRET CODE MATERIAL")
        inventory = PACKAGE.state_inventory(config, require_complete=False)
        self.assertNotIn("SECRET CODE MATERIAL", json.dumps(inventory))

    def test_dry_run_validates_links_and_never_creates_source(self):
        bundle = self.bundle()
        app = self.root / "canonical"
        PACKAGE.install_source(bundle, app, dry_run=True)
        self.assertFalse(app.exists())
        app.mkdir()
        other = self.root / "other"
        other.mkdir()
        (app / "services").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            PACKAGE.install_source(bundle, app, dry_run=True)
        self.assertFalse((app / "main.jac").exists())

    def test_exclusive_lock_prevents_overlapping_backend_or_source_switch(self):
        config = self.config(self.root / "canonical")
        Path(config["durable_root"]).mkdir()
        lock = PACKAGE.acquire_lock(config)
        self.addCleanup(os.close, lock)
        with self.assertRaisesRegex(ValueError, "still running"):
            PACKAGE.acquire_lock(config)

    def test_pg_url_password_stays_in_environment_and_options_refused(self):
        env = PACKAGE.pg_environment("postgresql://operator:SECRET_PASSWORD@localhost:15432/disposable")
        self.assertEqual(env["PGPASSWORD"], "SECRET_PASSWORD")
        self.assertEqual(env["PGDATABASE"], "disposable")
        with self.assertRaisesRegex(ValueError, "without query"):
            PACKAGE.pg_environment("postgresql://operator:SECRET_PASSWORD@localhost/db?options=unreviewed")

    def test_artifact_requires_exact_source_and_digest_receipt(self):
        artifact = self.root / "fixture.jab"
        artifact.write_bytes(b"compiled application fixture")
        receipt = self.root / "build.json"
        receipt.write_text(json.dumps({"source_sha": "wrong", "source_tree": self.git("rev-parse", "HEAD^{tree}"),
                                       "artifact_sha256": PACKAGE.digest(artifact)}))
        with self.assertRaisesRegex(ValueError, "exact source"):
            PACKAGE.create_source_package(self.source, self.root / "bad-artifact", artifact=artifact, build_receipt=receipt)

    def test_existing_recovery_database_blocks_before_restore_or_private_mutation(self):
        config = self.config(self.root / "canonical")
        manifest = {"source_sha": "fixture", "runtime": {}}
        receipt = {"source_sha": "fixture", "runtime": {}, "canonical_entry": config["canonical_entry"]}
        with patch.object(PACKAGE, "verify_recovery_set", return_value=receipt), \
             patch.object(PACKAGE, "verify_package", return_value=manifest), \
             patch.object(PACKAGE, "pg_command", return_value="17") as command, \
             patch.dict(os.environ, {"JAC_DB_URL": "postgresql://localhost/serving", "MLOCAL_RECOVERY_DB_URL": "postgresql://localhost/recovery"}):
            with self.assertRaisesRegex(ValueError, "application tables"):
                PACKAGE.coordinated_restore(self.root / "backup", config, self.root / "bundle")
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0][0], "psql")
        self.assertFalse(Path(config["onboarding_dir"]).exists())

    def test_dependency_archive_cannot_escape_into_native_signing_state(self):
        archive = self.root / "libraries.tar"
        with tarfile.open(archive, "w") as stream:
            member = tarfile.TarInfo(".jac/venv/lib/../../data/jwt_secret")
            member.size = 7
            stream.addfile(member, io.BytesIO(b"replace"))
        with self.assertRaisesRegex(ValueError, "unsupported"):
            PACKAGE.verify_dependencies(archive)

    def test_dependency_symlink_cannot_escape_into_private_state(self):
        archive = self.root / "libraries.tar"
        with tarfile.open(archive, "w") as stream:
            member = tarfile.TarInfo(".jac/client/node_modules/evil")
            member.type = tarfile.SYMTYPE
            member.linkname = "../../../data/jwt_secret"
            stream.addfile(member)
        with self.assertRaisesRegex(ValueError, "escapes"):
            PACKAGE.verify_dependencies(archive)

    def test_dependency_install_and_rollback_preserve_keys_and_safe_links(self):
        for name in PACKAGE.DEPENDENCY_ROOTS:
            path = self.source / name
            if name.endswith(".json"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"dependencies":{}}')
            else:
                path.mkdir(parents=True)
                (path / "library.js").write_text("tested library")
        (self.source / ".jac/client/node_modules/alias.js").symlink_to("library.js")
        dependency = self.root / "libraries.tar"
        PACKAGE.create_dependencies(self.source, dependency)
        build = self.root / "build.json"
        build.write_text(json.dumps({"source_sha": self.git("rev-parse", "HEAD"), "source_tree": self.git("rev-parse", "HEAD^{tree}"),
                                    "dependency_archive_sha256": PACKAGE.digest(dependency)}))
        bundle = self.root / "deps-package"
        # Installed compiler caches are ignored/private and must not be tracked.
        (self.source / ".git/info/exclude").write_text(".jac/\n")
        PACKAGE.create_source_package(self.source, bundle, dependency_archive=dependency, build_receipt=build)
        app = self.root / "canonical"
        (app / ".jac/data").mkdir(parents=True)
        (app / ".jac/data/jwt_secret").write_text("original key")
        PACKAGE.install_source(bundle, app)
        PACKAGE.install_source(bundle, app)
        self.assertEqual((app / ".jac/data/jwt_secret").read_text(), "original key")
        self.assertEqual((app / ".jac/client/node_modules/alias.js").read_text(), "tested library")

    def test_production_gateway_refuses_raw_direct_ingress_before_listener(self):
        with socket.socket() as port_source:
            port_source.bind(("127.0.0.1", 0))
            port = port_source.getsockname()[1]
        environment = os.environ.copy()
        environment.update(MLOCAL_ENV="production", MLOCAL_INGRESS="direct", PORT=str(port),
                           MLOCAL_TRUSTED_HTTPS_EDGE="1", MLOCAL_PUBLIC_INGRESS="restricted",
                           MLOCAL_DEPLOYMENT_TOPOLOGY="single-instance-serialized", MLOCAL_APP_REPLICAS="1")
        result = subprocess.run(["node", str(ROOT / "scripts/hosted-gateway.mjs")], env=environment, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Production gateway requires", result.stderr)
        with socket.socket() as probe:
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)

    def test_production_gateway_refuses_missing_explicit_edge_policy(self):
        environment = os.environ.copy()
        environment.update(MLOCAL_ENV="production", MLOCAL_INGRESS="restricted-edge", MLOCAL_TRUSTED_HTTPS_EDGE="0",
                           MLOCAL_PUBLIC_INGRESS="restricted", MLOCAL_DEPLOYMENT_TOPOLOGY="single-instance-serialized", MLOCAL_APP_REPLICAS="1")
        result = subprocess.run(["node", str(ROOT / "scripts/hosted-gateway.mjs")], env=environment, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Production gateway requires", result.stderr)

    def test_cleanup_stops_serving_descendant_after_parent_has_exited(self):
        with socket.socket() as port_source:
            port_source.bind(("127.0.0.1", 0))
            port = port_source.getsockname()[1]
        child = "import socket,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); s=socket.socket(); s.bind(('127.0.0.1'," + str(port) + ")); s.listen(); time.sleep(60)"
        parent = "import subprocess,sys; subprocess.Popen([sys.executable,'-c'," + repr(child) + "],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
        process = subprocess.Popen([sys.executable, "-c", parent], start_new_session=True)
        self.addCleanup(PACKAGE.stop_owned, [process])
        process.wait(timeout=5)
        for _ in range(50):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.02)
        else:
            self.fail("disposable child did not open its listener")
        PACKAGE.stop_owned([process])
        for _ in range(50):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) != 0:
                    break
            time.sleep(0.02)
        else:
            self.fail("serving descendant retained its listener")

    def test_occupied_backend_port_blocks_replacement_without_killing_listener(self):
        config = self.config(self.root / "canonical")
        with socket.socket() as sentinel:
            sentinel.bind(("127.0.0.1", 0))
            sentinel.listen()
            config["backend_port"] = sentinel.getsockname()[1]
            with self.assertRaisesRegex(ValueError, "occupied"):
                PACKAGE.require_free_ports(config)
            with socket.socket() as probe:
                self.assertEqual(probe.connect_ex(("127.0.0.1", config["backend_port"])), 0)


if __name__ == "__main__":
    unittest.main()
