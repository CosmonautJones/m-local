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
import tomllib
import urllib.request
from urllib.parse import urlsplit, unquote
import posixpath
import re

PIN = "0.37.23"
PRIVATE_NAMES = {"code.key", "jwt_secret", "onboarding.sqlite3", "photo-ownership.sqlite3"}
MANAGED = {"main.jac", "theme.jac", "jac.toml", ".jac-version", "services", "client", "data", "public", "assets", "scripts", "deploy"}
REQUIRED_CASES = {"all_rpc_serialized", "readiness_serialized", "exclusive_backend", "concurrent_claim",
                  "concurrent_redemption", "disconnect", "commit_failure", "unknown_commit",
                  "next_request_cache", "restart_convergence"}
DEPENDENCY_ROOTS = (".jac/venv/lib", ".jac/client/node_modules", ".jac/client/configs/package.json")
# Reviewed public trust material from the tested dependency inventory. Exact
# bytes are required: a filename or PEM label cannot establish public content.
PUBLIC_DEPENDENCY_PEMS = {
    ".jac/venv/lib/python3.14/site-packages/certifi/cacert.pem": "9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f",
    ".jac/venv/lib/python3.14/site-packages/pip/_vendor/certifi/cacert.pem": "bbc7e9c01d7551bb8a159b5dedd989b8ee3ce105aff522b68eb1b01bf854cab0",
    ".jac/venv/lib/python3.14/site-packages/botocore/cacert.pem": "ed93d6346236d4f0278f617f5245091f37d001806a49ce42ce0ad5bec858d28e",
    ".jac/venv/lib/python3.14/site-packages/litellm/proxy/auth/public_key.pem": "02cd2f76b5167a06c3c2195a22138a18e3c5c5b7fb141dc752d21f240e32c677",
}


class ReleaseError(ValueError):
    """Fixed, public diagnostic written by this tool; never a raw input error."""


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
            raise ReleaseError("Paths must not contain a symlink")
    if tree and path.exists():
        for current in path.rglob("*"):
            if current.is_symlink() or not (current.is_dir() or current.is_file()):
                raise ReleaseError("Tree must contain only regular files and directories, without symlinks")


def reject_app_links(app):
    reject_links(app)
    if not app.exists():
        return
    for path in app.rglob("*"):
        if not path.is_symlink():
            if not (path.is_dir() or path.is_file()):
                raise ReleaseError("Application tree contains a nonregular file")
            continue
        relative = str(path.relative_to(app))
        # The runtime creates interpreter links in its disposable venv metadata.
        # They are never copied from the dependency artifact or followed during
        # source/data removal. Library links must still stay inside that cache.
        if relative.startswith(".jac/venv/bin/") and not path.is_dir():
            continue
        if relative == ".jac/venv/lib64" and path.resolve() == (app / ".jac/venv/lib").resolve():
            continue
        allowed = next((root for root in DEPENDENCY_ROOTS if relative.startswith(root + "/")), None)
        if allowed is None or not path.resolve().is_relative_to((app / allowed).resolve()):
            raise ReleaseError("Application or private data paths must not contain a symlink")


def private_path(relative):
    parts = Path(relative).parts
    return any(part in {".jac", ".git", "node_modules", "venv", ".venv"} or
               part in PRIVATE_NAMES or (part.startswith(".env") and part != ".env.example") or part.endswith((".pem", ".p12", ".key"))
               for part in parts) or parts[:2] == ("assets", "photos")


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode:
        raise ReleaseError("Git source inspection failed")
    return result.stdout


def clean_checkout(root):
    if (root / ".git").exists() and git(root, "status", "--porcelain", "--untracked-files=normal").strip():
        raise ReleaseError("Source has uncommitted changes; preserve and commit the intended candidate first")


def inventory(root):
    reject_links(root, tree=True)
    return {str(path.relative_to(root)): digest(path) for path in sorted(root.rglob("*")) if path.is_file()}


def dependency_member_safe(member):
    name = Path(member.name)
    allowed = any(member.name == root or member.name.startswith(root + "/") for root in DEPENDENCY_ROOTS)
    if not allowed or name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir() or member.issym()):
        raise ReleaseError("Dependency archive contains an unsupported path or file type")
    reviewed_public = member.name in PUBLIC_DEPENDENCY_PEMS and member.isfile()
    if not reviewed_public and any(part in PRIVATE_NAMES or part.startswith(".env") or part.endswith((".pem", ".p12", ".key")) for part in name.parts):
        raise ReleaseError("Dependency archive contains a private filename requiring review")
    if member.issym():
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
        if member.linkname.startswith("/") or not any(resolved == root or resolved.startswith(root + "/") for root in DEPENDENCY_ROOTS):
            raise ReleaseError("Dependency symlink escapes the installed library tree")


def verify_dependencies(archive):
    with tarfile.open(archive) as stream:
        seen = set()
        for member in stream.getmembers():
            dependency_member_safe(member)
            if member.name in seen:
                raise ReleaseError("Dependency archive has duplicate paths")
            seen.add(member.name)
            if member.name in PUBLIC_DEPENDENCY_PEMS:
                if member.size > 1024 * 1024 or hashlib.sha256(stream.extractfile(member).read()).hexdigest() != PUBLIC_DEPENDENCY_PEMS[member.name]:
                    raise ReleaseError("Public dependency trust material differs from its reviewed fingerprint")
        if not all(any(name == root or name.startswith(root + "/") for name in seen) for root in DEPENDENCY_ROOTS):
            raise ReleaseError("Dependency archive lacks tested Python, npm or generated client metadata")


def create_dependencies(source, output):
    source, output = Path(source), Path(output)
    reject_links(output)
    if output.exists():
        raise ReleaseError("Dependency artifact already exists")
    for name in DEPENDENCY_ROOTS:
        if not (source / name).exists():
            raise ReleaseError("Install/test dependencies with the pinned runtime before packaging")
    with tarfile.open(output, "w") as stream:
        def validate(member):
            dependency_member_safe(member)
            if member.name in PUBLIC_DEPENDENCY_PEMS and digest(source / member.name) != PUBLIC_DEPENDENCY_PEMS[member.name]:
                raise ReleaseError("Public dependency trust material differs from its reviewed fingerprint")
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
        raise ReleaseError("Package destination already exists; never replace an evidence artifact")
    sha = git(source, "rev-parse", "HEAD").decode().strip()
    tree = git(source, "rev-parse", "HEAD^{tree}").decode().strip()
    archive = git(source, "archive", "--format=tar", sha)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source_tar:
        members = source_tar.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ReleaseError("Source archive contains unsafe paths or symlinks")
            if private_path(path):
                raise ReleaseError("Tracked private data must not enter a source release")
        version = source_tar.extractfile(".jac-version").read().decode().strip()
        if version != PIN:
            raise ReleaseError("Release requires official Jac 0.37.23")
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
                raise ReleaseError("Official runtime checksum evidence is missing or differs")
        version = subprocess.run([str(runtime / "jac"), "--version"], capture_output=True, text=True, timeout=30)
        if version.returncode or version.stdout.split()[:2] != ["jac", PIN]:
            raise ReleaseError("Runtime version differs from official pinned Jac")
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
            raise ReleaseError("Build receipt does not bind the artifact to this exact source")
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
            raise ReleaseError("Dependency receipt does not bind installed libraries to this exact source")
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
        raise ReleaseError("Package inventory differs")
    if actual != expected:
        raise ReleaseError("Package file digest differs")
    if manifest.get("schema") != 1 or manifest.get("jac_version") != PIN:
        raise ReleaseError("Unsupported release manifest or runtime")
    if any(private_path(Path(name).relative_to("source")) for name in expected if name.startswith("source/")):
        raise ReleaseError("Source package contains private data")
    return manifest


def install_source(package, app, *, dry_run=False):
    """Switch generated source only. Caller must hold the stopped-writer lock."""
    package, app = Path(package), Path(app)
    manifest = verify_package(package)
    reject_app_links(app)
    if app.exists():
        clean_checkout(app)
    if app.resolve() == package.resolve() or app.resolve() in package.resolve().parents or package.resolve() in app.resolve().parents:
        raise ReleaseError("Canonical application and release package must not overlap")
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
                    raise ReleaseError("Private files inside managed source require operator migration before source switching")
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
        if manifest.get("runtime", {}).get("jacpython"):
            prepare_venv(package, app)
        with tarfile.open(archive) as stream:
            stream.extractall(app, filter="data")


def prepare_venv(package, app):
    # Build metadata with the exact packaged runtime's unpacked CPython. Copying
    # the build workspace's bin links/pyvenv.cfg would retain foreign paths.
    # --without-pip performs no dependency fetch. The archive supplies the
    # tested libraries, including any build-installed pip metadata afterward.
    code = ("import subprocess,sys; from pathlib import Path; "
            "python=Path(sys.prefix)/'bin'/('python'+str(sys.version_info.major)+'.'+str(sys.version_info.minor)); "
            "raise SystemExit(subprocess.run([str(python),'-m','venv','--without-pip',str(Path.cwd()/'.jac/venv')]).returncode)")
    result = subprocess.run([str(Path(package) / "runtime/jacpython"), "-c", code], cwd=app, capture_output=True, timeout=60)
    if result.returncode:
        raise ReleaseError("Offline dependency environment initialization failed; candidate remains stopped")


def validate_config(config):
    entry = Path(config.get("canonical_entry", ""))
    if not entry.is_absolute() or entry.name != "main.jac" or str(entry) != str(entry.resolve()):
        raise ReleaseError("Record the exact resolved canonical main.jac entry path")
    for name in ("canonical_entry", "durable_root", "onboarding_dir", "native_signing_file", "photos_dir"):
        path = Path(config.get(name, ""))
        if not path.is_absolute():
            raise ReleaseError("Deployment paths must be absolute")
        reject_links(path)
    native_data = Path(config.get("native_data_dir", str(entry.parent / ".jac/data")))
    if not native_data.is_absolute():
        raise ReleaseError("Record the existing absolute native data directory")
    reject_links(native_data)
    if Path(config["native_signing_file"]) != native_data / "jwt_secret" or Path(config["photos_dir"]) != entry.parent / "assets/photos":
        raise ReleaseError("Native signing state and photos must retain their existing canonical paths")
    if config.get("topology") != "single-instance-serialized" or config.get("replicas") != 1:
        raise ReleaseError("Only the proposed exclusive single-instance serialized topology is supported")
    ports = [config.get("backend_port"), config.get("gateway_port")]
    if any(type(port) is not int or not 1024 <= port <= 65535 for port in ports) or ports[0] == ports[1]:
        raise ReleaseError("Use distinct unprivileged backend and gateway ports")
    return entry.parent


def sqlite_inventory(path):
    reject_links(path)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ReleaseError("Private SQLite integrity check failed")
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
                raise ReleaseError("Existing private state is incomplete; use an audited migration, never create replacement keys")
            continue
        result["files"][name] = {"sha256": digest(path), "bytes": path.stat().st_size}
        if name.endswith(".sqlite3"):
            result["sqlite"][name] = sqlite_inventory(path)
    photos = Path(config["photos_dir"])
    reject_links(photos, tree=True)
    if require_complete and not photos.is_dir():
        raise ReleaseError("Existing photo volume is missing")
    if photos.exists():
        result["photos"] = inventory(photos)
    return result


def backup_private_state(config, destination):
    state_inventory(config)
    destination = Path(destination)
    reject_links(destination)
    if destination.exists():
        raise ReleaseError("Backup destination already exists")
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
        raise ReleaseError("Recovery set checksum or inventory differs")
    for name in ("onboarding.sqlite3", "photo-ownership.sqlite3"):
        if sqlite_inventory(backup / name) != receipt["sqlite"][name]:
            raise ReleaseError("Recovery SQLite row inventory differs")
    return receipt


def restore_private_state(backup, config):
    validate_config(config)
    targets = [Path(config["onboarding_dir"]), Path(config["native_signing_file"]), Path(config["photos_dir"])]
    for path in targets:
        reject_links(path, tree=True)
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise ReleaseError("Refusing to overwrite existing private state or identity; restore into empty isolated storage")
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
    try:
        parsed = urlsplit(url)
        port = parsed.port or 5432
    except (ValueError, TypeError):
        raise ReleaseError("PostgreSQL URL format or port is invalid; no connection settings were logged") from None
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path.strip("/") or parsed.query or parsed.fragment:
        raise ReleaseError("Use an explicit PostgreSQL URL without query options; configure TLS through PostgreSQL environment settings")
    # Official Jac 0.37.23 decodes credentials but keeps the database path
    # literal. Refuse forms libpq would interpret differently rather than
    # silently selecting another durable identity/graph namespace.
    database = parsed.path[1:]
    user, password = unquote(parsed.username or ""), unquote(parsed.password or "")
    if (not user or any(char in parsed.hostname for char in ("%", ",", "/"))
            or any(char.isspace() for char in parsed.hostname)
            or not database or any(char in database for char in ("%", "/", "="))
            or any(ord(char) < 32 or ord(char) == 127 for char in database)
            or "\x00" in user or "\x00" in password):
        raise ReleaseError("PostgreSQL URL requires an explicit role, one host and one literal database name; ambiguous target refused")
    env = os.environ.copy()
    # Service files and hostaddr override explicit environment settings;
    # PGOPTIONS can change the session role. Preserve reviewed TLS settings,
    # but use only the URL's credentials, never an ambient password file.
    for name in ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR", "PGOPTIONS"):
        env.pop(name, None)
    env.update(PGHOST=parsed.hostname, PGPORT=str(port), PGDATABASE=database,
               PGUSER=user, PGPASSWORD=password, PGPASSFILE=os.devnull, PGCONNECT_TIMEOUT="10")
    return env


def pg_command(args, env, timeout=300):
    # URLs/passwords are never passed as process arguments, printed, or placed
    # in public receipts. PostgreSQL stderr may include private connection data.
    result = subprocess.run(args, env=env, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ReleaseError("PostgreSQL backup/recovery command failed; preserve its protected operator diagnostics")
    return result.stdout.decode().strip()


def coordinated_backup(config, destination, package):
    destination = Path(destination)
    reject_links(destination)
    if destination.exists():
        raise ReleaseError("Backup destination already exists")
    manifest = verify_package(package)
    installed = verify_installed_source(package, config)
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
               "installed_source_verified": installed,
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
        raise ReleaseError("Coordinated recovery set checksum or inventory differs")
    verify_backup(backup / "private")
    return receipt


def coordinated_restore(backup, config, package):
    receipt = verify_recovery_set(backup)
    manifest = verify_package(package)
    if receipt.get("canonical_entry") != config["canonical_entry"] or receipt.get("source_sha") != manifest["source_sha"] or \
            receipt.get("runtime") != manifest["runtime"]:
        raise ReleaseError("Recovery requires the original canonical entry, matching source and official runtime")
    # Validate file destinations before any PostgreSQL write. Recovery does not
    # repair collisions or overwrite an existing native account store.
    for name in ("onboarding_dir", "native_signing_file", "photos_dir"):
        target = Path(config[name])
        reject_links(target, tree=True)
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ReleaseError("Recovery refuses existing identity, private state or photos")
    environment = pg_environment(os.environ.get("MLOCAL_RECOVERY_DB_URL", ""))
    if environment.get("PGDATABASE") == pg_environment(os.environ.get("JAC_DB_URL", ""))["PGDATABASE"]:
        raise ReleaseError("Recovery database must differ from the serving database")
    count = pg_command(["psql", "--no-psqlrc", "--tuples-only", "--no-align", "--command",
                        "SELECT COUNT(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')"], environment, timeout=30)
    if count != "0":
        raise ReleaseError("Recovery target database contains application tables; never overwrite existing accounts")
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
        raise ReleaseError("Launch blocked: independent official-runtime safety evidence is incomplete or does not match the candidate")
    host = evidence.get("host_acceptance", {})
    if host.get("canonical_entry") != config["canonical_entry"] or host.get("durable_storage") is not True or \
            host.get("private_backend") is not True or host.get("exclusive_ingress") is not True or host.get("nonoverlapping_rollout") is not True:
        raise ReleaseError("Launch blocked: canonical host, storage and exclusive ingress acceptance is incomplete")
    if evidence.get("operator_rollout_approved") is not True:
        raise ReleaseError("Launch blocked: Travis's explicit rollout approval has not been recorded")


def verify_installed_source(package, config, require_marker=False):
    package = Path(package)
    manifest = verify_package(package)
    app = validate_config(config)
    reject_app_links(app)
    marker_path = app / ".jac/release-installed.json"
    if marker_path.exists():
        marker = read_json(marker_path)
        if marker.get("source_sha") != manifest["source_sha"] or marker.get("source_tree") != manifest["source_tree"] or \
                marker.get("package_manifest_sha256") != digest(package / "manifest.json") or marker.get("canonical_entry") != config["canonical_entry"]:
            raise ReleaseError("Installed source marker does not match the recovery package or canonical entry")
    elif require_marker:
        raise ReleaseError("Installed source marker is missing; verify and install the intended candidate before launch")
    expected = {name[7:]: value for name, value in manifest["files"].items()
                if name.startswith("source/") and Path(name).parts[1] in MANAGED}
    actual = {}
    for name in MANAGED:
        root = app / name
        if root.is_file():
            actual[name] = digest(root)
        elif root.is_dir():
            for path in root.rglob("*"):
                relative = str(path.relative_to(app))
                if path.is_file() and Path(relative).parts[:2] != ("assets", "photos") and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                    actual[relative] = digest(path)
    if actual != expected:
        raise ReleaseError("Installed source inventory or digest differs from the supplied package; backup cannot label a proposed candidate as the serving source")
    return {"source_sha": manifest["source_sha"], "source_tree": manifest["source_tree"], "canonical_entry": config["canonical_entry"],
            "marker_present": marker_path.exists(), "source_inventory_verified": True}


def acquire_lock(config):
    root = Path(config["durable_root"])
    reject_links(root)
    if not root.is_dir():
        raise ReleaseError("Durable root must already be provisioned")
    lock = root / "deployment.lock"
    reject_links(lock)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ReleaseError("Backend or deployment operation is still running; stop it before switching source") from None
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
                raise ReleaseError("Configured backend/gateway port is occupied; establish prior process termination before launch") from None


def require_canonical_project_entry(app):
    # No-target `jac run` reads this declaration from cwd. Do not let a changed
    # entry select another source path/native namespace after migration.
    try:
        with (app / "jac.toml").open("rb") as stream:
            project = tomllib.load(stream).get("project", {})
        entry = project.get("entry-point") if isinstance(project, dict) else None
    except (OSError, ValueError):
        raise ReleaseError("The canonical project entry must be explicitly declared as main in valid jac.toml") from None
    if entry != "main":
        raise ReleaseError("The canonical project entry must be explicitly declared as main in valid jac.toml")


def launch(package, config, evidence):
    package = Path(package)
    app = validate_config(config)
    manifest = verify_package(package)
    require_launch_evidence(config, manifest, evidence)
    if not manifest.get("dependencies") or not manifest.get("build") or set(manifest.get("runtime", {})) != {"jac", "jacpython"}:
        raise ReleaseError("Launch requires the complete tested source, official runtime, build and dependency package")
    state_inventory(config)
    verify_installed_source(package, config, require_marker=True)
    environment = os.environ.copy()
    pg_environment(environment.get("JAC_DB_URL", ""))
    environment.update(MLOCAL_ENV="production", MLOCAL_PUBLIC_INGRESS="restricted", MLOCAL_DEPLOYMENT_TOPOLOGY="single-instance-serialized",
                       MLOCAL_APP_REPLICAS="1", MLOCAL_DURABLE_ROOT=config["durable_root"], MLOCAL_ONBOARDING_DIR=config["onboarding_dir"],
                       MLOCAL_BACKEND_PORT=str(config["backend_port"]), PORT=str(config["gateway_port"]),
                       MLOCAL_INGRESS_EVENT_LOG="stderr", MLOCAL_DOMAIN_EVENT_LOG="stderr")
    # Official authcrypt.project_data_dir treats JAC_DATA_PATH as a base and
    # appends .jac/data. It is not the signing-directory setting itself.
    raw_native_base = environment.get("JAC_DATA_PATH", "")
    if raw_native_base != raw_native_base.strip():
        raise ReleaseError("JAC_DATA_PATH must retain its exact absolute base without leading or trailing whitespace")
    native_base = Path(raw_native_base or str(app))
    if not native_base.is_absolute() or (native_base / ".jac/data/jwt_secret").resolve() != Path(config["native_signing_file"]):
        raise ReleaseError("JAC_DATA_PATH differs from the recorded original native signing state; preserve the existing path and key")
    # Node/gateway provenance and explicit trusted edge are host capabilities.
    if environment.get("MLOCAL_INGRESS") not in {"render", "funnel", "restricted-edge"}:
        raise ReleaseError("Select the verified restricted HTTPS edge; production direct ingress is prohibited")
    require_canonical_project_entry(app)
    lock = acquire_lock(config)
    processes = []
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        require_free_ports(config)
        guard = subprocess.run([str(package / "runtime/jacpython"), "-c",
                                "import json,os; from pathlib import Path; from services.production_guard import validate_production_config; "
                                "errors=validate_production_config(os.environ,Path.cwd()); print(json.dumps(errors)); raise SystemExit(78 if errors else 0)"],
                               cwd=app, env=environment, timeout=30, capture_output=True)
        if guard.returncode:
            names = sorted(set(re.findall(r"\b(?:MLOCAL_|JAC_)[A-Z_]+\b", guard.stdout.decode(errors="replace"))))
            raise ReleaseError("Production configuration guard refused startup: " + (", ".join(names) or "required setting names unavailable; inspect protected guard check"))
        # Guard is also run by Jac onboarding import. Failure of either process
        # terminates both process groups; no restart while queue outcome is unknown.
        # In official 0.37.23, options following a positional target become
        # script arguments. Run the declared project from its canonical cwd so
        # --no-dev/host/port stay CLI options and no default Vite server starts.
        processes.append(subprocess.Popen([str(package / "runtime/jac"), "run", "--no-dev", "--host", "127.0.0.1", "--port", str(config["backend_port"])], cwd=app, env=environment, start_new_session=True))
        deadline = time.monotonic() + 300
        native_ready = False
        # No gateway or public traffic exists yet. This native metadata probe
        # performs no graph RPC. Starting the gateway before compilation ends
        # would turn its first refused connection into an uncertainty latch.
        while processes[0].poll() is None and time.monotonic() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:" + str(config["backend_port"]) + "/healthz/ready", timeout=5) as response:
                    body = response.read(64 * 1024 + 1)
                    value = json.loads(body) if len(body) <= 64 * 1024 else None
                    native_ready = response.status == 200 and isinstance(value, dict) and value.get("ready") is True
                if native_ready:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(1)
        if not native_ready:
            raise ReleaseError("Candidate failed private native startup readiness; owned process groups were stopped")
        processes.append(subprocess.Popen(["node", str(app / "scripts/hosted-gateway.mjs")], cwd=app, env=environment, start_new_session=True))
        ready = False
        # Both phases share the original total startup deadline. After gateway
        # creation, its readiness and every graph RPC use only the same lane.
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
            raise ReleaseError("Candidate failed meaningful gateway readiness; both process groups were stopped")
        print("Candidate reached gateway readiness; external traffic remains an operator responsibility.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise ReleaseError("Backend or gateway exited; both process groups were stopped")
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
            if not args.output:
                raise ReleaseError("Inventory requires an explicit protected --output receipt destination")
            reject_links(args.output)
            args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_json(args.output, result, private=True)
        elif args.action in {"switch-source", "backup-private", "restore-private", "backup", "restore"}:
            validate_config(config)
            if not args.acknowledge_quiesced:
                raise ReleaseError("Close ingress and stop all graph/CLI/private-store writers, then acknowledge quiescence")
            lock = acquire_lock(config)
            require_free_ports(config)
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
            pg_environment(os.environ.get("JAC_DB_URL", ""))
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
        print(str(error) if isinstance(error, ReleaseError) else "Release operation failed; inspect protected local state.", file=__import__("sys").stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if lock is not None:
            os.close(lock)


if __name__ == "__main__":
    raise SystemExit(main())
