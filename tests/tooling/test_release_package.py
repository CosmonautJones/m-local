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
import getpass
import shutil
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

    def test_recorded_existing_native_data_override_is_preserved(self):
        config = self.config(self.root / "canonical")
        config["native_data_dir"] = str(self.root / "state/existing-native")
        config["native_signing_file"] = str(self.root / "state/existing-native/jwt_secret")
        self.assertEqual(PACKAGE.validate_config(config), self.root / "canonical")
        config["native_signing_file"] = str(self.root / "state/different-native/jwt_secret")
        with self.assertRaisesRegex(ValueError, "existing canonical paths"):
            PACKAGE.validate_config(config)

    def test_launcher_accepts_preserved_native_base_override(self):
        app = self.root / "canonical"
        base = self.root / "state/existing-native-base"
        config = self.config(app)
        config["native_data_dir"] = str(base / ".jac/data")
        config["native_signing_file"] = str(base / ".jac/data/jwt_secret")
        manifest = {"dependencies": {"archive": "libraries.tar"}, "build": {"artifact": "fixture.jab"},
                    "runtime": {"jac": "fixture", "jacpython": "fixture"}}
        with patch.object(PACKAGE, "verify_package", return_value=manifest), \
             patch.object(PACKAGE, "require_launch_evidence"), \
             patch.object(PACKAGE, "state_inventory"), \
             patch.object(PACKAGE, "verify_installed_source"), \
             patch.object(PACKAGE, "acquire_lock", side_effect=RuntimeError("PASSED_SIGNING_POLICY")), \
             patch.dict(os.environ, {"JAC_DB_URL": "postgresql://localhost/disposable", "JAC_DATA_PATH": str(base),
                                    "MLOCAL_INGRESS": "restricted-edge"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "PASSED_SIGNING_POLICY"):
                PACKAGE.launch(self.root / "package", config, {})

    def test_launcher_rejects_signing_directory_misused_as_native_base(self):
        app = self.root / "canonical"
        base = self.root / "state/existing-native-base"
        config = self.config(app)
        config["native_data_dir"] = str(base / ".jac/data")
        config["native_signing_file"] = str(base / ".jac/data/jwt_secret")
        manifest = {"dependencies": {"archive": "libraries.tar"}, "build": {"artifact": "fixture.jab"},
                    "runtime": {"jac": "fixture", "jacpython": "fixture"}}
        with patch.object(PACKAGE, "verify_package", return_value=manifest), \
             patch.object(PACKAGE, "require_launch_evidence"), \
             patch.object(PACKAGE, "state_inventory"), \
             patch.object(PACKAGE, "verify_installed_source"), \
             patch.object(PACKAGE, "acquire_lock", side_effect=RuntimeError("UNEXPECTED_LOCK_ATTEMPT")) as lock, \
             patch.dict(os.environ, {"JAC_DB_URL": "postgresql://localhost/disposable", "MLOCAL_INGRESS": "restricted-edge"}, clear=True):
            for index, supplied in enumerate((str(base / ".jac/data"), " " + str(base), str(base) + " ", "   ")):
                with self.subTest(supplied_index=index):
                    os.environ["JAC_DATA_PATH"] = supplied
                    with self.assertRaisesRegex(ValueError, "JAC_DATA_PATH"):
                        PACKAGE.launch(self.root / "package", self.config(app) if not supplied.strip() else config, {})
            lock.assert_not_called()

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

    def test_source_switch_cli_refuses_live_listener_after_lock_was_released(self):
        bundle = self.bundle()
        app = self.root / "canonical"
        app.mkdir()
        (app / "main.jac").write_text("serving old source")
        config = self.config(app)
        Path(config["durable_root"]).mkdir()
        with socket.socket() as sentinel:
            sentinel.bind(("127.0.0.1", 0))
            sentinel.listen()
            config["backend_port"] = sentinel.getsockname()[1]
            config_file = self.root / "config.json"
            config_file.write_text(json.dumps(config))
            result = subprocess.run([sys.executable, str(ROOT / "deploy/release/package.py"), "switch-source", "--package", str(bundle),
                                     "--config", str(config_file), "--acknowledge-quiesced"], capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"occupied", result.stderr)
            self.assertEqual((app / "main.jac").read_text(), "serving old source")
            with socket.socket() as probe:
                self.assertEqual(probe.connect_ex(("127.0.0.1", config["backend_port"])), 0)

    def test_malformed_secret_port_is_redacted(self):
        with self.assertRaisesRegex(ValueError, "format or port") as error:
            PACKAGE.pg_environment("postgresql://user:password@localhost:SECRET_PORT_MARKER/db")
        self.assertNotIn("SECRET_PORT_MARKER", str(error.exception))

    def test_backup_rejects_proposed_package_and_tampered_installed_source(self):
        bundle_a = self.bundle()
        app = self.root / "canonical"
        config = self.config(app)
        PACKAGE.install_source(bundle_a, app)
        (self.source / "main.jac").write_text("new proposed source")
        self.git("add", "main.jac")
        self.git("commit", "-qm", "new proposal")
        bundle_b = self.root / "package-b"
        PACKAGE.create_source_package(self.source, bundle_b)
        with patch.object(PACKAGE, "pg_command") as command:
            with self.assertRaisesRegex(ValueError, "marker does not match"):
                PACKAGE.coordinated_backup(config, self.root / "wrong-backup", bundle_b)
        command.assert_not_called()
        (app / "main.jac").write_text("tampered actual source")
        with self.assertRaisesRegex(ValueError, "Installed source inventory"):
            PACKAGE.verify_installed_source(bundle_a, config)

    def test_explicit_inventory_receipt_is_private_and_never_overwrites_evidence(self):
        output = self.root / "inventory.json"
        PACKAGE.write_json(output, {"private_inventory": True}, private=True)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            PACKAGE.write_json(output, {"private_inventory": False}, private=True)
        self.assertTrue(json.loads(output.read_text())["private_inventory"])

    def test_source_switch_cli_refuses_live_listener_after_supervisor_lock_release(self):
        bundle = self.bundle()
        config = self.config(self.root / "canonical")
        Path(config["durable_root"]).mkdir()
        Path(config["canonical_entry"]).parent.mkdir()
        Path(config["canonical_entry"]).write_text("old serving source")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            config["backend_port"] = listener.getsockname()[1]
            config_file = self.root / "config.json"
            config_file.write_text(json.dumps(config))
            result = subprocess.run([sys.executable, str(ROOT / "deploy/release/package.py"), "switch-source", "--package", str(bundle),
                                     "--config", str(config_file), "--acknowledge-quiesced"], capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"occupied", result.stderr)
            self.assertEqual(Path(config["canonical_entry"]).read_text(), "old serving source")
            with socket.socket() as probe:
                self.assertEqual(probe.connect_ex(("127.0.0.1", config["backend_port"])), 0)

    def test_invalid_secret_bearing_pg_port_has_fixed_redacted_cli_error(self):
        with self.assertRaisesRegex(ValueError, "format or port") as captured:
            PACKAGE.pg_environment("postgresql://operator:TOP_SECRET@localhost:PORT_SECRET/db")
        self.assertNotIn("TOP_SECRET", str(captured.exception))
        self.assertNotIn("PORT_SECRET", str(captured.exception))

    def test_backup_refuses_mislabeled_proposed_package_and_stale_source_marker(self):
        original = self.bundle()
        app = self.root / "canonical"
        config = self.config(app)
        PACKAGE.install_source(original, app)
        (self.source / "services/example.py").write_text("VALUE = 2\n")
        self.git("add", ".")
        self.git("commit", "-qm", "next candidate")
        proposed = self.root / "next-package"
        PACKAGE.create_source_package(self.source, proposed)
        with self.assertRaisesRegex(ValueError, "marker"):
            PACKAGE.coordinated_backup(config, self.root / "backup", proposed)
        self.assertFalse((self.root / "backup").exists())
        (app / "services/example.py").write_text("unrecorded mutation")
        with self.assertRaisesRegex(ValueError, "inventory or digest"):
            PACKAGE.coordinated_backup(config, self.root / "backup", original)
        self.assertFalse((self.root / "backup").exists())


@unittest.skipUnless(os.environ.get("MLOCAL_RELEASE_PG_TOOLS"), "Native logical recovery drill requires explicit disposable PostgreSQL tools")
class NativeReleaseRecoveryTests(unittest.TestCase):
    """Actual PostgreSQL logical dump/restore; synthetic identities, never live users.

    Run explicitly with MLOCAL_RELEASE_PG_TOOLS pointing to official tools. This
    proves the package's data-preservation procedure, not Jac transaction safety,
    authenticated graph recovery or hosted durability (those have separate gates).
    """
    setUp = ReleasePackageTests.setUp
    git = ReleasePackageTests.git
    bundle = ReleasePackageTests.bundle
    config = ReleasePackageTests.config

    def test_native_logical_recovery_and_offline_dependency_activation(self):
        tools_root = Path(os.environ["MLOCAL_RELEASE_PG_TOOLS"])
        binary = tools_root / "usr/lib/postgresql/16/bin"
        self.assertTrue((binary / "pg_dump").is_file())
        with tempfile.TemporaryDirectory(prefix="m-local-release-proof-", dir="/var/tmp") as stage_name:
            stage = Path(stage_name)
            stage.chmod(0o700)
            cluster = stage / "pgdata"
            socket_dir = stage / "socket"
            socket_dir.mkdir(mode=0o700)
            with socket.socket() as port_source:
                port_source.bind(("127.0.0.1", 0))
                port = port_source.getsockname()[1]
            environment = os.environ.copy()
            environment.update(PATH=str(binary) + ":" + environment.get("PATH", ""),
                               LD_LIBRARY_PATH=str(tools_root / "usr/lib/x86_64-linux-gnu"),
                               PGHOST="127.0.0.1", PGPORT=str(port), PGUSER=getpass.getuser())
            def command(*args):
                result = subprocess.run(args, env=environment, capture_output=True, text=True, timeout=60)
                if result.returncode:
                    self.fail("Disposable PostgreSQL command failed: " + result.stderr[-1200:])
                return result.stdout.strip()
            command(str(binary / "initdb"), "-D", str(cluster), "--auth=trust", "--no-locale",
                    "--encoding=UTF8", "-L", str(tools_root / "usr/share/postgresql/16"))
            command(str(binary / "pg_ctl"), "-D", str(cluster), "-l", str(stage / "postgres.log"),
                    "-o", "-h 127.0.0.1 -p " + str(port) + " -k " + str(socket_dir), "-w", "start")
            try:
                command(str(binary / "createdb"), "release_source")
                command(str(binary / "createdb"), "release_recovery")
                sql = ("CREATE TABLE native_identity(actor TEXT PRIMARY KEY, signing_binding BYTEA);"
                       "INSERT INTO native_identity VALUES('synthetic-merchant',decode('aabbcc','hex')),('synthetic-student',decode('ddeeff','hex'));"
                       "CREATE TABLE native_graph(id TEXT PRIMARY KEY, payload BYTEA);"
                       "INSERT INTO native_graph VALUES('synthetic-held',decode('0011ff','hex')),('synthetic-redeemed',decode('0022ee','hex'));"
                       "CREATE TABLE native_outbox(id INT PRIMARY KEY, delivered BOOLEAN); INSERT INTO native_outbox VALUES(1,false);")
                command(str(binary / "psql"), "-d", "release_source", "-v", "ON_ERROR_STOP=1", "-c", sql)
                bundle = self.bundle()
                app = stage / "canonical"
                config = self.config(app)
                config["durable_root"] = str(stage)
                config["onboarding_dir"] = str(stage / "onboarding")
                PACKAGE.install_source(bundle, app)
                onboarding = Path(config["onboarding_dir"])
                onboarding.mkdir(mode=0o700)
                for name in ("onboarding.sqlite3", "photo-ownership.sqlite3"):
                    with sqlite3.connect(onboarding / name) as db:
                        db.execute("CREATE TABLE preserved(value TEXT)")
                        db.execute("INSERT INTO preserved VALUES('synthetic original identity')")
                (onboarding / "code.key").write_bytes(b"c" * 32)
                signing = Path(config["native_signing_file"])
                signing.parent.mkdir(parents=True)
                signing.write_bytes(b"j" * 48)
                photos = Path(config["photos_dir"])
                photos.mkdir(parents=True)
                (photos / "original.jpg").write_bytes(b"synthetic JPEG sentinel")
                before = PACKAGE.state_inventory(config)
                source_url = "postgresql://" + getpass.getuser() + "@127.0.0.1:" + str(port) + "/release_source"
                restore_url = "postgresql://" + getpass.getuser() + "@127.0.0.1:" + str(port) + "/release_recovery"
                with patch.dict(os.environ, {**environment, "JAC_DB_URL": source_url, "MLOCAL_RECOVERY_DB_URL": restore_url}):
                    backup = stage / "backup"
                    receipt = PACKAGE.coordinated_backup(config, backup, bundle)
                    self.assertEqual(receipt["source_sha"], self.git("rev-parse", "HEAD"))
                    self.assertTrue(receipt["installed_source_verified"]["source_inventory_verified"])
                    self.assertEqual(PACKAGE.state_inventory(config), before)
                    PACKAGE.verify_recovery_set(backup)
                    # Preserve every original disposable component, then restore
                    # to empty targets at the same canonical entry path.
                    onboarding.rename(stage / "preserved-onboarding")
                    signing.rename(stage / "preserved-jwt")
                    photos.rename(stage / "preserved-photos")
                    PACKAGE.coordinated_restore(backup, config, bundle)
                    restored = PACKAGE.state_inventory(config)
                    self.assertEqual(restored["sqlite"], before["sqlite"])
                    self.assertEqual(restored["photos"], before["photos"])
                    for name in ("code.key", "jwt_secret"):
                        self.assertEqual(restored["files"][name], before["files"][name])
                    for name in ("onboarding.sqlite3", "photo-ownership.sqlite3"):
                        self.assertEqual(restored["files"][name]["sha256"], PACKAGE.digest(backup / "private" / name))
                        with sqlite3.connect(stage / "preserved-onboarding" / name) as original, sqlite3.connect(onboarding / name) as recovered:
                            self.assertEqual(original.execute("SELECT * FROM preserved").fetchall(), recovered.execute("SELECT * FROM preserved").fetchall())
                    for table in ("native_identity", "native_graph", "native_outbox"):
                        query = "SELECT row_to_json(t)::text FROM (SELECT * FROM " + table + " ORDER BY 1) t"
                        self.assertEqual(command(str(binary / "psql"), "-d", "release_source", "-Atc", query),
                                         command(str(binary / "psql"), "-d", "release_recovery", "-Atc", query))
                    self.assertEqual((stage / "preserved-jwt").read_bytes(), b"j" * 48)
                    with self.assertRaisesRegex(ValueError, "existing"):
                        PACKAGE.coordinated_restore(backup, config, bundle)
                runtime = Path(os.environ.get("JAC_BIN", str(Path.home() / ".local/share/m-local/runtimes/0.37.23/jac")))
                runtime_package = stage / "official-package"
                (runtime_package / "runtime").mkdir(parents=True)
                (runtime_package / "runtime/jacpython").symlink_to(Path(str(runtime) + "python"))
                with patch.dict(os.environ, {"PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}):
                    PACKAGE.prepare_venv(runtime_package, app)
                    cfg = app / ".jac/venv/pyvenv.cfg"
                    self.assertTrue(cfg.is_file())
                    library = app / ".jac/venv/lib/python3.14/site-packages/release_sentinel.py"
                    library.parent.mkdir(parents=True, exist_ok=True)
                    library.write_text("VALUE = 'retained offline dependency'\n")
                    code = ("from pathlib import Path; from jaclang.project.pyvenv import ensure_venv; "
                            "ensure_venv(Path.cwd()/'.jac/venv'); "
                            "assert (Path.cwd()/'.jac/venv/lib/python3.14/site-packages/release_sentinel.py').is_file()")
                    result = subprocess.run([str(runtime_package / "runtime/jacpython"), "-c", code], cwd=app,
                                            env=os.environ.copy(), capture_output=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stderr[-1000:].decode(errors="replace"))
                    self.assertEqual(PACKAGE.state_inventory(config), restored)
            finally:
                command(str(binary / "pg_ctl"), "-D", str(cluster), "-m", "fast", "-w", "stop")
                with socket.socket() as stopped:
                    self.assertNotEqual(stopped.connect_ex(("127.0.0.1", port)), 0)


if __name__ == "__main__":
    unittest.main()
