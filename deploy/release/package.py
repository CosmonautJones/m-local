"""Offline release packaging and preservation tools; never a provider deploy client.

Source rollback deliberately does not roll back databases. Production launch
requires separately reviewed official-runtime safety evidence and host acceptance.
Errors use fixed messages: configuration secrets and subprocess output are private.
"""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import tarfile
import time
import urllib.request
from urllib.parse import urlsplit, unquote
import posixpath

PIN = "0.37.23"
PRIVATE_NAMES = {"code.key", "jwt_secret", "onboarding.sqlite3", "photo-ownership.sqlite3"}
MANAGED = {"main.jac", "theme.jac", "jac.toml", ".jac-version", "services", "client", "data", "public", "assets", "scripts", "deploy"}
REQUIRED_CASES = {"all_rpc_serialized", "readiness_serialized", "exclusive_backend", "concurrent_claim",
                  "concurrent_redemption", "disconnect", "commit_failure", "unknown_commit",
                  "next_request_cache", "restart_convergence"}
DEPENDENCY_ROOTS = (".jac/venv/lib", ".jac/client/node_modules", ".jac/client/package.json")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(path, flags, 0o600 if private else 0o644), "w") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def reject_links(path, tree=False):
    path = Path(os.path.abspath(path))
    for current in (path, *path.parents):
        if current.is_symlink():
            raise ValueError("Paths must not contain a symlink")
    if tree and path.exists():
        for current in path.rglob("*"):
            if current.is_symlink() or not (current.is_dir() or current.is_file()):
                raise ValueError("Tree must contain only regular files and directories, without symlinks")


def reject_app_links(app):
    reject_links(app)
    if not app.exists():
        return
    for path in app.rglob("*"):
        if not path.is_symlink():
            if not (path.is_dir() or path.is_file()):
                raise ValueError("Application tree contains a nonregular file")
            continue
        relative = str(path.relative_to(app))
        allowed = next((root for root in DEPENDENCY_ROOTS if relative.startswith(root + "/")), None)
        if allowed is None or not path.resolve().is_relative_to((app / allowed).resolve()):
            raise ValueError("Application or private data paths must not contain a symlink")


def private_path(relative):
    parts = Path(relative).parts
    return any(part in {".jac", ".git", "node_modules", "venv", ".venv"} or
               part in PRIVATE_NAMES or (part.startswith(".env") and part != ".env.example") or part.endswith((".pem", ".p12", ".key"))
               for part in parts) or parts[:2] == ("assets", "photos")


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError("Git source inspection failed")
    return result.stdout


def clean_checkout(root):
    if (root / ".git").exists() and git(root, "status", "--porcelain", "--untracked-files=normal").strip():
        raise ValueError("Source has uncommitted changes; preserve and commit the intended candidate first")


def inventory(root):
    reject_links(root, tree=True)
    return {str(path.relative_to(root)): digest(path) for path in sorted(root.rglob("*")) if path.is_file()}


def dependency_member_safe(member):
    name = Path(member.name)
    allowed = any(member.name == root or member.name.startswith(root + "/") for root in DEPENDENCY_ROOTS)
    if not allowed or name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir() or member.issym()):
        raise ValueError("Dependency archive contains an unsupported path or file type")
    if any(part in PRIVATE_NAMES or part.startswith(".env") or part.endswith((".pem", ".p12", ".key")) for part in name.parts):
        raise ValueError("Dependency archive contains a private filename requiring review")
    if member.issym():
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
        if member.linkname.startswith("/") or not any(resolved == root or resolved.startswith(root + "/") for root in DEPENDENCY_ROOTS):
            raise ValueError("Dependency symlink escapes the installed library tree")


def verify_dependencies(archive):
    with tarfile.open(archive) as stream:
        seen = set()
        for member in stream.getmembers():
            dependency_member_safe(member)
            if member.name in seen:
                raise ValueError("Dependency archive has duplicate paths")
            seen.add(member.name)
        if not all(any(name == root or name.startswith(root + "/") for name in seen) for root in DEPENDENCY_ROOTS):
            raise ValueError("Dependency archive lacks tested Python, npm or generated client metadata")


def create_dependencies(source, output):
    source, output = Path(source), Path(output)
    reject_links(output)
    if output.exists():
        raise ValueError("Dependency artifact already exists")
    for name in DEPENDENCY_ROOTS:
        if not (source / name).exists():
            raise ValueError("Install/test dependencies with the pinned runtime before packaging")
    with tarfile.open(output, "w") as stream:
        def validate(member):
            dependency_member_safe(member)
            return member
        for name in DEPENDENCY_ROOTS:
            stream.add(source / name, arcname=name, filter=validate)
    verify_dependencies(output)
    return {"dependency_archive_sha256": digest(output)}


def create_source_package(source, destination, *, runtime=None, artifact=None, build_receipt=None,
                          dependency_archive=None,
                          official_checksums=None):
    source, destination = Path(source), Path(destination)
    reject_links(source)
    reject_links(destination)
    clean_checkout(source)
    if destination.exists():
        raise ValueError("Package destination already exists; never replace an evidence artifact")
    sha = git(source, "rev-parse", "HEAD").decode().strip()
    tree = git(source, "rev-parse", "HEAD^{tree}").decode().strip()
    archive = git(source, "archive", "--format=tar", sha)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source_tar:
        members = source_tar.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Source archive contains unsafe paths or symlinks")
            if private_path(path):
                raise ValueError("Tracked private data must not enter a source release")
        version = source_tar.extractfile(".jac-version").read().decode().strip()
        if version != PIN:
            raise ValueError("Release requires official Jac 0.37.23")
        destination.mkdir(mode=0o755)
        (destination / "source").mkdir()
        for member in members:
            target = destination / "source" / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source_tar.extractfile(member).read())
                target.chmod(member.mode & 0o777)
    manifest = {"schema": 1, "source_sha": sha, "source_tree": tree, "jac_version": PIN,
                "serving_mode": "source-at-fixed-canonical-entry", "topology": "single-instance-serialized",
                "launch_status": "BLOCKED_PENDING_RUNTIME_AND_HOST_ACCEPTANCE", "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "runtime": {}, "build": {}, "files": {}}
    if runtime:
        runtime = Path(runtime)
        for name in ("jac", "jacpython"):
            original = runtime / name
            reject_links(original)
            expected = (official_checksums or {}).get(name)
            if not expected or digest(original) != expected:
                raise ValueError("Official runtime checksum evidence is missing or differs")
        version = subprocess.run([str(runtime / "jac"), "--version"], capture_output=True, text=True, timeout=30)
        if version.returncode or version.stdout.split()[:2] != ["jac", PIN]:
            raise ValueError("Runtime version differs from official pinned Jac")
        (destination / "runtime").mkdir()
        for name in ("jac", "jacpython"):
            shutil.copy2(runtime / name, destination / "runtime" / name)
            manifest["runtime"][name] = digest(destination / "runtime" / name)
    if artifact:
        receipt = read_json(build_receipt) if build_receipt else {}
        artifact = Path(artifact)
        reject_links(artifact)
        artifact_sha = digest(artifact)
        if receipt.get("source_sha") != sha or receipt.get("source_tree") != tree or receipt.get("artifact_sha256") != artifact_sha:
            raise ValueError("Build receipt does not bind the artifact to this exact source")
        (destination / "artifact").mkdir()
        shutil.copy2(artifact, destination / "artifact" / artifact.name)
        write_json(destination / "artifact/build-receipt.json", {"source_sha": sha, "source_tree": tree,
                                                                "artifact_sha256": artifact_sha})
        manifest["build"] = {"artifact": str(Path("artifact") / artifact.name), "sha256": artifact_sha,
                             "dependency_files": {name: digest(destination / "source" / name) for name in
                                                  ("jac.toml", "package-lock.json", "jac.lock") if (destination / "source" / name).is_file()}}
    if dependency_archive:
        receipt = read_json(build_receipt) if build_receipt else {}
        verify_dependencies(dependency_archive)
        expected = digest(dependency_archive)
        if receipt.get("source_sha") != sha or receipt.get("source_tree") != tree or receipt.get("dependency_archive_sha256") != expected:
            raise ValueError("Dependency receipt does not bind installed libraries to this exact source")
        (destination / "dependencies").mkdir()
        shutil.copyfile(dependency_archive, destination / "dependencies/libraries.tar")
        manifest["dependencies"] = {"archive": "dependencies/libraries.tar", "sha256": expected}
    manifest["files"] = inventory(destination)
    manifest["source_files_sha256"] = hashlib.sha256(json.dumps(
        {name[7:]: value for name, value in manifest["files"].items() if name.startswith("source/")}, sort_keys=True).encode()).hexdigest()
    write_json(destination / "manifest.json", manifest)
    return manifest


def verify_package(package):
    package = Path(package)
    reject_links(package, tree=True)
    manifest = read_json(package / "manifest.json")
    actual = inventory(package)
    actual.pop("manifest.json", None)
    expected = manifest.get("files", {})
    if actual.keys() != expected.keys():
        raise ValueError("Package inventory differs")
    if actual != expected:
        raise ValueError("Package file digest differs")
    if manifest.get("schema") != 1 or manifest.get("jac_version") != PIN:
        raise ValueError("Unsupported release manifest or runtime")
    if any(private_path(Path(name).relative_to("source")) for name in expected if name.startswith("source/")):
        raise ValueError("Source package contains private data")
    return manifest


def install_source(package, app, *, dry_run=False):
    """Switch generated source only. Caller must hold the stopped-writer lock."""
    package, app = Path(package), Path(app)
    manifest = verify_package(package)
    reject_app_links(app)
    if app.exists():
        clean_checkout(app)
    if app.resolve() == package.resolve() or app.resolve() in package.resolve().parents or package.resolve() in app.resolve().parents:
        raise ValueError("Canonical application and release package must not overlap")
    source = package / "source"
    if manifest.get("dependencies"):
        verify_dependencies(package / manifest["dependencies"]["archive"])
        for name in DEPENDENCY_ROOTS:
            reject_links(app / name)
    for name in MANAGED:
        target, origin = app / name, source / name
        if target.is_dir():
            for path in target.rglob("*"):
                relative = path.relative_to(app)
                if private_path(relative) and relative.parts[:2] != ("assets", "photos"):
                    raise ValueError("Private files inside managed source require operator migration before source switching")
    if dry_run:
        return
    app.mkdir(mode=0o755, parents=True, exist_ok=True)
    # Validate every path before removing obsolete generated source.
    for name in sorted(MANAGED):
        target, origin = app / name, source / name
        if target.is_dir():
            for path in sorted(target.rglob("*"), key=lambda value: len(value.parts), reverse=True):
                if path.relative_to(app).parts[:2] == ("assets", "photos"):
                    continue
                matching = source / path.relative_to(app)
                if path.is_file() and not matching.is_file():
                    path.unlink()
                elif path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
        if origin.is_dir():
            for path in origin.rglob("*"):
                destination = app / path.relative_to(source)
                if path.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination)
        elif origin.is_file():
            shutil.copy2(origin, target)
        elif target.is_file():
            target.unlink()
    (app / ".jac").mkdir(mode=0o700, exist_ok=True)
    marker = app / ".jac/release-installed.json"
    temporary = app / ".jac/release-installed.next.json"
    write_json(temporary, {"source_sha": manifest["source_sha"], "source_tree": manifest["source_tree"],
                           "package_manifest_sha256": digest(package / "manifest.json"), "canonical_entry": str((app / "main.jac").resolve())}, private=True)
    os.replace(temporary, marker)
    if manifest.get("dependencies"):
        archive = package / manifest["dependencies"]["archive"]
        verify_dependencies(archive)
        # Only compiler dependency caches are replaced; never .jac/data or any
        # onboarding/key/photo state. Validate targets before deleting caches.
        roots = [app / name for name in DEPENDENCY_ROOTS]
        for path in roots:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.is_file():
                path.unlink()
        with tarfile.open(archive) as stream:
            stream.extractall(app, filter="data")


def validate_config(config):
    entry = Path(config.get("canonical_entry", ""))
    if not entry.is_absolute() or entry.name != "main.jac" or str(entry) != str(entry.resolve()):
        raise ValueError("Record the exact resolved canonical main.jac entry path")
    for name in ("canonical_entry", "durable_root", "onboarding_dir", "native_signing_file", "photos_dir"):
        path = Path(config.get(name, ""))
        if not path.is_absolute():
            raise ValueError("Deployment paths must be absolute")
        reject_links(path)
    if Path(config["native_signing_file"]) != entry.parent / ".jac/data/jwt_secret" or Path(config["photos_dir"]) != entry.parent / "assets/photos":
        raise ValueError("Native signing state and photos must retain their existing canonical paths")
    if config.get("topology") != "single-instance-serialized" or config.get("replicas") != 1:
        raise ValueError("Only the proposed exclusive single-instance serialized topology is supported")
    ports = [config.get("backend_port"), config.get("gateway_port")]
    if any(type(port) is not int or not 1024 <= port <= 65535 for port in ports) or ports[0] == ports[1]:
        raise ValueError("Use distinct unprivileged backend and gateway ports")
    return entry.parent


def sqlite_inventory(path):
    reject_links(path)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("Private SQLite integrity check failed")
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'") if not row[0].startswith("sqlite_")]
        return {table: db.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] for table in tables}


def state_inventory(config, require_complete=True):
    validate_config(config)
    onboarding = Path(config["onboarding_dir"])
    paths = {"onboarding.sqlite3": onboarding / "onboarding.sqlite3", "photo-ownership.sqlite3": onboarding / "photo-ownership.sqlite3",
             "code.key": onboarding / "code.key", "jwt_secret": Path(config["native_signing_file"])}
    result = {"files": {}, "sqlite": {}, "photos": {}}
    for name, path in paths.items():
        reject_links(path)
        if not path.is_file():
            if require_complete:
                raise ValueError("Existing private state is incomplete; use an audited migration, never create replacement keys")
            continue
        result["files"][name] = {"sha256": digest(path), "bytes": path.stat().st_size}
        if name.endswith(".sqlite3"):
            result["sqlite"][name] = sqlite_inventory(path)
    photos = Path(config["photos_dir"])
    reject_links(photos, tree=True)
    if require_complete and not photos.is_dir():
        raise ValueError("Existing photo volume is missing")
    if photos.exists():
        result["photos"] = inventory(photos)
    return result


def backup_private_state(config, destination):
    state_inventory(config)
    destination = Path(destination)
    reject_links(destination)
    if destination.exists():
        raise ValueError("Backup destination already exists")
    destination.mkdir(mode=0o700)
    sqlite_counts = {}
    for name in ("onboarding.sqlite3", "photo-ownership.sqlite3"):
        source = Path(config["onboarding_dir"]) / name
        target = destination / name
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(target) as copied:
            original.backup(copied)
        target.chmod(0o600)
        sqlite_counts[name] = sqlite_inventory(target)
    for name, source in (("code.key", Path(config["onboarding_dir"]) / "code.key"), ("jwt_secret", Path(config["native_signing_file"]))):
        shutil.copyfile(source, destination / name)
        (destination / name).chmod(0o600)
    shutil.copytree(config["photos_dir"], destination / "photos")
    for path in (destination / "photos").rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    receipt = {"schema": 1, "snapshot_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "canonical_entry": config["canonical_entry"], "sqlite": sqlite_counts, "files": inventory(destination),
               "scope": "quiesced private state; complete PostgreSQL dump must be recorded separately"}
    write_json(destination / "backup-manifest.json", receipt, private=True)
    return receipt


def verify_backup(backup):
    backup = Path(backup)
    reject_links(backup, tree=True)
    receipt = read_json(backup / "backup-manifest.json")
    actual = inventory(backup)
    actual.pop("backup-manifest.json", None)
    if actual != receipt.get("files"):
        raise ValueError("Recovery set checksum or inventory differs")
    for name in ("onboarding.sqlite3", "photo-ownership.sqlite3"):
        if sqlite_inventory(backup / name) != receipt["sqlite"][name]:
            raise ValueError("Recovery SQLite row inventory differs")
    return receipt


def restore_private_state(backup, config):
    validate_config(config)
    targets = [Path(config["onboarding_dir"]), Path(config["native_signing_file"]), Path(config["photos_dir"])]
    for path in targets:
        reject_links(path, tree=True)
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise ValueError("Refusing to overwrite existing private state or identity; restore into empty isolated storage")
    receipt = verify_backup(backup)
    backup = Path(backup)
    onboarding, signing, photos = targets
    onboarding.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("onboarding.sqlite3", "photo-ownership.sqlite3", "code.key"):
        shutil.copyfile(backup / name, onboarding / name)
        (onboarding / name).chmod(0o600)
    signing.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copyfile(backup / "jwt_secret", signing)
    signing.chmod(0o600)
    if photos.exists():
        photos.rmdir()
    shutil.copytree(backup / "photos", photos)
    return receipt


def pg_environment(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path.strip("/") or parsed.query or parsed.fragment:
        raise ValueError("Use an explicit PostgreSQL URL without query options; configure TLS through PostgreSQL environment settings")
    env = os.environ.copy()
    env.update(PGHOST=parsed.hostname, PGPORT=str(parsed.port or 5432), PGDATABASE=unquote(parsed.path[1:]),
               PGUSER=unquote(parsed.username or ""), PGPASSWORD=unquote(parsed.password or ""), PGCONNECT_TIMEOUT="10")
    return env


def pg_command(args, env, timeout=300):
    # URLs/passwords are never passed as process arguments, printed, or placed
    # in public receipts. PostgreSQL stderr may include private connection data.
    result = subprocess.run(args, env=env, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError("PostgreSQL backup/recovery command failed; preserve its protected operator diagnostics")
    return result.stdout.decode().strip()


def coordinated_backup(config, destination, package):
    destination = Path(destination)
    reject_links(destination)
    if destination.exists():
        raise ValueError("Backup destination already exists")
    manifest = verify_package(package)
    environment = pg_environment(os.environ.get("JAC_DB_URL", ""))
    destination.mkdir(mode=0o700)
    backup_private_state(config, destination / "private")
    dump = destination / "postgresql.dump"
    pg_command(["pg_dump", "--format=custom", "--no-owner", "--file", str(dump)], environment)
    dump.chmod(0o600)
    pg_version = pg_command(["pg_dump", "--version"], environment, timeout=10)
    receipt = {"schema": 1, "snapshot_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "canonical_entry": config["canonical_entry"], "source_sha": manifest["source_sha"],
               "source_tree": manifest["source_tree"], "runtime": manifest["runtime"],
               "package_manifest_sha256": digest(Path(package) / "manifest.json"), "pg_client_version": pg_version,
               "files": inventory(destination), "scope": "complete logical PostgreSQL dump plus quiesced SQLite, code.key, native JWT, photo ownership and JPEGs"}
    write_json(destination / "recovery-manifest.json", receipt, private=True)
    return receipt


def verify_recovery_set(backup):
    backup = Path(backup)
    reject_links(backup, tree=True)
    receipt = read_json(backup / "recovery-manifest.json")
    actual = inventory(backup)
    actual.pop("recovery-manifest.json", None)
    if actual != receipt.get("files"):
        raise ValueError("Coordinated recovery set checksum or inventory differs")
    verify_backup(backup / "private")
    return receipt


def coordinated_restore(backup, config, package):
    receipt = verify_recovery_set(backup)
    manifest = verify_package(package)
    if receipt.get("canonical_entry") != config["canonical_entry"] or receipt.get("source_sha") != manifest["source_sha"] or \
            receipt.get("runtime") != manifest["runtime"]:
        raise ValueError("Recovery requires the original canonical entry, matching source and official runtime")
    # Validate file destinations before any PostgreSQL write. Recovery does not
    # repair collisions or overwrite an existing native account store.
    for name in ("onboarding_dir", "native_signing_file", "photos_dir"):
        target = Path(config[name])
        reject_links(target, tree=True)
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError("Recovery refuses existing identity, private state or photos")
    environment = pg_environment(os.environ.get("MLOCAL_RECOVERY_DB_URL", ""))
    if environment.get("PGDATABASE") == pg_environment(os.environ.get("JAC_DB_URL", ""))["PGDATABASE"]:
        raise ValueError("Recovery database must differ from the serving database")
    count = pg_command(["psql", "--no-psqlrc", "--tuples-only", "--no-align", "--command",
                        "SELECT COUNT(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')"], environment, timeout=30)
    if count != "0":
        raise ValueError("Recovery target database contains application tables; never overwrite existing accounts")
    pg_command(["pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--dbname", environment["PGDATABASE"],
                str(Path(backup) / "postgresql.dump")], environment)
    restore_private_state(Path(backup) / "private", config)
    return receipt


def require_launch_evidence(config, manifest, evidence):
    # A queue cannot fix failed finalization. An offline package never grants
    # authority to open traffic or substitutes a patched runtime for this pin.
    runtime = evidence.get("runtime_safety", {})
    if runtime.get("verdict") != "PASS" or runtime.get("jac_version") != PIN or runtime.get("topology") != config["topology"] or \
            runtime.get("source_sha") != manifest["source_sha"] or runtime.get("jac_sha256") != manifest.get("runtime", {}).get("jac") or \
            not REQUIRED_CASES.issubset({name for name, passed in runtime.get("cases", {}).items() if passed is True}):
        raise ValueError("Launch blocked: independent official-runtime safety evidence is incomplete or does not match the candidate")
    host = evidence.get("host_acceptance", {})
    if host.get("canonical_entry") != config["canonical_entry"] or host.get("durable_storage") is not True or \
            host.get("private_backend") is not True or host.get("exclusive_ingress") is not True or host.get("nonoverlapping_rollout") is not True:
        raise ValueError("Launch blocked: canonical host, storage and exclusive ingress acceptance is incomplete")
    if evidence.get("operator_rollout_approved") is not True:
        raise ValueError("Launch blocked: Travis's explicit rollout approval has not been recorded")


def acquire_lock(config):
    root = Path(config["durable_root"])
    reject_links(root)
    if not root.is_dir():
        raise ValueError("Durable root must already be provisioned")
    lock = root / "deployment.lock"
    reject_links(lock)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ValueError("Backend or deployment operation is still running; stop it before switching source") from None
    return fd


def stop_owned(processes):
    for process in reversed(processes):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 10
    for process in reversed(processes):
        try:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        # A dead parent may have left serving descendants in its owned group.
        # Parent exit alone never proves that its listener is gone.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def require_free_ports(config):
    # A supervisor crash can release flock before its backend descendants exit.
    # Never spawn a replacement over an existing listener or unknown process.
    for port in (config["backend_port"], config["gateway_port"]):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise ValueError("Configured backend/gateway port is occupied; establish prior process termination before launch") from None


def launch(package, config, evidence):
    package = Path(package)
    app = validate_config(config)
    manifest = verify_package(package)
    require_launch_evidence(config, manifest, evidence)
    if not manifest.get("dependencies") or not manifest.get("build") or set(manifest.get("runtime", {})) != {"jac", "jacpython"}:
        raise ValueError("Launch requires the complete tested source, official runtime, build and dependency package")
    state_inventory(config)
    marker = read_json(app / ".jac/release-installed.json")
    if marker.get("package_manifest_sha256") != digest(package / "manifest.json") or marker.get("canonical_entry") != config["canonical_entry"]:
        raise ValueError("Installed source does not match this package or canonical entry")
    for name, expected in manifest["files"].items():
        relative = Path(name)
        if relative.parts[0] == "source" and relative.parts[1] in MANAGED:
            target = app.joinpath(*relative.parts[1:])
            if not target.is_file() or digest(target) != expected:
                raise ValueError("Installed candidate source digest differs")
    environment = os.environ.copy()
    if not environment.get("JAC_DB_URL", "").startswith(("postgres://", "postgresql://")):
        raise ValueError("Explicit durable PostgreSQL JAC_DB_URL is required")
    environment.update(MLOCAL_ENV="production", MLOCAL_PUBLIC_INGRESS="restricted", MLOCAL_DEPLOYMENT_TOPOLOGY="single-instance-serialized",
                       MLOCAL_APP_REPLICAS="1", MLOCAL_DURABLE_ROOT=config["durable_root"], MLOCAL_ONBOARDING_DIR=config["onboarding_dir"],
                       MLOCAL_BACKEND_PORT=str(config["backend_port"]), PORT=str(config["gateway_port"]), MLOCAL_INGRESS_EVENT_LOG="stderr")
    # Node/gateway provenance and explicit trusted edge are host capabilities.
    if environment.get("MLOCAL_INGRESS") not in {"render", "funnel", "restricted-edge"}:
        raise ValueError("Select the verified restricted HTTPS edge; production direct ingress is prohibited")
    lock = acquire_lock(config)
    processes = []
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        require_free_ports(config)
        guard = subprocess.run([str(package / "runtime/jacpython"), "-c",
                                "from services.production_guard import enforce_production_config; enforce_production_config()"],
                               cwd=app, env=environment, timeout=30, capture_output=True)
        if guard.returncode:
            raise ValueError("Production configuration guard refused startup; inspect required setting names in the protected guard check")
        # Guard is also run by Jac onboarding import. Failure of either process
        # terminates both process groups; no restart while queue outcome is unknown.
        processes.append(subprocess.Popen([str(package / "runtime/jac"), "run", str(app / "main.jac"), "--no-dev", "--host", "127.0.0.1", "--port", str(config["backend_port"])], cwd=app, env=environment, start_new_session=True))
        processes.append(subprocess.Popen(["node", str(app / "scripts/hosted-gateway.mjs")], cwd=app, env=environment, start_new_session=True))
        ready = False
        deadline = time.monotonic() + 300
        while all(process.poll() is None for process in processes) and time.monotonic() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:" + str(config["gateway_port"]) + "/healthz", timeout=5) as response:
                    ready = response.status == 200 and json.load(response).get("ready") is True
                if ready:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(1)
        if not ready:
            raise ValueError("Candidate failed meaningful gateway readiness; both process groups were stopped")
        print("Candidate reached gateway readiness; external traffic remains an operator responsibility.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise ValueError("Backend or gateway exited; both process groups were stopped")
    finally:
        stop_owned(processes)
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "make-dependencies", "verify", "inventory", "switch-source", "backup-private", "verify-backup", "restore-private", "backup", "verify-recovery", "restore", "preflight", "run"])
    parser.add_argument("--package", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--official-checksums", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--build-receipt", type=Path)
    parser.add_argument("--dependency-archive", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--acknowledge-quiesced", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    lock = None
    try:
        config = read_json(args.config) if args.config else None
        if args.action == "create":
            result = create_source_package(args.source, args.output, runtime=args.runtime, artifact=args.artifact,
                                           build_receipt=args.build_receipt, dependency_archive=args.dependency_archive,
                                           official_checksums=read_json(args.official_checksums) if args.official_checksums else None)
        elif args.action == "make-dependencies":
            result = create_dependencies(args.source, args.output)
        elif args.action == "verify":
            result = verify_package(args.package)
        elif args.action == "inventory":
            result = state_inventory(config)
        elif args.action in {"switch-source", "backup-private", "restore-private", "backup", "restore"}:
            validate_config(config)
            if not args.acknowledge_quiesced:
                raise ValueError("Close ingress and stop all graph/CLI/private-store writers, then acknowledge quiescence")
            lock = acquire_lock(config)
            if args.action == "switch-source":
                verify_package(args.package)
                install_source(args.package, Path(config["canonical_entry"]).parent, dry_run=args.dry_run)
                result = {"source_switch": "DRY_RUN" if args.dry_run else "complete", "data_changed": False}
            elif args.action == "backup-private":
                result = backup_private_state(config, args.output)
            elif args.action == "restore-private":
                result = restore_private_state(args.backup, config)
            elif args.action == "backup":
                result = coordinated_backup(config, args.output, args.package)
            else:
                result = coordinated_restore(args.backup, config, args.package)
        elif args.action == "verify-backup":
            result = verify_backup(args.backup)
        elif args.action == "verify-recovery":
            result = verify_recovery_set(args.backup)
        elif args.action == "preflight":
            validate_config(config)
            manifest = verify_package(args.package)
            state = state_inventory(config)
            require_launch_evidence(config, manifest, read_json(args.evidence) if args.evidence else {})
            result = {"preflight": "PASS", "source_sha": manifest["source_sha"], "state_inventory": state,
                      "scope": "local checks; does not certify provider state, inbox, devices, or off-host recovery"}
        else:
            launch(args.package, config, read_json(args.evidence))
            result = {"stopped": True}
        # Never print private-state digests/inventory or subprocess errors here.
        print(json.dumps({"action": args.action, "result": "PASS", "source_sha": result.get("source_sha"), "scope": result.get("scope")}))
        return 0
    except (ValueError, KeyError, OSError, sqlite3.Error, subprocess.SubprocessError) as error:
        # OS paths may contain sensitive account names. Only fixed ValueError
        # messages above are public; other diagnostic details remain local.
        print(str(error) if isinstance(error, ValueError) else "Release operation failed; inspect protected local state.", file=__import__("sys").stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if lock is not None:
            os.close(lock)


if __name__ == "__main__":
    raise SystemExit(main())
