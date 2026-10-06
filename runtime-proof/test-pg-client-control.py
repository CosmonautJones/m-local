"""Pure and Linux-root tests for the committed PostgreSQL client control."""

from pathlib import Path
import ast
import copy
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / 'run-fresh-pg-client-control.py'
SOURCE_TEST = ROOT / 'test-source-isolation.py'
EXTRACTOR = ROOT / 'native-inputs/extract-pg-client-v1.py'
MANIFEST = ROOT / 'native-inputs/pg-client-download-pins-v1.json'
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
    namespace = {'__file__': str(RUNNER), '__name__': 'pg_client_test_runner'}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER), 'exec'), namespace)
    return namespace


class PureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control = load(CONTROL, 'pg_client_control')
        cls.extractor_raw = EXTRACTOR.read_bytes()
        cls.manifest_raw = MANIFEST.read_bytes()
        cls.extractor_sha = sha(cls.extractor_raw)
        cls.manifest_sha = sha(cls.manifest_raw)
        cls.manifest = json.loads(cls.manifest_raw)

    def test_frozen_inputs_and_module_pins(self):
        self.assertEqual((len(self.extractor_raw), self.extractor_sha),
                         (1914, '613690e6b45348e64d736c400b2273e6ff386cb3426c20e64da3aa5467f44e4d'))
        self.assertEqual(self.manifest_sha,
                         '81d93240ca340937197838f2f942e269b78a47ec39cf15d2390c0c07c9ad63a2')
        self.assertEqual(self.control.EXTRACTOR_SHA256, self.extractor_sha)
        self.assertEqual(self.control.MANIFEST_SHA256, self.manifest_sha)
        self.assertEqual(self.control.CONTROL_PREFIX, 'm-local-pg-client-control-v1-')

    def test_manifest_accepts_exact_pins(self):
        self.assertEqual(self.control._validate_manifest(self.manifest_raw), self.manifest)

    def test_manifest_rejects_schema_url_size_hash_and_identity_mutations(self):
        cases = {}
        for key in self.control.MANIFEST_KEYS:
            value = copy.deepcopy(self.manifest)
            value.pop(key)
            cases['missing ' + key] = value
        cases.update({
            'schema': dict(self.manifest, schema='wrong'),
            'scope': dict(self.manifest, scope='wrong'),
            'status': dict(self.manifest, status='verified_download'),
            'version': dict(self.manifest, version='17.0'),
            'documentation': dict(self.manifest, repository_documentation='https://evil.example/'),
        })
        value = copy.deepcopy(self.manifest)
        value['packages'][0]['bytes'] += 1
        cases['package size'] = value
        value = copy.deepcopy(self.manifest)
        value['packages'][0]['sha256'] = 'a' * 64
        cases['package hash'] = value
        value = copy.deepcopy(self.manifest)
        value['packages'][0]['url'] = 'https://evil.example/' + value['packages'][0]['file']
        cases['package URL'] = value
        value = copy.deepcopy(self.manifest)
        value['packages'][1] = copy.deepcopy(value['packages'][0])
        cases['duplicate package'] = value
        value = copy.deepcopy(self.manifest)
        value['repository_index']['bytes'] += 1
        cases['index size'] = value
        value = copy.deepcopy(self.manifest)
        value['repository_index']['sha256'] = 'b' * 64
        cases['index hash'] = value
        value = copy.deepcopy(self.manifest)
        value['repository_index']['url'] = 'http://apt.postgresql.org/index'
        cases['index URL'] = value
        for name, value in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.control._validate_manifest(json.dumps(value).encode())
        with self.assertRaises(ValueError):
            self.control._validate_manifest(self.manifest_raw + b'\x00')

    def test_adapt_extractor_rebinds_only_private_paths_and_rejects_markers(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary).resolve()
            origin, clients = root / 'downloads', root / 'clients'
            adapted = self.control.adapt_extractor(self.extractor_raw, origin, clients)
            self.assertIn(b'control = Path(' + repr(str(origin)).encode() + b')', adapted)
            self.assertIn(b'directory = Path(' + repr(str(clients)).encode() + b')', adapted)
            self.assertNotIn(b'/mnt/e/CodexWork/m-local-recovery-01a1050e-20261004/pg-client-control-v1', adapted)
            self.assertNotIn(b'/var/tmp/m-local-kali-pg-client-01a1050e', adapted)
            for marker in (b'control = Path(', b'directory = Path('):
                with self.assertRaises(ValueError):
                    self.control.adapt_extractor(self.extractor_raw.replace(marker, b'', 1), origin, clients)
            with self.assertRaises(ValueError):
                self.control.adapt_extractor(self.extractor_raw + b'\n', origin, clients)
            with self.assertRaises(ValueError):
                self.control.adapt_extractor(self.extractor_raw, Path('relative'), clients)
            with self.assertRaises(ValueError):
                self.control.adapt_extractor(self.extractor_raw, origin, Path('relative'))

    def test_download_rejects_unofficial_urls_bounds_and_redirects_before_open(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            destination = Path(temporary) / 'client.deb'
            deadline = self.control.time.monotonic() + 60
            opener = patch.object(self.control.urllib.request, 'build_opener',
                                  side_effect=AssertionError('network opened'))
            with opener:
                for url in ('http://apt.postgresql.org/client.deb', 'https://evil.example/client.deb',
                            'https://user:pw@apt.postgresql.org/client.deb',
                            'https://apt.postgresql.org/client.deb?redirect=1'):
                    with self.subTest(url=url), self.assertRaises(ValueError):
                        self.control._download(url, destination, 1, 'a' * 64, deadline)
                for size, digest in ((0, 'a' * 64), (self.control.MAX_DOWNLOAD_BYTES + 1, 'a' * 64),
                                     (1, 'bad')):
                    with self.subTest(size=size, digest=digest), self.assertRaises(ValueError):
                        self.control._download('https://apt.postgresql.org/client.deb', destination,
                                               size, digest, deadline)
            handler = self.control._PinnedRedirectHandler()
            request = self.control.urllib.request.Request('https://apt.postgresql.org/client.deb')
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, 'redirect', {}, 'https://evil.example/client.deb')

    def _frozen_fixture(self, root):
        clients = root / 'clients'
        tool_root = clients / 'root/usr/lib/postgresql/18/bin'
        tool_root.mkdir(parents=True)
        rows = []
        for name in self.control.FILE_NAMES:
            path = tool_root / name
            path.write_bytes((name + ' binary').encode())
            rows.append({'name': name, 'version': ' ' + '(PostgreSQL) 18.6 (Ubuntu)' + name,
                         'sha256': sha(path.read_bytes())})
        receipt = {'status': 'passed', 'scope': self.control.FROZEN_SCOPE, 'workspace': str(clients),
                   'package_index_sha256': self.manifest['repository_index']['sha256'],
                   'package_version': self.manifest['version'], 'tools': rows}
        return clients, receipt

    def test_frozen_receipt_accepts_files_and_rejects_schema_tool_and_hash_mutations(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            clients, receipt = self._frozen_fixture(root)
            raw = json.dumps(receipt).encode()
            validated, hashes = self.control._validate_frozen_receipt(raw, clients, self.manifest)
            self.assertEqual(validated, receipt)
            self.assertEqual(set(hashes), set(self.control.FILE_NAMES))
            cases = {}
            for key in self.control.FROZEN_KEYS:
                value = copy.deepcopy(receipt)
                value.pop(key)
                cases['missing ' + key] = value
            cases.update({
                'status': dict(receipt, status='failed'),
                'scope': dict(receipt, scope='wrong'),
                'workspace': dict(receipt, workspace=str(root)),
                'index hash': dict(receipt, package_index_sha256='a' * 64),
                'version': dict(receipt, package_version='17.0'),
            })
            value = copy.deepcopy(receipt)
            value['tools'][0]['sha256'] = 'a' * 64
            cases['tool hash'] = value
            value = copy.deepcopy(receipt)
            value['tools'][0]['version'] = 'PostgreSQL 17'
            cases['tool version'] = value
            value = copy.deepcopy(receipt)
            value['tools'] = value['tools'][:2]
            cases['tool count'] = value
            value = copy.deepcopy(receipt)
            value['tools'][1] = copy.deepcopy(value['tools'][0])
            cases['tool duplicate'] = value
            for name, value in cases.items():
                with self.subTest(case=name), self.assertRaises(ValueError):
                    self.control._validate_frozen_receipt(json.dumps(value).encode(), clients, self.manifest)

    def test_origin_and_probe_receipts_bind_archives_workspace_identity_and_versions(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            downloads = root / 'downloads'
            downloads.mkdir()
            origin = {'status': 'verified_download', 'scope': self.control.DOWNLOAD_SCOPE,
                      'packages': self.manifest['packages'],
                      'index_sha256': self.manifest['repository_index']['sha256'],
                      'version': self.manifest['version'],
                      'repository_index_provenance': self.manifest['repository_index'],
                      'repository_index_downloaded': False}
            origin_raw = json.dumps(origin).encode()
            fake_hashes = {str(downloads / row['file']): (row['sha256'], row['bytes'], ())
                           for row in self.manifest['packages']}
            def hash_file(path, maximum=None):
                return fake_hashes[str(path)]
            with patch.object(self.control, '_hash_file', side_effect=hash_file):
                self.assertEqual(self.control._validate_origin(origin_raw, self.manifest, downloads,
                                                               sha(origin_raw)), origin)
                for name, value in (('status', dict(origin, status='failed')),
                                    ('scope', dict(origin, scope='wrong')),
                                    ('index hash', dict(origin, index_sha256='a' * 64)),
                                    ('version', dict(origin, version='17.0')),
                                    ('index downloaded', dict(origin, repository_index_downloaded=True))):
                    with self.subTest(case=name), self.assertRaises(ValueError):
                        self.control._validate_origin(json.dumps(value).encode(), self.manifest, downloads,
                                                      sha(origin_raw))
            clients = root / 'clients'
            probe = {'status': 'passed', 'workspace': str(clients), 'uid': 65534, 'gid': 65534,
                     'supplementary_groups': [],
                     'tools': [{'name': name, 'version': '(PostgreSQL) 18.6 (Ubuntu)'}
                               for name in self.control.FILE_NAMES]}
            self.assertEqual(self.control._validate_probe(json.dumps(probe).encode(), clients,
                                                          self.manifest)[0], probe)
            for name, value in (('uid', dict(probe, uid=0)), ('gid', dict(probe, gid=0)),
                                ('groups', dict(probe, supplementary_groups=[0])),
                                ('tool count', dict(probe, tools=probe['tools'][:2]))):
                with self.subTest(case=name), self.assertRaises(ValueError):
                    self.control._validate_probe(json.dumps(value).encode(), clients, self.manifest)

    def test_private_receipts_reject_wrong_owner_group_mode_and_links(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'receipt.json'
            path.write_bytes(b'private receipt')
            fields = dict(st_dev=1, st_ino=2, st_size=15, st_mtime_ns=3,
                          st_mode=stat.S_IFREG | 0o400, st_uid=0, st_gid=0, st_nlink=1)
            with patch.object(Path, 'lstat', return_value=SimpleNamespace(**fields)), \
                    patch.object(self.control, '_read_file', return_value=b'private receipt'):
                raw, identity = self.control._private_file(path, sha(b'private receipt'), mode=0o400)
            self.assertEqual((raw, identity), (b'private receipt', tuple(fields.values())))
            for field, value in (('st_uid', 65534), ('st_gid', 65534),
                                 ('st_mode', stat.S_IFREG | 0o600), ('st_nlink', 2)):
                mutated = dict(fields, **{field: value})
                with self.subTest(field=field), \
                        patch.object(Path, 'lstat', return_value=SimpleNamespace(**mutated)), \
                        patch.object(self.control, '_read_file', return_value=b'private receipt'):
                    with self.assertRaisesRegex(ValueError, 'private file'):
                        self.control._private_file(path, sha(b'private receipt'), mode=0o400)
            dropped_fields = dict(fields, st_mode=stat.S_IFREG | 0o600, st_uid=65534, st_gid=65534)
            dropped_identity = tuple(dropped_fields.values())
            with patch.object(self.control, '_hash_file',
                              return_value=(sha(b'private receipt'), len(b'private receipt'), dropped_identity)):
                self.assertEqual(self.control._dropped_file(path, 'probe identity'),
                                 (sha(b'private receipt'), dropped_identity))
            for field, value in (('st_uid', 0), ('st_gid', 0),
                                 ('st_mode', stat.S_IFREG | 0o400), ('st_nlink', 2)):
                mutated = dict(dropped_fields, **{field: value})
                with self.subTest(dropped_field=field), \
                        patch.object(self.control, '_hash_file',
                                     return_value=(sha(b'private receipt'), len(b'private receipt'),
                                                   tuple(mutated.values()))):
                    with self.assertRaisesRegex(ValueError, 'identity'):
                        self.control._dropped_file(path, 'probe identity')

    def test_run_control_rejects_preexisting_paths_input_pins_and_deadlines_before_exec(self):
        runner_calls = []
        def committed(_root, _commit, relative):
            if relative == self.control.EXTRACTOR_RELATIVE:
                return self.extractor_raw
            return self.manifest_raw
        preflight = {'committed_file': committed}
        runner = {'minimal_environment': lambda: {},
                  'run_command': lambda *args, **kwargs: runner_calls.append(args)}
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary).resolve()
            (directory / 'foreign').write_bytes(b'foreign')
            with patch.object(self.control, '_mount_identity', return_value=(directory, ())):
                with self.assertRaisesRegex(ValueError, 'pre-existing files'):
                    self.control.run_control(preflight, runner, directory, 'commit', 180)
            self.assertEqual(runner_calls, [])
            (directory / 'foreign').unlink()
            probe = directory / 'pg-client-version-probe.py'
            probe.write_bytes(b'foreign probe')
            with patch.object(self.control, '_mount_identity', return_value=(directory, ())):
                with self.assertRaisesRegex(ValueError, 'pre-existing files'):
                    self.control.run_control(preflight, runner, directory, 'commit', 180)
            self.assertEqual(runner_calls, [])
            probe.unlink()
            for relative, raw in ((self.control.EXTRACTOR_RELATIVE, b'wrong'),
                                  (self.control.MANIFEST_RELATIVE, b'wrong')):
                def mismatch(_root, _commit, item, relative=relative, raw=raw):
                    return raw if item == relative else committed(_root, _commit, item)
                with self.subTest(relative=relative), patch.object(self.control, '_mount_identity',
                                                                   return_value=(directory, ())), \
                        patch.object(self.control, '_download', side_effect=AssertionError('download started')):
                    with self.assertRaisesRegex(ValueError, 'input pin'):
                        self.control.run_control({'committed_file': mismatch}, runner, directory, 'commit', 180)
            self.assertEqual(runner_calls, [])
        for timeout in (0, 181, True, 1.0):
            with tempfile.TemporaryDirectory(dir=ROOT) as temporary, \
                    self.assertRaisesRegex(ValueError, 'timeout'):
                self.control.run_control(preflight, runner, Path(temporary), 'commit', timeout)

    def test_version_probe_writes_parseable_identity_receipt_with_real_newline(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary) / 'clients'
            tool_root = root / 'root/usr/lib/postgresql/18/bin'
            tool_root.mkdir(parents=True)
            tools = []
            for name in self.control.FILE_NAMES:
                path = tool_root / name
                path.write_bytes(b'private tool placeholder')
                tools.append(path)
            output = root / 'version-probe.json'
            argv = ['version-probe.py', str(root), str(output)] + [str(path) for path in tools]
            privilege_calls = []
            version_calls = []

            def setgroups(groups):
                privilege_calls.append(('groups', groups))

            def setgid(gid):
                privilege_calls.append(('gid', gid))

            def setuid(uid):
                privilege_calls.append(('uid', uid))

            def check_output(command, **kwargs):
                version_calls.append((command, kwargs))
                self.assertEqual(kwargs['env']['PATH'], '/usr/bin:/bin')
                self.assertEqual(kwargs['env']['HOME'], '/nonexistent')
                self.assertEqual(kwargs['env']['LANG'], 'C.UTF-8')
                self.assertEqual(kwargs['env']['LD_LIBRARY_PATH'],
                                 str(root / 'root/usr/lib/x86_64-linux-gnu'))
                return Path(command[0]).name + ' (PostgreSQL) 18.6 (Ubuntu)\n'

            with patch.object(self.control.os, 'setgroups', setgroups, create=True), \
                    patch.object(self.control.os, 'setgid', setgid, create=True), \
                    patch.object(self.control.os, 'setuid', setuid, create=True), \
                    patch.object(self.control.os, 'getuid', return_value=65534, create=True), \
                    patch.object(self.control.os, 'getgid', return_value=65534, create=True), \
                    patch.object(self.control.os, 'getgroups', return_value=[], create=True), \
                    patch.object(subprocess, 'check_output', side_effect=check_output), \
                    patch.object(self.control.sys, 'argv', argv):
                exec(compile(self.control.VERSION_PROBE_SOURCE, '<version-probe>', 'exec'),
                     {'__name__': '__main__', '__file__': str(CONTROL)})

            raw = output.read_bytes()
            self.assertTrue(raw.endswith(b'\n'))
            self.assertFalse(raw.endswith(b'\\n'))
            receipt = json.loads(raw.decode('utf-8'))
            self.assertEqual(receipt['status'], 'passed')
            self.assertEqual(receipt['workspace'], str(root))
            self.assertEqual((receipt['uid'], receipt['gid'], receipt['supplementary_groups']),
                             (65534, 65534, []))
            self.assertEqual(privilege_calls, [('groups', []), ('gid', 65534), ('uid', 65534)])
            self.assertEqual([Path(command[0]).name for command, _ in version_calls],
                             list(self.control.FILE_NAMES))
            self.assertEqual([row['version'] for row in receipt['tools']],
                             [name + ' (PostgreSQL) 18.6 (Ubuntu)' for name in self.control.FILE_NAMES])

    def test_partial_fixture_setup_forwards_non_strict_cleanup_and_original_error(self):
        source = load(SOURCE_TEST, 'pg_client_fixture_failure_source')
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
        cls.control = load(CONTROL, 'pg_client_root_control')
        cls.preflight_module = load(PREFLIGHT, 'pg_client_root_preflight')
        cls.runner_namespace = load_runner_definitions()
        cls.source_tests = load(SOURCE_TEST, 'pg_client_fixture_source_tests')

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

    def test_real_root_control_extracts_binds_versions_and_cleans_original_runner(self):
        fixture = self.fixture()
        base, image, e_root, backing, alias, loop = fixture
        try:
            preflight, commit = self.preflight()
            result = self.control.run_control(preflight, self.runner(base, e_root), alias, commit, 180)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['executed_extractor_sha256'], sha(self.control.adapt_extractor(
                EXTRACTOR.read_bytes(), alias / 'downloads', alias / 'clients')))
            self.assertEqual(set(result['tool_binary_sha256']), set(self.control.FILE_NAMES))
            self.assertEqual(set(result['dependency_sha256']), set(self.control.FILE_NAMES))
            downloads = alias / 'downloads'
            self.assertFalse((downloads / 'repository-index').exists())
            for row in self.control._validate_manifest(MANIFEST.read_bytes())['packages']:
                archive = downloads / row['file']
                self.assertTrue(archive.is_file() and not archive.is_symlink())
                self.assertEqual(archive.stat().st_size, row['bytes'])
                self.assertEqual(sha(archive.read_bytes()), row['sha256'])
            clients = Path(result['clients_directory'])
            clients_info = clients.stat()
            self.assertEqual((clients_info.st_uid, clients_info.st_gid, stat.S_IMODE(clients_info.st_mode)),
                             (65534, 65534, 0o700))
            frozen = Path(result['frozen_receipt_path'])
            binding = Path(result['binding_receipt_path'])
            for path, expected in ((frozen, result['frozen_receipt_sha256']),
                                   (binding, result['binding_receipt_sha256']),
                                   (alias / 'executed-extract-pg-client.py', result['executed_extractor_sha256'])):
                info = path.stat()
                self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink),
                                 (0, 0, 0o400, 1))
                self.assertEqual(sha(path.read_bytes()), expected)
            frozen_receipt = json.loads(frozen.read_bytes())
            self.assertEqual(frozen_receipt['status'], 'passed')
            self.assertEqual(frozen_receipt['package_version'], self.control.PACKAGE_PINS['libpq5'][2])
            self.assertEqual([row['name'] for row in frozen_receipt['tools']], list(self.control.FILE_NAMES))
            probe = json.loads((clients / 'version-probe.json').read_bytes())
            self.assertEqual((probe['uid'], probe['gid'], probe['supplementary_groups']), (65534, 65534, []))
            self.assertEqual([row['name'] for row in probe['tools']], list(self.control.FILE_NAMES))
            binding_receipt = json.loads(binding.read_bytes())
            self.assertEqual(binding_receipt['status'], 'passed')
            self.assertEqual(binding_receipt['uid'], 65534)
            self.assertEqual(binding_receipt['gid'], 65534)
            self.assertEqual(binding_receipt['supplementary_groups'], [])
            self.assertEqual(binding_receipt['tool_binary_sha256'], result['tool_binary_sha256'])
            self.assertEqual(binding_receipt['dependency_sha256'], result['dependency_sha256'])
            for name in self.control.FILE_NAMES:
                tool = clients / 'root/usr/lib/postgresql/18/bin' / name
                self.assertEqual(sha(tool.read_bytes()), result['tool_binary_sha256'][name])
            for name in ('extract.log', 'ldd-psql.log', 'ldd-pg_dump.log', 'ldd-pg_restore.log',
                         'version-probe.log'):
                path = alias / name
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
