"""Default authority selection must not acquire the optional SQL dependency."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]


class SelectorImportTests(unittest.TestCase):
    def test_default_sqlite_selection_without_optional_driver(self):
        program = r"""
import builtins, sys
sys.path.insert(0, sys.argv[1])
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


if __name__ == '__main__':
    unittest.main()
