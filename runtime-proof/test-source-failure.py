#!/usr/bin/env python3
"""Regression tests for sanitized source-runner failure context."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import ast
import json
import unittest


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
