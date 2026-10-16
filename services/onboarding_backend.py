"""Explicit authority-only backend selection for the disposable SQL proof.

SQLite remains the application default. Native startup and media deliberately
refuse this proof mode until their separate cutover/recovery contracts are met.
The optional SQL driver is imported only after explicit selection and admission.
"""
from contextlib import contextmanager
import os


_UNAVAILABLE = ('Selected PostgreSQL proof authority is unavailable or incompatible. '
                'Preserve existing state and check the explicit proof configuration; '
                'no replacement or SQLite fallback was used.')


def backend_name():
    name = os.environ.get('MLOCAL_ONBOARDING_BACKEND', 'sqlite')
    if name not in {'sqlite', 'postgres-proof'}:
        raise ValueError('MLOCAL_ONBOARDING_BACKEND must select a supported authority backend.')
    return name


def require_sqlite_backend():
    if backend_name() != 'sqlite':
        raise ValueError('Media requires the SQLite application backend; PostgreSQL authority proof mode does not support photo serving or writes.')


def selected_store(store_class, clock):
    if backend_name() == 'sqlite':
        return None
    if os.environ.get('MLOCAL_ENV', '').strip().lower() == 'production':
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
        backend = PostgresAuxiliary(dsn, schema)
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
