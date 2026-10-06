"""Pure and Linux-root tests for the committed file-trace control."""

from pathlib import Path
import ast
import copy
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / 'run-fresh-file-trace-control.py'
SOURCE_TEST = ROOT / 'test-source-isolation.py'
PREPARE = ROOT / 'native-inputs/prepare-file-trace-control-v1.py'
ENVIRONMENT = ROOT / 'native-inputs/test-file-trace-environment-v1.py'
MANIFEST = ROOT / 'native-inputs/file-trace-download-pins-v1.json'
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
    namespace = {'__file__': str(RUNNER), '__name__': 'file_trace_test_runner'}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER), 'exec'), namespace)
    return namespace


class PureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control = load(CONTROL, 'file_trace_control')
        cls.prepare_raw = PREPARE.read_bytes()
        cls.environment_raw = ENVIRONMENT.read_bytes()
        cls.manifest_raw = MANIFEST.read_bytes()
        cls.prepare_sha = sha(cls.prepare_raw)
        cls.environment_sha = sha(cls.environment_raw)
        cls.manifest_sha = sha(cls.manifest_raw)
        cls.manifest = json.loads(cls.manifest_raw)

    def test_frozen_inputs_and_module_pins(self):
        self.assertEqual((len(self.prepare_raw), self.prepare_sha),
                         (2994, 'e9624c40e7614d28dfb6aea7aabed097b537aa10ea64a086809550e773cabfa8'))
        self.assertEqual((len(self.environment_raw), self.environment_sha),
                         (1260, '65cb7645b36d441846a34242f87658f50e61cee4e4a71b0aca220d0733b51e3c'))
        self.assertEqual(self.manifest_sha,
                         'e70a83652f580fbf15527633801aeedefa0196917b5128fb47afae8326483a67')
        self.assertEqual(self.control.PREPARE_SHA256, self.prepare_sha)
        self.assertEqual(self.control.ENVIRONMENT_SHA256, self.environment_sha)
        self.assertEqual(self.control.MANIFEST_SHA256, self.manifest_sha)
        self.assertEqual(self.control.CONTROL_PREFIX, 'm-local-file-trace-control-v1-')

    def test_manifest_accepts_exact_declared_inputs(self):
        self.assertEqual(self.control._validate_manifest(self.manifest_raw), self.manifest)

    def test_manifest_rejects_schema_size_hash_url_duplicates_and_index_mutations(self):
        cases = {}
        for key in self.control.MANIFEST_KEYS:
            value = copy.deepcopy(self.manifest)
            value.pop(key)
            cases['missing ' + key] = value
        cases['schema'] = dict(self.manifest, schema='wrong')
        cases['status'] = dict(self.manifest, status='verified_download')
        cases['scope'] = dict(self.manifest, scope='wrong')
        value = copy.deepcopy(self.manifest)
        value['packages'][0]['bytes'] = '1'
        cases['package size'] = value
        value = copy.deepcopy(self.manifest)
        value['packages'][0]['sha256'] = 'z' * 64
        cases['package hash'] = value
        value = copy.deepcopy(self.manifest)
        value['packages'][0]['url'] = 'https://evil.example/' + value['packages'][0]['file']
        cases['package host'] = value
        value = copy.deepcopy(self.manifest)
        value['packages'][1] = copy.deepcopy(value['packages'][0])
        cases['duplicate package'] = value
        value = copy.deepcopy(self.manifest)
        value['repository_index']['bytes'] = '1'
        cases['index size'] = value
        value = copy.deepcopy(self.manifest)
        value['repository_index']['sha256'] = 'z' * 64
        cases['index hash'] = value
        value = copy.deepcopy(self.manifest)
        value['repository_index']['url'] = 'http://kali.download/index'
        cases['index URL'] = value
        for name, value in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.control._validate_manifest(json.dumps(value).encode())
        with self.assertRaises(ValueError):
            self.control._validate_manifest(self.manifest_raw + b'\x00')

    def test_adapters_rebind_only_private_paths_and_reject_input_markers(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary).resolve()
            origin, directory = root / 'downloads', root / 'tools'
            adapted = self.control.adapt_prepare(self.prepare_raw, origin, directory)
            self.assertIn(b'origin = Path(' + repr(str(origin)).encode() + b')', adapted)
            self.assertIn(b'directory = Path(' + repr(str(directory)).encode() + b')', adapted)
            self.assertNotIn(b'/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/strace-client-control-v3', adapted)
            parent = root / 'environment'
            probe = self.control.adapt_environment_probe(self.environment_raw, directory, parent)
            self.assertIn(b'root = Path(' + repr(str(directory)).encode() + b')', probe)
            self.assertIn(repr(str(parent)).encode(), probe)
            self.assertNotIn(b'/var/tmp/m-local-kali-file-trace-01a1050e', probe)
            for function, raw, args, marker in (
                    (self.control.adapt_prepare, self.prepare_raw, (origin, directory), b'origin = Path('),
                    (self.control.adapt_environment_probe, self.environment_raw, (directory, parent), b'root = Path(')):
                with self.subTest(function=function.__name__):
                    with self.assertRaises(ValueError):
                        function(raw + b'\n', *args)
                    with self.assertRaises(ValueError):
                        function(raw.replace(marker, b'', 1), *args)
            with self.assertRaises(ValueError):
                self.control.adapt_prepare(self.prepare_raw, Path('relative'), directory)
            with self.assertRaises(ValueError):
                self.control.adapt_environment_probe(self.environment_raw, directory, Path('relative'))

    def test_download_rejects_unofficial_urls_and_bounds_before_open(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            destination = Path(temporary) / 'archive.deb'
            deadline = self.control.time.monotonic() + 60
            opener = patch.object(self.control.urllib.request, 'build_opener', side_effect=AssertionError('network opened'))
            with opener:
                for url in ('http://kali.download/pkg.deb', 'https://evil.example/pkg.deb',
                            'https://user:kali.download@kali.download/pkg.deb',
                            'https://kali.download/pkg.deb?redirect=1'):
                    with self.subTest(url=url), self.assertRaises(ValueError):
                        self.control._download(url, destination, 1, 'a' * 64, deadline)
                for size, digest in ((0, 'a' * 64), (self.control.MAX_DOWNLOAD_BYTES + 1, 'a' * 64),
                                     (1, 'bad')):
                    with self.subTest(size=size, digest=digest), self.assertRaises(ValueError):
                        self.control._download('https://kali.download/pkg.deb', destination, size, digest, deadline)
            handler = self.control._PinnedRedirectHandler()
            request = self.control.urllib.request.Request('https://kali.download/pkg.deb')
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, 'redirect', {}, 'https://evil.example/pkg.deb')

    def test_download_reads_incrementally_and_enforces_deadline_between_chunks(self):
        class Response:
            status = 200
            headers = {'Content-Length': '8'}

            def __init__(self, chunks):
                self.chunks = list(chunks)
                self.read1_calls = 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return 'https://kali.download/pkg.deb'

            def read1(self, _maximum):
                self.read1_calls += 1
                return self.chunks.pop(0) if self.chunks else b''

            def read(self, _maximum):
                raise AssertionError('download used unbounded read')

        class Opener:
            def __init__(self, response):
                self.response = response

            def open(self, request, timeout):
                self.timeout = timeout
                return self.response

        def private_file(path, expected=None, mode=None):
            return Path(path).read_bytes(), (1, 2, 3, 4, stat.S_IFREG | 0o400, 1)

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            destination = Path(temporary) / 'archive.deb'
            response = Response([b'ab', b'cd', b'ef', b'gh'])
            opener = Opener(response)
            with patch.object(self.control.urllib.request, 'build_opener', return_value=opener), \
                    patch.object(self.control, '_private_file', private_file), \
                    patch.object(self.control.os, 'chown', lambda *args: None, create=True), \
                    patch.object(self.control.time, 'monotonic', return_value=100):
                self.control._download('https://kali.download/pkg.deb', destination, 8, sha(b'abcdefgh'), 160)
            self.assertEqual(destination.read_bytes(), b'abcdefgh')
            self.assertEqual(response.read1_calls, 5)

            destination.chmod(0o600)
            destination.unlink()
            response = Response([b'ab', b'cd'])
            response.headers = {'Content-Length': '4'}
            opener = Opener(response)
            clock = iter((100, 101, 106))
            with patch.object(self.control.urllib.request, 'build_opener', return_value=opener), \
                    patch.object(self.control, '_private_file', private_file), \
                    patch.object(self.control.os, 'chown', lambda *args: None, create=True), \
                    patch.object(self.control.time, 'monotonic', side_effect=lambda: next(clock)):
                with self.assertRaisesRegex(ValueError, 'deadline'):
                    self.control._download('https://kali.download/pkg.deb', destination, 4, sha(b'abcd'), 105)
            self.assertEqual(response.read1_calls, 1)

            class NoRead1Response(Response):
                read1 = None

                def read(self, _maximum):
                    return b'abcdefgh'

            destination.unlink(missing_ok=True)
            response = NoRead1Response([])
            opener = Opener(response)
            with patch.object(self.control.urllib.request, 'build_opener', return_value=opener), \
                    patch.object(self.control, '_private_file', private_file), \
                    patch.object(self.control.os, 'chown', lambda *args: None, create=True), \
                    patch.object(self.control.time, 'monotonic', return_value=100):
                with self.assertRaises(ValueError):
                    self.control._download('https://kali.download/pkg.deb', destination, 8,
                                           sha(b'abcdefgh'), 160)

    def _prepare_receipt_fixture(self, root):
        tools = root / 'tools'
        binary = tools / 'root/usr/bin/strace'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b'strace client')
        dependency = root / 'libunwind.so'
        dependency.write_bytes(b'library')
        trace = tools / 'control.trace'
        trace.parent.mkdir(parents=True, exist_ok=True)
        controlled = tools / 'read-control.txt'
        controlled.write_text('Controlled file read\n')
        trace.write_bytes(str(controlled).encode() + b' openat\n')
        receipt = {
            'status': 'passed', 'scope': self.control.PREPARE_SCOPE, 'workspace': str(tools),
            'version': 'strace -- version 7.0', 'binary_sha256': sha(binary.read_bytes()),
            'repository_receipt_sha256': 'a' * 64,
            'dependency_sha256': {str(dependency): sha(dependency.read_bytes())},
            'file_syscalls': self.control.FILE_SYSCALLS, 'execve_arguments_traced': False,
            'controlled_trace_sha256': sha(trace.read_bytes()),
        }
        return tools, receipt

    def test_prepare_receipt_accepts_real_fixture_and_rejects_bound_mutations(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            tools, receipt = self._prepare_receipt_fixture(root)
            raw = json.dumps(receipt).encode()
            validated, trace = self.control._validate_prepare_receipt(raw, tools, 'a' * 64)
            self.assertEqual(validated, receipt)
            self.assertTrue(trace)
            cases = {}
            for key in self.control.RECEIPT_KEYS:
                value = copy.deepcopy(receipt)
                value.pop(key)
                cases['missing ' + key] = value
            cases.update({
                'status': dict(receipt, status='failed'),
                'scope': dict(receipt, scope='wrong'),
                'workspace': dict(receipt, workspace=str(root)),
                'version': dict(receipt, version='strace -- version 6.0'),
                'binary hash': dict(receipt, binary_sha256='b' * 64),
                'origin hash': dict(receipt, repository_receipt_sha256='b' * 64),
                'syscalls': dict(receipt, file_syscalls='openat'),
                'execve': dict(receipt, execve_arguments_traced=True),
                'trace hash': dict(receipt, controlled_trace_sha256='c' * 64),
                'dependency path': dict(receipt, dependency_sha256={'relative': 'a' * 64}),
                'dependency hash': dict(receipt, dependency_sha256={str(root / 'libunwind.so'): 'b' * 64}),
            })
            for name, value in cases.items():
                with self.subTest(case=name), self.assertRaises(ValueError):
                    self.control._validate_prepare_receipt(json.dumps(value).encode(), tools, 'a' * 64)
            with patch.object(Path, 'is_symlink', return_value=True):
                with self.assertRaises(ValueError):
                    self.control._validate_prepare_receipt(raw, tools, 'a' * 64)

    def test_environment_receipt_accepts_real_fixture_and_rejects_mutations(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            workspace = Path(temporary) / 'm-local-trace-environment-control-abc_def1'
            workspace.mkdir()
            trace = workspace / 'file.trace'
            trace.write_bytes(b'openat\n')
            receipt = {'status': 'passed', 'scope': self.control.ENVIRONMENT_SCOPE,
                       'workspace': str(workspace), 'trace_sha256': sha(trace.read_bytes()),
                       'executed_probe_sha256': self.environment_sha}
            self.assertEqual(self.control._validate_environment_receipt(
                json.dumps(receipt).encode(), workspace, self.environment_sha)[0], receipt)
            for key in self.control.ENVIRONMENT_RECEIPT_KEYS:
                value = copy.deepcopy(receipt)
                value.pop(key)
                with self.subTest(case='missing ' + key), self.assertRaises(ValueError):
                    self.control._validate_environment_receipt(json.dumps(value).encode(), workspace,
                                                               self.environment_sha)
            for name, value in (('status', dict(receipt, status='failed')),
                                ('scope', dict(receipt, scope='wrong')),
                                ('workspace', dict(receipt, workspace=str(Path(temporary)))),
                                ('trace hash', dict(receipt, trace_sha256='a' * 64)),
                                ('probe hash', dict(receipt, executed_probe_sha256='a' * 64))):
                with self.subTest(case=name), self.assertRaises(ValueError):
                    self.control._validate_environment_receipt(json.dumps(value).encode(), workspace,
                                                               self.environment_sha)

    def test_private_and_identity_guards_reject_wrong_mode_symlink_and_changed_read(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'input'
            path.write_bytes(b'input')
            class FakePath:
                def __init__(self, value):
                    self.value = value

                def lstat(self):
                    return self.info

                def is_symlink(self):
                    return False

            fake = FakePath(path)
            fake.info = SimpleNamespace(st_mode=stat.S_IFREG | 0o400, st_uid=0, st_nlink=1,
                                        st_dev=1, st_ino=2, st_size=5, st_mtime_ns=3)
            with patch.object(self.control, 'Path', return_value=fake), \
                    patch.object(self.control, '_read_file', return_value=b'input'):
                raw, identity = self.control._private_file(path, sha(b'input'), mode=0o400)
            self.assertEqual(raw, b'input')
            self.assertEqual(identity[2], len(raw))
            fake.info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1,
                                        st_dev=1, st_ino=2, st_size=5, st_mtime_ns=3)
            with patch.object(self.control, 'Path', return_value=fake), \
                    patch.object(self.control, '_read_file', return_value=b'input'), \
                    self.assertRaises(ValueError):
                self.control._private_file(path, sha(b'input'), mode=0o400)
            with patch.object(Path, 'is_symlink', return_value=True):
                with self.assertRaises(ValueError):
                    self.control._hash_file(path)
            info = path.lstat()
            fake_stat = SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size,
                                        st_mtime_ns=info.st_mtime_ns, st_mode=info.st_mode,
                                        st_nlink=info.st_nlink)
            class ChangedStream:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def fileno(self):
                    return 1

                def read(self, _maximum):
                    return b'changed'

            with patch.object(self.control.os, 'open', return_value=1), \
                    patch.object(self.control.os, 'fdopen', return_value=ChangedStream()), \
                    patch.object(self.control.os, 'fstat', return_value=fake_stat):
                with self.assertRaises(ValueError):
                    self.control._read_file(path)

    def test_run_control_rejects_input_mutations_preexisting_paths_and_deadlines_before_exec(self):
        runner_calls = []
        preflight_calls = []
        def committed(_root, _commit, relative):
            preflight_calls.append(relative)
            if relative == self.control.PREPARE_RELATIVE:
                return self.prepare_raw
            if relative == self.control.ENVIRONMENT_RELATIVE:
                return self.environment_raw
            return self.manifest_raw
        preflight = {'committed_file': committed}
        runner = {'minimal_environment': lambda: {}, 'run_command': lambda *args, **kwargs: runner_calls.append(args)}
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary).resolve()
            with patch.object(self.control, '_mount_identity', return_value=(directory, ())):
                with self.assertRaisesRegex(ValueError, 'pre-existing files'):
                    (directory / 'foreign').write_bytes(b'foreign')
                    self.control.run_control(preflight, runner, directory, 'commit', 180)
            self.assertEqual(runner_calls, [])
            (directory / 'foreign').unlink()
            for name, mutated in (
                    ('manifest size', dict(self.manifest, packages=[dict(self.manifest['packages'][0], bytes='1'),
                                                                     self.manifest['packages'][1]])),
                    ('manifest hash', dict(self.manifest, packages=[dict(self.manifest['packages'][0], sha256='z' * 64),
                                                                     self.manifest['packages'][1]])),
                    ('manifest URL', dict(self.manifest, packages=[dict(self.manifest['packages'][0],
                                                                        url='https://evil.example/pkg.deb'),
                                                                    self.manifest['packages'][1]]))):
                def mutated_committed(_root, _commit, relative, mutated=mutated):
                    if relative == self.control.MANIFEST_RELATIVE:
                        return json.dumps(mutated).encode()
                    return committed(_root, _commit, relative)
                with self.subTest(case=name), patch.object(self.control, '_mount_identity', return_value=(directory, ())), \
                        patch.object(self.control, '_download', side_effect=AssertionError('download started')):
                    with self.assertRaisesRegex(ValueError, 'input pin'):
                        self.control.run_control({'committed_file': mutated_committed}, runner, directory, 'commit', 180)
                self.assertEqual(runner_calls, [])
            def mismatch(_root, _commit, relative):
                preflight_calls.append(relative)
                return b'wrong' if relative == self.control.MANIFEST_RELATIVE else committed(_root, _commit, relative)
            with patch.object(self.control, '_mount_identity', return_value=(directory, ())), \
                    patch.object(self.control, '_download', side_effect=AssertionError('download started')):
                with self.assertRaisesRegex(ValueError, 'input pin'):
                    self.control.run_control({'committed_file': mismatch}, runner, directory, 'commit', 180)
            self.assertEqual(runner_calls, [])
        for timeout in (0, 181, True, 1.0):
            with tempfile.TemporaryDirectory(dir=ROOT) as temporary, \
                    self.assertRaisesRegex(ValueError, 'timeout'):
                self.control.run_control(preflight, runner, Path(temporary), 'commit', timeout)

    def test_composed_fixture_forwards_partial_cleanup_and_preserves_setup_error(self):
        source = load(SOURCE_TEST, 'file_trace_fixture_failure_source')
        calls = []
        wrapper = LinuxRootTests('runTest')
        wrapper.control = SimpleNamespace(CONTROL_PREFIX='m-local-file-trace-control-v1-')
        wrapper.source_tests = source

        def failing_command(argv, *, text=False):
            raise RuntimeError('simulated mkfs failure')

        wrapper.command = failing_command

        def fake_cleanup(instance, base, image, e_root, backing, alias, loop, *, strict=True):
            calls.append((base, image, e_root, backing, alias, loop, strict))
            for path in (backing, alias):
                if path.exists() and not path.is_symlink():
                    path.rmdir()
            if e_root.exists() and not e_root.is_symlink():
                e_root.rmdir()
            if image.exists() and not image.is_symlink():
                image.unlink()
            if base.exists() and not base.is_symlink():
                base.rmdir()
            return []

        original_cleanup = source.LinuxRootTests.cleanup_fixture
        source.LinuxRootTests.cleanup_fixture = fake_cleanup
        try:
            with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
                root = Path(temporary).resolve()
                original_path = source.Path
                source.Path = lambda value, *args: root if str(value) == '/var/tmp' else original_path(value, *args)
                try:
                    with self.assertRaisesRegex(RuntimeError, 'simulated mkfs failure'):
                        source.LinuxRootTests.fixture(wrapper)
                finally:
                    source.Path = original_path
        finally:
            source.LinuxRootTests.cleanup_fixture = original_cleanup
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0][-1])
        self.assertFalse(calls[0][0].exists())


class LinuxRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'posix' or os.geteuid() != 0:
            raise AssertionError('LinuxRootTests require a root Linux CI host')
        cls.control = load(CONTROL, 'file_trace_root_control')
        cls.preflight_module = load(PREFLIGHT, 'file_trace_root_preflight')
        cls.runner_namespace = load_runner_definitions()
        cls.source_tests = load(SOURCE_TEST, 'file_trace_fixture_source_tests')

    def command(self, argv, *, text=False):
        return self.source_tests.LinuxRootTests.command(self, argv, text=text)

    def fixture(self):
        return self.source_tests.LinuxRootTests.fixture(self)

    def cleanup_fixture(self, *fixture, strict=True):
        return self.source_tests.LinuxRootTests.cleanup_fixture(self, *fixture, strict=strict)

    def runner(self, directory, e_root):
        self.runner_namespace['PRIVATE_LOG_DIR'] = directory
        return {'E_ROOT': e_root,
                'minimal_environment': self.runner_namespace['minimal_environment'],
                'run_command': self.runner_namespace['run_command']}

    def preflight(self):
        commit = self.preflight_module.git(ROOT.parent, ['rev-parse', 'HEAD']).decode().strip()
        return vars(self.preflight_module), commit

    def test_real_root_control_downloads_traces_and_binds_receipts(self):
        fixture = self.fixture()
        base, image, e_root, backing, alias, loop = fixture
        try:
            preflight, commit = self.preflight()
            result = self.control.run_control(preflight, self.runner(base, e_root), alias, commit, 180)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['executed_prepare_sha256'], sha(self.control.adapt_prepare(
                PREPARE.read_bytes(), alias / 'downloads', alias / 'tools')))
            self.assertEqual(result['executed_environment_probe_sha256'], sha(self.control.adapt_environment_probe(
                ENVIRONMENT.read_bytes(), alias / 'tools', alias / 'environment')))
            downloads = alias / 'downloads'
            self.assertFalse((downloads / 'repository-index').exists())
            for row in self.control._validate_manifest(MANIFEST.read_bytes())['packages']:
                archive = downloads / row['file']
                self.assertTrue(archive.is_file() and not archive.is_symlink())
                self.assertEqual(archive.stat().st_size, row['bytes'])
                self.assertEqual(sha(archive.read_bytes()), row['sha256'])
            for key in ('trace_tools_directory', 'environment_control_directory',
                        'tracing_client_receipt_path', 'tracee_environment_receipt_path'):
                self.assertIsInstance(result[key], Path)
            self.assertEqual(result['trace_tools_directory'].parent, alias)
            self.assertEqual(result['environment_control_directory'].parent, alias / 'environment')
            self.assertEqual(result['tracing_client_receipt_path'].parent.parent, alias)
            self.assertEqual(result['tracee_environment_receipt_path'].parent.parent.parent, alias)
            for key in ('tracing_client_receipt_path', 'tracee_environment_receipt_path'):
                path = result[key]
                info = path.stat()
                self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink),
                                 (0, 0, 0o400, 1))
                self.assertEqual(sha(path.read_bytes()), result['tracing_client_receipt_sha256']
                                 if key.startswith('tracing') else result['tracee_environment_receipt_sha256'])
            prepare_receipt = json.loads(result['tracing_client_receipt_path'].read_bytes())
            self.assertEqual(prepare_receipt['status'], 'passed')
            self.assertEqual(prepare_receipt['scope'], self.control.PREPARE_SCOPE)
            self.assertEqual(prepare_receipt['file_syscalls'], self.control.FILE_SYSCALLS)
            self.assertFalse(prepare_receipt['execve_arguments_traced'])
            self.assertEqual(prepare_receipt['binary_sha256'], result['client_binary_sha256'])
            self.assertRegex(prepare_receipt['controlled_trace_sha256'], r'^[0-9a-f]{64}$')
            self.assertTrue(prepare_receipt['dependency_sha256'])
            environment_receipt = json.loads(result['tracee_environment_receipt_path'].read_bytes())
            self.assertEqual(environment_receipt['status'], 'passed')
            self.assertEqual(environment_receipt['scope'], self.control.ENVIRONMENT_SCOPE)
            self.assertEqual(environment_receipt['executed_probe_sha256'],
                             result['executed_environment_probe_sha256'])
            self.assertRegex(environment_receipt['trace_sha256'], r'^[0-9a-f]{64}$')
            binary = alias / 'tools/root/usr/bin/strace'
            self.assertTrue(binary.is_file() and not binary.is_symlink())
            self.assertEqual(sha(binary.read_bytes()), result['client_binary_sha256'])
            for name, expected in (('executed-prepare.py', result['executed_prepare_sha256']),
                                   ('executed-environment-probe.py', result['executed_environment_probe_sha256'])):
                path = alias / name
                info = path.stat()
                self.assertEqual((info.st_uid, stat.S_IMODE(info.st_mode), info.st_nlink), (0, 0o400, 1))
                self.assertEqual(sha(path.read_bytes()), expected)
            for name in ('prepare.log', 'environment.log'):
                path = alias / name
                info = path.stat()
                self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink),
                                 (0, 0, 0o600, 1))
                self.assertTrue(path.read_bytes())
            self.assertEqual(result['client_binary_sha256'].__class__, str)
            self.assertRegex(result['client_binary_sha256'], r'^[0-9a-f]{64}$')
            self.assertTrue((alias / 'tools/control.trace').is_file())
            self.assertTrue((Path(result['environment_control_directory']) / 'file.trace').is_file())
            self.runner_namespace['IMAGE'] = image
            self.runner_namespace['E_ROOT'] = e_root
            self.runner_namespace['IMAGE_LOOP'] = loop
            self.runner_namespace['OWNED_MOUNTS'] = {alias}
            self.runner_namespace['FAILURE_DIAGNOSTICS'] = {}
            self.runner_namespace['cleanup_mounts']()
            self.assertFalse(alias.exists())
            self.assertFalse(e_root.exists())
            associated = subprocess.run(['/usr/sbin/losetup', '--associated', str(image)],
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, check=False, timeout=30)
            self.assertEqual(associated.returncode, 0)
            self.assertEqual(associated.stdout.strip(), '')
            self.assertEqual(self.runner_namespace['FAILURE_DIAGNOSTICS']['cleanup_failures'], [])
        finally:
            self.cleanup_fixture(*fixture)

    def test_real_root_guards_reject_preexisting_private_path_and_unmounted_alias(self):
        fixture = self.fixture()
        base, image, e_root, backing, alias, loop = fixture
        try:
            preflight, commit = self.preflight()
            calls = []
            runner = self.runner(base, e_root)
            runner['run_command'] = lambda *args, **kwargs: calls.append(args)
            (backing / 'foreign').write_bytes(b'foreign')
            with self.assertRaisesRegex(ValueError, 'pre-existing files'):
                self.control.run_control(preflight, runner, alias, commit, 180)
            self.assertEqual(calls, [])
            (backing / 'foreign').unlink()
            with self.assertRaisesRegex(ValueError, 'mount path'):
                bad_runner = dict(runner, E_ROOT=Path('/var/tmp'))
                self.control.run_control(preflight, bad_runner, alias, commit, 180)
            self.assertEqual(calls, [])
            self.command(['/usr/bin/umount', str(alias)])
            alias.rmdir()
            bad = Path('/var/tmp') / (self.control.CONTROL_PREFIX + hashlib.sha256(os.urandom(32)).hexdigest()[:8])
            bad.mkdir(mode=0o700)
            try:
                with self.assertRaisesRegex(ValueError, 'mount path'):
                    self.control.run_control(preflight, runner, bad, commit, 180)
                self.assertEqual(calls, [])
            finally:
                bad.rmdir()
        finally:
            self.cleanup_fixture(*fixture)


if __name__ == '__main__':
    unittest.main()
