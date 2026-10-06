#!/usr/bin/env python3
"""Synthetic producer/build/export integration tests for the source handoff."""

from pathlib import Path
import ast
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
CHECKOUT = ROOT.parent
VERIFY_SPEC = importlib.util.spec_from_file_location('verify_source_handoff', ROOT / 'verify-source-handoff-v9.py')
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)
FIXTURE_SPEC = importlib.util.spec_from_file_location('test_source_handoff', ROOT / 'test-source-handoff.py')
FIXTURE = importlib.util.module_from_spec(FIXTURE_SPEC)
FIXTURE_SPEC.loader.exec_module(FIXTURE)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_runner():
    path = ROOT / 'run-fresh-source.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign,
                                                              ast.AnnAssign, ast.FunctionDef))]
    namespace = {'__file__': str(path), '__name__': 'source_export_test_runner'}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class SourceExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner()
        cls.commit = subprocess.check_output(['git', '-C', str(CHECKOUT), 'rev-parse', 'HEAD'], text=True).strip()

    def setUp(self):
        self.fixture = FIXTURE.SourceHandoffTests('test_valid_synthetic_commitment_bundle')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def _git_io(self, *, head=None, tamper=None):
        head = head or self.commit
        live = {
            'runtime-proof/run-fresh-source.py': (ROOT / 'run-fresh-source.py').read_bytes(),
            'runtime-proof/kali-build-resources-v2.py': (ROOT / 'kali-build-resources-v2.py').read_bytes(),
            'runtime-proof/verify-source-handoff-v8.py': (ROOT / 'verify-source-handoff-v8.py').read_bytes(),
            'runtime-proof/verify-source-handoff-v9.py': (ROOT / 'verify-source-handoff-v9.py').read_bytes(),
        }
        if tamper:
            live[tamper] += b' injected blob mismatch'

        def fake(command, *args, **kwargs):
            command = [str(part) for part in command]
            if 'rev-parse' in command:
                value = head.encode() + b'\n'
            elif 'show' in command:
                relative = command[-1].split(':', 1)[-1]
                if relative not in live:
                    raise subprocess.CalledProcessError(128, command)
                value = live[relative]
            else:
                raise AssertionError('unexpected git command: ' + ' '.join(command))
            if kwargs.get('text') or kwargs.get('encoding'):
                return value.decode(kwargs.get('encoding') or 'utf-8')
            return value

        return fake

    def _producer(self, **changes):
        environment = {'GITHUB_SHA': self.commit, 'GITHUB_RUN_ID': '123'}
        environment.update(changes.pop('environment', {}))
        fake_git = self._git_io(head=changes.pop('head', None), tamper=changes.pop('tamper', None))
        with patch.dict(self.runner['os'].environ, environment, clear=False), \
                patch.object(self.runner['subprocess'], 'check_output', side_effect=fake_git):
            if changes.pop('missing_commit', False):
                self.runner['os'].environ.pop('GITHUB_SHA', None)
            if changes.pop('missing_run', False):
                self.runner['os'].environ.pop('GITHUB_RUN_ID', None)
            return self.runner['producer_binding']()

    def _synthetic_inputs(self):
        contract = self.fixture._contract()
        bootstrap = json.loads((self.fixture.bundle / 'source-bootstrap-receipt.json').read_text())
        matrix = json.loads((self.fixture.bundle / 'source-matrix-receipt.json').read_text())
        cold_contract = contract['cold_compile_provenance']
        phases = []
        for index, leaf in enumerate(cold_contract['leaf_controls']):
            expected = cold_contract['expected_e1030'] if index == 0 else cold_contract['corrected_compile']
            phases.append({'status': cold_contract['phase_statuses'][index], 'exit_code': expected['exit_code'],
                           'runtime_patch_sha256': cold_contract['phase_patches'][index],
                           'compiler_log_sha256': expected['compiler_log_sha256'],
                           'kernel_memory_scope': {'controls_confirmed_before_workload': True,
                                                  'cleanup': copy.deepcopy(leaf['cleanup'])},
                           'private_log': 'RAW_PRIVATE_LOG_SENTINEL',
                           'compiler_log': 'RAW_COMPILER_LOG_SENTINEL',
                           'credential': 'RAW_CREDENTIAL_SENTINEL'})
        cold = {'status': 'passed', 'phases': phases}
        return self.fixture.manifest, {'status': 'passed'}, bootstrap, matrix, cold

    def _build(self):
        producer = self._producer()
        manifest, cold_stage, bootstrap, matrix, cold = self._synthetic_inputs()
        workspace = Path(tempfile.mkdtemp(prefix='producer-workspace-', dir=self.fixture.temp.name))
        summary = self.runner['build_handoff'](workspace, manifest, cold_stage, bootstrap, matrix,
                                               cold, bootstrap['child'], matrix['child'], producer=producer)
        private = workspace / 'source-handoff-v7'
        return workspace, private, summary, producer

    def test_producer_binding_returns_exact_contract_and_rejects_bad_bindings(self):
        producer = self._producer()
        self.assertEqual(set(producer), {'commit_sha', 'run_id', 'source_runner_sha256', 'adapter_manifest_sha256',
                                         'application_revision', 'application_digest', 'jac_base',
                                         'official_binary_sha256', 'jacpython_sha256', 'helper_sha256',
                                         'entrypoint_policy', 'evidence_scope'})
        self.assertEqual(producer['commit_sha'], self.commit)
        self.assertEqual(producer['run_id'], '123')
        self.assertEqual(producer['source_runner_sha256'], digest(ROOT / 'run-fresh-source.py'))
        self.assertEqual(producer['helper_sha256'], digest(ROOT / 'kali-build-resources-v2.py'))
        failures = [
            ({'environment': {'GITHUB_SHA': 'x' * 40}}, 'source producer context'),
            ({'environment': {'GITHUB_RUN_ID': '0'}}, 'source producer context'),
            ({'environment': {'GITHUB_RUN_ID': '１２３'}}, 'source producer context'),
            ({'environment': {'GITHUB_RUN_ID': '01'}}, 'source producer context'),
            ({'missing_commit': True}, 'source producer context'),
            ({'missing_run': True}, 'source producer context'),
            ({'head': 'a' * 40}, 'source producer HEAD binding'),
        ]
        for source in ('runtime-proof/run-fresh-source.py', 'runtime-proof/kali-build-resources-v2.py',
                       'runtime-proof/verify-source-handoff-v8.py', 'runtime-proof/verify-source-handoff-v9.py'):
            failures.append(({'tamper': source}, 'source producer code binding'))
        for changes, label in failures:
            with self.subTest(changes=changes), self.assertRaisesRegex(RuntimeError, '^' + label + '$'):
                self._producer(**changes)

    def test_workflow_summary_output_is_one_line_and_requires_bindings(self):
        workflow = (CHECKOUT / '.github' / 'workflows' / 'runtime-source-proof.yml').read_text(encoding='utf-8')
        marker = "python3 -B - \"$RUNNER_TEMP/m-local-source-summary.json\" <<'PY'\n"
        start = workflow.index(marker) + len(marker)
        script = textwrap.dedent(workflow[start:workflow.index('\n          PY', start)])
        value = 'b' * 64
        summary = {'status': 'passed', 'handoff': {
            'contract_sha256': value,
            'verification': {'status': 'passed', 'commit_sha': self.commit, 'run_id': '123',
                             'contract_sha256': value},
        }}

        def run(case, *, environment=None):
            with tempfile.TemporaryDirectory(dir=self.fixture.temp.name) as directory:
                directory = Path(directory)
                summary_path = directory / 'summary.json'
                output_path = directory / 'github-output'
                summary_path.write_text(json.dumps(case), encoding='utf-8')
                env = os.environ.copy()
                env.update({'GITHUB_SHA': self.commit, 'GITHUB_RUN_ID': '123',
                            'GITHUB_OUTPUT': str(output_path), 'PYTHONDONTWRITEBYTECODE': '1'})
                if environment:
                    env.update(environment)
                result = subprocess.run([sys.executable, '-B', '-c', script, str(summary_path)],
                                        capture_output=True, text=True, env=env)
                return result, output_path.exists(), output_path.read_bytes() if output_path.exists() else b''

        result, exists, output = run(summary)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(exists)
        self.assertEqual(output, ('contract_sha256=' + value + '\n').encode('ascii'))
        self.assertEqual(output.count(b'\n'), 1)

        cases = [
            ('commit', summary, {'GITHUB_SHA': 'f' * 40}),
            ('run', summary, {'GITHUB_RUN_ID': '999'}),
            ('status', dict(summary, status='failed'), None),
            ('hash', dict(summary, handoff=dict(summary['handoff'], contract_sha256='c' * 64)), None),
        ]
        for label, case, environment in cases:
            with self.subTest(binding=label):
                result, exists, output = run(case, environment=environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(exists)
                self.assertEqual(output, b'')

    def test_builder_creates_strict_38_file_private_bundle_without_private_sentinels(self):
        workspace, private, summary, producer = self._build()
        result = VERIFY.verify_bundle(private, CHECKOUT, expected_commit=producer['commit_sha'],
                                      expected_run_id=producer['run_id'],
                                      expected_contract_sha256=summary['contract_sha256'])
        self.assertEqual(result['member_count'], 36)
        self.assertEqual(len([path for path in private.rglob('*') if path.is_file()]), 38)
        blob = b''.join(path.read_bytes() for path in private.rglob('*') if path.is_file())
        for sentinel in (b'RAW_PRIVATE_LOG_SENTINEL', b'RAW_COMPILER_LOG_SENTINEL', b'RAW_CREDENTIAL_SENTINEL'):
            self.assertNotIn(sentinel, blob)

    def test_valid_export_matches_private_bundle_and_normalizes_modes(self):
        workspace, private, summary, producer = self._build()
        export = Path(self.fixture.temp.name) / 'public-export'
        with patch.dict(self.runner, {'SOURCE_EXPORT': export}):
            exported = self.runner['export_handoff'](workspace, summary, producer)
        private_files = {path.relative_to(private).as_posix(): path.read_bytes() for path in private.rglob('*') if path.is_file()}
        public_files = {path.relative_to(export).as_posix(): path.read_bytes() for path in export.rglob('*') if path.is_file()}
        self.assertEqual(public_files, private_files)
        self.assertEqual(exported['contract_sha256'], summary['contract_sha256'])
        self.assertEqual(exported['scope'], 'sanitized commitment bundle verification')
        if os.name == 'posix':
            self.assertEqual(export.stat().st_mode & 0o777, 0o755)
            for path in export.rglob('*'):
                if path.is_dir():
                    self.assertEqual(path.stat().st_mode & 0o777, 0o755)
                else:
                    self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_invalid_bundle_rejects_before_public_copy(self):
        workspace, private, summary, producer = self._build()
        source = private / 'files/source/jac/jaclang/runtime/context.jac'
        source.write_bytes(source.read_bytes() + b' invalid handoff')
        export = Path(self.fixture.temp.name) / 'public-export'
        with patch.dict(self.runner, {'SOURCE_EXPORT': export}), \
                self.assertRaisesRegex(ValueError, '^source member identity$'):
            self.runner['export_handoff'](workspace, summary, producer)
        self.assertFalse(export.exists())

    def test_existing_export_directory_or_symlink_is_preserved(self):
        workspace, private, summary, producer = self._build()
        export = Path(self.fixture.temp.name) / 'public-export'
        export.mkdir()
        keep = export / 'keep.bin'
        keep.write_bytes(b'unknown bytes')
        with patch.dict(self.runner, {'SOURCE_EXPORT': export}), \
                self.assertRaisesRegex(RuntimeError, '^source export destination occupied$'):
            self.runner['export_handoff'](workspace, summary, producer)
        self.assertEqual(keep.read_bytes(), b'unknown bytes')

        workspace, private, summary, producer = self._build()
        export = Path(self.fixture.temp.name) / 'public-symlink'
        outside = Path(self.fixture.temp.name) / 'outside.bin'
        outside.write_bytes(b'outside bytes')
        if os.name == 'posix':
            export.symlink_to(Path(self.fixture.temp.name) / 'missing-export-target')
        guard_calls = []
        original_exists = Path.exists
        original_is_symlink = Path.is_symlink

        def exists(path):
            return False if Path(path) == export else original_exists(path)

        def is_symlink(path):
            if Path(path) == export:
                guard_calls.append(Path(path))
                return True
            return original_is_symlink(path)

        with patch.object(Path, 'exists', new=exists), patch.object(Path, 'is_symlink', new=is_symlink), \
                patch.dict(self.runner, {'SOURCE_EXPORT': export}), \
                self.assertRaisesRegex(RuntimeError, '^source export destination occupied$'):
            self.runner['export_handoff'](workspace, summary, producer)
        self.assertEqual(guard_calls, [export])
        self.assertEqual(outside.read_bytes(), b'outside bytes')
        self.assertFalse(export.exists())
        if os.name == 'posix':
            self.assertTrue(export.is_symlink())


if __name__ == '__main__':
    unittest.main()
