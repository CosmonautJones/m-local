"""Pure tests for the authenticated UI dependency lock generator."""

from pathlib import Path
import base64
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / 'generate-ui-dependency-lock.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha512_integrity(raw):
    return 'sha512-' + base64.b64encode(hashlib.sha512(raw).digest()).decode('ascii')


class PureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control = load(CONTROL, 'ui_dependency_lock_control')
        cls.lock = cls._base_lock()
        cls.lock['packages']['node_modules/parse5'].pop('name')
        cls.lock['packages']['node_modules/jsdom/node_modules/whatwg-url'].pop('name')
        cls.raw = cls._encode(cls.lock)

    @classmethod
    def _integrity(cls, marker):
        return 'sha512-' + base64.b64encode(bytes([marker]) * 64).decode('ascii')

    @classmethod
    def _package(cls, name, version, url, integrity, **flags):
        value = {'name': name, 'version': version, 'resolved': url, 'integrity': integrity}
        value.update(flags)
        return value

    @classmethod
    def _base_lock(cls):
        return {
            'name': cls.control.PACKAGE_NAME,
            'version': cls.control.PACKAGE_VERSION,
            'lockfileVersion': 3,
            'requires': True,
            'packages': {
                '': {
                    'name': cls.control.PACKAGE_NAME,
                    'version': cls.control.PACKAGE_VERSION,
                    'dependencies': {'jsdom': cls.control.JSDOM_VERSION},
                },
                'node_modules/jsdom': cls._package(
                    'jsdom', cls.control.JSDOM_VERSION,
                    'https://registry.npmjs.org/jsdom/-/jsdom-26.1.0.tgz', cls.control.JSDOM_INTEGRITY),
                'node_modules/parse5': cls._package(
                    'parse5', '7.2.1', 'https://registry.npmjs.org/parse5/-/parse5-7.2.1.tgz', cls._integrity(1)),
                'node_modules/jsdom/node_modules/whatwg-url': cls._package(
                    'whatwg-url', '14.2.0', 'https://registry.npmjs.org/whatwg-url/-/whatwg-url-14.2.0.tgz',
                    cls._integrity(2)),
            },
        }

    @staticmethod
    def _encode(lock):
        return json.dumps(lock, sort_keys=True, indent=2).encode('utf-8') + b'\n'

    def assert_rejected(self, raw):
        with self.assertRaises(ValueError):
            self.control.parse_lock(raw)

    def test_package_raw_and_valid_lock_are_pinned_and_sorted(self):
        self.assertEqual(self.control.PACKAGE_RAW, b'''{
  "name": "m-local-ui-test-runtime",
  "version": "1.0.0",
  "private": true,
  "dependencies": {
    "jsdom": "26.1.0"
  }
}
''')
        rows = self.control.parse_lock(self.raw)
        self.assertEqual([row['path'] for row in rows], sorted(row['path'] for row in rows))
        self.assertEqual([row['name'] for row in rows], ['jsdom', 'whatwg-url', 'parse5'])
        self.assertEqual(set(rows[0]), {'path', 'name', 'version', 'url', 'integrity'})
        self.assertEqual(rows[0]['integrity'], self.control.JSDOM_INTEGRITY)
        self.assertEqual(rows[0]['url'], 'https://registry.npmjs.org/jsdom/-/jsdom-26.1.0.tgz')

    def test_lock_rejects_schema_root_and_size_mutations(self):
        cases = []
        value = copy.deepcopy(self.lock)
        value['name'] = 'wrong-header'
        cases.append(value)
        value = copy.deepcopy(self.lock)
        value['version'] = '0.0.0'
        cases.append(value)
        value = copy.deepcopy(self.lock)
        value['lockfileVersion'] = 3.0
        cases.append(value)
        value = copy.deepcopy(self.lock)
        value['requires'] = 1
        cases.append(value)
        value = copy.deepcopy(self.lock)
        value['lockfileVersion'] = 2
        cases.append(value)
        value = copy.deepcopy(self.lock)
        value['requires'] = False
        cases.append(value)
        value = copy.deepcopy(self.lock)
        value['packages']['']['name'] = 'wrong-root'
        cases.append(value)
        value = copy.deepcopy(self.lock)
        value['packages']['']['version'] = '2.0.0'
        cases.append(value)
        value = copy.deepcopy(self.lock)
        value['packages']['']['dependencies'] = {'jsdom': '^26.1.0'}
        cases.append(value)
        value = copy.deepcopy(self.lock)
        value['packages']['node_modules/jsdom']['version'] = 'latest'
        cases.append(value)
        for value in cases:
            with self.subTest(case=len(cases)):
                self.assert_rejected(self._encode(value))
        self.assert_rejected(b'{"lockfileVersion":3')
        self.assert_rejected(b'{"lockfileVersion":3,"lockfileVersion":3}')
        self.assert_rejected(b'0' * (self.control.MAX_LOCK_BYTES + 1))

    def test_lock_rejects_unsafe_paths_links_and_controls(self):
        cases = (
            'node_modules/../escape',
            '/node_modules/jsdom',
            'node_modules\\evil',
            'node_modules/./evil',
            'node_modules/@scope',
            'node_modules/@scope/pkg/extra',
            'node_modules/jsdom/node_modules/../escape',
            'node_modules/jsdom/node_modules/@scope/pkg/../escape',
        )
        for path in cases:
            value = copy.deepcopy(self.lock)
            name = path.rsplit('/', 1)[-1]
            value['packages'][path] = self._package(name, '1.0.0',
                                                     'https://registry.npmjs.org/' + name + '/-/' + name + '-1.0.0.tgz',
                                                     self._integrity(3))
            with self.subTest(path=path):
                self.assert_rejected(self._encode(value))
        for flag in ('link', 'bundled', 'hasInstallScript'):
            value = copy.deepcopy(self.lock)
            value['packages']['node_modules/parse5'][flag] = True
            with self.subTest(flag=flag):
                self.assert_rejected(self._encode(value))

    def test_lock_rejects_nonofficial_and_noncanonical_urls(self):
        urls = (
            'http://registry.npmjs.org/parse5/-/parse5-7.2.1.tgz',
            'https://evil.example/parse5/-/parse5-7.2.1.tgz',
            'https://user:pw@registry.npmjs.org/parse5/-/parse5-7.2.1.tgz',
            'https://registry.npmjs.org:443/parse5/-/parse5-7.2.1.tgz',
            'https://registry.npmjs.org/parse5/-/parse5-7.2.1.tgz?redirect=1',
            'https://registry.npmjs.org/parse5/-/parse5-7.2.1.tgz#redirect',
            'https://registry.npmjs.org/parse5/../escape.tgz',
            'https://registry.npmjs.org/%2e%2e/escape.tgz',
            'https://registry.npmjs.org/parse5//-/parse5-7.2.1.tgz',
            'https://REGISTRY.NPMJS.ORG/parse5/-/parse5-7.2.1.tgz',
            'https://registry.npmjs.org/parse5/-/parse5-7.2.1.zip',
        )
        for url in urls:
            value = copy.deepcopy(self.lock)
            value['packages']['node_modules/parse5']['resolved'] = url
            with self.subTest(url=url):
                self.assert_rejected(self._encode(value))

    def test_lock_rejects_integrity_and_cardinality_mutations(self):
        for integrity in ('sha256-' + 'A' * 88, 'sha512-not-base64', 'sha512-' + 'A' * 87):
            value = copy.deepcopy(self.lock)
            value['packages']['node_modules/parse5']['integrity'] = integrity
            with self.subTest(integrity=integrity):
                self.assert_rejected(self._encode(value))
        value = copy.deepcopy(self.lock)
        for index in range(self.control.MAX_PACKAGES):
            name = 'dep' + str(index)
            value['packages']['node_modules/' + name] = self._package(
                name, '1.0.0', 'https://registry.npmjs.org/' + name + '/-/' + name + '-1.0.0.tgz', self._integrity(4))
        self.assert_rejected(self._encode(value))

    @staticmethod
    def make_tarball(name='package/package.json'):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            body = b'{"name":"fixture"}\n'
            info = tarfile.TarInfo(name)
            info.size = len(body)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(body))
        return output.getvalue()

    @staticmethod
    def make_link_tarball():
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            info = tarfile.TarInfo('package/link')
            info.type = tarfile.SYMTYPE
            info.linkname = '../escape'
            archive.addfile(info)
        return output.getvalue()

    def test_validate_tarball_checks_integrity_size_and_safe_members(self):
        raw = self.make_tarball()
        self.assertIsNone(self.control.validate_tarball(raw, sha512_integrity(raw)))
        tampered = bytearray(raw)
        tampered[-1] ^= 1
        with self.assertRaises(ValueError):
            self.control.validate_tarball(bytes(tampered), sha512_integrity(raw))
        for value in (b'', b'x' * (self.control.MAX_TARBALL_BYTES + 1)):
            with self.subTest(size=len(value)), self.assertRaises(ValueError):
                self.control.validate_tarball(value, sha512_integrity(value))
        unsafe = self.make_tarball('../escape')
        with self.assertRaises(ValueError):
            self.control.validate_tarball(unsafe, sha512_integrity(unsafe))
        unsafe_link = self.make_link_tarball()
        with self.assertRaises(ValueError):
            self.control.validate_tarball(unsafe_link, sha512_integrity(unsafe_link))

    def test_safe_environment_scrubs_private_values_and_forces_cache_policy(self):
        runner = {'minimal_environment': lambda: {
            'PATH': '/original/bin', 'HOME': '/original/home', 'LANG': 'C', 'LC_ALL': 'C',
            'PYTHONDONTWRITEBYTECODE': '1', 'GIT_TERMINAL_PROMPT': '0',
            'GIT_CONFIG_NOSYSTEM': '0', 'GIT_CONFIG_GLOBAL': '/bad/config',
            'MLOCAL_SECRET': 'private', 'HTTPS_PROXY': 'http://proxy.invalid',
            'NPM_CONFIG_USERCONFIG': '/bad/user', 'NPM_CONFIG_CACHE': '/bad/cache',
            'AWS_TOKEN': 'private', 'PASSWORD': 'private',
        }}
        cache = Path('/tmp/ui-lock-cache')
        home = Path('/tmp/ui-lock-home')
        folder = Path('/tmp/ui-lock-node')
        environment = self.control._safe_env(runner, cache=cache, home=home, folder=folder, offline=False)
        self.assertEqual(environment['PATH'], str(folder / 'bin') + ':/usr/bin:/bin')
        self.assertEqual(environment['HOME'], str(home))
        self.assertEqual(environment['NPM_CONFIG_CACHE'], str(cache))
        self.assertEqual(environment['npm_config_cache'], str(cache))
        self.assertEqual(environment['NPM_CONFIG_USERCONFIG'], '/dev/null')
        for key in ('MLOCAL_SECRET', 'HTTPS_PROXY', 'NPM_CONFIG_USERCONFIG', 'AWS_TOKEN', 'PASSWORD'):
            if key != 'NPM_CONFIG_USERCONFIG':
                self.assertNotIn(key, environment)
        self.assertNotIn('npm_config_offline', environment)
        offline = self.control._safe_env(runner, cache=cache, home=home, folder=folder, offline=True)
        self.assertEqual(offline['COREPACK_ENABLE_NETWORK'], '0')
        self.assertEqual(offline['npm_config_offline'], 'true')
        self.assertEqual(offline['NPM_CONFIG_OFFLINE'], 'true')

    def test_preflight_pin_rejects_tamper_before_dynamic_import_or_output(self):
        preflight_path = self.control.CHECKOUT / self.control.PREFLIGHT_RELATIVE
        original_read = self.control._read_bounded

        def tampered_read(path, maximum, *, allow_empty=False):
            raw = original_read(path, maximum, allow_empty=allow_empty)
            if Path(path) == preflight_path:
                return raw + b'\n# tampered'
            return raw

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary) / 'dependency-output'
            with patch.object(self.control, '_read_bounded', side_effect=tampered_read), \
                    patch.object(self.control, '_load_verified', side_effect=AssertionError('dynamic import')) as loader:
                with self.assertRaises(ValueError):
                    self.control.generate(output, 'a' * 40)
            loader.assert_not_called()
            self.assertFalse(output.exists())

    def test_failed_preparation_runs_strict_cleanup_before_publishing_output(self):
        expected_commit = 'a' * 40
        events = []
        cleanup_calls = []

        def checked_checkout(checkout, commit):
            events.append(('checked_checkout', Path(checkout), commit))

        def committed_file(checkout, commit, relative):
            events.append(('committed_file', relative))
            return (Path(checkout) / relative).read_bytes()

        preflight_module = SimpleNamespace(checked_checkout=checked_checkout, committed_file=committed_file)

        def run_control(*_args, **_kwargs):
            events.append(('run_control',))
            raise RuntimeError('simulated preparation failure')

        class FakeLinuxRootTests:
            control = SimpleNamespace(run_control=run_control)

            def __init__(self, *_args):
                pass

            @classmethod
            def setUpClass(cls):
                events.append(('fixture_setup',))

            def fixture(self):
                events.append(('fixture_created',))
                return tuple(Path(ROOT) / ('fake-fixture-' + str(index)) for index in range(6))

            def preflight(self):
                events.append(('fixture_preflight',))
                return {}, expected_commit

            def runner(self, base, e_root):
                events.append(('runner_created', base, e_root))
                return {}

            def cleanup_fixture(self, *fixture, strict=False):
                cleanup_calls.append((fixture, strict))
                raise RuntimeError('simulated cleanup failure')

        node_tests_module = SimpleNamespace(LinuxRootTests=FakeLinuxRootTests)

        def fake_load(path, name):
            if name == 'ui_dependency_preflight':
                return preflight_module
            if name == 'ui_dependency_node_tests':
                return node_tests_module
            raise AssertionError('unexpected dynamic import ' + name)

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary) / 'dependency-output'
            with patch.object(self.control, '_load_verified', side_effect=fake_load):
                with self.assertRaisesRegex(RuntimeError, 'simulated cleanup failure'):
                    self.control.generate(output, expected_commit)
            self.assertFalse(output.exists())
            self.assertEqual(len(cleanup_calls), 1)
            self.assertIs(cleanup_calls[0][1], True)
            self.assertIn(('run_control',), events)
            self.assertEqual(events[-1], ('run_control',))


if __name__ == '__main__':
    unittest.main()
