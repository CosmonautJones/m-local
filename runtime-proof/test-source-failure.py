#!/usr/bin/env python3
"""Regression tests for sanitized source-runner failure context."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import ast
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
RUNNER = ROOT / 'run-fresh-source.py'


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
                                      cleanup_failures=['loop detach']))
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
