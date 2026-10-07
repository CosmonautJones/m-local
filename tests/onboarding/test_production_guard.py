"""Production configuration guard: opt-in, loud, and never prints setting values."""
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

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
        onboarding = self.data / 'onboarding'
        onboarding.mkdir()
        (onboarding / 'code.key').write_bytes(b'x' * 32)
        with closing(sqlite3.connect(onboarding / 'onboarding.sqlite3')) as db:
            db.execute('CREATE TABLE accounts (actor TEXT, email TEXT, kind TEXT, name TEXT)')
            db.execute('CREATE TABLE business_owners (actor TEXT, slug TEXT, active INTEGER)')
            db.execute('CREATE TABLE drafts (actor TEXT, body TEXT, updated REAL)')
            db.commit()
        signing = self.data / 'native'
        signing.mkdir()
        (signing / 'jwt_secret').write_bytes(b'x' * 64)
        photos = self.data / 'photos'
        photos.mkdir()
        (self.root / '.jac').mkdir()
        (self.root / 'assets').mkdir()
        (self.root / '.jac/data').symlink_to(signing, target_is_directory=True)
        (self.root / 'assets/photos').symlink_to(photos, target_is_directory=True)
        from services.production_guard import _mounted_volume
        self.mount_parser = _mounted_volume
        mount = patch('services.production_guard._mounted_volume', return_value=True)
        mount.start()
        self.addCleanup(mount.stop)
        self.good = {
            'MLOCAL_ENV': 'production', 'MLOCAL_ONBOARDING_DIR': str(onboarding),
            'MLOCAL_DURABLE_ROOT': str(self.data),
            'JAC_DB_URL': 'postgresql://fixture:fixture-secret@example.test/native',
            'MLOCAL_SHOW_SAMPLES': '0', 'MLOCAL_PUBLIC_INGRESS': 'restricted',
            'MLOCAL_DEPLOYMENT_TOPOLOGY': 'single-instance-serialized', 'MLOCAL_APP_REPLICAS': '1',
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
        directory = Path(self.good['MLOCAL_ONBOARDING_DIR'])
        directory.chmod(0o500)
        self.addCleanup(directory.chmod, 0o700)
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

    def test_writable_directory_is_not_mount_or_durability_proof(self):
        with patch('services.production_guard._mounted_volume', return_value=False):
            self.assertTrue(any('persistent-volume mount' in p for p in self.problems()))

    def test_each_policy_setting_is_required(self):
        for name in ('JAC_DB_URL', 'MLOCAL_DURABLE_ROOT', 'MLOCAL_PUBLIC_INGRESS',
                     'MLOCAL_DEPLOYMENT_TOPOLOGY', 'MLOCAL_APP_REPLICAS', 'MLOCAL_SHOW_SAMPLES'):
            self.assertTrue(any(name in p for p in self.problems(**{name: ''})), name)
        self.assertTrue(any('JAC_DEV_SOURCE' in p for p in self.problems(JAC_DEV_SOURCE='secret-override')))
        self.assertTrue(any('MLOCAL_APP_REPLICAS' in p for p in self.problems(MLOCAL_APP_REPLICAS='2')))
        self.assertTrue(any('MLOCAL_SHOW_SAMPLES' in p for p in self.problems(MLOCAL_SHOW_SAMPLES='true')))

    def test_missing_or_short_keys_refuse_without_creating_replacements(self):
        code = Path(self.good['MLOCAL_ONBOARDING_DIR']) / 'code.key'
        signing = self.root / '.jac/data/jwt_secret'
        for path in (code, signing):
            with self.subTest(path=path.name):
                data = path.read_bytes()
                path.unlink()
                self.assertTrue(self.problems())
                self.assertFalse(path.exists())
                path.write_bytes(b'short')
                self.assertTrue(self.problems())
                path.write_bytes(data)

    def test_state_symlink_outside_volume_is_rejected(self):
        photos = self.root / 'assets/photos'
        photos.unlink()
        outside = Path(self.good['MLOCAL_DURABLE_ROOT']).parent / 'ephemeral-photos'
        outside.mkdir()
        photos.symlink_to(outside, target_is_directory=True)
        self.assertTrue(any('photo storage' in p for p in self.problems()))

    def test_database_and_smtp_validation_redacts_values(self):
        for value in ('', 'sqlite:///secret-value', 'postgresql://secret:secret@host:bad/native'):
            self.assertTrue(any('JAC_DB_URL' in p for p in self.problems(JAC_DB_URL=value)))
        self.assertTrue(any('MLOCAL_SMTP_PORT' in p for p in self.problems(MLOCAL_SMTP_PORT='bad-secret-port')))
        with self.assertRaises(ProductionConfigError) as caught:
            enforce_production_config({**self.good, 'JAC_DB_URL': 'secret-value', 'MLOCAL_SMTP_PORT': 'secret-port'}, self.root)
        self.assertNotIn('secret-value', str(caught.exception))
        self.assertNotIn('secret-port', str(caught.exception))

    def test_empty_sqlite_and_missing_photo_ownership_are_not_recovery(self):
        database = Path(self.good['MLOCAL_ONBOARDING_DIR']) / 'onboarding.sqlite3'
        original = database.read_bytes()
        database.write_bytes(b'')
        self.assertTrue(any('original code.key' in p for p in self.problems()))
        database.write_bytes(original)
        (self.root / 'assets/photos/fixture.jpg').write_bytes(b'fixture')
        self.assertTrue(any('photo-ownership.sqlite3' in p for p in self.problems()))

    def test_malformed_path_is_redacted_at_enforcement_boundary(self):
        with self.assertRaises(ProductionConfigError) as caught:
            enforce_production_config({**self.good, 'MLOCAL_DURABLE_ROOT': '\x00private-secret-path'}, self.root)
        self.assertNotIn('private-secret-path', str(caught.exception))

    def test_nested_ephemeral_mounts_are_rejected_at_every_actual_state_leaf(self):
        leaves = (Path(self.good['MLOCAL_ONBOARDING_DIR']),
                  (self.root / '.jac/data').resolve(), (self.root / 'assets/photos').resolve())
        for filesystem in ('tmpfs', 'overlay'):
            for leaf in leaves:
                with self.subTest(filesystem=filesystem, leaf=leaf.name):
                    # A persistent root mount may contain an ephemeral submount.
                    mounts = ('10 1 8:1 / ' + str(self.data) + ' rw - ext4 /dev/fixture rw\n' +
                              '11 10 0:1 / ' + str(leaf) + ' rw - ' + filesystem + ' fixture rw\n')
                    # Bypass setUp's successful-volume stand-in and execute the
                    # actual parser for these synthetic mountinfo records.
                    from services import production_guard
                    parser = self.mount_parser
                    with patch('pathlib.Path.read_text', return_value=mounts), patch.object(production_guard, '_mounted_volume', parser):
                        self.assertTrue(self.problems(), 'Ephemeral ' + leaf.name + ' must refuse startup')

    def test_required_state_file_symlinks_cannot_escape_the_durable_volume(self):
        for relative in ('onboarding/code.key', 'native/jwt_secret', 'onboarding/onboarding.sqlite3'):
            path = self.data / relative
            outside = self.data.parent / ('outside-' + path.name)
            original = path.read_bytes()
            outside.write_bytes(original)
            path.unlink()
            path.symlink_to(outside)
            try:
                with self.subTest(file=path.name):
                    self.assertTrue(self.problems(), 'Escaped required file must refuse startup')
            finally:
                path.unlink()
                path.write_bytes(original)
                outside.unlink()

    def test_effective_native_data_override_and_configured_key_preserve_the_original_secret(self):
        native_base = self.data / 'preserved-native-base'
        signing = native_base / '.jac/data'
        signing.mkdir(parents=True)
        original = (self.data / 'native/jwt_secret').read_bytes()
        (signing / 'jwt_secret').write_bytes(original)
        self.assertEqual(self.problems(JAC_DATA_PATH=str(native_base)), [])
        self.assertTrue(any('JAC_DATA_PATH' in p for p in self.problems(JAC_DATA_PATH='relative-secret-path')))
        self.assertEqual(self.problems(JAC_SERVE_AUTH_SECRET=original.decode()), [])
        self.assertTrue(any('JAC_SERVE_AUTH_SECRET' in p for p in self.problems(JAC_SERVE_AUTH_SECRET='another-private-key')))
        self.assertTrue(any('ALGORITHM' in p for p in self.problems(JAC_SERVE_AUTH_ALGORITHM='unsupported')))

    def test_invalid_typed_auth_configuration_fails_with_redacted_configuration_error(self):
        for text in ('[serve.auth]\nsecret = 42\n', '[serve.auth]\nalgorithm = 42\n',
                     'serve = 42\n', '[serve]\nauth = 42\n'):
            with self.subTest(configuration=text):
                (self.root / 'jac.toml').write_text(text)
                with self.assertRaises(ProductionConfigError) as caught:
                    enforce_production_config(self.good, self.root)
                self.assertIn('[serve.auth]', str(caught.exception))
                self.assertNotIn(str(self.root), str(caught.exception))
                self.assertNotIn('42', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
