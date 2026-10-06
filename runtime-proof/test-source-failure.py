#!/usr/bin/env python3
"""Regression tests for sanitized source-runner failure context."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path, PurePosixPath
import ast
import json
import os
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
RUNNER = ROOT / 'run-fresh-source.py'


class VirtualLinuxPath:
    base = None
    symlinks = set()
    stat_overrides = {}

    def __init__(self, display, actual=None):
        if isinstance(display, VirtualLinuxPath):
            self.display = display.display
            self.actual = display.actual
            return
        self.display = PurePosixPath(str(display)).as_posix()
        if actual is None:
            relative = self.display.lstrip('/').replace('/', os.sep)
            actual = self.base / relative
        self.actual = Path(actual)

    @classmethod
    def reset(cls):
        cls.symlinks = set()
        cls.stat_overrides = {}

    @property
    def name(self):
        return PurePosixPath(self.display).name

    @property
    def parent(self):
        return VirtualLinuxPath(PurePosixPath(self.display).parent.as_posix(), self.actual.parent)

    @property
    def parts(self):
        return PurePosixPath(self.display).parts

    def __truediv__(self, value):
        text = value.display if isinstance(value, VirtualLinuxPath) else str(value)
        return VirtualLinuxPath(PurePosixPath(self.display, text).as_posix(), self.actual / text)

    def __str__(self):
        return self.display

    def __fspath__(self):
        return os.fspath(self.actual)

    def __repr__(self):
        return 'VirtualLinuxPath(%r)' % self.display

    def __hash__(self):
        return hash(self.display)

    def __eq__(self, other):
        return isinstance(other, VirtualLinuxPath) and self.display == other.display

    def __lt__(self, other):
        return self.display < other.display

    def is_absolute(self):
        return self.display.startswith('/')

    def resolve(self):
        return self

    def relative_to(self, other):
        return PurePosixPath(self.display).relative_to(PurePosixPath(str(other)))

    def exists(self):
        return self.actual.exists()

    def is_file(self):
        return self.actual.is_file()

    def is_dir(self):
        return self.actual.is_dir()

    def is_symlink(self):
        return self.display in self.symlinks or self.actual.is_symlink()

    def stat(self):
        if self.display in self.stat_overrides:
            return self.stat_overrides[self.display]
        if self.display.endswith('/result.json'):
            return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1,
                                   st_size=self.actual.stat().st_size, st_mtime_ns=17,
                                   st_dev=30, st_ino=31)
        if self.display == '/e-root' or self.display.startswith('/e-root/') or \
                self.display.startswith('/var/tmp/m-local-kali-runtime-regressions-v3-'):
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=65534, st_nlink=2,
                                   st_size=0, st_mtime_ns=17, st_dev=20,
                                   st_ino=23 if self.display == '/e-root' else 22)
        return self.actual.stat()

    def lstat(self):
        if self.display in self.symlinks:
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0, st_nlink=1,
                                   st_size=0, st_mtime_ns=17, st_dev=30, st_ino=31)
        return self.stat()

    def read_bytes(self):
        return self.actual.read_bytes()

    def read_text(self, **kwargs):
        return self.actual.read_text(**kwargs)

    def open(self, *args, **kwargs):
        return self.actual.open(*args, **kwargs)


class VirtualOS:
    def __init__(self, payload):
        self.payload = payload
        self._os = os
        self.O_RDONLY = os.O_RDONLY
        self.O_NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0x20000)
        self.O_CLOEXEC = getattr(os, 'O_CLOEXEC', 0x80000)

    def __getattr__(self, name):
        return getattr(self._os, name)

    def open(self, path, flags, *args, **kwargs):
        if not flags & self.O_NOFOLLOW:
            raise AssertionError('capture must request no-follow descriptor')
        return self._os.open(os.fspath(path), self._os.O_RDONLY)

    def fstat(self, _fd):
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1,
                               st_size=len(self.payload), st_mtime_ns=17,
                               st_dev=30, st_ino=31)


def load_runner_source():
    tree = ast.parse(RUNNER.read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign,
                                                              ast.AnnAssign, ast.FunctionDef))]
    namespace = {'__file__': str(RUNNER), '__name__': 'source_failure_test_runner'}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER), 'exec'), namespace)
    handler = next(node for node in tree.body if isinstance(node, ast.If) and
                   isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) and
                   node.test.left.id == '__name__' and len(node.test.comparators) == 1 and
                   isinstance(node.test.comparators[0], ast.Constant) and
                   node.test.comparators[0].value == '__main__')
    return namespace, compile(ast.Module(body=[handler], type_ignores=[]), str(RUNNER), 'exec')


def known_failure_chain():
    try:
        raise RuntimeError('source cold-compile failed')
    except RuntimeError as stage_error:
        try:
            raise RuntimeError('source cold-compile unidentified mount cleanup') from stage_error
        except RuntimeError as cleanup_error:
            try:
                raise RuntimeError('owned mount cleanup guard') from cleanup_error
            except RuntimeError as guard_error:
                return guard_error


class SourceFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.namespace, cls.handler = load_runner_source()

    def helper(self):
        helper = self.namespace.get('sanitized_failure_context')
        self.assertIsNotNone(helper, 'runner must expose sanitized_failure_context')
        return helper

    def execute_handler(self, error):
        namespace = dict(self.namespace)
        namespace.update({'__name__': '__main__', 'PRIVATE_LOG_DIR': None})

        def failing_main():
            raise error

        namespace['main'] = failing_main
        output = StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                exec(self.handler, namespace)
        return raised.exception.code, output.getvalue()

    def execute_actual_main_failure(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT)
        root = Path(temporary.name) / 'e-root'
        root.mkdir()
        workspace = Path(temporary.name) / 'runner-workspace'
        workspace.mkdir()

        def fake_run(command, *args, **kwargs):
            if command[:2] == ['/usr/sbin/losetup', '--detach']:
                return SimpleNamespace(returncode=1, stdout='')
            if command[:2] == ['/usr/sbin/losetup', '--associated']:
                return SimpleNamespace(returncode=1, stdout='')
            return SimpleNamespace(returncode=0, stdout='')

        diagnostics = dict(operation='setup', last_scoped_command=None, body_completed=False,
                           body_failure_type=None, cleanup_failures=[])
        stubs = {
            'producer_binding': lambda: {},
            'host_guard': lambda: None,
            'manifest_inputs': lambda: ({}, {}, {}),
            'run_probe': lambda ignored: (Path(temporary.name) / 'probe.json', {}),
            'mount_image': lambda: None,
            'prepare_task': lambda *args: 'app',
            'materialize_runtime': lambda *args: (_ for _ in ()).throw(
                RuntimeError('PRIVATE_MATERIALIZE_SENTINEL /private/path')),
            'E_ROOT': root,
            'IMAGE_LOOP': root / 'loop-device',
            'OWNED_MOUNTS': set(),
            'FAILURE_DIAGNOSTICS': diagnostics,
        }
        original_name = self.namespace['__name__']
        try:
            with patch.dict(self.namespace, stubs), \
                    patch.object(self.namespace['tempfile'], 'mkdtemp', return_value=str(workspace)), \
                    patch.object(self.namespace['signal'], 'signal', return_value=None), \
                    patch.object(self.namespace['subprocess'], 'run', side_effect=fake_run), \
                    patch.dict(self.namespace['os'].environ, {}, clear=False):
                self.namespace['__name__'] = '__main__'
                output = StringIO()
                with redirect_stdout(output):
                    with self.assertRaises(SystemExit) as raised:
                        exec(self.handler, self.namespace)
                return raised.exception.code, json.loads(output.getvalue()), diagnostics
        finally:
            self.namespace['__name__'] = original_name
            temporary.cleanup()

    def matrix_fixture(self, *, result=None):
        temporary = tempfile.TemporaryDirectory(dir=ROOT)
        base = Path(temporary.name)
        name = 'm-local-kali-runtime-regressions-v3-fixture'
        candidate = base / 'var' / 'tmp' / name
        backing = base / 'e-root' / name
        candidate.mkdir(parents=True)
        backing.mkdir(parents=True)
        if result is None:
            phases = [dict(name=name, status='passed', exit_code=0, guard_reason=None)
                      for name in self.namespace['MATRIX_PHASE_NAMES'][:10]]
            interfaces = [dict(name='codec', status='passed', exit_code=0, guard_reason=None),
                          dict(name='controls', status='failed', exit_code=17, guard_reason=None)]
            result = dict(status='failed', phases=phases, interface_proofs=interfaces)
        payload = json.dumps(result, separators=(',', ':')).encode()
        (candidate / 'result.json').write_bytes(payload)
        VirtualLinuxPath.base = base
        VirtualLinuxPath.reset()
        return temporary, VirtualLinuxPath('/var/tmp/' + name), VirtualLinuxPath('/e-root'), payload

    def capture_fixture(self, *, result=None, before=None, owned=None):
        temporary, candidate, e_root, payload = self.matrix_fixture(result=result)
        before = set() if before is None else before
        owned = set() if owned is None else owned
        virtual_os = VirtualOS(payload)
        paths = {
            'Path': lambda value: VirtualLinuxPath(value),
            'E_ROOT': e_root,
            'OWNED_MOUNTS': owned,
            'mounts': lambda: {candidate},
            'is_mount': lambda path: path in {candidate, e_root},
            'os': virtual_os,
        }
        return temporary, candidate, e_root, before, owned, paths

    def test_main_handler_preserves_known_failure_chain(self):
        code, output = self.execute_handler(known_failure_chain())
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload['status'], 'failed')
        self.assertEqual(payload['error'], 'owned mount cleanup guard')
        self.assertEqual(payload['failure_context'], [
            'owned mount cleanup guard',
            'source cold-compile unidentified mount cleanup',
            'source cold-compile failed',
        ])

    def test_generic_error_keeps_allowed_cause_without_private_text(self):
        error = ValueError('PRIVATE_FAILURE_SENTINEL /var/lib/secret-token')
        error.__cause__ = RuntimeError('source bootstrap failed')
        code, output = self.execute_handler(error)
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload['error'], 'source runner aborted')
        self.assertEqual(payload['failure_context'], ['source bootstrap failed'])
        self.assertNotIn('PRIVATE_FAILURE_SENTINEL', output)

    def test_subclasses_and_non_string_runtime_args_are_omitted(self):
        class DerivedRuntimeError(RuntimeError):
            pass

        class PrivateText:
            def __str__(self):
                return 'PRIVATE_STR_SENTINEL'

        self.assertEqual(self.helper()(DerivedRuntimeError('source matrix failed')), [])
        self.assertEqual(self.helper()(RuntimeError(PrivateText())), [])
        self.assertEqual(self.helper()(RuntimeError('source matrix failed', 'private detail')), [])

    def test_actual_main_failure_diagnostics_survive_cleanup_masking(self):
        code, payload, diagnostics = self.execute_actual_main_failure()
        self.assertEqual(code, 1)
        self.assertEqual(payload['error'], 'owned mount cleanup guard')
        self.assertEqual(payload['failure_diagnostics']['operation'], 'runtime-materialization')
        self.assertIsNone(payload['failure_diagnostics']['last_scoped_command'])
        self.assertFalse(payload['failure_diagnostics']['body_completed'])
        self.assertEqual(payload['failure_diagnostics']['body_failure_type'], 'RuntimeError')
        self.assertEqual(payload['failure_diagnostics']['cleanup_failures'],
                         ['loop detach', 'loop detach confirmation'])
        self.assertNotIn('PRIVATE_MATERIALIZE_SENTINEL', json.dumps(payload))

    def test_matrix_failure_diagnostics_survive_cleanup_masking(self):
        state = self.namespace['FAILURE_DIAGNOSTICS']
        original = dict(state)
        state.update(matrix_failure=dict(name='runtime-boundary-probe', status='failed',
                                        exit_code=17, guard_reason=None))
        try:
            code, output = self.execute_handler(RuntimeError('owned mount cleanup guard'))
            self.assertEqual(code, 1)
            payload = json.loads(output)
            self.assertEqual(payload['failure_diagnostics']['matrix_failure'],
                             dict(name='runtime-boundary-probe', status='failed',
                                  exit_code=17, guard_reason=None))
        finally:
            state.clear()
            state.update(original)

    def test_matrix_failure_sanitizer_projects_finite_four_key_shape(self):
        helper = self.namespace.get('sanitized_matrix_failure')
        self.assertIsNotNone(helper, 'runner must expose sanitized_matrix_failure')
        valid = dict(name='controls', status='failed', exit_code=17, guard_reason=None,
                     private='PRIVATE_SENTINEL')
        self.assertEqual(helper(valid), dict(name='controls', status='failed',
                                             exit_code=17, guard_reason=None))
        self.assertEqual(helper(dict(name='codec', status='guarded', exit_code=-2,
                                     guard_reason='timeout')),
                         dict(name='codec', status='guarded', exit_code=-2,
                              guard_reason='timeout'))
        invalid = [None, [], {'name': 'private'},
                   dict(name='controls', status='failed', exit_code=True, guard_reason=None),
                   dict(name='controls', status='failed', exit_code=256, guard_reason=None),
                   dict(name='controls', status='failed', exit_code=0, guard_reason='timeout'),
                   dict(name='controls', status='guarded', exit_code=0, guard_reason=None),
                   dict(name='controls', status='guarded', exit_code=0, guard_reason='PRIVATE')]
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(helper(value))

    def test_capture_matrix_failure_valid_virtual_mount_is_read_only(self):
        temporary, candidate, _e_root, _before, owned, paths = self.capture_fixture(
            owned=None)
        sentinel = VirtualLinuxPath('/var/tmp/owned-marker')
        owned.add(sentinel)
        paths['OWNED_MOUNTS'] = owned
        original_owned = set(owned)
        try:
            with patch.dict(self.namespace, paths):
                result = self.namespace['capture_matrix_failure'](set())
            self.assertEqual(result, dict(name='controls', status='failed', exit_code=17,
                                          guard_reason=None))
            self.assertEqual(owned, original_owned)
        finally:
            temporary.cleanup()

    def test_capture_matrix_failure_rejects_unsafe_mount_and_receipt_shapes(self):
        cases = ('missing', 'ambiguous', 'non-backed', 'mount-symlink', 'result-symlink',
                 'file-link', 'nonregular', 'oversized', 'unknown-row', 'status-mismatch',
                 'early-failure', 'short-prefix', 'wrong-interface-prefix')
        for case in cases:
            with self.subTest(case=case):
                temporary, candidate, e_root, _before, owned, paths = self.capture_fixture(
                    owned=None)
                sentinel = VirtualLinuxPath('/var/tmp/owned-marker')
                owned.add(sentinel)
                paths['OWNED_MOUNTS'] = owned
                try:
                    backing = e_root / candidate.name
                    result_path = candidate / 'result.json'
                    if case == 'missing':
                        result_path.actual.unlink()
                    elif case == 'ambiguous':
                        paths['mounts'] = lambda: {candidate, VirtualLinuxPath(
                            '/var/tmp/m-local-kali-runtime-regressions-v3-other')}
                    elif case == 'non-backed':
                        VirtualLinuxPath.stat_overrides[backing.display] = SimpleNamespace(
                            st_mode=stat.S_IFDIR | 0o700, st_uid=65534, st_nlink=2,
                            st_size=0, st_mtime_ns=17, st_dev=20, st_ino=99)
                    elif case == 'mount-symlink':
                        VirtualLinuxPath.symlinks.add(candidate.display)
                    elif case == 'result-symlink':
                        VirtualLinuxPath.symlinks.add(result_path.display)
                    elif case == 'file-link':
                        VirtualLinuxPath.stat_overrides[result_path.display] = SimpleNamespace(
                            st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=2,
                            st_size=1, st_mtime_ns=17, st_dev=30, st_ino=31)
                    elif case == 'nonregular':
                        VirtualLinuxPath.stat_overrides[result_path.display] = SimpleNamespace(
                            st_mode=stat.S_IFDIR | 0o600, st_uid=0, st_nlink=1,
                            st_size=1, st_mtime_ns=17, st_dev=30, st_ino=31)
                    elif case == 'oversized':
                        result_path.actual.write_bytes(b'x' * (1024 ** 2 + 1))
                    else:
                        receipt = json.loads(result_path.actual.read_text(encoding='utf-8'))
                        if case == 'unknown-row':
                            receipt['phases'][0]['name'] = 'private'
                        elif case == 'status-mismatch':
                            receipt['status'] = 'passed'
                        elif case == 'early-failure':
                            receipt['phases'][-1].update(status='failed', exit_code=3,
                                                        guard_reason=None)
                        elif case == 'short-prefix':
                            receipt['phases'] = []
                        else:
                            receipt['interface_proofs'][0]['name'] = 'private'
                        result_path.actual.write_text(json.dumps(receipt), encoding='utf-8')
                        paths['os'] = VirtualOS(result_path.actual.read_bytes())
                    with patch.dict(self.namespace, paths):
                        self.assertIsNone(self.namespace['capture_matrix_failure'](set()))
                    self.assertEqual(owned, {sentinel})
                finally:
                    temporary.cleanup()

    def test_run_stage_captures_matrix_failure_before_cleanup_masks_error(self):
        temporary, candidate, _e_root, _before, owned, paths = self.capture_fixture()
        sentinel = VirtualLinuxPath('/var/tmp/owned-marker')
        owned.add(sentinel)
        paths['OWNED_MOUNTS'] = owned
        workspace = Path(temporary.name) / 'workspace'
        workspace.mkdir()
        diagnostics = dict(operation='matrix', last_scoped_command=None,
                           body_completed=False, body_failure_type=None,
                           cleanup_failures=[], matrix_failure=None)
        actual_capture = self.namespace['capture_matrix_failure']

        def capture_with_virtual_paths(before):
            with patch.dict(self.namespace, paths):
                return actual_capture(before)

        def fail_run(*args, **kwargs):
            raise RuntimeError('source matrix failed')

        def mask_cleanup(*args):
            raise RuntimeError('owned mount cleanup guard')

        try:
            mounts_seen = iter((set(), {candidate}))
            with patch.dict(self.namespace, {'mounts': lambda: next(mounts_seen),
                                             'run_command': fail_run,
                                             'assert_no_new_mounts': mask_cleanup,
                                             'capture_matrix_failure': capture_with_virtual_paths,
                                             'FAILURE_DIAGNOSTICS': diagnostics,
                                             'OWNED_MOUNTS': owned}):
                with self.assertRaisesRegex(RuntimeError, '^owned mount cleanup guard$'):
                    self.namespace['run_stage'](Path(temporary.name), workspace, 'matrix',
                                                Path(temporary.name), Path(temporary.name),
                                                deadline=None)
            self.assertEqual(diagnostics['matrix_failure'],
                             dict(name='controls', status='failed', exit_code=17,
                                  guard_reason=None))
            self.assertEqual(owned, {sentinel})
        finally:
            temporary.cleanup()

    def test_actual_cleanup_sanitizes_finite_categories(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT)
        root = Path(temporary.name) / 'e-root'
        root.mkdir()
        (root / 'busy').write_text('busy', encoding='utf-8')
        bind_mount = Path(temporary.name) / 'bind-mount'
        bind_mount.mkdir()
        bind_target = Path(temporary.name) / 'bind-target'
        bind_target.mkdir()
        (bind_target / 'busy').write_text('busy', encoding='utf-8')
        diagnostics = dict(operation='setup', last_scoped_command=None, body_completed=False,
                           body_failure_type=None, cleanup_failures=[])
        root_unmounted = [False]

        def fake_run(command, *args, **kwargs):
            if command[:2] == ['/usr/bin/umount', str(root)]:
                root_unmounted[0] = True
            return SimpleNamespace(returncode=1, stdout='PRIVATE_CLEANUP_SENTINEL')

        def fake_is_mount(path):
            return (Path(path) == root and not root_unmounted[0]) or Path(path) == bind_mount

        try:
            with patch.dict(self.namespace, {'E_ROOT': root, 'IMAGE_LOOP': root / 'loop-device',
                                             'OWNED_MOUNTS': {bind_mount, bind_target},
                                             'FAILURE_DIAGNOSTICS': diagnostics}), \
                    patch.object(self.namespace['subprocess'], 'run', side_effect=fake_run), \
                    patch.dict(self.namespace, {'is_mount': fake_is_mount}):
                with self.assertRaisesRegex(RuntimeError, '^owned mount cleanup guard$'):
                    self.namespace['cleanup_mounts']()
                diagnostics['cleanup_failures'].append('loop detach')
                diagnostics['cleanup_failures'].append('PRIVATE_CLEANUP_SENTINEL')
                result = self.namespace['sanitized_failure_diagnostics']()
            self.assertEqual(set(result['cleanup_failures']), {
                'owned bind unmount', 'owned bind target cleanup', 'image unmount',
                'loop detach', 'loop detach confirmation', 'image target cleanup',
            })
            self.assertEqual(len(result['cleanup_failures']), 6)
            self.assertNotIn('PRIVATE_CLEANUP_SENTINEL', json.dumps(result))
        finally:
            temporary.cleanup()

    def test_diagnostics_sanitizer_rejects_invalid_private_fields(self):
        state = dict(operation={'private': 'OPERATION_SENTINEL'},
                     last_scoped_command='PRIVATE_COMMAND_SENTINEL', body_completed='yes',
                     body_failure_type=object(),
                     cleanup_failures=['loop detach', {'private': 'CLEANUP_SENTINEL'}, 'unknown'])
        with patch.dict(self.namespace, {'FAILURE_DIAGNOSTICS': state}):
            result = self.namespace['sanitized_failure_diagnostics']()
        self.assertEqual(result, dict(operation=None, last_scoped_command=None,
                                      body_completed=False, body_failure_type=None,
                                      cleanup_failures=['loop detach'], matrix_failure=None))
        self.assertNotIn('SENTINEL', json.dumps(result))

    def test_scoped_command_records_entered_finite_label(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT)
        root = Path(temporary.name)
        mountpoint = root / 'mountpoint'
        mountpoint.mkdir()
        process = SimpleNamespace(returncode=0, poll=lambda: 0, wait=lambda *args, **kwargs: None)
        state = dict(controls_confirmed_before_workload=True, requested_limits={}, cleanup={})
        helper = {
            'mounted_empty': lambda ignored: mountpoint,
            'launch_scope': lambda *args, **kwargs: (process, state),
            'sample_scope': lambda ignored: 0,
            'scope_guard': lambda *args, **kwargs: None,
            'stop_scope': lambda *args, **kwargs: {'cgroup_empty': True, 'launcher_stopped': True},
        }
        diagnostics = dict(operation='setup', last_scoped_command=None, body_completed=False,
                           body_failure_type=None, cleanup_failures=[])
        try:
            with patch.dict(self.namespace, {'E_ROOT': root, 'OWNED_MOUNTS': set(),
                                             'FAILURE_DIAGNOSTICS': diagnostics,
                                             'resource_helper': lambda: helper}):
                result = self.namespace['scoped_command']('Pillow dependency guard', ['fake-command'],
                                                          cwd=root, environment={}, workspace=root)
                sanitized = self.namespace['sanitized_failure_diagnostics']()
            self.assertEqual(result['controls_confirmed_before_workload'], True)
            self.assertEqual(sanitized['last_scoped_command'], 'Pillow dependency guard')
        finally:
            temporary.cleanup()

    def test_stage_validation_context_survives_cleanup_masking(self):
        error = RuntimeError('owned mount cleanup guard')
        error.__cause__ = RuntimeError('source cold-compile unidentified mounts')
        code, output = self.execute_handler(error)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)['failure_context'], [
            'owned mount cleanup guard', 'source cold-compile unidentified mounts'])

    def test_explicit_cause_precedes_context(self):
        error = RuntimeError('owned mount cleanup guard')
        error.__cause__ = RuntimeError('source bootstrap failed')
        error.__context__ = RuntimeError('source matrix timeout')
        self.assertEqual(self.helper()(error), ['owned mount cleanup guard', 'source bootstrap failed'])

        suppressed = RuntimeError('owned mount cleanup guard')
        suppressed.__context__ = RuntimeError('source matrix timeout')
        suppressed.__suppress_context__ = True
        self.assertEqual(self.helper()(suppressed), ['owned mount cleanup guard'])

    def test_private_and_non_runtime_messages_are_omitted(self):
        error = RuntimeError('owned mount cleanup guard')
        error.__cause__ = RuntimeError('private /var/log/token=SECRET')
        error.__cause__.__cause__ = ValueError('source matrix failed')
        error.__cause__.__cause__.__cause__ = RuntimeError('source matrix failed', 'private detail')
        self.assertEqual(self.helper()(error), ['owned mount cleanup guard'])

    def test_cycle_and_depth_are_bounded(self):
        first = RuntimeError('source cold-compile failed')
        second = RuntimeError('source matrix timeout')
        first.__cause__ = second
        second.__cause__ = first
        result = self.helper()(first)
        self.assertEqual(set(result), {'source cold-compile failed', 'source matrix timeout'})
        self.assertLessEqual(len(result), 8)

        labels = [
            'owned mount cleanup guard', 'source cold-compile failed', 'source cold-compile timeout',
            'source cold-compile unavailable', 'source cold-compile unidentified mount cleanup',
            'source bootstrap failed', 'source bootstrap timeout', 'source bootstrap unavailable',
            'source bootstrap unidentified mount cleanup',
        ]
        error = None
        for label in reversed(labels):
            current = RuntimeError(label)
            if error is not None:
                current.__cause__ = error
            error = current
        self.assertEqual(self.helper()(error), labels[:8])

    def test_bare_cleanup_failure_has_one_sanitized_label(self):
        self.assertEqual(self.helper()(RuntimeError('owned mount cleanup guard')),
                         ['owned mount cleanup guard'])


if __name__ == '__main__':
    unittest.main()
