"""Pure and Linux-root tests for the committed source-isolation control."""

from pathlib import Path, PurePosixPath
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
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / 'run-fresh-source-isolation.py'
HELPER = ROOT / 'native-inputs/runtime-build-source-isolation-v1.py'
PROBE = ROOT / 'native-inputs/test-runtime-build-source-isolation-v1.py'
PREFLIGHT = ROOT / 'verify-package-preflight.py'
RUNNER = ROOT / 'run-fresh-source.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_runner_definitions():
    tree = ast.parse(RUNNER.read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign,
                                                              ast.AnnAssign, ast.FunctionDef))]
    namespace = {'__file__': str(RUNNER), '__name__': 'source_isolation_test_runner'}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER), 'exec'), namespace)
    return namespace


class ReceiptPath:
    def __init__(self, value):
        self.value = PurePosixPath(str(value).replace('\\', '/')).as_posix()

    @property
    def parent(self):
        return ReceiptPath(PurePosixPath(self.value).parent)

    @property
    def name(self):
        return PurePosixPath(self.value).name

    def __truediv__(self, value):
        return ReceiptPath(PurePosixPath(self.value, str(value)))

    def __str__(self):
        return self.value

    def __fspath__(self):
        return self.value

    def __repr__(self):
        return 'ReceiptPath(%r)' % self.value

    def __eq__(self, other):
        return isinstance(other, ReceiptPath) and self.value == other.value

    def __hash__(self):
        return hash(self.value)

    def is_absolute(self):
        return self.value.startswith('/')

    def resolve(self):
        return self

    def is_symlink(self):
        return False

    def is_dir(self):
        return True

    def stat(self):
        return SimpleNamespace(st_uid=65534, st_gid=65534, st_mode=stat.S_IFDIR | 0o700, st_dev=91)


class PureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control = load(CONTROL, 'source_isolation_control')
        cls.helper_raw = HELPER.read_bytes()
        cls.probe_raw = PROBE.read_bytes()
        cls.helper_sha = sha(cls.helper_raw)
        cls.probe_sha = sha(cls.probe_raw)

    def valid_receipt(self, root='/var/tmp/m-local-isolation-kernel-test-ABCDEFGH'):
        workspace = root + '/' + self.control.WORKSPACE_PREFIX + 'abc_def1'
        aliases = [workspace + '/fork.unavailable', workspace + '/stage.unavailable']
        operations = [dict(alias=alias, operation=operation, errno=13)
                      for alias in aliases for operation in ('directory-list', 'relative-file-read')]
        return {
            'status': 'passed', 'scope': self.control.SCOPE, 'workspace': workspace,
            'helper_sha256': self.helper_sha, 'executed_probe_sha256': self.probe_sha,
            'readable_baselines_verified': True,
            'denial': {'uid': 65534, 'gid': 65534, 'effective_capabilities': '0000000000000000',
                       'operations': operations},
            'exact_restoration_verified': True,
        }

    def validate_receipt(self, receipt, *, root='/var/tmp/m-local-isolation-kernel-test-ABCDEFGH',
                         helper_sha=None, probe_sha=None):
        raw = json.dumps(receipt, sort_keys=True).encode()
        helper_sha = self.helper_sha if helper_sha is None else helper_sha
        probe_sha = self.probe_sha if probe_sha is None else probe_sha
        private = lambda path, expected=None, mode=0o400: (
            b'private fixture', (91, 7, 16, 1, stat.S_IFREG | mode, 0, 1))
        with patch.object(self.control, 'Path', ReceiptPath), \
                patch.object(self.control, '_private_file', private):
            return self.control.validate_receipt(raw, root, helper_sha, probe_sha)

    def test_native_inputs_have_fixed_bytes_and_hashes(self):
        self.assertEqual(len(self.helper_raw), 3326)
        self.assertEqual(self.helper_sha, 'da9af3a768782c6ca9b28134df2b04ab4bac464a434e8ce3e29b69692c96ec9c')
        self.assertEqual(len(self.probe_raw), 2685)
        self.assertEqual(self.probe_sha, '92c9a941a1956928be202b687c43aee3eeb0a71be68816c610ee4adb86b92708')

    def test_adapt_probe_rebinds_only_expected_paths_and_preserves_control_body(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary).resolve()
            helper = root / 'helper.py'
            output = root / 'result.json'
            adapted = self.control.adapt_probe(self.probe_raw, helper, root, output)
            self.assertIsInstance(adapted, bytes)
            self.assertNotEqual(adapted, self.probe_raw)
            self.assertEqual(adapted.count(b"helper = Path(" + repr(str(helper)).encode() + b")"), 1)
            self.assertEqual(adapted.count(b"e_root = Path(" + repr(str(root)).encode() + b")"), 1)
            self.assertEqual(adapted.count(b"public = Path(" + repr(str(output)).encode() + b")"), 1)
            for marker in (self.control.LEGACY_HELPER, self.control.LEGACY_E_ROOT, self.control.LEGACY_PUBLIC):
                self.assertNotIn(marker, adapted)
            for marker in (b'readable_baselines_verified', b"result['denial'] = isolation['prove_denied'](hidden)",
                           b"result['exact_restoration_verified'] = True", b'_source_isolation_signal'):
                self.assertIn(marker, adapted)

    def test_adapt_probe_rejects_hash_markers_and_non_private_paths(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary).resolve()
            paths = (root / 'helper.py', root, root / 'result.json')
            with self.assertRaisesRegex(ValueError, 'probe pin'):
                self.control.adapt_probe(self.probe_raw + b'\n', *paths)
            for marker in (self.control.LEGACY_HELPER, self.control.LEGACY_E_ROOT,
                           self.control.LEGACY_PUBLIC, b'import runpy\n', b'os.umask(0o077)\n'):
                with self.subTest(marker=marker):
                    with self.assertRaises(ValueError):
                        self.control.adapt_probe(self.probe_raw.replace(marker, b'', 1), *paths)
            with self.assertRaisesRegex(ValueError, 'private path'):
                self.control.adapt_probe(self.probe_raw, Path('helper.py'), root, paths[2])
            with self.assertRaisesRegex(ValueError, 'private path'):
                self.control.adapt_probe(self.probe_raw, paths[0], Path('storage'), paths[2])
            with self.assertRaisesRegex(ValueError, 'private path'):
                self.control.adapt_probe(self.probe_raw, paths[0], root, Path('result.json'))

    def test_validate_receipt_accepts_exact_baseline(self):
        receipt = self.valid_receipt()
        self.assertEqual(self.validate_receipt(receipt), receipt)

    def test_validate_receipt_rejects_schema_identity_and_restoration_mutations(self):
        base = self.valid_receipt()
        cases = {}
        for key in self.control.RECEIPT_KEYS:
            value = copy.deepcopy(base)
            value.pop(key)
            cases['missing ' + key] = value
        cases.update({
            'status': dict(base, status='failed'),
            'scope': dict(base, scope='private'),
            'workspace type': dict(base, workspace=7),
            'workspace foreign': dict(base, workspace='/var/tmp/foreign/source-isolation-control-v1-ABCDEFGH'),
            'helper hash': dict(base, helper_sha256='a' * 64),
            'probe hash': dict(base, executed_probe_sha256='b' * 64),
            'baseline bool': dict(base, readable_baselines_verified=1),
            'restoration bool': dict(base, exact_restoration_verified=False),
        })
        for name, value in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.validate_receipt(value)

    def test_validate_receipt_rejects_uid_caps_errno_types_counts_and_aliases(self):
        base = self.valid_receipt()
        cases = {}
        for key in self.control.DENIAL_KEYS:
            value = copy.deepcopy(base)
            value['denial'].pop(key)
            cases['missing denial ' + key] = value
        value = copy.deepcopy(base)
        value['denial']['uid'] = 0
        cases['uid'] = value
        value = copy.deepcopy(base)
        value['denial']['gid'] = 0
        cases['gid'] = value
        value = copy.deepcopy(base)
        value['denial']['effective_capabilities'] = '1'
        cases['capabilities'] = value
        for key in ('alias', 'operation', 'errno'):
            value = copy.deepcopy(base)
            value['denial']['operations'][0][key] = 'bad'
            cases['operation ' + key] = value
        value = copy.deepcopy(base)
        value['denial']['operations'][0] = ['bad']
        cases['operation row type'] = value
        value = copy.deepcopy(base)
        value['denial']['operations'] = 'bad'
        cases['operation type'] = value
        value = copy.deepcopy(base)
        value['denial']['operations'] = value['denial']['operations'][:3]
        cases['operation count'] = value
        value = copy.deepcopy(base)
        value['denial']['operations'][0]['alias'] = '/var/tmp/foreign-alias'
        cases['operation alias'] = value
        value = copy.deepcopy(base)
        value['denial']['operations'][0]['operation'] = 'write'
        cases['operation name'] = value
        value = copy.deepcopy(base)
        value['denial']['operations'][1] = value['denial']['operations'][0]
        cases['duplicate operation'] = value
        for name, value in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.validate_receipt(value)

    def test_validate_receipt_rejects_input_hash_and_private_workspace_bindings(self):
        base = self.valid_receipt()
        for name, kwargs in (('helper input', {'helper_sha': 'a' * 64}),
                             ('probe input', {'probe_sha': 'b' * 64}),
                             ('helper format', {'helper_sha': 'bad'}),
                             ('probe format', {'probe_sha': 'bad'})):
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.validate_receipt(base, **kwargs)
        for name, root in (('relative root', 'storage'),
                           ('root symlink shape', '/var/tmp/m-local-isolation-kernel-test-ABCDEFGH/link')):
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.validate_receipt(base, root=root)

    def test_run_control_rejects_mismatch_preexisting_files_and_deadlines_before_exec(self):
        probe = self.probe_raw
        runner_calls = []
        preflight_calls = []
        def committed_mismatch(_root, _commit, relative):
            preflight_calls.append(relative)
            return b'bad' if relative == self.control.HELPER_RELATIVE else probe
        preflight = {'committed_file': committed_mismatch}
        runner = {'minimal_environment': lambda: {}, 'run_command': lambda *args, **kwargs: runner_calls.append(args)}
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary).resolve()
            with patch.object(self.control, '_mount_identity', return_value=directory):
                with self.assertRaisesRegex(ValueError, 'input pin'):
                    self.control.run_control(preflight, runner, directory, 'commit', 60)
            self.assertEqual(runner_calls, [])
            preflight_calls.clear()
            (directory / 'foreign').write_bytes(b'foreign')
            with patch.object(self.control, '_mount_identity', return_value=directory):
                with self.assertRaisesRegex(ValueError, 'pre-existing files'):
                    self.control.run_control(preflight, runner, directory, 'commit', 60)
            self.assertEqual(preflight_calls, [])
        for timeout in (0, 76, True, 1.0):
            with tempfile.TemporaryDirectory(dir=ROOT) as temporary, \
                    self.assertRaisesRegex(ValueError, 'timeout'):
                self.control.run_control(preflight, runner, Path(temporary), 'commit', timeout)

    def test_run_control_binds_inputs_and_receipt_without_kernel(self):
        preflight_calls = []
        runner_calls = []
        def committed(_root, _commit, relative):
            preflight_calls.append(relative)
            return self.helper_raw if relative == self.control.HELPER_RELATIVE else self.probe_raw
        preflight = {'committed_file': committed}
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary).resolve()
            adapted = self.control.adapt_probe(self.probe_raw, directory / 'helper.py', directory,
                                               directory / 'result.json')

            def run_command(label, command, **kwargs):
                runner_calls.append((label, command, kwargs))
                result_path = directory / 'result.json'
                receipt = self.valid_receipt(root=str(directory))
                workspace = Path(receipt['workspace'])
                workspace.mkdir(mode=0o700)
                (workspace / 'executed-helper.py').write_bytes(self.helper_raw)
                (workspace / 'executed-probe.py').write_bytes(adapted)
                result_path.write_bytes(json.dumps(receipt, sort_keys=True).encode())
                result_path.chmod(0o600)

            runner = {'minimal_environment': lambda: {'PATH': '/usr/bin'}, 'run_command': run_command}
            def write_private(path, raw):
                Path(path).write_bytes(raw)

            def private_file(path, expected=None, mode=0o400):
                raw = Path(path).read_bytes()
                return raw, (1, 2, len(raw), 3, stat.S_IFREG | mode, 0, 1)

            original_lstat = Path.lstat
            def lstat(path):
                if path.name == 'result.json':
                    return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_uid=0)
                return original_lstat(path)

            with patch.object(self.control, '_mount_identity', return_value=directory), \
                    patch.object(self.control, '_write_private', write_private), \
                    patch.object(self.control, '_private_file', private_file), \
                    patch.object(self.control, '_validate_private_inputs', lambda path, expected: Path(path).read_bytes()), \
                    patch.object(self.control, '_read_regular', lambda path: Path(path).read_bytes()), \
                    patch.object(self.control.os, 'chown', lambda *args: None, create=True), \
                    patch.object(Path, 'lstat', lstat), \
                    patch.object(self.control, 'validate_receipt', return_value=self.valid_receipt(str(directory))):
                result = self.control.run_control(preflight, runner, directory, 'commit', 60)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['helper_sha256'], self.helper_sha)
            self.assertEqual(result['probe_sha256'], sha(adapted))
            self.assertEqual(len(runner_calls), 1)
            self.assertEqual(runner_calls[0][0], 'source isolation control')
            self.assertEqual(runner_calls[0][1][1:3], ['-I', '-B'])
            self.assertEqual(preflight_calls.count(self.control.HELPER_RELATIVE), 2)
            self.assertEqual(preflight_calls.count(self.control.PROBE_RELATIVE), 2)


class LinuxRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'posix' or os.geteuid() != 0:
            raise AssertionError('LinuxRootTests require a root Linux CI host')
        cls.control = load(CONTROL, 'source_isolation_root_control')
        cls.preflight_module = load(PREFLIGHT, 'source_isolation_root_preflight')
        cls.runner_namespace = load_runner_definitions()

    def command(self, argv, *, text=False):
        return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=text, check=True, timeout=60)

    def fixture(self):
        token = hashlib.sha256(os.urandom(32)).hexdigest()[:8]
        base = Path('/var/tmp') / ('m-local-isolation-kernel-test-' + token)
        alias = Path('/var/tmp') / (self.control.CONTROL_PREFIX + token)
        self.assertFalse(base.exists())
        self.assertFalse(alias.exists())
        image, e_root = base / 'storage.ext4', base / 'e-root'
        backing = e_root / alias.name
        loop_path = None
        try:
            base.mkdir(mode=0o700)
            e_root.mkdir(mode=0o700)
            self.command(['/usr/bin/truncate', '-s', str(64 * 1024 ** 2), str(image)])
            self.command(['/usr/sbin/mkfs.ext4', '-F', '-q', str(image)])
            loop = self.command(['/usr/sbin/losetup', '--find', '--show', str(image)], text=True).stdout.strip()
            loop_path = Path(loop)
            self.assertEqual(loop_path.parent, Path('/dev'))
            self.assertTrue(loop_path.name.startswith('loop'))
            self.command(['/usr/bin/mount', '-o', 'nosuid,nodev', loop, str(e_root)])
            os.chown(e_root, 65534, 65534)
            e_root.chmod(0o700)
            backing.mkdir(mode=0o700)
            os.chown(backing, 65534, 65534)
            alias.mkdir(mode=0o700)
            os.chown(alias, 65534, 65534)
            self.command(['/usr/bin/mount', '--bind', str(backing), str(alias)])
            self.assertTrue(alias.is_mount())
            self.assertEqual(alias.stat().st_dev, e_root.stat().st_dev)
            return base, image, e_root, backing, alias, loop_path
        except BaseException:
            errors = self.cleanup_fixture(base, image, e_root, backing, alias, loop_path, strict=False)
            if errors:
                raise AssertionError('fixture setup cleanup failed: ' + '; '.join(errors))
            raise

    def cleanup_fixture(self, base, image, e_root, backing, alias, loop, *, strict=True):
        errors = []
        owned_base = (base.parent == Path('/var/tmp') and
                      base.name.startswith('m-local-isolation-kernel-test-') and
                      not base.is_symlink())
        owned_alias = (alias.parent == Path('/var/tmp') and
                       alias.name.startswith(self.control.CONTROL_PREFIX) and
                       not alias.is_symlink())
        owned_e_root = (e_root.parent == base and e_root.name == 'e-root' and not e_root.is_symlink())
        owned_image = (image.parent == base and image.name == 'storage.ext4' and not image.is_symlink())
        owned_backing = (backing.parent == e_root and backing.name == alias.name and not backing.is_symlink())
        if not (owned_base and owned_alias and owned_e_root and owned_image and owned_backing):
            errors.append('fixture path ownership check')
            if strict:
                self.fail('fixture cleanup failed: ' + '; '.join(errors))
            return errors
        if alias.is_mount():
            completed = subprocess.run(['/usr/bin/umount', str(alias)], check=False, timeout=30,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if completed.returncode != 0 or alias.is_mount():
                errors.append('alias remained mounted')
        if backing.is_symlink() or backing.exists():
            if (not owned_backing or backing.is_symlink() or backing.resolve() != backing or
                    not backing.is_dir()):
                errors.append('unsafe backing cleanup target')
            else:
                try:
                    shutil.rmtree(backing)
                except OSError as exc:
                    errors.append('backing removal: ' + str(exc))
        if alias.exists():
            if alias.is_symlink() or not owned_alias:
                errors.append('unsafe alias cleanup target')
            else:
                try:
                    alias.rmdir()
                except OSError as exc:
                    errors.append('alias removal: ' + str(exc))
        if e_root.is_symlink():
            errors.append('unsafe e-root cleanup target')
        elif e_root.is_mount():
            completed = subprocess.run(['/usr/bin/umount', str(e_root)], check=False, timeout=30,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if completed.returncode != 0 or e_root.is_mount():
                errors.append('e-root remained mounted')
        if e_root.exists():
            try:
                e_root.rmdir()
            except OSError as exc:
                errors.append('e-root removal: ' + str(exc))
        associated = subprocess.run(['/usr/sbin/losetup', '--associated', str(image)], check=False, timeout=30,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True)
        if associated.returncode not in (0, 1):
            errors.append('loop association query failed')
            associated_loops = set()
        else:
            associated_loops = {line.split(':', 1)[0].strip()
                                for line in associated.stdout.splitlines() if line.strip()}
        if loop is not None and str(loop) in associated_loops:
            completed = subprocess.run(['/usr/sbin/losetup', '--detach', str(loop)], check=False, timeout=30,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if completed.returncode != 0:
                errors.append('owned loop detach failed')
        elif associated_loops:
            errors.append('unexpected loop association')
        remaining = subprocess.run(['/usr/sbin/losetup', '--associated', str(image)], check=False, timeout=30,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True)
        if remaining.returncode not in (0, 1) or any(line.strip() for line in remaining.stdout.splitlines()):
            errors.append('loop association remained')
        if image.is_symlink() or image.exists():
            if not owned_image:
                errors.append('unsafe image cleanup target')
            else:
                try:
                    image.unlink()
                except OSError as exc:
                    errors.append('image removal: ' + str(exc))
        if base.exists():
            if not owned_base:
                errors.append('unsafe base cleanup target')
            else:
                try:
                    base.rmdir()
                except OSError as exc:
                    errors.append('base removal: ' + str(exc))
        if strict and errors:
            self.fail('fixture cleanup failed: ' + '; '.join(errors))
        return errors

    def runner(self, directory, e_root):
        self.runner_namespace['PRIVATE_LOG_DIR'] = directory
        return {'E_ROOT': e_root,
                'minimal_environment': self.runner_namespace['minimal_environment'],
                'run_command': self.runner_namespace['run_command']}

    def preflight(self):
        commit = self.preflight_module.git(ROOT.parent, ['rev-parse', 'HEAD']).decode().strip()
        return vars(self.preflight_module), commit

    def test_real_root_control_proves_denial_and_exact_restoration(self):
        fixture = self.fixture()
        base, image, e_root, backing, alias, loop = fixture
        try:
            preflight, commit = self.preflight()
            result = self.control.run_control(preflight, self.runner(base, e_root), alias, commit, 60)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['helper_sha256'], self.control.HELPER_SHA256)
            self.assertEqual(result['probe_sha256'], sha((alias / 'probe.py').read_bytes()))
            receipt = json.loads((alias / 'result.json').read_bytes())
            self.assertEqual(receipt['status'], 'passed')
            self.assertTrue(receipt['readable_baselines_verified'])
            self.assertTrue(receipt['exact_restoration_verified'])
            self.assertEqual(receipt['denial']['uid'], 65534)
            self.assertEqual(receipt['denial']['gid'], 65534)
            self.assertEqual(int(receipt['denial']['effective_capabilities'], 16), 0)
            self.assertEqual(len(receipt['denial']['operations']), 4)
            for name, expected in (('result.json', sha((alias / 'result.json').read_bytes())),
                                   ('executed-helper.py', self.control.HELPER_SHA256),
                                   ('executed-probe.py', result['probe_sha256'])):
                info = (alias / name).stat()
                self.assertEqual((info.st_uid, stat.S_IMODE(info.st_mode), info.st_nlink), (0, 0o400, 1))
                self.assertEqual(sha((alias / name).read_bytes()), expected)
            workspace = Path(receipt['workspace'])
            self.assertEqual(workspace.parent, alias)
            for name, expected in (('executed-helper.py', self.control.HELPER_SHA256),
                                   ('executed-probe.py', result['probe_sha256'])):
                info = (workspace / name).stat()
                self.assertEqual((info.st_uid, stat.S_IMODE(info.st_mode), info.st_nlink), (0, 0o400, 1))
                self.assertEqual(sha((workspace / name).read_bytes()), expected)
            for name, mode in (('fork', 0o700), ('stage', 0o755)):
                path = workspace / name
                self.assertTrue(path.is_dir() and not path.is_symlink())
                self.assertEqual((path.stat().st_uid, path.stat().st_gid, stat.S_IMODE(path.stat().st_mode)),
                                 (65534, 65534, mode))
                self.assertTrue((path / 'fixture.py').is_file())
                self.assertFalse((workspace / (name + '.unavailable')).exists())
        finally:
            self.cleanup_fixture(*fixture)

    def test_real_root_guards_reject_preexisting_symlink_and_unmounted_alias_before_exec(self):
        fixture = self.fixture()
        base, image, e_root, backing, alias, loop = fixture
        try:
            preflight, commit = self.preflight()
            calls = []
            runner = self.runner(base, e_root)
            original_run = runner['run_command']
            runner['run_command'] = lambda *args, **kwargs: calls.append(args)
            (backing / 'foreign').write_bytes(b'foreign')
            with self.assertRaisesRegex(ValueError, 'pre-existing files'):
                self.control.run_control(preflight, runner, alias, commit, 60)
            self.assertEqual(calls, [])
            (backing / 'foreign').unlink()
            self.command(['/usr/bin/umount', str(alias)])
            alias.rmdir()
            bad_unmounted = Path('/var/tmp') / (self.control.CONTROL_PREFIX + hashlib.sha256(os.urandom(32)).hexdigest()[:8])
            bad_unmounted.mkdir(mode=0o700)
            try:
                with self.assertRaisesRegex(ValueError, 'mount path'):
                    self.control.run_control(preflight, runner, bad_unmounted, commit, 60)
                self.assertEqual(calls, [])
            finally:
                bad_unmounted.rmdir()
            foreign_parent = base / 'foreign-parent'
            foreign_parent.mkdir(mode=0o700)
            bad_foreign = foreign_parent / (self.control.CONTROL_PREFIX + hashlib.sha256(os.urandom(32)).hexdigest()[:8])
            bad_foreign.mkdir(mode=0o700)
            try:
                with self.assertRaisesRegex(ValueError, 'mount path'):
                    self.control.run_control(preflight, runner, bad_foreign, commit, 60)
                self.assertEqual(calls, [])
            finally:
                bad_foreign.rmdir()
                foreign_parent.rmdir()
            bad = Path('/var/tmp') / (self.control.CONTROL_PREFIX + hashlib.sha256(os.urandom(32)).hexdigest()[:8])
            bad.symlink_to(e_root)
            try:
                with self.assertRaisesRegex(ValueError, 'mount path'):
                    self.control.run_control(preflight, runner, bad, commit, 60)
                self.assertEqual(calls, [])
            finally:
                bad.unlink()
        finally:
            self.cleanup_fixture(*fixture)


if __name__ == '__main__':
    unittest.main()
