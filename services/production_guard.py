"""Refuse unsafe production startup before the native server can serve traffic.

Filesystem checks establish a dedicated mounted state volume and existing keys,
not the provider's durability SLA, backups, or transaction safety. Those remain
hosting acceptance gates. Diagnostics contain setting names and no values.
"""
import os
import sys
import sqlite3
import hmac
import tomllib
import tempfile
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

ENV_NAME = "MLOCAL_ENV"
ONBOARDING_DIR = "MLOCAL_ONBOARDING_DIR"
EXIT_CODE = 78
SMTP_SETTINGS = ("MLOCAL_SMTP_HOST", "MLOCAL_SMTP_FROM", "MLOCAL_SMTP_USERNAME", "MLOCAL_SMTP_PASSWORD")
_FALSE = {"0", "false", "no", "off"}
_EPHEMERAL_FILESYSTEMS = {"overlay", "tmpfs", "ramfs", "rootfs", "squashfs"}


class ProductionConfigError(RuntimeError):
    """Configuration errors contain names, never secrets or private paths."""


def is_production(env: Mapping[str, str]) -> bool:
    return env.get(ENV_NAME, "").strip().lower() == "production"


def _inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _writable(directory: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".mlocal-write-check-"):
            return True
    except OSError:
        return False


def _existing_sqlite(path: Path, required: Mapping[str, set[str]]) -> bool:
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                return False
            return all(columns.issubset({row[1] for row in db.execute('PRAGMA table_info(' + table + ')')})
                       for table, columns in required.items())
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return False


def _mounted_volume(path: Path) -> bool:
    """Require Linux's dedicated mount; the root/container filesystem is insufficient.

    Bind mounts appear as separate mountinfo entries. Their actual backing store
    must additionally be recorded and accepted by the deployment operator.
    """
    try:
        matches = []
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            left, right = line.split(' - ', 1)
            fields = left.split()
            mount = Path(fields[4].replace('\\040', ' ').replace('\\134', '\\'))
            if _inside(path, mount):
                matches.append((len(mount.parts), mount, right.split()[0], fields[5]))
        if not matches:
            return False
        _, mount, filesystem, options = max(matches, key=lambda item: item[0])
        return mount != Path('/') and filesystem not in _EPHEMERAL_FILESYSTEMS and 'rw' in options.split(',')
    except (OSError, ValueError, IndexError):
        return False


def _required_file_on_volume(path: Path, durable: Path | None) -> bool:
    return (not path.is_symlink() and path.is_file() and durable is not None
            and _inside(path.resolve(), durable) and _mounted_volume(path.resolve()))


def _demo_enabled(env: Mapping[str, str]) -> list[str]:
    enabled = []
    if env.get("MLOCAL_DEMO_MODE", "").strip().lower() not in ('', *_FALSE):
        enabled.append("MLOCAL_DEMO_MODE")
    if env.get("MLOCAL_DEMO_COMPANIES", "").strip() not in ("", "0"):
        enabled.append("MLOCAL_DEMO_COMPANIES")
    if env.get("MLOCAL_HOSTED_DATASET", "").strip().lower() not in ('', *_FALSE):
        enabled.append("MLOCAL_HOSTED_DATASET")
    if env.get("MLOCAL_DEMO_STUDENTS", "").strip() not in ("", "[]", "null"):
        enabled.append("MLOCAL_DEMO_STUDENTS")
    return enabled


def validate_production_config(env: Mapping[str, str], app_root: Path) -> list[str]:
    if not is_production(env):
        return []
    problems: list[str] = []
    root = Path(os.path.realpath(app_root))
    durable = None
    raw_root = env.get('MLOCAL_DURABLE_ROOT', '').strip()
    if not raw_root:
        problems.append('MLOCAL_DURABLE_ROOT is not set. Mount and preserve the coordinated state volume.')
    elif not os.path.isabs(raw_root):
        problems.append('MLOCAL_DURABLE_ROOT must be an absolute path.')
    else:
        durable = Path(os.path.realpath(raw_root))
        if _inside(durable, root):
            problems.append('MLOCAL_DURABLE_ROOT must be outside the application source directory.')
        if not durable.is_dir() or not _mounted_volume(durable):
            problems.append('MLOCAL_DURABLE_ROOT requires an existing writable dedicated persistent-volume mount; the root filesystem and temporary filesystems are insufficient.')

    raw_dir = env.get(ONBOARDING_DIR, '').strip()
    directory = Path(os.path.realpath(raw_dir)) if raw_dir and os.path.isabs(raw_dir) else None
    if not raw_dir:
        problems.append(f'{ONBOARDING_DIR} is not set. Restore its database and original key on the state volume.')
    elif directory is None:
        problems.append(f'{ONBOARDING_DIR} must be an absolute path.')
    elif _inside(directory, root):
        problems.append(f'{ONBOARDING_DIR} must be outside the application source directory.')
    elif not directory.is_dir():
        problems.append(f'{ONBOARDING_DIR} must be an existing directory (mount the volume first).')
    elif not _writable(directory):
        problems.append(f'{ONBOARDING_DIR} is not writable by the app.')
    elif not _mounted_volume(directory):
        problems.append(f'{ONBOARDING_DIR} must use the persistent volume; an ephemeral nested mount is insufficient.')
    if directory is not None and (durable is None or not _inside(directory, durable)):
        problems.append(f'{ONBOARDING_DIR} must resolve inside MLOCAL_DURABLE_ROOT.')
    if directory is not None and directory.is_dir():
        try:
            if not _required_file_on_volume(directory / 'code.key', durable) or len((directory / 'code.key').read_bytes()) != 32:
                raise ValueError
            if not _required_file_on_volume(directory / 'onboarding.sqlite3', durable) or not _existing_sqlite(directory / 'onboarding.sqlite3', {
                'accounts': {'actor', 'email', 'kind', 'name'},
                'business_owners': {'actor', 'slug', 'active'},
                'drafts': {'actor', 'body', 'updated'},
            }):
                raise ValueError
        except (OSError, ValueError):
            problems.append(f'{ONBOARDING_DIR} requires the existing onboarding.sqlite3 and complete original code.key; do not generate replacement state during rollout.')

    native_base = root
    raw_native = env.get('JAC_DATA_PATH', '').strip()
    if raw_native:
        if not os.path.isabs(raw_native):
            problems.append('JAC_DATA_PATH must be an absolute preserved native-data location inside MLOCAL_DURABLE_ROOT.')
        else:
            native_base = Path(raw_native)
    native_data = (native_base / '.jac/data').resolve()
    for target, label, relative in ((native_data, 'native signing-state', '.jac/data'),
                                    ((root / 'assets/photos').resolve(), 'photo storage', 'assets/photos')):
        if not target.is_dir() or durable is None or not _inside(target, durable) or not _writable(target) or not _mounted_volume(target):
            problems.append(f'MLOCAL_DURABLE_ROOT must contain writable {label}; mount the application {relative} path onto that volume.')
    photos = root / 'assets/photos'
    if photos.is_dir() and any(photos.glob('*.jpg')) and (
        directory is None or not _required_file_on_volume(directory / 'photo-ownership.sqlite3', durable) or not _existing_sqlite(directory / 'photo-ownership.sqlite3', {
            'photos': {'filename', 'actor', 'digest', 'bytes', 'created'},
        })
    ):
        problems.append('MLOCAL_ONBOARDING_DIR requires the matching existing photo-ownership.sqlite3 when stored photos exist; restore ownership and bytes together.')
    try:
        secret_path = native_data / 'jwt_secret'
        if not _required_file_on_volume(secret_path, durable):
            raise ValueError
        secret = secret_path.read_bytes()
        if len(secret.strip()) < 32:
            raise ValueError
    except (OSError, ValueError):
        secret = None
        problems.append('MLOCAL_DURABLE_ROOT requires the existing native jwt_secret; preserve it from the coordinated recovery set.')
    try:
        config_file = root / 'jac.toml'
        config = tomllib.loads(config_file.read_text()) if config_file.is_file() else {}
        serve = config.get('serve', {})
        if not isinstance(serve, Mapping):
            raise ValueError
        auth = serve.get('auth', {})
        if not isinstance(auth, Mapping):
            raise ValueError
        configured_secret = env.get('JAC_SERVE_AUTH_SECRET', '') or auth.get('secret', '')
        configured_algorithm = env.get('JAC_SERVE_AUTH_ALGORITHM', '') or auth.get('algorithm', 'HS256')
        if not isinstance(configured_secret, str) or not isinstance(configured_algorithm, str):
            raise ValueError
        configured_secret = configured_secret.strip()
        # The stock testing placeholder falls back to the project file; it is
        # never treated as a production secret by the native runtime.
        if secret is not None and configured_secret and configured_secret != 'supersecretkey_for_testing_only!' and not hmac.compare_digest(
            configured_secret.encode(), secret.strip()
        ):
            problems.append('JAC_SERVE_AUTH_SECRET or [serve.auth] secret must match the preserved native jwt_secret recovery state; rotating it is a separate approved migration.')
        if configured_algorithm.strip() != 'HS256':
            problems.append('JAC_SERVE_AUTH_ALGORITHM or [serve.auth] algorithm must use the supported release signing policy (HS256).')
    except (OSError, ValueError):
        problems.append('JAC_SERVE_AUTH_SECRET, JAC_SERVE_AUTH_ALGORITHM and [serve.auth] require valid string settings; check the preserved signing configuration.')

    try:
        database = urlsplit(env.get('JAC_DB_URL', ''))
        valid_database = database.scheme in ('postgresql', 'postgres') and bool(database.hostname) and bool(database.path.strip('/'))
        _ = database.port
    except ValueError:
        valid_database = False
    if not valid_database:
        problems.append('JAC_DB_URL must explicitly select the persistent PostgreSQL graph and identity database; implicit embedded storage is not a production configuration.')
    if env.get('JAC_DEV_SOURCE', '').strip():
        problems.append('JAC_DEV_SOURCE must be unset; production requires the official pinned runtime.')

    for name in SMTP_SETTINGS:
        if not env.get(name, '').strip():
            problems.append(f'{name} is not set (email delivery is required in production).')
    try:
        if not 1 <= int(env.get('MLOCAL_SMTP_PORT', '587')) <= 65535:
            raise ValueError
    except ValueError:
        problems.append('MLOCAL_SMTP_PORT must be a valid TLS SMTP port.')
    for name in _demo_enabled(env):
        problems.append(f'{name} must be off in production.')
    if env.get('MLOCAL_SHOW_SAMPLES', '').strip().lower() not in _FALSE:
        problems.append('MLOCAL_SHOW_SAMPLES must explicitly be off in production.')
    for name, required in (
        ('MLOCAL_PUBLIC_INGRESS', 'restricted'),
        ('MLOCAL_DEPLOYMENT_TOPOLOGY', 'single-instance-serialized'),
        ('MLOCAL_APP_REPLICAS', '1'),
    ):
        if env.get(name, '').strip() != required:
            problems.append(f'{name} must select the release hosting policy ({required}).')
    return problems


def enforce_production_config(env: Mapping[str, str] | None = None, app_root: Path | None = None) -> bool:
    source = os.environ if env is None else env
    root = Path(__file__).resolve().parent.parent if app_root is None else app_root
    try:
        problems = validate_production_config(source, root)
    except (OSError, ValueError, RuntimeError):
        problems = ['Production storage or configuration could not be inspected. Check MLOCAL_DURABLE_ROOT, MLOCAL_ONBOARDING_DIR and JAC_DB_URL; no replacement state was created.']
    if problems:
        raise ProductionConfigError('M-Local refuses to start: production configuration is incomplete.\n- ' + '\n- '.join(problems))
    return True


def exit_unless_production_ready() -> bool:
    """Jac can continue after ordinary module import failures; terminate the process."""
    try:
        return enforce_production_config()
    except ProductionConfigError as error:
        print(str(error), file=sys.stderr, flush=True)
        os._exit(EXIT_CODE)
