"""Offline boundary tests for fresh package acceptance and cleanup."""

from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
PACKAGE = None


def load_package():
    spec = importlib.util.spec_from_file_location('fresh_package', ROOT / 'run-fresh-package.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def committed_head_blob(relative):
    checkout = ROOT.parent
    environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_NO_REPLACE_OBJECTS='1', GIT_OPTIONAL_LOCKS='0')
    result = subprocess.run(
        ['git', '--no-replace-objects', '-c', 'safe.directory=' + str(checkout), '-C', str(checkout),
         'show', 'HEAD:' + relative],
        env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        check=True, timeout=5)
    if len(result.stdout) > 1024 ** 2:
        raise AssertionError('committed test input exceeds bound')
    return result.stdout


def inherited():
    values = {'jac/jaclang/compiler/backends/native/llvm/libjacllvm.so':
              {'sha256': '02f499e9becacf36161aa9f4b39a9f950f4dd8dbcb744acded0f04618652b4de'}}
    values.update({'jac/jaclang/vendor/typeshed/file-' + str(i): {'sha256': 'a' * 64} for i in range(749)})
    return values


def fixture(root):
    fork, package = root / 'fork', root / 'package'
    fork.mkdir()
    package.mkdir()
    canonical = {
        'transaction.patch': ROOT / 'inputs/work/identity-runtime-v3/runtime.patch',
        'executed-recipe.py': ROOT / 'package-inputs/package-runtime-candidate-v7.py',
        'executed-classifier.py': ROOT / 'package-inputs/classify-runtime-build-paths-v7.py',
        'diagnostic-policy.json': ROOT / 'package-inputs/diagnostic-policy-v7.json',
        'executed-catalog-probe.py': ROOT / 'package-inputs/runtime-catalog-relocation-probe-v7.py',
    }
    files = {}
    for name in PACKAGE.PACKAGE_HASH_FIELDS:
        raw = canonical[name].read_bytes() if name in canonical else (name + ':fixture').encode()
        (package / name).write_bytes(raw)
        files[name] = sha(raw)
    metadata = {key: files[name] for name, key in PACKAGE.PACKAGE_HASH_FIELDS.items()}
    metadata.update(executed_recipe_sha256=PACKAGE.RECIPE_SHA, executed_classifier_sha256=PACKAGE.CLASSIFIER_SHA,
                    diagnostic_policy_sha256=PACKAGE.POLICY_SHA, executed_catalog_probe_sha256=PACKAGE.CATALOG_SHA,
                    runtime_base='58cb97eb75cdff8b5ee78f4094ca2be16376601c',
                    runtime_patch_sha256='d3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366',
                    candidate=str(package / 'jac'), candidate_binary_bytes=len((package / 'jac').read_bytes()))
    metadata['official_payload_sha256'] = sha(b'official payload fixture')
    metadata_raw = json.dumps(metadata, sort_keys=True).encode()
    (package / 'result.json').write_bytes(metadata_raw)
    launcher = package / 'jacpython'
    try:
        launcher.symlink_to('jac')
        link_real = True
    except (OSError, NotImplementedError):
        launcher.write_bytes(b'link fixture')
        link_real = False
    independent = {'status': 'passed', 'executed_verifier_sha256': PACKAGE.VERIFIER_SHA,
                   'package_metadata_sha256': sha(metadata_raw), 'file_hashes': files}
    loader = {'status': 'passed', 'runtime_roots': [str(fork / 'jaclang')],
              'implementation_files': {str(i): str(fork / ('implementation-' + str(i) + '.py')) for i in range(16)}}
    control_code = b'classifier fixture source'
    controls = {'status': 'passed', 'executed_controls_sha256': sha(control_code),
                'classifier_sha256': PACKAGE.CLASSIFIER_SHA,
                'policy_sha256': PACKAGE.POLICY_SHA, 'package_metadata_sha256': sha(metadata_raw),
                'original_stage_classification_sha256': metadata['stage_classification_sha256'],
                'cases': [{'name': name, 'status': 'passed'} for name in PACKAGE.CONTROL_NAMES]}
    preflight = {'read_regular': lambda path: Path(path).read_bytes(), 'sha': sha,
                 'require_pattern': lambda value, pattern, label: re.fullmatch(pattern, value) or
                 (_ for _ in ()).throw(ValueError(label)),
                 'no_links': lambda path: None,
                 'verify_direct_use_assembly': lambda *args, **kwargs:
                     {'status': 'passed', 'inherited_fork_inputs': inherited()}}
    cache_code = b'official cache precheck fixture'
    official_cache = {'status': 'passed', 'recipe_sha256': PACKAGE.RECIPE_SHA,
                      'official_binary_sha256': '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad',
                      'official_payload_sha256': metadata['official_payload_sha256'],
                      'extracted_inventory_sha256': 'b' * 64,
                      'executed_precheck_sha256': sha(cache_code)}
    return dict(fork=fork, package=package, metadata=metadata, metadata_raw=metadata_raw,
                independent=json.dumps(independent).encode(), loader=json.dumps(loader).encode(),
                controls=json.dumps(controls).encode(), official_cache=json.dumps(official_cache).encode(),
                cache_code=cache_code, preflight=preflight,
                declaration=b'{}', source_manifest=b'{}', link_real=link_real, control_code=control_code)


def invoke(f, *, preflight=None, independent=None, loader=None, controls=None, metadata=None, official_cache=None):
    preflight, independent, loader, controls = (preflight or f['preflight'], independent or f['independent'],
                                                loader or f['loader'], controls or f['controls'])
    official_cache = official_cache or f['official_cache']
    expected_metadata = sha(metadata or f['metadata_raw'])
    call = lambda: PACKAGE.accept_package(
        preflight, f['fork'], f['package'], independent, loader, controls, f['declaration'], f['source_manifest'],
        expected_metadata_sha256=expected_metadata, expected_loader_sha256=sha(loader),
        expected_controls_sha256=sha(controls), expected_controls_code_sha256=sha(f['control_code']),
        official_cache_raw=official_cache, expected_official_cache_receipt_sha256=sha(official_cache),
        expected_official_cache_code_sha256=sha(f['cache_code']))
    if f['link_real']:
        return call()
    launcher = f['package'] / 'jacpython'
    original_symlink, original_resolve, original_readlink = Path.is_symlink, Path.resolve, PACKAGE.os.readlink
    with patch.object(Path, 'is_symlink', lambda path: True if path == launcher else original_symlink(path)), \
            patch.object(Path, 'resolve', lambda path: f['package'] / 'jac' if path == launcher else original_resolve(path)), \
            patch.object(PACKAGE.os, 'readlink', lambda path: 'jac' if path == launcher else original_readlink(path)):
        return call()


def accepted(f):
    return invoke(f)


class Process:
    def __init__(self, returncode=0, pending=False):
        self.returncode = returncode
        self.pending = pending

    def poll(self):
        if self.pending:
            return None
        return self.returncode


def bounded_runner(process, *, guard=None, launch_error=None, sample_error=None):
    events = []
    state = {'limits': {'high': 7 * 1024 ** 3, 'max': 8 * 1024 ** 3, 'swap_max': 0},
             'requested_limits': {'high': 7 * 1024 ** 3, 'max': 8 * 1024 ** 3, 'swap_max': 0},
             'oom_policy': 'stop', 'controls_confirmed_before_workload': True,
             'cleanup': {'cgroup_empty': True, 'launcher_stopped': True,
                         'unit_state': {'Result': 'success'}}}

    def launch(*args):
        events.append('launch')
        if launch_error:
            raise launch_error
        return process, state

    def sample(*args):
        events.append('sample')
        if sample_error:
            raise sample_error

    def stop(*args):
        events.append('stop')

    helper = {'launch_scope': launch, 'sample_scope': sample, 'scope_guard': lambda *args: guard,
              'stop_scope': stop}
    runner = {'resource_helper': lambda: helper, 'run_command': lambda *args: None}
    return runner, events


class FakeStat:
    def __init__(self, dev=7, ino=9):
        self.st_mode = stat.S_IFDIR | 0o700
        self.st_uid, self.st_dev, self.st_ino = 65534, dev, ino


class FakePath:
    def __init__(self, token, parent=None, name=None, info=None, backing=None, mount=True):
        self.token, self._parent, self._name = token, parent, name or token
        self.info, self.backing, self.mount = info or FakeStat(), backing, mount

    @property
    def parent(self):
        return self._parent

    @property
    def name(self):
        return self._name

    def resolve(self):
        return self

    def is_symlink(self):
        return False

    def is_mount(self):
        return self.mount

    def stat(self):
        return self.info

    def lstat(self):
        return self.backing.info if self.backing else self.info

    def __truediv__(self, value):
        return self.backing

    def __eq__(self, other):
        return isinstance(other, FakePath) and self.token == other.token


class FreshPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global PACKAGE
        PACKAGE = load_package()

    def test_accept_package_success_and_binding_rejections(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            f = fixture(Path(temporary))
            result = accepted(f)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['scope'], PACKAGE.SCOPE)
            cases = {}
            cases['stale metadata'] = lambda item: accepted(dict(item, metadata_raw=b'stale'))
            cases['wrong recipe'] = lambda item: self.mutate_metadata(item, executed_recipe_sha256='bad')
            cases['candidate size'] = lambda item: self.mutate_metadata(item, candidate_binary_bytes=99)
            bad_independent = json.loads(f['independent'])
            bad_independent['executed_verifier_sha256'] = 'bad'
            cases['independent verifier'] = lambda item: self.call(item, independent=json.dumps(bad_independent).encode())
            bad_cache = json.loads(f['official_cache'])
            bad_cache['status'] = 'failed'
            cases['official cache receipt'] = lambda item: self.call(item, official_cache=json.dumps(bad_cache).encode())
            bad_loader = json.loads(f['loader'])
            bad_loader['runtime_roots'] = [str(Path(temporary) / 'outside')]
            cases['loader outside fork'] = lambda item: self.call(item, loader=json.dumps(bad_loader).encode())
            cases['controls missing'] = lambda item: self.call(item, controls=b'{}')
            bad_controls = json.loads(f['controls'])
            bad_controls['executed_controls_sha256'] = 'bad'
            cases['controls code'] = lambda item: self.call(item, controls=json.dumps(bad_controls).encode())
            cases['candidate missing'] = lambda item: self.remove_candidate(item)
            bad_inherited = dict(f['preflight'], verify_direct_use_assembly=lambda *a, **k: {'inherited_fork_inputs': {}})
            cases['required inheritance'] = lambda item: self.call(item, preflight=bad_inherited)
            for name, action in cases.items():
                with tempfile.TemporaryDirectory(dir=ROOT) as case_dir:
                    item = fixture(Path(case_dir))
                    with self.subTest(binding=name), self.assertRaises((ValueError, OSError, KeyError, TypeError)):
                        action(item)

    def test_runner_pin_matches_committed_head_blob(self):
        raw = committed_head_blob('runtime-proof/run-fresh-source.py')
        self.assertEqual(sha(raw), PACKAGE.RUNNER_SHA)

    def remove_candidate(self, f):
        (f['package'] / 'jac').unlink()
        return invoke(f)

    def mutate_metadata(self, f, **changes):
        metadata = dict(f['metadata'], **changes)
        raw = json.dumps(metadata, sort_keys=True).encode()
        f['package'].joinpath('result.json').write_bytes(raw)
        f['metadata'] = metadata
        f['metadata_raw'] = raw
        independent = json.loads(f['independent'])
        independent['package_metadata_sha256'] = sha(raw)
        controls = json.loads(f['controls'])
        controls['package_metadata_sha256'] = sha(raw)
        f['independent'] = json.dumps(independent).encode()
        f['controls'] = json.dumps(controls).encode()
        return invoke(f)

    def call(self, f, **overrides):
        return invoke(f, **overrides)

    def test_run_bounded_cleans_after_success_failure_guard_and_exception(self):
        cases = ((Process(), {}, None), (Process(returncode=1), {'error': 'nonzero'}, None),
                 (Process(pending=True), {'error': 'guard'}, 'timeout'),
                 (Process(pending=True), {'error': 'exception'}, RuntimeError('sample')))
        for process, expected, failure in cases:
            with self.subTest(case=expected):
                with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
                    runner, events = bounded_runner(process, guard=failure if failure == 'timeout' else None,
                                                    sample_error=failure if isinstance(failure, Exception) else None)
                    if expected:
                        with self.assertRaises((ValueError, RuntimeError)):
                            PACKAGE.run_bounded(runner, Path(temporary), ['fixture'], Path(temporary), {}, 1, 'case')
                    else:
                        PACKAGE.run_bounded(runner, Path(temporary), ['fixture'], Path(temporary), {}, 1, 'case')
                    self.assertIn('stop', events)
                    self.assertIsNone(runner.get('ACTIVE'))

    def test_mount_rebinding_and_loader_input_tamper_are_rejected_without_execution(self):
        var_tmp = FakePath('/var/tmp')
        e_root = FakePath('e-root', info=FakeStat(dev=7, ino=1), mount=True)
        backing = FakePath('backing', info=FakeStat(dev=7, ino=9), mount=False)
        e_root.backing = backing
        mount = FakePath('m', parent=var_tmp, name='m-local-runtime-package-12345678', info=FakeStat(), backing=backing)
        convert = lambda value: value if isinstance(value, FakePath) else var_tmp if value == '/var/tmp' else value
        with patch.object(PACKAGE, 'Path', convert):
            self.assertEqual(PACKAGE.mount_identity(mount, e_root, 'm-local-runtime-package-'), (7, 9))
            backing.info.st_ino = 10
            with self.assertRaisesRegex(ValueError, 'owned package mount identity'):
                PACKAGE.mount_identity(mount, e_root, 'm-local-runtime-package-')
        bad = b"raise RuntimeError('input executed')"
        preflight = {'committed_file': lambda *args: bad, 'sha': sha}
        with self.assertRaisesRegex(ValueError, 'package helper pin'):
            PACKAGE.load_committed(preflight, 'runtime-proof/check-fresh-package-classifier.py', 'a' * 40,
                                   pin=PACKAGE.CLASSIFIER_SHA)
        with self.assertRaisesRegex(ValueError, 'package helper pin'):
            PACKAGE.load_committed(preflight, 'runtime-proof/check-official-package-cache.py', 'a' * 40,
                                   pin=sha(b'cache helper source'))
        with self.assertRaisesRegex(ValueError, 'package helper pin'):
            PACKAGE.load_committed(preflight, 'runtime-proof/run-fresh-source-isolation.py', 'a' * 40,
                                   pin=PACKAGE.SOURCE_ISOLATION_SHA)
        marker = b"root = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork').resolve()"
        with self.assertRaisesRegex(ValueError, 'loader source binding'):
            PACKAGE.adapt_loader(marker + marker, Path('fork'))

    def test_stage_source_loads_pinned_downloader_and_scrubs_token(self):
        source_commit, package_commit, run_id = 'a' * 40, 'b' * 40, '1'
        origin_raw = (ROOT / 'verify-source-origin.py').read_bytes()
        downloader_raw = (ROOT / 'download-source-handoff.py').read_bytes()
        calls = []

        def committed(root, commit, relative):
            if relative == 'runtime-proof/verify-source-origin.py':
                return origin_raw
            if relative == 'runtime-proof/download-source-handoff.py':
                return downloader_raw
            raise AssertionError(relative)

        preflight = {'committed_file': committed, 'sha': sha}
        expected = {'status': 'passed', 'scope': 'authenticated source bundle and package commitments only',
                    'origin': {'status': 'passed', 'run_id': 1}, 'preflight': {'status': 'passed'}}

        def loader(preflight_value, relative, commit, *, pin=None):
            module = original_loader(preflight_value, relative, commit, pin=pin)
            def stage(destination, source, package, **kwargs):
                calls.append((destination, source, package, kwargs, PACKAGE.os.environ.get('GH_TOKEN')))
                return expected
            module['stage_handoff'] = stage
            return module

        original_loader = PACKAGE.load_committed
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary, patch.object(PACKAGE, 'load_committed', loader), \
                patch.dict(PACKAGE.os.environ, {'GH_TOKEN': 'private'}, clear=False):
            workspace = Path(temporary) / 'workspace'
            workspace.mkdir()
            result = PACKAGE.stage_source(preflight, workspace, Path(temporary) / 'source',
                                          source_commit, package_commit, run_id)
            self.assertEqual(result, expected)
            self.assertEqual(len(calls), 1)
            destination, source, package, kwargs, token = calls[0]
            self.assertEqual(destination, workspace / 'source-handoff')
            self.assertEqual(source, Path(temporary) / 'source')
            self.assertEqual(package, PACKAGE.ROOT)
            self.assertEqual(kwargs, {'expected_source_commit': source_commit,
                                      'expected_package_commit': package_commit, 'expected_run_id': run_id})
            self.assertEqual(token, 'private')
            self.assertNotIn('GH_TOKEN', PACKAGE.os.environ)

    def test_stage_source_rejects_fake_or_wrongly_pinned_inputs_and_scrubs_on_error(self):
        source_commit, package_commit = 'a' * 40, 'b' * 40
        downloader_raw = (ROOT / 'download-source-handoff.py').read_bytes()
        preflight = {'committed_file': lambda root, commit, relative: downloader_raw,
                     'sha': sha}
        original_loader = PACKAGE.load_committed
        loaded = []

        def tracking_loader(*args, **kwargs):
            loaded.append(True)
            return original_loader(*args, **kwargs)

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary, patch.object(PACKAGE, 'load_committed', tracking_loader), \
                patch.dict(PACKAGE.os.environ, {'GH_TOKEN': 'private'}, clear=False):
            with self.assertRaisesRegex(ValueError, 'source origin helper pin'):
                PACKAGE.stage_source(preflight, Path(temporary), Path(temporary) / 'source',
                                     source_commit, package_commit, '1')
            self.assertEqual(loaded, [])
            self.assertNotIn('GH_TOKEN', PACKAGE.os.environ)

        def committed(root, commit, relative):
            if relative == 'runtime-proof/verify-source-origin.py':
                return (ROOT / 'verify-source-origin.py').read_bytes()
            return downloader_raw

        def loader(preflight_value, relative, commit, *, pin=None):
            module = original_loader(preflight_value, relative, commit, pin=pin)
            module['stage_handoff'] = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('download failed'))
            return module

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary, patch.object(PACKAGE, 'load_committed', loader), \
                patch.dict(PACKAGE.os.environ, {'GH_TOKEN': 'private'}, clear=False):
            preflight = {'committed_file': committed, 'sha': sha}
            with self.assertRaisesRegex(RuntimeError, 'download failed'):
                PACKAGE.stage_source(preflight, Path(temporary), Path(temporary) / 'source',
                                     source_commit, package_commit, '1')
            self.assertNotIn('GH_TOKEN', PACKAGE.os.environ)

        def fake_loader(preflight_value, relative, commit, *, pin=None):
            module = original_loader(preflight_value, relative, commit, pin=pin)
            module['stage_handoff'] = lambda *args, **kwargs: {
                'status': 'failed', 'scope': 'authenticated source bundle and package commitments only',
                'origin': {'status': 'failed', 'run_id': 1}, 'preflight': {'status': 'failed'}}
            return module

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary, patch.object(PACKAGE, 'load_committed', fake_loader), \
                patch.dict(PACKAGE.os.environ, {'GH_TOKEN': 'private'}, clear=False):
            preflight = {'committed_file': committed, 'sha': sha}
            with self.assertRaisesRegex(ValueError, 'downloaded source handoff binding'):
                PACKAGE.stage_source(preflight, Path(temporary), Path(temporary) / 'source',
                                     source_commit, package_commit, '1')
            self.assertNotIn('GH_TOKEN', PACKAGE.os.environ)

    def test_main_rejects_stale_bundle_argument_before_work(self):
        with self.assertRaises(SystemExit):
            PACKAGE.main(['--trusted-source-checkout', 'source', '--expected-source-commit', 'a' * 40,
                          '--expected-package-commit', 'b' * 40, '--expected-run-id', '1',
                          '--bundle', 'old.zip'])

    def test_fresh_storage_rejects_files_directories_and_links(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            runner = {'E_ROOT': root / 'e-root', 'IMAGE': root / 'image', 'CANONICAL_TASK': root / 'task'}
            PACKAGE.require_fresh_storage(runner)
            for name, make in (
                    ('file', lambda path: path.write_bytes(b'foreign')),
                    ('directory', lambda path: path.mkdir())):
                path = root / name
                make(path)
                bad = dict(runner, E_ROOT=path)
                with self.subTest(storage=name), self.assertRaisesRegex(ValueError, 'pre-existing package storage'):
                    PACKAGE.require_fresh_storage(bad)
            link = root / 'link'
            try:
                link.symlink_to(root / 'target')
                check = lambda: PACKAGE.require_fresh_storage(dict(runner, IMAGE=link))
            except (OSError, NotImplementedError):
                check = lambda: PACKAGE.require_fresh_storage(dict(runner, IMAGE=link))
                with patch.object(Path, 'is_symlink', lambda path: path == link):
                    with self.assertRaisesRegex(ValueError, 'pre-existing package storage'):
                        check()
                return
            with self.assertRaisesRegex(ValueError, 'pre-existing package storage'):
                check()

    def test_invalid_and_expired_workload_deadlines_fail_before_launch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            for timeout in (0, 4201, True, 1.0):
                runner, events = bounded_runner(Process())
                with self.subTest(timeout=repr(timeout)), self.assertRaisesRegex(ValueError, 'package workload deadline'):
                    PACKAGE.run_bounded(runner, Path(temporary), ['fixture'], Path(temporary), {}, timeout, 'deadline')
                self.assertEqual(events, [])
                self.assertIsNone(runner.get('ACTIVE'))
        with self.assertRaisesRegex(ValueError, 'package job deadline'):
            PACKAGE.remaining_seconds(time.monotonic() - 1, 900)


if __name__ == '__main__':
    unittest.main()
