"""Production configuration guard: opt-in, loud, and never prints setting values."""
import os
import tempfile
import unittest
from pathlib import Path

from services.production_guard import (
    ProductionConfigError, enforce_production_config, is_production, validate_production_config,
)


class GuardTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name) / 'app'
        self.root.mkdir()
        self.data = Path(scratch.name) / 'data'
        self.data.mkdir()
        self.good = {
            'MLOCAL_ENV': 'production', 'MLOCAL_ONBOARDING_DIR': str(self.data),
            'MLOCAL_SMTP_HOST': 'smtp.example.test',
            'MLOCAL_SMTP_FROM': 'a@example.test', 'MLOCAL_SMTP_USERNAME': 'user', 'MLOCAL_SMTP_PASSWORD': 'pw-value',
        }

    def problems(self, **changes):
        env = {**self.good, **changes}
        return validate_production_config({k: v for k, v in env.items() if v is not None}, self.root)

    def test_not_production_is_a_no_op_even_with_nothing_configured(self):
        self.assertEqual(validate_production_config({}, self.root), [])
        self.assertEqual(validate_production_config({'MLOCAL_ENV': 'development'}, self.root), [])
        enforce_production_config({}, self.root)
        self.assertFalse(is_production({}))

    def test_production_flag_is_case_and_space_insensitive(self):
        self.assertTrue(is_production({'MLOCAL_ENV': ' Production '}))

    def test_complete_configuration_passes(self):
        self.assertEqual(self.problems(), [])
        enforce_production_config({**self.good}, self.root)

    def test_missing_onboarding_dir_relative_and_default_paths_fail(self):
        self.assertTrue(any('MLOCAL_ONBOARDING_DIR is not set' in p for p in self.problems(MLOCAL_ONBOARDING_DIR=None)))
        self.assertTrue(any('absolute' in p for p in self.problems(MLOCAL_ONBOARDING_DIR='.jac/onboarding')))
        self.assertTrue(any('absolute' in p for p in self.problems(MLOCAL_ONBOARDING_DIR='data')))

    def test_dir_inside_or_equal_to_the_app_source_fails(self):
        inside = self.root / '.jac' / 'onboarding'
        inside.mkdir(parents=True)
        for path in (self.root, inside):
            self.assertTrue(any('outside the application source' in p for p in self.problems(MLOCAL_ONBOARDING_DIR=str(path))))

    @unittest.skipIf(os.name == 'nt', 'symlinks need privileges on Windows')
    def test_symlink_into_the_app_source_is_resolved(self):
        link = self.data / 'link'
        os.symlink(self.root, link)
        self.assertTrue(any('outside the application source' in p for p in self.problems(MLOCAL_ONBOARDING_DIR=str(link))))

    def test_missing_directory_fails(self):
        self.assertTrue(any('existing directory' in p for p in self.problems(MLOCAL_ONBOARDING_DIR=str(self.data / 'nope'))))

    @unittest.skipIf(os.name == 'nt' or (hasattr(os, 'geteuid') and os.geteuid() == 0), 'needs a non-root POSIX user')
    def test_unwritable_directory_fails(self):
        self.data.chmod(0o500)
        self.addCleanup(self.data.chmod, 0o700)
        self.assertTrue(any('not writable' in p for p in self.problems()))

    def test_each_missing_smtp_setting_is_named(self):
        for name in ('MLOCAL_SMTP_HOST', 'MLOCAL_SMTP_FROM', 'MLOCAL_SMTP_USERNAME', 'MLOCAL_SMTP_PASSWORD'):
            with self.subTest(name=name):
                self.assertTrue(any(name in p for p in self.problems(**{name: ''})))

    def test_demo_settings_must_be_off(self):
        self.assertTrue(any('MLOCAL_DEMO_MODE' in p for p in self.problems(MLOCAL_DEMO_MODE='1')))
        self.assertEqual(self.problems(MLOCAL_DEMO_MODE='0'), [])
        self.assertTrue(any('MLOCAL_DEMO_STUDENTS' in p for p in self.problems(MLOCAL_DEMO_STUDENTS='["x"]')))
        self.assertEqual(self.problems(MLOCAL_DEMO_STUDENTS='[]'), [])
        self.assertTrue(any('MLOCAL_DEMO_COMPANIES' in p for p in self.problems(MLOCAL_DEMO_COMPANIES='30')))

    def test_all_problems_are_reported_together_and_values_never_appear(self):
        env = {'MLOCAL_ENV': 'production', 'MLOCAL_SMTP_PASSWORD': 'hunter2-password', 'MLOCAL_ONBOARDING_DIR': 'relative/secret-path',
               'MLOCAL_DEMO_MODE': 'yes'}
        with self.assertRaises(ProductionConfigError) as caught:
            enforce_production_config(env, self.root)
        message = str(caught.exception)
        for value in ('hunter2-password', 'relative/secret-path'):
            self.assertNotIn(value, message)
        for name in ('MLOCAL_ONBOARDING_DIR', 'MLOCAL_SMTP_HOST', 'MLOCAL_DEMO_MODE'):
            self.assertIn(name, message)


if __name__ == '__main__':
    unittest.main()
