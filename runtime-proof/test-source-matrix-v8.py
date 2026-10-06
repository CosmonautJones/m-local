#!/usr/bin/env python3
"""Tests for the v8 source-matrix loader-root adaptation boundary."""

from pathlib import Path, PurePosixPath
import ast
import hashlib
import importlib.util
import json
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
V3 = ROOT / 'inputs/work/identity-runtime-v3/run-identity-runtime-regressions.py'
LOADER = ROOT / 'inputs/work/identity-runtime-v3/runtime-loader-provenance.py'
V7_MATRIX = ROOT / 'inputs/work/identity-runtime-v7/run-source-matrix-v7.py'
V7_STAGE = ROOT / 'inputs/work/identity-runtime-v7/run-source-stage-v7.py'
V8_MATRIX = ROOT / 'inputs/work/identity-runtime-v8/run-source-matrix-v8.py'
V8_STAGE = ROOT / 'inputs/work/identity-runtime-v8/run-source-stage-v8.py'
V8_MANIFEST = ROOT / 'inputs/v8-adapter-manifest.json'
HISTORICAL_ROOT = "root = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork').resolve()"
LOADER_HASH_ASSERT = "assert hashlib.sha256(loader_text.encode()).hexdigest() == '94e4da642dfa1dfff57001517362f701da109acec7246d0c7ad08afe1d5f724c'"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    spec = importlib.util.spec_from_file_location('matrix_v8_adapter', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assignment(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and \
                node.targets[0].id == name and isinstance(node.value, ast.Constant):
            return node.value.value
    raise AssertionError('missing assignment: ' + name)


def loader_block(generated):
    tree = ast.parse(generated)
    selected = []
    started = False
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'loader_text'
                                                for target in node.targets):
            if not started:
                started = True
            else:
                selected.append(node)
                break
        if started:
            selected.append(node)
    if not selected or not isinstance(selected[-1], ast.Assign):
        raise AssertionError('generated loader binding block missing')
    return selected


def execute_loader_block(generated, task):
    nodes = loader_block(generated)
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    namespace = {'Path': Path, 'hashlib': hashlib, 'task': task}
    exec(compile(module, '<generated-loader-binding>', 'exec'), namespace)
    return namespace['loader_text']


def containment_asserts(text):
    tree = ast.parse(text)
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Assert) and 'is_relative_to' in ast.dump(node, include_attributes=False)]


class SourceMatrixV8Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = load(V8_MATRIX)
        cls.source_text = V3.read_text(encoding='utf-8')
        cls.loader_text = LOADER.read_text(encoding='utf-8')

    def adapt_once(self, task, fork=PurePosixPath('/fresh/source/fork')):
        return self.adapter.adapt(V3, task, task / 'gate', fork, task / 'pointer', 'a' * 64)

    def test_v8_adapt_generates_real_loader_rewrite_and_preserves_frozen_source(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            task = Path(temporary) / 'task'
            (task / 'work/identity-runtime-v3').mkdir(parents=True)
            (task / 'work/identity-runtime-v3/runtime-loader-provenance.py').write_text(
                self.loader_text, encoding='utf-8')
            generated = self.adapt_once(task)
            self.assertEqual(sha(V3.read_bytes()), self.adapter.MATRIX_SHA256)
            self.assertEqual(sha(LOADER.read_bytes()), self.adapter.LOADER_SHA256)
            self.assertEqual(generated.count(LOADER_HASH_ASSERT), 1)
            self.assertIn("loader_root = " + repr(HISTORICAL_ROOT), generated)
            self.assertIn("assert loader_text.count(loader_root) == 1, 'fresh source loader root marker'", generated)
            self.assertIn("loader_text = loader_text.replace(loader_root, ", generated)
            rewritten = execute_loader_block(generated, task)
            bound_root = "root = Path('/fresh/source/fork').resolve()"
            self.assertEqual(rewritten.count(HISTORICAL_ROOT), 0)
            self.assertEqual(rewritten.count(bound_root), 1)
            self.assertEqual(sha(self.loader_text.encode()), self.adapter.LOADER_SHA256)
            self.assertEqual(self.source_text, V3.read_text(encoding='utf-8'))

    def test_generated_loader_keeps_both_containment_guards_and_sixteen_paths(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            task = Path(temporary) / 'task'
            loader_path = task / 'work/identity-runtime-v3/runtime-loader-provenance.py'
            loader_path.parent.mkdir(parents=True)
            loader_path.write_text(self.loader_text, encoding='utf-8')
            fresh = Path(temporary) / 'fresh'
            generated = self.adapt_once(task, fork=PurePosixPath(str(fresh)))
            rewritten = execute_loader_block(generated, task)
            original_guards = containment_asserts(self.loader_text)
            rewritten_guards = containment_asserts(rewritten)
            self.assertGreaterEqual(len(rewritten_guards), 2)
            self.assertEqual([ast.dump(node, include_attributes=False) for node in rewritten_guards],
                             [ast.dump(node, include_attributes=False) for node in original_guards])
            rewritten_tree = ast.parse(rewritten)
            root_assignment = next(node for node in rewritten_tree.body
                                   if isinstance(node, ast.Assign) and
                                   any(isinstance(target, ast.Name) and target.id == 'root'
                                       for target in node.targets))
            provenance_guards = [node for node in rewritten_tree.body if isinstance(node, ast.Assert)]
            self.assertEqual(len(provenance_guards), 3)
            guard_module = ast.fix_missing_locations(ast.Module(
                body=[root_assignment] + provenance_guards, type_ignores=[]))
            historical = Path(temporary) / 'historical'
            paths = {str(index): str(fresh / ('implementation-' + str(index) + '.py'))
                     for index in range(16)}
            namespace = {'Path': Path, 'paths': paths,
                         'runtime_roots': [str(fresh / 'jaclang')]}
            exec(compile(guard_module, '<loader-containment-guards>', 'exec'), namespace)
            with self.assertRaises(AssertionError):
                bad = dict(namespace, paths=dict(paths, **{'0': str(historical / 'old.py')}))
                exec(compile(guard_module, '<loader-containment-guards>', 'exec'), bad)
            with self.assertRaises(AssertionError):
                bad = dict(namespace, runtime_roots=[str(historical / 'jaclang')])
                exec(compile(guard_module, '<loader-containment-guards>', 'exec'), bad)
            with self.assertRaises(AssertionError):
                bad = dict(namespace, paths={str(index): value for index, value in enumerate(list(paths.values())[:15])})
                exec(compile(guard_module, '<loader-containment-guards>', 'exec'), bad)

    def test_loader_marker_and_hash_failures_are_rejected_by_generated_guards(self):
        variants = {
            'missing-marker': self.loader_text.replace(HISTORICAL_ROOT,
                                                       "root = Path('/foreign/root').resolve()", 1),
            'multiple-marker': self.loader_text + '\n' + HISTORICAL_ROOT + '\n',
            'altered-hash': self.loader_text + '\n# altered loader commitment\n',
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            task = Path(temporary) / 'task'
            loader_path = task / 'work/identity-runtime-v3/runtime-loader-provenance.py'
            loader_path.parent.mkdir(parents=True)
            generated = self.adapt_once(task)
            for name, variant in variants.items():
                with self.subTest(variant=name):
                    loader_path.write_text(variant, encoding='utf-8')
                    with self.assertRaises(AssertionError):
                        execute_loader_block(generated, task)

    def test_stage_v8_points_only_matrix_to_v8_and_manifest_pins_all_adapters(self):
        v8_stage = ast.parse(V8_STAGE.read_text(encoding='utf-8'))
        v7_stage = ast.parse(V7_STAGE.read_text(encoding='utf-8'))
        self.assertEqual(assignment(v8_stage, 'BOOTSTRAP'), assignment(v7_stage, 'BOOTSTRAP'))
        self.assertEqual(assignment(v8_stage, 'COLD_COMPILE'), assignment(v7_stage, 'COLD_COMPILE'))
        self.assertEqual(assignment(v8_stage, 'MATRIX'), 'work/identity-runtime-v8/run-source-matrix-v8.py')
        matrix = V8_MATRIX.read_text(encoding='utf-8')
        self.assertIn("MATRIX_SOURCE = 'work/identity-runtime-v3/run-identity-runtime-regressions.py'", matrix)
        self.assertIn("BOOTSTRAP_WRAPPER = 'work/identity-runtime-v7/run-source-bootstrap-v7.py'", matrix)
        manifest = json.loads(V8_MANIFEST.read_text(encoding='utf-8'))
        self.assertEqual(set(manifest['files']), {
            'work/identity-runtime-v7/run-source-cold-compile-v7.py',
            'work/identity-runtime-v7/run-source-bootstrap-v7.py',
            'work/identity-runtime-v8/run-source-matrix-v8.py',
            'work/identity-runtime-v8/run-source-stage-v8.py'})
        for relative, metadata in manifest['files'].items():
            path = ROOT / 'inputs' / relative
            self.assertEqual(path.stat().st_size, metadata['bytes'])
            self.assertEqual(sha(path.read_bytes()), metadata['sha256'])


if __name__ == '__main__':
    unittest.main()
