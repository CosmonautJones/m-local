"""Pure and root-host tests for consuming the authenticated UI dependencies."""

from pathlib import Path
import ast
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / 'prepare-fresh-ui-dependencies.py'
GENERATOR = ROOT / 'generate-ui-dependency-lock.py'
NODE_CONTROL = ROOT / 'run-fresh-node-client-control.py'
NODE_TEST = ROOT / 'test-node-client-control.py'
PREFLIGHT = ROOT / 'verify-package-preflight.py'
SOURCE_TEST = ROOT / 'test-source-isolation.py'
RUNNER = ROOT / 'run-fresh-source.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class FakeTools:
    MAX_TARBALL_BYTES = 8 * 1024 * 1024
    MAX_LOCK_BYTES = 4 * 1024 * 1024

    def __init__(self, bad_download=False):
        self.bad_download = bad_download

    @staticmethod
    def _owned_dir(path):
        path = Path(path)
        path.mkdir(mode=0o700)
        return path

    @staticmethod
    def _write_bytes(path, raw, mode=0o600, owner=(65534, 65534)):
        path = Path(path)
        path.write_bytes(raw)
        path.chmod(mode)

    def _download(self, _url, _integrity, destination, _deadline, _total):
        Path(destination).write_bytes(b'bad')
        return (3, '0' * 64, None)

    @staticmethod
    def _safe_env(*_args, **_kwargs):
        return {}

    @staticmethod
    def _remaining(_deadline):
        return 60

    @staticmethod
    def _private_log(_path, **_kwargs):
        return None

    @staticmethod
    def _parse_smoke(_raw):
        return {'ok': 1, 'uid': 65534, 'gid': 65534, 'euid': 65534, 'egid': 65534, 'groups': []}

    @staticmethod
    def _read_bounded(path, _maximum):
        return Path(path).read_bytes()

    @staticmethod
    def _inventory(_path):
        return ('inventory', 1, 2)

    @staticmethod
    def _sha(raw):
        return sha(raw)

    @staticmethod
    def validate_tarball(_raw, _integrity):
        return None


class PureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control = load(CONTROL, 'ui_dependency_consumer_control')

    @staticmethod
    def authenticated_preflight(control, overrides=None):
        overrides = overrides or {}
        calls = []

        def checked_checkout(root, commit):
            calls.append(('checkout', root, commit))

        def committed_file(root, commit, relative):
            calls.append(('file', relative))
            if relative in overrides:
                return overrides[relative]
            return (root / relative).read_bytes()

        return dict(checked_checkout=checked_checkout, committed_file=committed_file), calls

    def test_load_inputs_authenticates_frozen_rows_and_probe_source(self):
        preflight, calls = self.authenticated_preflight(self.control)
        tools, node_control, files, receipt, smoke = self.control.load_inputs(preflight, 'HEAD')
        self.assertEqual(calls[0][0], 'checkout')
        self.assertEqual(len([item for item in calls if item[0] == 'file']), 5)
        self.assertEqual(len(tools.parse_lock(files['package-lock.json'])), 39)
        self.assertEqual(len(receipt['tarballs']), 39)
        self.assertEqual(node_control.NODE_VERSION, '22.16.0')
        self.assertIn('/proc/self/status', smoke)
        self.assertIn("require('jsdom')", smoke)
        self.assertEqual(tools.PACKAGE_RAW, files['package.json'])

    def test_load_inputs_rejects_code_pin_before_dynamic_import(self):
        relative = self.control.GENERATOR
        raw = (self.control.ROOT / relative).read_bytes()
        preflight, calls = self.authenticated_preflight(self.control, {relative: raw + b'\n'})
        with self.assertRaisesRegex(ValueError, 'code pin'):
            self.control.load_inputs(preflight, 'HEAD')
        self.assertEqual([item[1] for item in calls if item[0] == 'file'], [relative])

    def test_invalid_deadline_rejects_before_workspace_or_command(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary) / 'workspace'
            directory.mkdir()
            commands = []
            runner = {'E_ROOT': Path(temporary), 'run_command': lambda *args, **kwargs: commands.append(args)}
            for timeout in (0, -1, 361, True, 1.5):
                with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, 'deadline'):
                    self.control.prepare_dependencies({}, runner, directory, 'HEAD', {}, timeout)
            self.assertEqual(list(directory.iterdir()), [])
            self.assertEqual(commands, [])

    def test_node_binding_rejects_before_workspace_write(self):
        fake_tools = FakeTools()
        fake_frozen = {'tarballs': []}
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary) / 'workspace'
            directory.mkdir()
            runner = {'E_ROOT': Path(temporary), 'run_command': lambda *args, **kwargs: self.fail('command ran')}
            with patch.object(self.control, 'load_inputs', return_value=(
                    fake_tools, object(), {'package.json': b'{}', 'package-lock.json': b'{}'}, fake_frozen, 'smoke')), \
                    patch.object(self.control, 'mount_identity', return_value=[1, 2]), \
                    patch.object(self.control, 'node_binding', side_effect=ValueError('Node input binding')):
                with self.assertRaisesRegex(ValueError, 'Node input binding'):
                    self.control.prepare_dependencies({}, runner, directory, 'HEAD', {}, 60)
            self.assertEqual(list(directory.iterdir()), [])

    def test_download_byte_hash_mismatch_precedes_npm_commands(self):
        fake_tools = FakeTools(bad_download=True)
        fake_frozen = {
            'tarballs': [dict(url='https://registry.npmjs.org/fixture/-/fixture-1.0.0.tgz',
                              integrity='sha512-' + 'A' * 88, bytes=3, sha256='1' * 64)],
            'node_client_inventory_sha256': 'node-inventory',
            'node_binary_sha256': 'node-binary',
        }
        files = {'package.json': b'{}', 'package-lock.json': b'{}'}
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary) / 'workspace'
            directory.mkdir()
            commands = []
            runner = {'E_ROOT': Path(temporary), 'run_command': lambda *args, **kwargs: commands.append(args)}
            with patch.object(self.control, 'load_inputs', return_value=(fake_tools, object(), files, fake_frozen, 'smoke')), \
                    patch.object(self.control, 'mount_identity', return_value=[1, 2]), \
                    patch.object(self.control, 'node_binding', return_value=(Path(temporary) / 'clients', {})):
                with self.assertRaisesRegex(ValueError, 'downloaded input'):
                    self.control.prepare_dependencies({}, runner, directory, 'HEAD', {}, 60)
            self.assertEqual(commands, [])
            self.assertEqual(list(directory.rglob('*.log')), [])

    def test_mount_identity_change_stops_after_first_command(self):
        fake_tools = FakeTools()
        fake_frozen = {'tarballs': [], 'node_client_inventory_sha256': 'i', 'node_binary_sha256': 'b'}
        files = {'package.json': b'{}', 'package-lock.json': b'{}'}
        states = iter(([1, 2], [1, 2], [9, 9]))
        commands = []

        def run_command(label, command, **kwargs):
            commands.append((label, command))
            Path(kwargs['log']).write_bytes(b'command')

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary) / 'workspace'
            directory.mkdir()
            runner = {'E_ROOT': Path(temporary), 'run_command': run_command}
            with patch.object(self.control, 'load_inputs', return_value=(fake_tools, object(), files, fake_frozen, 'smoke')), \
                    patch.object(self.control, 'mount_identity', side_effect=lambda *_args: next(states)), \
                    patch.object(self.control, 'node_binding', return_value=(Path(temporary) / 'clients', {'node': 'bound'})):
                with self.assertRaisesRegex(ValueError, 'mount changed'):
                    self.control.prepare_dependencies({}, runner, directory, 'HEAD', {}, 60)
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][0], 'ui-offline-ci')
            self.assertFalse((directory / 'prepared-ui-inputs.json').exists())

    def _verify_fixture(self, temporary):
        directory = Path(temporary) / 'workspace'
        workspace = directory / 'workspace'
        install = workspace / 'install'
        modules = install / 'node_modules'
        modules.mkdir(parents=True)
        (install / 'package.json').write_bytes(b'{}')
        (install / 'package-lock.json').write_bytes(b'{}')
        for name in ['ui-cache-' + str(index) + '.log' for index in range(39)] + ['ui-offline-ci.log', 'ui-dom-smoke.log']:
            (directory / name).write_bytes(b'log')
        expected_logs = ['ui-cache-' + str(index) + '.log' for index in range(39)] + ['ui-offline-ci.log', 'ui-dom-smoke.log']
        frozen = {'tarballs': [], 'installed_inventory_sha256': 'inventory', 'installed_file_count': 1,
                  'installed_file_bytes': 2, 'node_client_inventory_sha256': 'node', 'node_binary_sha256': 'bin'}
        files = {'package.json': b'{}', 'package-lock.json': b'{}'}
        prepared = dict(schema=self.control.SCHEMA, status='dependencies_prepared', application_tests_executed=False,
                        package_commit='HEAD', mount_identity=[1, 2],
                        frozen_inputs_sha256={name: pin for name, (_, pin) in self.control.INPUTS.items()},
                        generator_sha256=self.control.GENERATOR_SHA, node_control_sha256=self.control.NODE_CONTROL_SHA,
                        installed_inventory_sha256='inventory', installed_file_count=1, installed_file_bytes=2,
                        node_binding={'node': 'bound'}, uid=65534, gid=65534, euid=65534, egid=65534,
                        supplementary_groups=[], smoke={'status': 'passed', 'ok': 1}, logs=expected_logs,
                        receipt_path=directory / 'prepared-ui-inputs.json', install_directory=install,
                        modules_directory=modules)
        receipt = {key: value for key, value in prepared.items()
                   if key not in {'receipt_path', 'receipt_sha256', 'install_directory', 'modules_directory'}}
        raw = json.dumps(receipt, sort_keys=True).encode() + b'\n'
        prepared['receipt_sha256'] = sha(raw)
        prepared['receipt_path'].write_bytes(raw)
        return directory, install, modules, files, frozen, prepared

    def test_verify_rejects_receipt_and_inventory_mutations(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory, install, modules, files, frozen, prepared = self._verify_fixture(temporary)
            fake_tools = FakeTools()
            fake_tools._inventory = lambda _path: ('inventory', 1, 2)
            fake_tools._private_receipt = lambda path, expected, _label: (
                Path(path).read_bytes() if sha(Path(path).read_bytes()) == expected else (_ for _ in ()).throw(ValueError('receipt hash')))
            fake_tools._json = lambda raw, _label: json.loads(raw)
            with patch.object(self.control, 'load_inputs', return_value=(fake_tools, object(), files, frozen, 'smoke')), \
                    patch.object(self.control, 'mount_identity', return_value=[1, 2]), \
                    patch.object(self.control, 'check_workspace'), patch.object(self.control, 'check_tarballs'), \
                    patch.object(self.control, 'node_binding', return_value=(Path(temporary) / 'clients', prepared['node_binding'])):
                self.assertEqual(self.control.verify_prepared({}, {'E_ROOT': Path(temporary)}, directory,
                                                               prepared, 'HEAD', {}), prepared)
                prepared['receipt_path'].write_bytes(prepared['receipt_path'].read_bytes() + b'changed')
                with self.assertRaisesRegex(ValueError, 'receipt hash'):
                    self.control.verify_prepared({}, {'E_ROOT': Path(temporary)}, directory,
                                                 prepared, 'HEAD', {})
                prepared['receipt_path'].write_bytes(raw := json.dumps(
                    {key: value for key, value in prepared.items()
                     if key not in {'receipt_path', 'receipt_sha256', 'install_directory', 'modules_directory'}},
                    sort_keys=True).encode() + b'\n')
                prepared['receipt_sha256'] = sha(raw)
                fake_tools._inventory = lambda _path: ('changed', 1, 2)
                with self.assertRaisesRegex(ValueError, 'installed inventory'):
                    self.control.verify_prepared({}, {'E_ROOT': Path(temporary)}, directory,
                                                 prepared, 'HEAD', {})

    def test_root_fixture_uses_an_independent_node_wrapper(self):
        source = Path(__file__).read_text(encoding='utf-8')
        self.assertIn("fixture_owner = self.node_tests.LinuxRootTests('runTest')", source)
        self.assertIn('fixture = fixture_owner.fixture()', source)
        self.assertIn('fixture_owner.cleanup_fixture(*fixture)', source)
        self.assertNotIn('self.node_tests.LinuxRootTests.' + 'fixture(self)', source)
        self.assertNotIn('self.node_tests.LinuxRootTests.' + 'cleanup_fixture(self', source)


class LinuxRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'posix' or os.geteuid() != 0:
            raise AssertionError('LinuxRootTests require a root Linux CI host')
        cls.control = load(CONTROL, 'ui_dependency_root_control')
        cls.generator = load(GENERATOR, 'ui_dependency_root_generator')
        cls.node_control = load(NODE_CONTROL, 'ui_dependency_root_node_control')
        cls.node_tests = load(NODE_TEST, 'ui_dependency_root_node_tests')
        cls.preflight_module = load(PREFLIGHT, 'ui_dependency_root_preflight')
        cls.source_tests = load(SOURCE_TEST, 'ui_dependency_root_source_tests')
        tree = ast.parse(RUNNER.read_text(encoding='utf-8'))
        nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef))]
        namespace = {'__file__': str(RUNNER), '__name__': 'ui_dependency_root_runner'}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER), 'exec'), namespace)
        cls.runner_namespace = namespace

    def command(self, argv, *, text=False):
        argv = list(argv)
        if (len(argv) >= 3 and argv[:2] == ['/usr/bin/truncate', '-s'] and
                argv[2] == str(64 * 1024 ** 2)):
            argv[2] = str(512 * 1024 ** 2)
        return self.source_tests.LinuxRootTests.command(self, argv, text=text)

    def ui_alias(self, e_root):
        token = hashlib.sha256(os.urandom(32)).hexdigest()[:8]
        alias = Path('/var/tmp') / (self.control.PREFIX + token)
        backing = Path(e_root) / alias.name
        self.assertFalse(alias.exists())
        self.assertFalse(backing.exists())
        try:
            backing.mkdir(mode=0o700)
            os.chown(backing, 65534, 65534)
            alias.mkdir(mode=0o700)
            os.chown(alias, 65534, 65534)
            self.command(['/usr/bin/mount', '--bind', str(backing), str(alias)])
            self.assertTrue(alias.is_mount())
            return alias, backing
        except BaseException:
            if alias.is_mount():
                subprocess.run(['/usr/bin/umount', str(alias)], check=False, timeout=30,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if alias.exists() and not alias.is_symlink() and alias.parent == Path('/var/tmp'):
                alias.rmdir()
            if backing.exists() and not backing.is_symlink() and backing.parent == Path(e_root):
                backing.rmdir()
            raise

    def cleanup_ui_alias(self, alias, backing, e_root):
        if alias is None:
            return
        if alias.parent != Path('/var/tmp') or not alias.name.startswith(self.control.PREFIX) or alias.is_symlink():
            self.fail('unsafe UI alias cleanup target')
        if (backing.parent != Path(e_root) or backing.name != alias.name or backing.is_symlink() or
                Path(e_root).is_symlink()):
            self.fail('unsafe UI backing cleanup target')
        if alias.is_mount():
            completed = subprocess.run(['/usr/bin/umount', str(alias)], check=False, timeout=30,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(completed.returncode, 0)
            self.assertFalse(alias.is_mount())
        if alias.exists():
            alias.rmdir()
        if backing.exists():
            shutil.rmtree(backing)

    def runner(self, directory, e_root):
        self.runner_namespace['PRIVATE_LOG_DIR'] = directory
        base = self.runner_namespace['run_command']

        def run_command(label, command, **kwargs):
            log = Path(kwargs['log'])
            fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            os.chown(log, 0, 0)
            os.chmod(log, 0o600)
            return base(label, self.generator._setpriv(command), **kwargs)

        return {'E_ROOT': e_root, 'minimal_environment': self.runner_namespace['minimal_environment'],
                'run_command': run_command}

    def preflight(self):
        commit = self.preflight_module.git(ROOT.parent, ['rev-parse', 'HEAD']).decode().strip()
        return vars(self.preflight_module), commit

    def test_real_root_prepares_offline_dependencies_and_rejects_receipt_tamper(self):
        fixture_owner = self.node_tests.LinuxRootTests('runTest')
        fixture_owner.setUpClass()
        fixture = fixture_owner.fixture()
        base, image, e_root, backing, original_alias, loop = fixture
        ui_alias = ui_backing = None
        try:
            ui_alias, ui_backing = self.ui_alias(e_root)
            preflight, commit = fixture_owner.preflight()
            node = fixture_owner.control.run_control(preflight, fixture_owner.runner(base, e_root),
                                                     original_alias, commit, 180)
            self.assertEqual(node['status'], 'passed')
            prepared = self.control.prepare_dependencies(preflight, self.runner(base, e_root), ui_alias,
                                                         commit, node, 180)
            self.assertEqual(prepared['status'], 'dependencies_prepared')
            self.assertFalse(prepared['application_tests_executed'])
            self.assertEqual(prepared['smoke'], {'status': 'passed', 'ok': 1})
            self.assertEqual(prepared['uid'], 65534)
            self.assertEqual(prepared['supplementary_groups'], [])
            receipt = Path(prepared['receipt_path'])
            raw = receipt.read_bytes()
            receipt.chmod(0o600)
            receipt.write_bytes(raw + b'tamper')
            receipt.chmod(0o400)
            with self.assertRaisesRegex(ValueError, 'private hash|receipt changed|receipt'):
                self.control.verify_prepared(preflight, self.runner(base, e_root), ui_alias,
                                             prepared, commit, node)
            receipt.chmod(0o600)
            receipt.write_bytes(raw)
            os.chown(receipt, 0, 0)
            receipt.chmod(0o400)
            self.assertEqual(self.control.verify_prepared(preflight, self.runner(base, e_root), ui_alias,
                                                          prepared, commit, node), prepared)
            installed_lock = Path(prepared['install_directory']) / 'package-lock.json'
            lock_raw = installed_lock.read_bytes()
            installed_lock.chmod(0o600)
            installed_lock.write_bytes(lock_raw + b'\n')
            with self.assertRaisesRegex(ValueError, 'installed input changed'):
                self.control.verify_prepared(preflight, self.runner(base, e_root), ui_alias,
                                             prepared, commit, node)
            installed_lock.write_bytes(lock_raw)
            os.chown(installed_lock, 65534, 65534)
            installed_lock.chmod(0o600)
            self.assertEqual(self.control.verify_prepared(preflight, self.runner(base, e_root), ui_alias,
                                                          prepared, commit, node), prepared)
            tarball = ui_alias / 'workspace/downloads/package-0.tgz'
            tar_raw = tarball.read_bytes()
            tarball.chmod(0o600)
            tarball.write_bytes(tar_raw + b'tamper')
            os.chown(tarball, 65534, 65534)
            tarball.chmod(0o400)
            with self.assertRaisesRegex(ValueError, 'download binding'):
                self.control.verify_prepared(preflight, self.runner(base, e_root), ui_alias,
                                             prepared, commit, node)
            tarball.chmod(0o600)
            tarball.write_bytes(tar_raw)
            os.chown(tarball, 65534, 65534)
            tarball.chmod(0o400)
            self.assertEqual(self.control.verify_prepared(preflight, self.runner(base, e_root), ui_alias,
                                                          prepared, commit, node), prepared)
            self.assertTrue(ui_alias.is_mount())
            self.assertFalse(ui_alias.is_symlink())
            self.assertEqual(ui_alias.resolve(), ui_alias)
            self.assertEqual((ui_alias.stat().st_dev, ui_alias.stat().st_ino),
                             (ui_backing.stat().st_dev, ui_backing.stat().st_ino))
            self.assertEqual((ui_backing.stat().st_uid, ui_backing.stat().st_gid,
                              stat.S_IMODE(ui_backing.stat().st_mode)), (65534, 65534, 0o700))
        finally:
            try:
                self.cleanup_ui_alias(ui_alias, ui_backing, e_root)
            finally:
                fixture_owner.cleanup_fixture(*fixture)


if __name__ == '__main__':
    unittest.main()
