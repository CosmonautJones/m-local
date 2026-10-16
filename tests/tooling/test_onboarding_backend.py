"""Default authority selection must not acquire the optional SQL dependency."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class SelectorImportTests(unittest.TestCase):
    def test_default_sqlite_selection_without_optional_driver(self):
        program = r"""
import builtins, sys
sys.path.insert(0, sys.argv[1])
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
original_import = builtins.__import__
def no_sql_driver(name, *args, **kwargs):
    if name == 'psycopg' or name.startswith('psycopg.') or name == 'services.postgres_auxiliary':
        raise AssertionError('Default selection imported the optional proof driver')
    return original_import(name, *args, **kwargs)
builtins.__import__ = no_sql_driver
from services import onboarding_backend
assert onboarding_backend.backend_name() == 'sqlite'
assert onboarding_backend.selected_store(object, lambda: 0) is None
assert onboarding_backend.selected_photo_owned('0' * 32 + '.jpg', 'fixture-actor') is None
onboarding_backend.require_sqlite_backend()
assert 'psycopg' not in sys.modules
assert 'services.postgres_auxiliary' not in sys.modules
"""
        for selector in (None, 'sqlite'):
            env = dict(os.environ)
            env.pop('MLOCAL_ONBOARDING_BACKEND', None)
            if selector is not None:
                env['MLOCAL_ONBOARDING_BACKEND'] = selector
            with self.subTest(selector=selector):
                result = subprocess.run([sys.executable, '-I', '-c', program, str(ROOT)],
                                        env=env, text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, 'Fresh default selector failed with the optional SQL driver forbidden')


    def test_disposable_sql_static_admission_without_driver_or_network(self):
        # Real configuration behavior only; forbid acquisition of the online
        # dependency/network so offline admission cannot drift into bootstrap.
        program = r"""
import builtins, os, socket, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
original_import = builtins.__import__
def no_sql_driver(name, *args, **kwargs):
    if name == 'psycopg' or name.startswith('psycopg.') or name == 'services.postgres_auxiliary':
        raise AssertionError('Static disposable admission imported an online dependency')
    return original_import(name, *args, **kwargs)
builtins.__import__ = no_sql_driver
def forbidden_socket(*args, **kwargs):
    raise AssertionError('Static disposable admission attempted network I/O')
socket.socket = forbidden_socket
from services import onboarding_backend
assert hasattr(onboarding_backend, 'validate_disposable_sql_config'), 'Missing explicit static disposable SQL admission'
with tempfile.TemporaryDirectory(prefix='m-local-package-live.') as temporary:
    root = Path(temporary)
    root.chmod(0o700)
    app = root / 'app'
    app.mkdir()
    dsn = 'postgresql://fixture@127.0.0.1:15432/mlocal_aux_test_startup'
    env = {'MLOCAL_ONBOARDING_BACKEND':'postgres-local', 'MLOCAL_ENV':'disposable',
           'MLOCAL_DISPOSABLE_SQL':'1', 'MLOCAL_DURABLE_ROOT':str(root),
           'RUNNER_TEMP':str(root.parent), 'JAC_DB_URL':dsn,
           'MLOCAL_AUXILIARY_TEST_DSN':dsn, 'MLOCAL_AUXILIARY_TEST_SCHEMA':'mlocal_aux_test_startup'}
    validate = onboarding_backend.validate_disposable_sql_config
    assert validate(env, app) == [], 'Owned explicit disposable context refused'
    invalid = [('MLOCAL_ENV', 'production'), ('MLOCAL_ENV', 'development'),
        ('MLOCAL_DISPOSABLE_SQL', ''), ('MLOCAL_ONBOARDING_BACKEND', 'postgres-proof'),
        ('MLOCAL_AUXILIARY_TEST_DSN', dsn + '_other'),
        ('MLOCAL_AUXILIARY_TEST_SCHEMA', 'public'), ('PGHOSTADDR', '192.0.2.1'),
        ('PGSERVICE', 'fixture'), ('PGSERVICEFILE', '/nonexistent'),
        ('PGOPTIONS', '-c role=other'), ('PGPASSWORD', 'private-fixture-only'),
        ('PGPASSFILE', '/nonexistent'), ('JAC_SV_SIBLING', '1')]
    for name, value in invalid:
        assert validate(dict(env, **{name:value}), app), 'Unsafe setting admitted: ' + name
    urls = ['postgresql://fixture@192.0.2.1:15432/mlocal_aux_test_startup',
        'postgresql://fixture@127.0.0.1/mlocal_aux_test_startup',
        'postgresql://fixture@127.0.0.1:15432/production',
        dsn + '?host=192.0.2.1', dsn + '#ignored',
        'postgresql://fixture@127.0.0.1:15432/mlocal_aux_test_%73tartup']
    for value in urls:
        assert validate(dict(env, JAC_DB_URL=value, MLOCAL_AUXILIARY_TEST_DSN=value), app), 'Unsafe SQL target admitted'
    root.chmod(0o755)
    assert validate(env, app), 'Nonprivate fixture root admitted'
assert 'psycopg' not in sys.modules
"""
        environment = dict(os.environ)
        with tempfile.TemporaryDirectory(prefix='m-local-static-proof.') as scratch:
            environment['TMPDIR'] = scratch
            result = subprocess.run([sys.executable, '-I', '-c', program, str(ROOT)],
                                    env=environment, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
