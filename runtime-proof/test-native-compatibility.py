"""Pure and narrow mount tests for the fresh native compatibility controller."""

from pathlib import Path
import ast
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / 'run-fresh-native-compatibility.py'
SUITE = ROOT / 'native-inputs/native-suite-v5/run-kali-package-suite.py'
LOADER = ROOT / 'native-inputs/native-suite-v5/package-runtime-loader-provenance.py'
SOURCE_TEST = ROOT / 'test-source-isolation.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class PureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control = load(CONTROL, 'native_compatibility_control')

    def test_frozen_phase_interface_and_catalog_contract_is_complete(self):
        self.assertEqual(self.control.PREFIX, 'm-local-native-compatibility-v1-')
        self.assertEqual(self.control.MAX_TIMEOUT, 8400)
        self.assertEqual(len(self.control.PHASES), 24)
        self.assertEqual(self.control.PHASES[:2], ('package-input-verification', 'catalog-cold-relocation'))
        self.assertEqual(self.control.PHASES[-2:], ('ui-dependencies', 'browser'))
        self.assertEqual(self.control.MATRIX_PHASES, (
            'materialization', 'commit-40001', 'commit-40P01', 'commit-55P03', 'commit-08006',
            'runtime-boundary-probe', 'runtime-lifecycle-probe', 'runtime-served-probe',
            'runtime-request-context-probe', 'runtime-nested-context-probe'))
        self.assertEqual(self.control.INTERFACES, ('codec', 'controls'))
        self.assertEqual(self.control.SCOPE, 'fresh-native-compatibility-only')

    def test_adaptation_rebinds_current_paths_and_preserves_immutable_suite(self):
        raw = SUITE.read_bytes()
        adapted = self.control._adapt_suite(raw, Path('/tmp/current-task'),
                                            Path('/tmp/verified-tools'), Path('/tmp/current-app'),
                                            Path('/tmp/current-fork'), Path('/tmp/current-app'))
        ast.parse(adapted.decode('utf-8'))
        for label, value in (('task', Path('/tmp/current-task')), ('verified', Path('/tmp/verified-tools')),
                             ('source', Path('/tmp/current-app'))):
            self.assertIn((label + ' = Path(' + repr(str(value)) + ')').encode(), adapted)
        self.assertIn(str(Path('/tmp/current-fork')).encode(), adapted)
        self.assertIn(b"hashlib.sha256((package / 'launcher').read_bytes()).hexdigest()", adapted)
        recipe_asserts = [node for node in ast.walk(ast.parse(adapted.decode('utf-8')))
                          if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)
                          and "executed_recipe_sha256" in ast.dump(node.test.left)]
        self.assertEqual(len(recipe_asserts), 1)
        self.assertEqual(recipe_asserts[0].test.comparators[0].value,
                         self.control.CURRENT_RECIPE_SHA256)
        for value in (self.control.OLD_TASK, self.control.OLD_VERIFIED,
                      self.control.OLD_FORK, self.control.OLD_APP):
            self.assertNotIn(value.encode(), adapted)
        self.assertEqual(raw, SUITE.read_bytes())

    def test_adaptation_preserves_frozen_assertion_set(self):
        raw = SUITE.read_bytes()
        adapted = self.control._adapt_suite(raw, Path('/tmp/current-task'),
                                            Path('/tmp/verified-tools'), Path('/tmp/current-app'),
                                            Path('/tmp/current-fork'), Path('/tmp/current-app'))

        def assertion_shapes(source):
            shapes = []
            for node in ast.walk(ast.parse(source.decode('utf-8'))):
                if not isinstance(node, ast.Assert):
                    continue
                shape = ast.dump(node, include_attributes=False)
                if "executed_recipe_sha256" in shape:
                    shape = 'allowed-recipe-binding'
                elif "launcher_sha256" in shape:
                    shape = 'allowed-launcher-binding'
                shapes.append(shape)
            return sorted(shapes)

        self.assertEqual(assertion_shapes(raw), assertion_shapes(adapted))

    def test_catalog_source_bounds_reads_and_preserves_frozen_assertions(self):
        raw = (ROOT / 'native-inputs/native-suite-v5/test-runtime-catalog-path-audit.py').read_bytes()
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            base = Path(temporary)
            catalog = base / 'catalog.bin'
            output = base / 'result.json'
            adapted = self.control._catalog_controls_source(
                raw, base / 'audit.py', catalog, base / 'package', base / 'roots.json', output)

            tree = ast.parse(adapted.decode('utf-8'))
            bounded_calls = [node for node in ast.walk(tree)
                             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                             and node.func.id == '_read_catalog_bounded']
            self.assertEqual(len(bounded_calls), 2)
            self.assertIn(b'_CATALOG_MAX_BYTES = 32 * 1024 ** 2', adapted)

            def assertion_shapes(source):
                return sorted(ast.dump(node, include_attributes=False)
                              for node in ast.walk(ast.parse(source))
                              if isinstance(node, ast.Assert))

            adapted_text = adapted.decode('utf-8')
            adapted_text = adapted_text.replace('assert directory.is_dir()\n', '')
            adapted_text = adapted_text.replace('assert probe.is_file()\n', '')
            generated_catalog = 'Path(' + repr(str(catalog)) + ')'
            adapted_text = adapted_text.replace(
                'hashlib.sha256(_read_catalog_bounded(' + generated_catalog + ')).hexdigest()',
                "hashlib.sha256((origin / 'stubcat.bin').read_bytes()).hexdigest()")
            self.assertEqual(assertion_shapes(raw.decode('utf-8')), assertion_shapes(adapted_text))

            catalog.write_bytes(b'x')
            selected = []
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    selected.append(node)
                elif isinstance(node, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == '_CATALOG_MAX_BYTES'
                        for target in node.targets):
                    selected.append(node)
                elif isinstance(node, ast.FunctionDef) and node.name == '_read_catalog_bounded':
                    selected.append(node)
            namespace = {}
            exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
                         'bounded-catalog-reader', 'exec'), namespace)
            namespace['_CATALOG_MAX_BYTES'] = 1
            oversized = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_size=2, st_nlink=1)
            with patch.object(Path, 'lstat', return_value=oversized), \
                    patch.object(Path, 'is_symlink', return_value=False), \
                    self.assertRaisesRegex(ValueError, 'catalog size or identity'):
                namespace['_read_catalog_bounded'](catalog)
            self.assertFalse(output.exists())

    def test_adaptation_rejects_missing_markers_and_historical_paths(self):
        raw = SUITE.read_bytes()
        marker = b"task = Path(" + repr(self.control.OLD_TASK).encode() + b")"
        self.assertEqual(raw.count(marker), 1)
        with self.assertRaisesRegex(ValueError, 'suite marker'):
            self.control._adapt_suite(raw.replace(marker, b'', 1), Path('/tmp/task'),
                                      Path('/tmp/verified'), Path('/tmp/source'),
                                      Path('/tmp/fork'), Path('/tmp/app'))

    def test_loader_and_environment_keep_no_dev_source_and_no_source_loader(self):
        loader = LOADER.read_bytes()
        self.assertIn(b"JAC_NO_DEV_SOURCE", loader)
        self.assertIn(b"not os.environ.get('JAC_DEV_SOURCE')", loader)
        self.assertIn(b'debug_filename_scope', loader)
        calls = []

        def minimal_environment(extra):
            calls.append(extra)
            return dict(extra, PATH='/usr/bin:/bin', MLOCAL_SECRET='x', JAC_DEV_SOURCE='bad',
                        JAC_DB_URL='bad', OPENAI_API_KEY='bad', HTTP_PROXY='bad',
                        MLOCAL_OLD='bad')

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            base = Path(temporary)
            result = self.control._safe_environment(
                {'minimal_environment': minimal_environment}, base / 'directory', base / 'runtime',
                base / 'cache', base / 'scratch', base / 'official', base / 'node/bin', base / 'app')
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['JAC_NO_DEV_SOURCE'], '1')
        self.assertEqual(result['MLOCAL_APP_ROOT'], str(base / 'app'))
        self.assertTrue(result['PATH'].startswith(str(base / 'node/bin') + ':'))
        for key in ('MLOCAL_SECRET', 'MLOCAL_OLD', 'JAC_DEV_SOURCE', 'JAC_DB_URL',
                    'OPENAI_API_KEY', 'HTTP_PROXY'):
            self.assertNotIn(key, result)

    def test_context_scope_and_committed_pin_guards_reject_before_work(self):
        with self.assertRaisesRegex(ValueError, 'context fields'):
            self.control._context_paths({})
        incomplete = {key: {} for key in (
            'package', 'application', 'fork', 'official', 'accepted', 'probe_path',
            'isolation', 'isolation_directory', 'trace', 'node_client', 'prepared_ui',
            'ui_control', 'ui_runner', 'ui_directory', 'matrix_directory',
            'prepared_matrix', 'matrix_control', 'run_bounded')}
        with self.assertRaisesRegex(TypeError, 'expected str'):
            self.control._context_paths(incomplete)
        absolute = str(Path('/var/tmp').resolve())
        for key in ('package', 'application', 'fork', 'official', 'probe_path',
                    'isolation_directory', 'ui_directory', 'matrix_directory'):
            incomplete[key] = absolute
        with self.assertRaisesRegex(ValueError, 'package path'):
            self.control._context_paths(incomplete)
        with self.assertRaisesRegex(ValueError, 'committed input pin'):
            self.control._read_committed(
                {'committed_file': lambda *_args: b'tampered'}, 'runtime-proof/x.py',
                'commit', 'a' * 64)

    def test_invalid_timeout_and_preexisting_mount_reject_before_preflight(self):
        for timeout in (0, -1, 8401, True, 1.5):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, 'timeout'):
                self.control.run_suite(None, None, None, 'commit', None, timeout)
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary) / 'm-local-native-compatibility-v1-12345678'
            directory.mkdir()
            (directory / 'foreign').write_bytes(b'foreign')
            committed = []
            context = {}
            with patch.object(self.control, '_context_paths', return_value={}), \
                    patch.object(self.control, '_mount_identity', return_value=(1, 2)):
                with self.assertRaisesRegex(ValueError, 'pre-existing mount files'):
                    self.control.run_suite({'committed_file': lambda *_args: committed.append(1)},
                                           {}, directory, 'commit', context, 1)
            self.assertEqual(committed, [])

    def test_bounded_phase_rejects_missing_cleanup_guard_before_acceptance(self):
        calls = []

        def run_bounded(*args):
            calls.append(args)
            return {'controls_confirmed_before_workload': True, 'cleanup': {'cgroup_empty': False}}

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            with self.assertRaisesRegex(ValueError, 'bounded controls'):
                self.control._run_phase(
                    {'run_bounded': run_bounded}, Path(temporary), Path(temporary), 'phase',
                    ['true'], Path(temporary), {}, 10, {}, {}, False)
        self.assertEqual(len(calls), 1)

    def test_bounded_phase_rejects_invalid_limits_oom_policy_and_launcher_state(self):
        requested = {'high': 7 * 1024 ** 3, 'max': 8 * 1024 ** 3, 'swap_max': 0}
        valid = dict(requested_limits=requested, limits=dict(requested), oom_policy='stop',
                     controls_confirmed_before_workload=True,
                     cleanup={'cgroup_empty': True, 'launcher_stopped': True})
        invalid = [
            dict(valid, limits=dict(high=8 * 1024 ** 3, max=7 * 1024 ** 3, swap_max=0)),
            dict(valid, oom_policy='continue'),
            dict(valid, controls_confirmed_before_workload='true'),
            dict(valid, cleanup={'cgroup_empty': True, 'launcher_stopped': False}),
        ]
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            for state in invalid:
                with self.subTest(state=state), self.assertRaisesRegex(ValueError, 'bounded controls'):
                    self.control._run_phase(
                        {'run_bounded': lambda *args, state=state: state}, Path(temporary),
                        Path(temporary), 'phase', ['true'], Path(temporary), {}, 1, {}, {}, False)

    def test_run_suite_fails_on_source_binding_before_any_bounded_execution(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary) / 'm-local-native-compatibility-v1-12345678'
            directory.mkdir()
            context = {'isolation': {'helper_sha256': 'wrong'}, 'accepted': {}}
            values = {key: Path(temporary) / key for key in ('package', 'official', 'application', 'fork')}
            with patch.object(self.control, '_context_paths', return_value=values), \
                     patch.object(self.control, '_mount_identity', return_value=(1, 2)), \
                     patch.object(self.control, '_verify_package', return_value=({}, 'b' * 64)), \
                     patch.object(self.control, '_adapt_suite', return_value=b'pass'), \
                     patch.object(self.control, '_suite_contract_source', return_value=b'contract'), \
                     patch.object(self.control, '_read_committed', return_value=b'pass') as read_committed, \
                     patch.object(self.control, '_validate_original_inputs'), \
                     patch.object(self.control, '_copy_application'), \
                    patch.object(self.control, '_run_phase', side_effect=AssertionError('bounded execution')):
                with self.assertRaisesRegex(ValueError, 'source helper fixture binding'):
                    self.control.run_suite({}, {}, directory, 'commit', context, 1)
            self.assertEqual(read_committed.call_count, 10)
            self.assertFalse((directory / 'result.json').exists())

    def test_graph_guard_rejects_nonzero_skip_failure_and_error_counts(self):
        bad = b'451 passed\nskipped: 1\n'
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'core.log'
            path.write_bytes(bad)
            with self.assertRaisesRegex(ValueError, 'graph counters'):
                self.control._assert_graph(path, 'core')

    def _mocked_suite(self, temporary, failure_label=None, restoration_failure=False):
        control = self.control
        root = Path(temporary)
        package = root / 'package'
        application = root / 'application'
        fork = root / 'fork'
        official = root / 'official'
        for path in (package, package / 'stage', application, fork, official):
            path.mkdir(parents=True, exist_ok=True)
        (package / 'jac').write_bytes(b'binary')
        (package / 'classifier-roots.json').write_text(json.dumps([str(root / 'cache')]))
        isolation_directory = root / 'isolation'
        isolation_directory.mkdir()
        matrix_directory = root / 'matrix'
        matrix_directory.mkdir()
        ui_install = root / 'ui-install'
        ui_modules = root / 'ui-modules'
        ui_install.mkdir()
        ui_modules.mkdir()
        matrix_names = list(control.MATRIX_PHASES) + list(control.INTERFACES)
        matrix_raws = {name: b'probe-source' for name in matrix_names}
        matrix_raws['runtime-served-probe'] = (
            b"subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()\n"
            b"hashlib.sha256(subprocess.check_output(['git', 'diff', '--binary'])).hexdigest()\n"
            b"Path('/var/tmp/m-local-kali-operator-056070bz/app/services/models.jac')\n")
        matrix_rows = [dict(name=name, original_probe_sha256='original-' + name,
                            prepared_probe_sha256='prepared-' + name,
                            fault_env={}, loader_sha256=control.LOADER_SHA256)
                       for name in matrix_names]
        for name in matrix_names:
            (matrix_directory / (name + '.py')).write_bytes(matrix_raws[name])
        matrix_receipt_path = root / 'prepared-matrix.json'
        matrix_receipt_path.write_text(json.dumps(dict(status='prepared_not_executed',
                                                       phases=matrix_rows[:10], interfaces=matrix_rows[10:])))
        ui_receipt_path = root / 'prepared-ui.json'
        ui_receipt_path.write_bytes(b'ui-receipt')
        context = dict(
            package=package, application=application, fork=fork, official=official,
            accepted={'status': 'passed'}, probe_path=root / 'probe.py', isolation={},
            isolation_directory=isolation_directory, trace={'status': 'passed'},
            node_client={'clients_directory': root / 'clients', 'tool_binary_sha256': {},
                         'dependency_sha256': {}}, prepared_ui={'install_directory': ui_install,
                         'modules_directory': ui_modules, 'receipt_path': ui_receipt_path},
            ui_control={}, ui_runner={},
            ui_directory=root / 'ui-directory', matrix_directory=matrix_directory,
            prepared_matrix={'receipt_path': matrix_receipt_path,
                             'prepared_file_sha256': {name + '.py': sha(matrix_raws[name]) for name in matrix_names}},
            matrix_control={}, run_bounded=lambda *args: {},
        )
        restore_line = ("    raise RuntimeError('simulated source restoration failure')"
                        if restoration_failure else
                        "    Path(" + repr(str(root / 'restore-marker')) + ").write_text(str(len(hidden)))")
        isolation_source = (
            "from pathlib import Path\n"
            "def hide_source(path, marker):\n"
            "    return {'original': Path(path)}\n"
            "def prove_denied(hidden):\n"
            "    return {'denied': True}\n"
            "def check_sources(hidden):\n"
            "    return None\n"
            "def restore_sources(hidden):\n"
            + restore_line + "\n"
        ).encode()
        context['isolation'].update(helper_sha256=control.ISOLATION_SHA256,
                                    receipt_path=root / 'isolation-receipt.json',
                                    receipt_sha256='isolation-receipt',
                                    probe_sha256=control.ISOLATION_PROBE_SHA256)
        values = {key: Path(value) for key, value in context.items()
                  if key in ('package', 'application', 'fork', 'official', 'probe_path',
                             'isolation_directory', 'ui_directory', 'matrix_directory')}
        labels = []
        phase_timeouts = []
        matrix_checks = []
        ui_checks = []
        restored = []

        def copy_application(_source, destination):
            for name in ('main.jac', 'theme.jac', 'jac.toml', '.jac-version'):
                (destination / name).parent.mkdir(parents=True, exist_ok=True)
                (destination / name).write_bytes(b'fixture')
            (destination / 'tests/ui/browser').mkdir(parents=True)
            (destination / 'tests/tooling').mkdir(parents=True)
            (destination / 'tests/tooling/__init__.py').write_bytes(b'')
            (destination / 'tests/ui/smoke.test.mjs').write_text('test')
            (destination / 'tests/ui/browser/smoke.test.mjs').write_text('test')
            (destination / 'tests/tooling/smoke.test.mjs').write_text('test')

        def read_committed(_preflight, relative, _commit, _expected):
            if relative == control.ISOLATION_RELATIVE:
                return isolation_source
            return b'pass'

        def run_phase(*args):
            directory, label, environment = Path(args[1]), args[3], args[6]
            phase_timeouts.append((label, args[7]))
            labels.append(label)
            if failure_label == label:
                raise RuntimeError('intermediate phase failure')
            if label == 'package-input-verification':
                (directory / 'package-input-verification.json').write_text(
                    json.dumps({'status': 'passed', 'candidate_binary_sha256': 'b' * 64}))
            elif label == 'catalog-cold-relocation':
                (directory / 'catalog-cold-relocation.json').write_text(json.dumps({
                    'status': 'passed', 'candidate_binary_sha256': 'b' * 64,
                    'module_path_records_verified': 587, 'module_type_records_verified': 161,
                    'sdk_roots': [environment['JAC_CACHE_HOME']]}))
            elif label == 'catalog-mutation-controls':
                (directory / 'catalog-controls.json').write_text(json.dumps({
                    'status': 'passed', 'audit_sha256': control.CATALOG_AUDIT_SHA256,
                    'executed_controls_sha256': sha(b'adapted-controls'),
                    'cases': [dict(name=name, status='passed', exit_code=0,
                                   expected_result={}, mutation_sha256='m' * 64,
                                   diagnostic='ok') for name in (
                        'complete-physical-catalog', 'unknown-absolute-resolution-field',
                        'missing-relative-target', 'payload-containment-escape',
                        'python-payload-traversal', 'unreferenced-absolute-string')]}))
            elif label == 'onboarding':
                (directory / 'onboarding.log').write_text('ran 71 tests')
            elif label == 'analytics':
                (directory / 'analytics.log').write_text('ran 12 tests')
            elif label == 'browser':
                (directory / 'browser.log').write_text('# pass 126\n# fail 0')
            elif label == 'build':
                (directory / 'app/dist').mkdir(parents=True, exist_ok=True)
                (directory / 'app/dist/mobile-starter.jab').write_bytes(b'artifact')
            else:
                for name in matrix_names:
                    if label in ('runtime-' + name, 'interface-' + name):
                        matrix_root = directory / 'runtime-matrix'
                        (matrix_root / (name + '-loader.json')).write_text(json.dumps({
                            'status': 'passed', 'sdk_roots': [environment['JAC_CACHE_HOME']],
                            'declaring_module_files': {
                                str(index): str(Path(environment['JAC_CACHE_HOME']) / ('module-' + str(index)))
                                for index in range(16)}}))
                        if label.startswith('interface-'):
                            (matrix_root / (name + '-probe-result.json')).write_text(json.dumps({
                                'status': 'passed', 'cases': [{}] * (2 if name == 'codec' else 6)}))
                        break
            return dict(phase=label, status='passed', kernel_memory_scope={
                'controls_confirmed_before_workload': True, 'cleanup': {'cgroup_empty': True}})

        def inventory(path):
            path = Path(path)
            if path == application:
                return {'app': 'stable'}
            if path == fork:
                return {'fork': 'stable'}
            return {}

        def restore_sources(hidden):
            restored.append(len(hidden))

        context['matrix_control']['verify_prepared'] = lambda *args: matrix_checks.append(args)
        context['ui_control']['verify_prepared'] = lambda *args: ui_checks.append(args)
        context['accepted'] = {'status': 'passed'}
        matrix_path = root / 'm-local-native-compatibility-v1-12345678' / 'runtime-matrix'
        real_path_stat = Path.stat

        def synthetic_matrix_stat(path, *args, **kwargs):
            info = real_path_stat(path, *args, **kwargs)
            if Path(path).name not in (matrix_path.name, ui_install.name, ui_modules.name):
                return info
            values = list(info)
            values[0] = (values[0] & ~0o777) | 0o700
            values[4], values[5] = 65534, 65534
            return os.stat_result(values)

        with ExitStack() as stack:
            stack.enter_context(patch.object(control, '_context_paths', return_value=values))
            stack.enter_context(patch.object(control, '_mount_identity', return_value=(1, 2)))
            stack.enter_context(patch.object(control, '_read_committed', side_effect=read_committed))
            stack.enter_context(patch.object(control, '_validate_original_inputs'))
            stack.enter_context(patch.object(control, '_verify_package', return_value=(
                {'runtime_base': 'base', 'runtime_patch_sha256': control.RUNTIME_PATCH_SHA256}, 'b' * 64)))
            stack.enter_context(patch.object(control, '_adapt_suite', return_value=b'adapted'))
            stack.enter_context(patch.object(control, '_suite_contract_source', return_value=b'contract'))
            stack.enter_context(patch.object(control, '_source_digest',
                                              return_value=control.PRODUCTION_SOURCE_DIGEST_SHA256))
            stack.enter_context(patch.object(control, '_catalog_controls_source',
                                              return_value=b'adapted-controls'))
            stack.enter_context(patch.object(control, '_copy_application', side_effect=copy_application))
            stack.enter_context(patch.object(control, '_inventory', side_effect=inventory))
            real_hash_checked = control._hash_checked

            def fake_hash(path, expected=None, maximum=1024 ** 3, allow_empty=False):
                if expected is not None:
                    return expected
                path = Path(path)
                app_output = root / 'm-local-native-compatibility-v1-12345678' / 'app'
                if allow_empty and path.is_relative_to(app_output):
                    return real_hash_checked(path, maximum=maximum, allow_empty=True)
                name = Path(path).name
                if name in ('app-input-files.json', 'ui-unit-test-paths.json'):
                    return real_hash_checked(path, maximum=maximum)
                if name == 'jac':
                    return 'b' * 64
                if name == 'test.sh':
                    return control.TEST_SCRIPT_SHA256
                return 'checked'

            stack.enter_context(patch.object(control, '_hash_checked', side_effect=fake_hash))
            stack.enter_context(patch.object(control, '_trace_binding',
                                              return_value=(root / 'trace-tools', 'open', 'trace-receipt')))
            stack.enter_context(patch.object(control, '_run_phase', side_effect=run_phase))
            stack.enter_context(patch.object(control, '_assert_graph'))
            stack.enter_context(patch.object(control, '_graph_controller_source'))
            stack.enter_context(patch.object(Path, 'stat', new=synthetic_matrix_stat))
            stack.enter_context(patch.object(Path, 'symlink_to', lambda path, target: path.write_bytes(b'link')))
            isolation_globals = {}
            exec(compile(isolation_source, control.ISOLATION_RELATIVE, 'exec'), isolation_globals)
            isolation_globals['restore_sources'] = restore_sources
            context['isolation'].update(isolation_globals)
            try:
                result = control.run_suite({}, {'minimal_environment': lambda extra: dict(extra, PATH='/bin')},
                                          root / 'm-local-native-compatibility-v1-12345678',
                                          'commit', context, 8400)
            except BaseException as error:
                result = error
            marker = root / 'restore-marker'
            if marker.exists():
                restored.append(int(marker.read_text()))
        return (result, labels, phase_timeouts, matrix_checks, ui_checks, restored,
                root / 'm-local-native-compatibility-v1-12345678')

    def test_mocked_suite_runs_all_phases_interfaces_and_catalog_cases(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary) / 'm-local-native-compatibility-v1-12345678'
            directory.mkdir()
            result, labels, phase_timeouts, matrix_checks, ui_checks, restored, output = self._mocked_suite(temporary)
            self.assertIsInstance(result, dict)
            self.assertEqual((result['status'], result['phase_count'], result['interface_count'], result['catalog_count']),
                             ('passed', 24, 2, 6))
            self.assertEqual([label for label in labels
                              if label != 'catalog-mutation-controls' and
                              not label.startswith('interface-')],
                             list(self.control.PHASES))
            self.assertEqual([label for label in labels if label.startswith('interface-')],
                             ['interface-codec', 'interface-controls'])
            self.assertEqual(len(matrix_checks), 1)
            self.assertEqual(len(ui_checks), 2)
            self.assertEqual(restored, [2])
            self.assertTrue(all(0 < timeout <= 300 for label, timeout in phase_timeouts
                                if label.startswith('runtime-')))
            receipt = json.loads((output / 'result.json').read_bytes())
            self.assertEqual(receipt['phase_count'], 24)
            self.assertEqual(receipt['original_suite_sha256'], self.control.SUITE_SHA256)
            self.assertEqual(receipt['adapted_suite_reference_sha256'], sha(b'adapted'))
            self.assertEqual(receipt['executed_suite_contract_sha256'], sha(b'contract'))
            self.assertEqual(receipt['frozen_suite_contract_sha256'], sha(b'contract'))
            self.assertEqual(receipt['source_isolation_helper_sha256'], self.control.ISOLATION_SHA256)
            self.assertTrue(receipt['source_restoration_verified'])

    def test_mocked_suite_restores_sources_and_seals_failed_receipt(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary) / 'm-local-native-compatibility-v1-12345678'
            directory.mkdir()
            result, labels, _phase_timeouts, _matrix_checks, ui_checks, restored, output = self._mocked_suite(
                temporary, failure_label='runtime-commit-40P01')
            self.assertIsInstance(result, RuntimeError)
            self.assertIn('intermediate phase failure', str(result))
            self.assertIn('runtime-commit-40P01', labels)
            self.assertEqual(ui_checks, [])
            self.assertEqual(restored, [2])
            receipt = json.loads((output / 'result.json').read_bytes())
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(receipt['failure_type'], 'RuntimeError')
            self.assertTrue(receipt['source_restoration_verified'])

    def test_mocked_suite_restoration_failure_seals_failed_receipt_and_raises(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary) / 'm-local-native-compatibility-v1-12345678'
            directory.mkdir()
            result, _labels, _phase_timeouts, _matrix_checks, _ui_checks, _restored, output = self._mocked_suite(
                temporary, restoration_failure=True)
            self.assertIsInstance(result, RuntimeError)
            self.assertIn('simulated source restoration failure', str(result))
            receipt = json.loads((output / 'result.json').read_bytes())
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(receipt['failure_type'], 'RuntimeError')


class LinuxRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'posix' or os.geteuid() != 0:
            raise AssertionError('LinuxRootTests require a root Linux CI host')
        cls.control = load(CONTROL, 'native_compatibility_root_control')
        cls.source_tests = load(SOURCE_TEST, 'native_compatibility_source_tests')

    def test_real_small_mount_identity_and_owned_cleanup(self):
        owner = self.source_tests.LinuxRootTests('runTest')
        owner.setUpClass()
        fixture = owner.fixture()
        base, image, e_root, backing, original_alias, loop = fixture
        token = hashlib.sha256(os.urandom(32)).hexdigest()[:8]
        alias = Path('/var/tmp') / (self.control.PREFIX + token)
        fresh_backing = e_root / alias.name
        try:
            fresh_backing.mkdir(mode=0o700)
            os.chown(fresh_backing, 65534, 65534)
            alias.mkdir(mode=0o700)
            os.chown(alias, 65534, 65534)
            subprocess.run(['/usr/bin/mount', '--bind', str(fresh_backing), str(alias)],
                           check=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=30)
            identity = self.control._mount_identity({'E_ROOT': e_root}, alias)
            self.assertEqual(identity, (alias.stat().st_dev, alias.stat().st_ino))
            self.assertEqual((fresh_backing.stat().st_uid, fresh_backing.stat().st_gid,
                              stat.S_IMODE(fresh_backing.stat().st_mode)), (65534, 65534, 0o700))
        finally:
            if alias.is_mount():
                subprocess.run(['/usr/bin/umount', str(alias)], check=True, timeout=30,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if alias.exists() and not alias.is_symlink():
                alias.rmdir()
            if fresh_backing.exists() and not fresh_backing.is_symlink():
                fresh_backing.rmdir()
            owner.cleanup_fixture(*fixture)


if __name__ == '__main__':
    unittest.main()
