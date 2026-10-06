"""Pure and Linux-root tests for the committed Node.js client control."""

from pathlib import Path
import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / 'run-fresh-node-client-control.py'
SOURCE_TEST = ROOT / 'test-source-isolation.py'
PREPARE = ROOT / 'native-inputs/prepare-node-client-v1.py'
MANIFEST = ROOT / 'native-inputs/node-client-download-pins-v1.json'
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
    namespace = {'__file__': str(RUNNER), '__name__': 'node_client_test_runner'}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER), 'exec'), namespace)
    return namespace


class PureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control = load(CONTROL, 'node_client_control')
        cls.prepare_raw = PREPARE.read_bytes()
        cls.manifest_raw = MANIFEST.read_bytes()
        cls.prepare_sha = sha(cls.prepare_raw)
        cls.manifest_sha = sha(cls.manifest_raw)
        cls.manifest = json.loads(cls.manifest_raw)

    def test_frozen_inputs_and_module_pins(self):
        self.assertEqual((len(self.prepare_raw), self.prepare_sha),
                         (1334, 'c6e41ddd4f43460f73c81046412d6ecaac56a4651566e744d87686560cd41bf9'))
        self.assertEqual(self.manifest_sha,
                         'e328e11253f55f6edd4e66e91e57c1c11f544c8678e62e498f9115ba8aeb8708')
        self.assertEqual(self.control.PREPARE_SHA256, self.prepare_sha)
        self.assertEqual(self.control.MANIFEST_SHA256, self.manifest_sha)
        self.assertEqual(self.control.CONTROL_PREFIX, 'm-local-node-client-control-v1-')
        self.assertEqual(self.control.NODE_VERSION, '22.16.0')
        self.assertEqual(self.control.NPM_VERSION, '10.9.2')
        self.assertEqual(self.control.COREPACK_VERSION, '0.32.0')

    def test_manifest_accepts_exact_pins_and_rejects_mutations(self):
        self.assertEqual(self.control._validate_manifest(self.manifest_raw), self.manifest)
        cases = {}
        for key in self.control.MANIFEST_KEYS:
            value = copy.deepcopy(self.manifest)
            value.pop(key)
            cases['missing ' + key] = value
        cases.update({
            'schema': dict(self.manifest, schema='wrong'),
            'scope': dict(self.manifest, scope='wrong'),
            'status': dict(self.manifest, status='verified'),
            'version': dict(self.manifest, version='21.0.0'),
            'npm version': dict(self.manifest, npm_version='10.0.0'),
            'documentation': dict(self.manifest, release_documentation='https://evil.example/'),
        })
        for asset in ('archive', 'checksums'):
            value = copy.deepcopy(self.manifest)
            value[asset]['bytes'] += 1
            cases[asset + ' size'] = value
            value = copy.deepcopy(self.manifest)
            value[asset]['sha256'] = 'a' * 64
            cases[asset + ' hash'] = value
            value = copy.deepcopy(self.manifest)
            value[asset]['url'] = 'https://evil.example/' + value[asset]['file']
            cases[asset + ' URL'] = value
        for name, value in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.control._validate_manifest(json.dumps(value).encode())
        with self.assertRaises(ValueError):
            self.control._validate_manifest(self.manifest_raw + b'\x00')

    def test_adapt_prepare_rebinds_only_private_assets_and_rejects_markers(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            assets = Path(temporary).resolve()
            adapted = self.control.adapt_prepare(self.prepare_raw, assets)
            self.assertIn(b'assets = Path(' + repr(str(assets)).encode() + b')', adapted)
            self.assertIn(b'origin = None', adapted)
            self.assertIn(b'os.setgroups([])', adapted)
            self.assertNotIn(b'urllib.request.urlopen', adapted)
            self.assertNotIn(b'/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/client-tools', adapted)
            for marker in (b"assets = Path(", b"origin = f'https://nodejs.org/dist/v{version}/'",
                           b"checks = urllib.request.urlopen(origin + 'SHASUMS256.txt', timeout=30).read()"):
                with self.assertRaises(ValueError):
                    self.control.adapt_prepare(self.prepare_raw.replace(marker, b'', 1), assets)
            with self.assertRaises(ValueError):
                self.control.adapt_prepare(self.prepare_raw + b'\n', assets)
            with self.assertRaises(ValueError):
                self.control.adapt_prepare(self.prepare_raw, Path('relative'))

    def test_download_rejects_unofficial_urls_bounds_deadlines_and_redirects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            destination = Path(temporary) / 'node.tar.xz'
            deadline = self.control.time.monotonic() + 60
            with patch.object(self.control.urllib.request, 'build_opener',
                              side_effect=AssertionError('network opened')):
                for url in ('http://nodejs.org/node.tar.xz', 'https://evil.example/node.tar.xz',
                            'https://user:pw@nodejs.org/node.tar.xz',
                            'https://nodejs.org/node.tar.xz?redirect=1',
                            'https://nodejs.org:443/node.tar.xz'):
                    with self.subTest(url=url), self.assertRaises(ValueError):
                        self.control._download(url, destination, 1, 'a' * 64, deadline)
                for size, digest in ((0, 'a' * 64), (self.control.MAX_DOWNLOAD_BYTES + 1, 'a' * 64),
                                     (1, 'bad')):
                    with self.subTest(size=size, digest=digest), self.assertRaises(ValueError):
                        self.control._download(self.control.CHECKSUM_PIN[3], destination,
                                               size, digest, deadline)
            class ExpiredResponse:
                def __enter__(self):
                    return self
                def __exit__(self, *_args):
                    return None
                def geturl(self):
                    return 'https://nodejs.org/dist/v22.16.0/SHASUMS256.txt'

            class ExpiredOpener:
                def open(self, *_args, **_kwargs):
                    return ExpiredResponse()

            with patch.object(self.control.urllib.request, 'build_opener', return_value=ExpiredOpener()), \
                    patch.object(self.control, '_remaining', side_effect=ValueError('node client deadline')):
                with self.assertRaisesRegex(ValueError, 'deadline'):
                    self.control._download(self.control.CHECKSUM_PIN[3], destination, 1,
                                           'a' * 64, self.control.time.monotonic() + 60)
            handler = self.control._PinnedRedirectHandler()
            request = self.control.urllib.request.Request('https://nodejs.org/node.tar.xz')
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, 'redirect', {}, 'https://evil.example/node.tar.xz')

            class NoRead1:
                status = 200
                headers = {'Content-Length': '1'}
                def __enter__(self):
                    return self
                def __exit__(self, *_args):
                    return None
                def geturl(self):
                    return 'https://nodejs.org/dist/v22.16.0/SHASUMS256.txt'

            class Opener:
                def open(self, *_args, **_kwargs):
                    return NoRead1()

            with patch.object(self.control.urllib.request, 'build_opener', return_value=Opener()):
                with self.assertRaisesRegex(ValueError, 'read1'):
                    self.control._download(self.control.CHECKSUM_PIN[3], destination, 1,
                                           'a' * 64, deadline)

            class TooMuch(NoRead1):
                def read1(self, _size):
                    return b'xx'

            class TooMuchOpener:
                def open(self, *_args, **_kwargs):
                    return TooMuch()

            with patch.object(self.control.urllib.request, 'build_opener', return_value=TooMuchOpener()):
                with self.assertRaisesRegex(ValueError, 'download bound'):
                    self.control._download(self.control.CHECKSUM_PIN[3], destination, 1,
                                           'a' * 64, deadline)

    def test_safe_environment_removes_network_and_secret_controls(self):
        environment = {
            'PATH': '/usr/bin', 'HTTP_PROXY': 'http://proxy', 'NPM_CONFIG_USERCONFIG': 'secret',
            'COREPACK_ENABLE_NETWORK': '1', 'NODE_OPTIONS': '--require evil', 'TOKEN': 'secret',
            'LANG': 'C.UTF-8', 'SAFE': 'kept',
        }
        result = self.control._safe_environment({'minimal_environment': lambda: environment})
        self.assertEqual(result, {'PATH': '/usr/bin', 'LANG': 'C.UTF-8', 'SAFE': 'kept'})

    def test_checks_validation_binds_exact_archive_checksum(self):
        archive = self.manifest['archive']
        raw = (archive['sha256'] + '  ' + archive['file'] + '\n').encode()
        manifest = copy.deepcopy(self.manifest)
        manifest['checksums'] = dict(bytes=len(raw), file='SHASUMS256.txt', sha256=sha(raw),
                                     url='https://nodejs.org/dist/v22.16.0/SHASUMS256.txt')
        self.assertIsNone(self.control._validate_checks(raw, manifest))
        for value in (raw + raw, raw.replace(archive['sha256'].encode(), b'a' * 64), b'bad\n'):
            with self.subTest(value=value[:12]), self.assertRaises(ValueError):
                self.control._validate_checks(value, manifest)

    def _write_archive(self, path, *, duplicate=False, link_to_link=False, wrong_link=False):
        prefix = 'node-v22.16.0-linux-x64/'
        directories = [prefix.rstrip('/'), prefix + 'bin', prefix + 'lib', prefix + 'lib/node_modules',
                       prefix + 'lib/node_modules/npm', prefix + 'lib/node_modules/npm/bin',
                       prefix + 'lib/node_modules/corepack', prefix + 'lib/node_modules/corepack/dist']
        files = [prefix + 'bin/node', prefix + 'lib/node_modules/npm/bin/npm-cli.js',
                 prefix + 'lib/node_modules/npm/bin/npx-cli.js',
                 prefix + 'lib/node_modules/corepack/dist/corepack.js',
                 prefix + 'lib/node_modules/npm/empty']
        links = {
            prefix + 'bin/npm': '../lib/node_modules/npm/bin/npm-cli.js',
            prefix + 'bin/npx': '../lib/node_modules/npm/bin/npx-cli.js',
            prefix + 'bin/corepack': '../lib/node_modules/corepack/dist/corepack.js',
        }
        if wrong_link:
            links[prefix + 'bin/npm'] = '/tmp/escape'
        with tarfile.open(path, 'w:xz') as archive:
            for name in directories:
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                archive.addfile(info)
            for name in files:
                if link_to_link and name == files[1]:
                    info = tarfile.TarInfo(name)
                    info.type = tarfile.SYMTYPE
                    info.linkname = '../other.js'
                    archive.addfile(info)
                    continue
                info = tarfile.TarInfo(name)
                data = b'' if name.endswith('/empty') else b'data'
                info.size = len(data)
                info.mode = 0o755 if name.endswith('/node') else 0o644
                archive.addfile(info, io.BytesIO(data))
            for name, target in links.items():
                info = tarfile.TarInfo(name)
                info.type = tarfile.SYMTYPE
                info.linkname = target
                archive.addfile(info)
            if duplicate:
                info = tarfile.TarInfo(files[0])
                info.size = 4
                info.mode = 0o755
                archive.addfile(info, io.BytesIO(b'data'))

    def test_archive_inventory_rejects_duplicate_and_link_escape_entries(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            valid = root / 'valid.tar.xz'
            self._write_archive(valid)
            expected = dict(EXPECTED_MEMBER_COUNT=16, EXPECTED_DIRECTORY_COUNT=8,
                            EXPECTED_FILE_COUNT=5, EXPECTED_SYMLINK_COUNT=3)
            with patch.multiple(self.control, **expected):
                records, digest = self.control._archive_inventory(valid, self.manifest)
            self.assertEqual(len(records), 16)
            self.assertEqual(digest, sha(json.dumps(records, sort_keys=True, separators=(',', ':')).encode() + b'\n'))
            for name, kwargs in (('duplicate', {'duplicate': True}),
                                 ('link-to-link', {'link_to_link': True}),
                                 ('wrong-link', {'wrong_link': True})):
                archive = root / (name + '.tar.xz')
                self._write_archive(archive, **kwargs)
                case_expected = dict(expected)
                if name == 'duplicate':
                    case_expected['EXPECTED_MEMBER_COUNT'] = 17
                with self.subTest(case=name), patch.multiple(self.control, **case_expected), \
                        self.assertRaises(ValueError):
                    self.control._archive_inventory(archive, self.manifest)

    def test_inventory_and_receipt_validation_reject_tamper_and_schema_mutations(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary) / 'node-v22.16.0-linux-x64'
            (root / 'bin').mkdir(parents=True)
            (root / 'bin/node').write_bytes(b'node')
            original_lstat = Path.lstat

            def owned_lstat(path):
                info = original_lstat(path)
                values = {name: getattr(info, name) for name in
                          ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_uid',
                           'st_gid', 'st_nlink')}
                values.update(st_uid=65534, st_gid=65534)
                return SimpleNamespace(**values)

            def owned_hash(path, maximum=None, allow_empty=False):
                raw = Path(path).read_bytes()
                info = owned_lstat(Path(path))
                return sha(raw), len(raw), (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                                            info.st_mode, info.st_uid, info.st_gid, info.st_nlink)

            with patch.object(Path, 'lstat', owned_lstat), \
                    patch.object(self.control, '_hash_file', side_effect=owned_hash):
                records = self.control._tree_inventory(root)
                digest = self.control._inventory_digest(records)
                self.assertEqual(self.control.verify_inventory(root, digest), digest)
                (root / 'bin/node').write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'inventory hash'):
                    self.control.verify_inventory(root, digest)
            receipt = {'node_version': self.manifest['version'],
                       'archive_sha256': self.manifest['archive']['sha256'],
                       'tools_directory': str(root), 'provenance': self.control.PROVENANCE}
            self.assertEqual(self.control._parse_receipt(json.dumps(receipt).encode(), root, self.manifest), receipt)
            for key in receipt:
                value = dict(receipt)
                value.pop(key)
                with self.subTest(receipt_key=key), self.assertRaises(ValueError):
                    self.control._parse_receipt(json.dumps(value).encode(), root, self.manifest)

    def test_private_and_dropped_file_identities_reject_owner_mode_and_link_changes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'receipt.json'
            path.write_bytes(b'private receipt')
            fields = dict(st_dev=1, st_ino=2, st_size=15, st_mtime_ns=3,
                          st_mode=stat.S_IFREG | 0o400, st_uid=0, st_gid=0, st_nlink=1)
            with patch.object(Path, 'lstat', return_value=SimpleNamespace(**fields)), \
                    patch.object(self.control, '_read_file', return_value=b'private receipt'):
                self.control._private_file(path, sha(b'private receipt'), mode=0o400)
            for field, value in (('st_uid', 65534), ('st_gid', 65534),
                                 ('st_mode', stat.S_IFREG | 0o600), ('st_nlink', 2)):
                mutated = dict(fields, **{field: value})
                with self.subTest(field=field), patch.object(Path, 'lstat',
                        return_value=SimpleNamespace(**mutated)), patch.object(self.control, '_read_file',
                        return_value=b'private receipt'), self.assertRaisesRegex(ValueError, 'private file'):
                    self.control._private_file(path, sha(b'private receipt'), mode=0o400)
            dropped_fields = dict(fields, st_mode=stat.S_IFREG | 0o600, st_uid=65534, st_gid=65534)
            good_identity = tuple(dropped_fields.values())
            with patch.object(self.control, '_hash_file',
                              return_value=(sha(b'private receipt'), 15, good_identity)):
                self.assertEqual(self.control._dropped_file(path, 'dropped identity'),
                                 (sha(b'private receipt'), good_identity))
            for field, value in (('st_uid', 0), ('st_gid', 0),
                                 ('st_mode', stat.S_IFREG | 0o400), ('st_nlink', 2)):
                mutated = dict(dropped_fields, **{field: value})
                with self.subTest(dropped_field=field), patch.object(self.control, '_hash_file',
                        return_value=(sha(b'private receipt'), 15, tuple(mutated.values()))), \
                        self.assertRaisesRegex(ValueError, 'identity'):
                    self.control._dropped_file(path, 'dropped identity')

    def test_version_probe_executes_with_exact_identity_versions_and_smoke(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary) / 'node-v22.16.0-linux-x64'
            bin_dir = root / 'bin'
            bin_dir.mkdir(parents=True)
            tools = []
            for name in self.control.TOOL_NAMES:
                path = bin_dir / name
                path.write_bytes(b'private node tool')
                tools.append(path)
            output = root / 'version-probe.json'
            argv = ['node-probe.py', str(root), str(output)] + [str(path) for path in tools]
            privilege_calls, calls = [], []
            versions = {'node': 'v22.16.0', 'npm': '10.9.2', 'npx': '10.9.2', 'corepack': '0.32.0'}

            def record_groups(value):
                privilege_calls.append(('groups', value))

            def record_gid(value):
                privilege_calls.append(('gid', value))

            def record_uid(value):
                privilege_calls.append(('uid', value))

            def check_output(command, **kwargs):
                calls.append((command, kwargs))
                env = kwargs['env']
                self.assertEqual(env['PATH'], str(root / 'bin') + ':/usr/bin:/bin')
                self.assertEqual(env['HOME'], '/nonexistent')
                self.assertEqual(env['LANG'], 'C.UTF-8')
                self.assertEqual(env['LC_ALL'], 'C.UTF-8')
                self.assertEqual(env['COREPACK_ENABLE_NETWORK'], '0')
                self.assertEqual(env['npm_config_offline'], 'true')
                self.assertEqual(env['NPM_CONFIG_USERCONFIG'], '/dev/null')
                if len(command) == 3 and command[1] == '-e':
                    return '{"node":"v22.16.0","ok":1}'
                return versions[Path(command[0]).name]

            with patch.object(self.control.os, 'setgroups', record_groups, create=True), \
                    patch.object(self.control.os, 'setgid', record_gid, create=True), \
                    patch.object(self.control.os, 'setuid', record_uid, create=True), \
                    patch.object(self.control.os, 'getuid', return_value=65534, create=True), \
                    patch.object(self.control.os, 'getgid', return_value=65534, create=True), \
                    patch.object(self.control.os, 'getgroups', return_value=[], create=True), \
                    patch.object(subprocess, 'check_output', side_effect=check_output), \
                    patch.object(self.control.sys, 'argv', argv):
                exec(compile(self.control.VERSION_PROBE_SOURCE, '<node-version-probe>', 'exec'),
                     {'__name__': '__main__', '__file__': str(CONTROL)})
            raw = output.read_bytes()
            self.assertTrue(raw.endswith(b'\n'))
            self.assertFalse(raw.endswith(b'\\n'))
            receipt = json.loads(raw.decode())
            self.assertEqual((receipt['uid'], receipt['gid'], receipt['supplementary_groups']),
                             (65534, 65534, []))
            self.assertEqual(receipt['js_smoke'], '{"node":"v22.16.0","ok":1}')
            self.assertEqual([row['name'] for row in receipt['tools']], list(self.control.TOOL_NAMES))
            self.assertEqual([row['version'] for row in receipt['tools']],
                             [versions[name] for name in self.control.TOOL_NAMES])
            self.assertEqual(privilege_calls, [('groups', []), ('gid', 65534), ('uid', 65534)])
            self.assertEqual(len(calls), 5)
            self.assertEqual(self.control._validate_probe(raw, root, self.manifest)[0], receipt)

    def test_run_control_rejects_preexisting_inputs_and_deadlines_before_execution(self):
        calls = []

        def committed(_root, _commit, relative):
            return self.prepare_raw if relative == self.control.PREPARE_RELATIVE else self.manifest_raw

        preflight = {'committed_file': committed}
        runner = {'minimal_environment': lambda: {},
                  'run_command': lambda *args, **kwargs: calls.append(args)}
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary).resolve()
            for name in ('foreign', 'node-client-version-probe.py'):
                (directory / name).write_bytes(b'foreign')
                with patch.object(self.control, '_mount_identity', return_value=(directory, ())):
                    with self.assertRaisesRegex(ValueError, 'pre-existing files'):
                        self.control.run_control(preflight, runner, directory, 'commit', 180)
                (directory / name).unlink()
            for relative in (self.control.PREPARE_RELATIVE, self.control.MANIFEST_RELATIVE):
                def mismatch(_root, _commit, item, relative=relative):
                    return b'wrong' if item == relative else committed(_root, _commit, item)
                with self.subTest(relative=relative), patch.object(self.control, '_mount_identity',
                        return_value=(directory, ())), patch.object(self.control, '_download',
                        side_effect=AssertionError('download started')):
                    with self.assertRaisesRegex(ValueError, 'input pin'):
                        self.control.run_control({'committed_file': mismatch}, runner, directory, 'commit', 180)
            self.assertEqual(calls, [])
        for timeout in (0, 181, True, 1.0):
            with tempfile.TemporaryDirectory(dir=ROOT) as temporary, \
                    self.assertRaisesRegex(ValueError, 'timeout'):
                self.control.run_control(preflight, runner, Path(temporary), 'commit', timeout)

    def test_partial_fixture_setup_forwards_non_strict_cleanup_and_original_error(self):
        source = load(SOURCE_TEST, 'node_client_fixture_failure_source')
        wrapper = LinuxRootTests('runTest')
        wrapper.control = SimpleNamespace(CONTROL_PREFIX=self.control.CONTROL_PREFIX)
        wrapper.source_tests = source
        cleanup_calls = []

        def fail_command(_argv, **_kwargs):
            raise RuntimeError('simulated fixture setup failure')

        wrapper.command = fail_command
        original_path = source.Path
        real_var_tmp = original_path('/var/tmp')
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            temporary = original_path(temporary)

            def mapped_path(value):
                value = original_path(value)
                return temporary if value == real_var_tmp else value

            def cleanup(self, base, image, e_root, backing, alias, loop, *, strict=True):
                cleanup_calls.append((base, image, e_root, backing, alias, loop, strict))
                if e_root.is_dir():
                    e_root.rmdir()
                if base.is_dir():
                    base.rmdir()
                return []

            with patch.object(source, 'Path', mapped_path), \
                    patch.object(source.LinuxRootTests, 'cleanup_fixture', cleanup):
                with self.assertRaisesRegex(RuntimeError, 'simulated fixture setup failure'):
                    wrapper.fixture()
        self.assertEqual(len(cleanup_calls), 1)
        self.assertFalse(cleanup_calls[0][-1])
        self.assertFalse(cleanup_calls[0][0].exists())


class LinuxRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'posix' or os.geteuid() != 0:
            raise AssertionError('LinuxRootTests require a root Linux CI host')
        cls.control = load(CONTROL, 'node_client_root_control')
        cls.preflight_module = load(PREFLIGHT, 'node_client_root_preflight')
        cls.runner_namespace = load_runner_definitions()
        cls.source_tests = load(SOURCE_TEST, 'node_client_fixture_source_tests')

    def command(self, argv, *, text=False):
        argv = list(argv)
        if (len(argv) >= 3 and argv[:2] == ['/usr/bin/truncate', '-s'] and
                argv[2] == str(64 * 1024 ** 2)):
            argv[2] = str(512 * 1024 ** 2)
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

    def test_real_root_control_extracts_node_binds_probe_and_cleans_original_runner(self):
        fixture = self.fixture()
        base, image, e_root, backing, alias, loop = fixture
        try:
            preflight, commit = self.preflight()
            result = self.control.run_control(preflight, self.runner(base, e_root), alias, commit, 180)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['executed_prepare_sha256'], sha(self.control.adapt_prepare(
                PREPARE.read_bytes(), alias / 'clients')))
            expected_tool_paths = {'bin/node', 'lib/node_modules/npm/bin/npm-cli.js',
                                   'lib/node_modules/npm/bin/npx-cli.js',
                                   'lib/node_modules/corepack/dist/corepack.js'}
            self.assertEqual(set(result['tool_binary_sha256']), expected_tool_paths)
            self.assertTrue(result['dependency_sha256'])
            control = alias
            clients_root = control / 'clients'
            clients = Path(result['clients_directory'])
            self.assertEqual(clients, clients_root / 'node-v22.16.0-linux-x64')
            for row in self.control._validate_manifest(MANIFEST.read_bytes()).values():
                if isinstance(row, dict) and row.get('file') in {
                        self.control.ARCHIVE_PIN[1], self.control.CHECKSUM_PIN[1]}:
                    path = clients_root / row['file']
                    self.assertTrue(path.is_file() and not path.is_symlink())
                    self.assertEqual(path.stat().st_size, row['bytes'])
            archive = clients_root / self.control.ARCHIVE_PIN[1]
            checks = clients_root / 'official-checksums.txt'
            for path, expected in ((archive, self.control.ARCHIVE_PIN[2]),
                                   (checks, self.control.CHECKSUM_PIN[2])):
                info = path.stat()
                self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink),
                                 (65534, 65534, 0o400, 1))
                self.assertEqual(sha(path.read_bytes()), expected)
            info = clients.stat()
            self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)), (65534, 65534, 0o700))
            self.assertEqual(result['extracted_inventory_sha256'],
                             self.control.verify_inventory(clients, result['extracted_inventory_sha256']))
            for relative, expected in result['tool_binary_sha256'].items():
                self.assertEqual(sha((clients / relative).read_bytes()), expected)
            for path, expected in result['dependency_sha256'].items():
                dependency = Path(path)
                self.assertTrue(dependency.is_absolute() and dependency.resolve() == dependency)
                self.assertTrue(dependency.is_file() and not dependency.is_symlink())
                self.assertEqual(sha(dependency.read_bytes()), expected)
            frozen = Path(result['frozen_receipt_path'])
            binding = Path(result['binding_receipt_path'])
            for path, expected in ((frozen, result['frozen_receipt_sha256']),
                                   (binding, result['binding_receipt_sha256']),
                                   (control / 'executed-prepare-node-client.py',
                                    result['executed_prepare_sha256']),
                                   (control / 'node-client-version-probe.py',
                                    sha(self.control.VERSION_PROBE_SOURCE))):
                info = path.stat()
                self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink),
                                 (0, 0, 0o400, 1))
                self.assertEqual(sha(path.read_bytes()), expected)
            receipt = json.loads(frozen.read_bytes())
            self.assertEqual(receipt['node_version'], self.control.NODE_VERSION)
            self.assertEqual(receipt['archive_sha256'], self.control.ARCHIVE_PIN[2])
            self.assertEqual(receipt['tools_directory'], str(clients))
            probe_path = clients_root / 'version-probe.json'
            self.assertFalse((clients / 'version-probe.json').exists())
            probe = json.loads(probe_path.read_bytes())
            for path in (clients_root / 'SHASUMS256.txt', probe_path):
                info = path.stat()
                self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink),
                                 (0, 0, 0o400, 1))
            self.assertEqual((probe['uid'], probe['gid'], probe['supplementary_groups']), (65534, 65534, []))
            self.assertEqual(probe['js_smoke'], '{"node":"v22.16.0","ok":1}')
            self.assertEqual([row['name'] for row in probe['tools']], list(self.control.TOOL_NAMES))
            self.assertEqual([row['version'] for row in probe['tools']],
                             ['v22.16.0', '10.9.2', '10.9.2', '0.32.0'])
            binding_receipt = json.loads(binding.read_bytes())
            self.assertEqual(binding_receipt['status'], 'passed')
            self.assertEqual(binding_receipt['version_probe_sha256'],
                             sha(probe_path.read_bytes()))
            self.assertEqual(binding_receipt['checksums_sha256'], self.control.CHECKSUM_PIN[2])
            self.assertEqual(binding_receipt['tool_binary_sha256'], result['tool_binary_sha256'])
            self.assertEqual(binding_receipt['dependency_sha256'], result['dependency_sha256'])
            self.assertEqual(binding_receipt['extracted_inventory_sha256'], result['extracted_inventory_sha256'])
            for name in ('prepare.log', 'ldd-node.log', 'version-probe.log'):
                path = control / name
                info = path.stat()
                self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink),
                                 (0, 0, 0o600, 1))
                self.assertTrue(path.read_bytes())
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

    def test_real_root_guards_reject_preexisting_wrong_root_and_unmounted_alias(self):
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
                self.control.run_control(preflight, dict(runner, E_ROOT=Path('/var/tmp')), alias, commit, 180)
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
