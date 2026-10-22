"""Explicit auxiliary authority and guarded disposable SQL application startup.

SQLite remains the default. The authority-only proof and disposable application
rehearsal are distinct; neither admits production SQL or replacement state.
SQL dependencies are imported only after explicit selection and admission.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import tomllib
import hmac
from urllib.parse import urlsplit, unquote


_UNAVAILABLE = ('Selected PostgreSQL proof authority is unavailable or incompatible. '
                'Preserve existing state and check the explicit proof configuration; '
                'no replacement or SQLite fallback was used.')


def backend_name():
    name = os.environ.get('MLOCAL_ONBOARDING_BACKEND', 'sqlite')
    if name not in {'sqlite', 'postgres-proof', 'postgres-local'}:
        raise ValueError('MLOCAL_ONBOARDING_BACKEND must select a supported authority backend.')
    return name


def require_sqlite_backend():
    if backend_name() == 'postgres-local':
        raise ValueError('Photo uploads are unavailable in this disposable SQL application mode.')
    if backend_name() != 'sqlite':
        raise ValueError('Media requires the SQLite application backend; PostgreSQL authority proof mode does not support photo serving or writes.')


def _proof_backend():
    if backend_name() == 'sqlite':
        return None
    if backend_name() == 'postgres-local':
        if validate_disposable_sql_config(os.environ, Path(__file__).resolve().parent.parent):
            raise ValueError(_UNAVAILABLE)
    elif os.environ.get('MLOCAL_ENV', '').strip().lower() == 'production':
        raise ValueError('PostgreSQL authority proof mode is unavailable in production.')
    dsn = os.environ.get('MLOCAL_AUXILIARY_TEST_DSN')
    schema = os.environ.get('MLOCAL_AUXILIARY_TEST_SCHEMA')
    if not dsn or not schema:
        raise ValueError('PostgreSQL authority proof requires explicit disposable database and schema configuration.')
    try:
        import psycopg
        from services.postgres_auxiliary import PostgresAuxiliary
    except ImportError:
        raise ValueError(_UNAVAILABLE) from None
    try:
        return PostgresAuxiliary(dsn, schema)
    except (psycopg.Error, ValueError):
        raise ValueError(_UNAVAILABLE) from None


def selected_store(store_class, clock):
    backend = _proof_backend()
    if backend is None:
        return None
    import psycopg
    try:
        # code_store validates the established schema, audit and both original
        # keys. It bypasses CodeStore postinit and never initializes/imports.
        state = backend.code_store(store_class, os.environ.get('MLOCAL_ONBOARDING_DIR', '.jac/onboarding'), clock)
    except (psycopg.Error, ValueError):
        raise ValueError(_UNAVAILABLE) from None

    @contextmanager
    def transaction():
        try:
            with backend.transaction() as database:
                yield database
        except psycopg.Error:
            # Also sanitize enter/body/commit failures after healthy admission.
            # Business validation ValueErrors retain their existing meaning.
            raise ValueError(_UNAVAILABLE) from None

    state.transaction = transaction
    return state


def selected_photo_owned(filename, actor):
    backend = _proof_backend()
    if backend is None:
        return None
    import psycopg
    try:
        # Require established original keys as well as schema/audit admission.
        # A validated absence denies ownership; it never selects SQLite fallback.
        backend.signing_material()
        return backend.photo_owned(filename, actor)
    except (psycopg.Error, ValueError):
        raise ValueError(_UNAVAILABLE) from None


def validate_disposable_sql_config(env, app_root):
    """Offline, dependency-free admission of an explicitly owned local fixture."""
    problems = []
    if (env.get('MLOCAL_ENV') != 'disposable'
            or env.get('MLOCAL_ONBOARDING_BACKEND') != 'postgres-local'
            or env.get('MLOCAL_DISPOSABLE_SQL') != '1'):
        problems.append('MLOCAL_ENV, MLOCAL_ONBOARDING_BACKEND and MLOCAL_DISPOSABLE_SQL require explicit disposable SQL application selection.')
    try:
        raw = env.get('MLOCAL_DURABLE_ROOT', '')
        root, app = Path(raw), Path(app_root)
        candidates = [Path(tempfile.gettempdir())]
        if env.get('RUNNER_TEMP'):
            candidates.append(Path(env['RUNNER_TEMP']))
        if (not raw or not root.is_absolute() or str(root) != str(root.resolve(strict=True))
                or not root.name.startswith('m-local-package-live.')
                or not root.is_dir() or stat.S_IMODE(root.stat().st_mode) != 0o700
                or root.stat().st_uid != os.getuid()
                or any(part.is_symlink() for part in (root, *root.parents, app, *app.parents))
                or not app.is_absolute() or app.resolve(strict=True) != app
                or root not in app.parents
                or not any(parent.is_absolute() and parent.resolve(strict=True) in root.parents for parent in candidates)):
            raise ValueError
    except (OSError, ValueError, AttributeError):
        problems.append('MLOCAL_DURABLE_ROOT requires an owned private resolved temporary package fixture containing the application.')
    try:
        dsn = env.get('MLOCAL_AUXILIARY_TEST_DSN', '')
        parsed = urlsplit(dsn)
        database = parsed.path[1:]
        user, password = unquote(parsed.username or ''), unquote(parsed.password or '')
        if (not dsn or env.get('JAC_DB_URL') != dsn
                or parsed.scheme not in {'postgres', 'postgresql'}
                or parsed.hostname not in {'127.0.0.1', '::1'}
                or parsed.port is None or not 1024 <= parsed.port <= 65535
                or parsed.query or parsed.fragment or not user
                or '\x00' in user or '\x00' in password
                or not re.fullmatch(r'mlocal_aux_test_[a-z0-9_]{1,47}', database)
                or not re.fullmatch(r'mlocal_aux_test_[a-z0-9_]{1,47}', env.get('MLOCAL_AUXILIARY_TEST_SCHEMA', ''))):
            raise ValueError
    except (ValueError, TypeError):
        problems.append('JAC_DB_URL and MLOCAL_AUXILIARY_TEST_DSN require the same explicit owned loopback database and MLOCAL_AUXILIARY_TEST_SCHEMA.')
    if (any(name in env for name in ('PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS'))
            or env.get('PGPASSWORD') or env.get('PGPASSFILE') not in (None, '', os.devnull)
            or env.get('JAC_SV_SIBLING') or env.get('MLOCAL_AUXILIARY_DRIVER_SITE')):
        problems.append('PGHOSTADDR, PGSERVICE, PGSERVICEFILE, PGOPTIONS, PGPASSWORD, PGPASSFILE, JAC_SV_SIBLING and MLOCAL_AUXILIARY_DRIVER_SITE must not redirect this disposable application.')
    return problems


def _application_driver(app, normal_venv):
    """Require the ordinary installed binary driver, including its C modules."""
    library = app / '.jac/venv/lib'
    if normal_venv and Path(sys.prefix).resolve() != (app / '.jac/venv').resolve():
        raise ValueError(_UNAVAILABLE)
    import psycopg
    import psycopg_binary
    from psycopg_binary import pq as binary_pq, _psycopg as binary_c
    from psycopg import _cmodule
    if (psycopg.__version__ != '3.3.6' or psycopg.pq.__impl__ != 'binary'
            or psycopg.pq.PGconn is not binary_pq.PGconn or _cmodule._psycopg is not binary_c):
        raise ValueError(_UNAVAILABLE)
    for module in (psycopg, psycopg_binary, binary_pq, binary_c):
        origin = Path(module.__file__).resolve(strict=True)
        if not origin.is_file() or library not in origin.parents:
            raise ValueError(_UNAVAILABLE)


def admit_disposable_sql_application(env, app_root, *, materialize=False, normal_venv=False):
    """Validate established SQL and preserved originals before native auth starts.

    Only bootstrap may publish an empty cache. Native import rechecks admission
    and the already selected key; it never chooses a key after auth initializes.
    """
    app = Path(app_root).resolve(strict=True)
    if validate_disposable_sql_config(env, app):
        raise ValueError(_UNAVAILABLE)
    _application_driver(app, normal_venv)
    from services.postgres_auxiliary import PostgresAuxiliary, _read_file
    backend = PostgresAuxiliary(env['MLOCAL_AUXILIARY_TEST_DSN'], env['MLOCAL_AUXILIARY_TEST_SCHEMA'])
    keys = backend.signing_material()
    onboarding = Path(env['MLOCAL_ONBOARDING_DIR'])
    code = _read_file(onboarding / 'code.key', 32)
    native = _read_file(Path(env.get('JAC_DATA_PATH') or app) / '.jac/data/jwt_secret', 65536)
    if (len(code) != 32 or not hmac.compare_digest(code, keys['code_key'])
            or not hmac.compare_digest(native, keys['native_key'])):
        raise ValueError(_UNAVAILABLE)
    effective = native.decode('utf-8').strip()
    if (len(effective.encode()) < 32 or effective == 'supersecretkey_for_testing_only!'
            or any(char in effective for char in ('\x00', '\r', '\n'))
            or effective.encode() != native.strip()):
        raise ValueError(_UNAVAILABLE)
    with (app / 'jac.toml').open('rb') as stream:
        auth = tomllib.load(stream).get('serve', {}).get('auth', {})
    for configured in (env.get('JAC_SERVE_AUTH_SECRET', ''), auth.get('secret', '')):
        if (not isinstance(configured, str)
                or (configured.strip() and not hmac.compare_digest(configured.strip().encode(), effective.encode()))):
            raise ValueError(_UNAVAILABLE)
    if not materialize and env.get('JAC_SERVE_AUTH_SECRET') != effective:
        raise ValueError(_UNAVAILABLE)
    cache = app / 'assets/photos'
    registry = onboarding / 'photo-ownership.sqlite3'
    if materialize and not any(cache.iterdir()):
        backend.materialize_photos(cache, preserved_registry=registry)
    backend.validate_photo_cache(cache, preserved_registry=registry)
    return effective


def bootstrap_native(argv=None):
    """Select original signing state in the native child, then exec pinned Jac."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        from services.production_guard import validate_production_config
        app = Path.cwd().resolve(strict=True)
        if validate_production_config(os.environ, app) or not arguments:
            raise ValueError(_UNAVAILABLE)
        effective = admit_disposable_sql_application(os.environ, app, materialize=True, normal_venv=True)
        os.environ['JAC_SERVE_AUTH_SECRET'] = effective
        os.execve(arguments[0], arguments, dict(os.environ))
    except Exception:
        # Driver, SQL, filesystem and decoding errors may include private data.
        print('Disposable SQL application admission failed; preserve original state and cache. No replacement or fallback was used.', file=sys.stderr, flush=True)
        raise SystemExit(78) from None
