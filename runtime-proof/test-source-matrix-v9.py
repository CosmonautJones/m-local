"""Synthetic tests for the v9 receipt and adapter binding boundary"""

from pathlib import Path
import ast
import hashlib
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
V8_MATRIX = ROOT / 'inputs/work/identity-runtime-v8/run-source-matrix-v8.py'
V8_STAGE = ROOT / 'inputs/work/identity-runtime-v8/run-source-stage-v8.py'
V9_MATRIX = ROOT / 'inputs/work/identity-runtime-v9/run-source-matrix-v9.py'
V9_STAGE = ROOT / 'inputs/work/identity-runtime-v9/run-source-stage-v9.py'
V9_MANIFEST = ROOT / 'inputs/v9-adapter-manifest.json'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def receipt_node(program):
    return next(node for node in ast.walk(ast.parse(program))
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'receipt'
                                                        for target in node.targets) and isinstance(node.value, ast.Call) and
                isinstance(node.value.func, ast.Name) and node.value.func.id == 'dict')


def emitted(program, verify):
    tree = ast.fix_missing_locations(ast.Module(body=[receipt_node(program)], type_ignores=[]))
    clock = type('Clock', (), {'monotonic': staticmethod(lambda: 1.0)})
    values = {'source': Path('source.py'), 'executed': Path('executed.py'), 'result_path': Path('workspace/result.json'),
              'official': Path('official'), 'work': Path('work'), 'gate_sha': 'a' * 64,
              'digest': lambda value: verify.JAC_SHA, 'PATCH_SHA256': verify.PATCH_AFTER,
              'MEMORY_HIGH': 7, 'MEMORY_MAX': 8, 'phases': [{}] * 10, 'interfaces': [{}] * 2,
              'started': 0.0, 'time': clock}
    exec(compile(tree, '<v9-receipt-fixture>', 'exec'), values)
    return values['receipt']

class SourceMatrixV9Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = load(V9_MATRIX, 'matrix_v9_adapter')
        cls.stage = load(V9_STAGE, 'stage_v9_adapter')
        cls.verify = load(ROOT / 'verify-source-handoff-v9.py', 'verify_v9_adapter')
        cls.runner = load(ROOT / 'run-fresh-source.py', 'fresh_runner_for_v9')
        cls.manifest = json.loads(V9_MANIFEST.read_text(encoding='utf-8'))

    def test_manifest_and_adapters_bind_counted_predecessors(self):
        expected = ('work/identity-runtime-v7/run-source-cold-compile-v7.py', 'work/identity-runtime-v7/run-source-bootstrap-v7.py',
                    'work/identity-runtime-v9/run-source-matrix-v9.py', 'work/identity-runtime-v9/run-source-stage-v9.py',
                    'work/identity-runtime-v8/run-source-matrix-v8.py', 'work/identity-runtime-v8/run-source-stage-v8.py')
        self.assertEqual(tuple(self.manifest['files']), expected)
        for module, predecessor in ((self.matrix, V8_MATRIX), (self.stage, V8_STAGE),
                                    (self.verify, ROOT / 'verify-source-handoff-v8.py')):
            self.assertEqual(sha(predecessor.read_bytes()), module.BASE_SHA)
        self.assertEqual(self.matrix.PROGRAM, V8_MATRIX.read_text(encoding='utf-8').replace(
            self.matrix.BEFORE, self.matrix.AFTER))
        self.assertEqual(self.stage.PROGRAM, V8_STAGE.read_text(encoding='utf-8').replace(
            self.stage.BEFORE, self.stage.AFTER))
        for path, metadata in self.manifest['files'].items():
            raw = (ROOT / 'inputs' / path).read_bytes()
            self.assertEqual((len(raw), sha(raw)), (metadata['bytes'], metadata['sha256']))

    def test_hash_and_marker_tampering_rejected_before_program_use(self):
        for module, predecessor in ((self.matrix, V8_MATRIX), (self.stage, V8_STAGE)):
            with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
                path = Path(temporary) / predecessor.name
                altered = predecessor.read_bytes() + b'\nraise RuntimeError("fixture must not execute")\n'
                path.write_bytes(altered)
                with self.assertRaisesRegex(RuntimeError, 'predecessor hash'):
                    module.load_program(path)
                for invalid in (altered.replace(module.BEFORE.encode(), b'', 1),
                                altered + module.BEFORE.encode()):
                    path.write_bytes(invalid)
                    with patch.object(module, 'BASE_SHA', sha(invalid)):
                        with self.assertRaisesRegex(RuntimeError, 'marker'):
                            module.load_program(path)
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'verify-source-handoff-v8.py'
            altered = (ROOT / 'verify-source-handoff-v8.py').read_bytes() + b'\nraise RuntimeError("fixture must not execute")\n'
            path.write_bytes(altered)
            with self.assertRaisesRegex(RuntimeError, 'predecessor hash'):
                self.verify.load_program(path)
            marker = b"ADAPTER_MANIFEST_SHA = 'dc8a0e3f50f01d43d0e1654e94648d581c54b064b1a9b18ce204c467a7ccb7a8'"
            invalid = altered.replace(marker, b'', 1)
            path.write_bytes(invalid)
            with patch.object(self.verify, 'BASE_SHA', sha(invalid)):
                with self.assertRaisesRegex(RuntimeError, 'adaptation marker'):
                    self.verify.load_program(path)

    def test_actual_constructor_scrub_and_strict_validator_require_false(self):
        child = emitted(self.matrix.PROGRAM, self.verify)
        self.assertIs(child['actual_smtp'], False)
        name = 'run-source-matrix-v9'
        scrub = self.runner.scrub_stage
        validate = self.verify._validate_receipt
        stage_sha = self.manifest['files'][self.verify.ADAPTER_PATHS[2]]['sha256']
        stage = {'status': 'passed', 'stage': name, 'wrapper_sha256': stage_sha,
                 'result_sha256': 'b' * 64, 'child_result_sha256': 'b' * 64,
                 'elapsed_seconds': 0.25, 'source_gate_sha256': 'a' * 64}
        valid = scrub(stage, child)
        validate(valid, name, stage_sha, 'a' * 64)
        old = scrub(stage, emitted(V8_MATRIX.read_text(encoding='utf-8'), self.verify))
        with self.assertRaises((RuntimeError, ValueError)):
            validate(old, name, stage_sha, 'a' * 64)
        for value in (None, True):
            child['actual_smtp'] = value
            with self.assertRaises((RuntimeError, ValueError)):
                validate(scrub(stage, child), name, stage_sha, 'a' * 64)

if __name__ == '__main__':
    unittest.main()
