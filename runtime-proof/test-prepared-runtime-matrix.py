"""Independent tests for the source-form runtime matrix preparation."""

from pathlib import Path, PurePosixPath
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / 'prepare-fresh-runtime-matrix.py'
PREFLIGHT = ROOT / 'verify-package-preflight.py'
VERIFIER = ROOT / 'verify-source-handoff-v8.py'
MANIFEST_PATH = 'runtime-proof/inputs/public-source-manifest.json'
REPO = ROOT.parent

APPLICATION = '/mnt/c/Users/Travis/Documents/Codex/2026-10-03/can-you-pull-in-m-local/work/m-local'
FORK = '/var/tmp/m-local-build-e-drive-v2-01a1050e/source-forks-v7/identity-type-source-v3-v7'
OLD_APPLICATION = '/var/tmp/m-local-release-readiness-01a1050e'
OLD_FORK = '/var/tmp/m-local-runtime-fork-01a1050e'
OLD_GUARD = "if workspace.parent != Path('/var/tmp') or not workspace.name.startswith(('m-local-release-readiness-', 'm-local-runtime-fork-', 'm-local-runtime-proof.')):"
OLD_LOADER_ROOT = "root = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork').resolve()"

SOURCE_INPUTS = (
    'work/identity-runtime-v3/run-identity-runtime-regressions.py',
    'work/identity-runtime-v3/runtime-loader-provenance.py',
    'work/identity-runtime-v3/runtime.patch',
    'work/runtime-materialization-probe.py',
    'work/runtime-probe.py',
    'work/runtime-boundary-probe.py',
    'work/runtime-lifecycle-probe.py',
    'work/runtime-served-probe.py',
    'work/runtime-request-context-probe.py',
    'work/runtime-nested-context-probe.py',
    'work/runtime-interface-codec-probe.py',
    'work/runtime-interface-codec-controls-probe.py',
)
PHASES = (
    ('materialization', 'runtime-materialization-probe.py', {}),
    ('commit-40001', 'runtime-probe.py', {'MLOCAL_PROBE_SQLSTATE': '40001', 'MLOCAL_PROBE_ACCEPTED_COMMIT': '0'}),
    ('commit-40P01', 'runtime-probe.py', {'MLOCAL_PROBE_SQLSTATE': '40P01', 'MLOCAL_PROBE_ACCEPTED_COMMIT': '0'}),
    ('commit-55P03', 'runtime-probe.py', {'MLOCAL_PROBE_SQLSTATE': '55P03', 'MLOCAL_PROBE_ACCEPTED_COMMIT': '0'}),
    ('commit-08006', 'runtime-probe.py', {'MLOCAL_PROBE_SQLSTATE': '08006', 'MLOCAL_PROBE_ACCEPTED_COMMIT': '1'}),
    ('runtime-boundary-probe', 'runtime-boundary-probe.py', {}),
    ('runtime-lifecycle-probe', 'runtime-lifecycle-probe.py', {}),
    ('runtime-served-probe', 'runtime-served-probe.py', {}),
    ('runtime-request-context-probe', 'runtime-request-context-probe.py', {}),
    ('runtime-nested-context-probe', 'runtime-nested-context-probe.py', {}),
)
INTERFACES = (
    ('codec', 'runtime-interface-codec-probe.py', {}),
    ('controls', 'runtime-interface-codec-controls-probe.py', {}),
)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')


def source_text(raw):
    with io.TextIOWrapper(io.BytesIO(raw), encoding='utf-8', newline=None) as stream:
        return stream.read()


class PureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control = load(CONTROL, 'prepared_runtime_matrix_control')
        cls.preflight = load(PREFLIGHT, 'prepared_runtime_matrix_preflight')
        cls.verifier = load(VERIFIER, 'prepared_runtime_matrix_verifier')
        cls.commit = cls.preflight.git(REPO, ['rev-parse', 'HEAD']).decode('ascii').strip()
        cls.manifest_raw = cls.preflight.git(REPO, ['show', 'HEAD:' + MANIFEST_PATH])

    def committed(self, relative):
        return self.preflight.git(REPO, ['show', 'HEAD:runtime-proof/inputs/' + relative])

    def source_bytes(self, relative):
        return self.preflight.git(REPO, ['show', 'HEAD:runtime-proof/inputs/' + relative])

    def build_matrix(self):
        h = self.control.PATCH_SHA256
        child = {
            'actual_smtp': False,
            'checks': None,
            'cold_compile_receipt_sha256': None,
            'interface_count': 2,
            'jacpython_sha256': None,
            'official_binary_sha256': self.control.OFFICIAL_BINARY_SHA256,
            'phase_count': 10,
            'runtime_patch_sha256': h,
            'source_override_explicit': None,
            'status': 'passed',
        }
        return {
            'child': child,
            'child_result_sha256': 'd' * 64,
            'cold_compile_receipt_sha256': None,
            'elapsed_seconds': 0.25,
            'parent_policy': self.verifier.PARENT_POLICY,
            'result_sha256': 'd' * 64,
            'source_gate_sha256': 'b' * 64,
            'stage': 'run-source-matrix-v9',
            'status': 'passed',
            'wrapper_sha256': 'c' * 64,
        }

    def build_contract(self, matrix_hash):
        producer = {
            'commit_sha': self.commit,
            'run_id': '12345',
            'source_runner_sha256': '1' * 64,
            'adapter_manifest_sha256': self.verifier.ADAPTER_MANIFEST_SHA,
            'application_revision': self.verifier.APP_REVISION,
            'application_digest': self.verifier.APP_SHA,
            'jac_base': self.verifier.JAC_BASE,
            'official_binary_sha256': self.verifier.JAC_SHA,
            'jacpython_sha256': self.verifier.JACPYTHON_SHA,
            'helper_sha256': '2' * 64,
            'entrypoint_policy': 'source_only_via_pinned_adapters',
            'evidence_scope': 'sanitized_commitments_only',
        }
        return {
            'status': 'prepared_not_uploaded',
            'member_count': 36,
            'total_bytes': 1,
            'source_manifest_sha256': self.control.MANIFEST_SHA256,
            'runtime_patch_sha256': self.control.PATCH_SHA256,
            'source_bootstrap_receipt_sha256': 'e' * 64,
            'source_matrix_receipt_sha256': matrix_hash,
            'members': [],
            'cold_compile_provenance': None,
            'jac_license_notice': None,
            'forbidden': [],
            'producer': producer,
        }

    def make_fixture(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT)
        root = Path(temporary.name).resolve()
        bundle = root / 'bundle'
        files = bundle / 'files'
        files.mkdir(parents=True)
        directory = root / 'prepared'
        directory.mkdir()
        if os.name == 'posix' and os.geteuid() == 0:
            os.chown(directory, 65534, 65534)
            os.chmod(directory, 0o700)
        originals = {relative: self.source_bytes(relative) for relative in SOURCE_INPUTS}
        for relative, raw in originals.items():
            path = files / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            os.chmod(path, 0o400)
        matrix = self.build_matrix()
        matrix_raw = json_bytes(matrix) + b'\n'
        (bundle / 'source-matrix-receipt.json').write_bytes(matrix_raw)
        os.chmod(bundle / 'source-matrix-receipt.json', 0o400)
        matrix_hash = sha(matrix_raw)
        contract = self.build_contract(matrix_hash)
        contract_raw = json_bytes(contract) + b'\n'
        (bundle / 'contract.json').write_bytes(contract_raw)
        os.chmod(bundle / 'contract.json', 0o400)
        contract_hash = sha(contract_raw)
        source_summary = {
            'status': 'passed',
            'scope': 'sanitized commitment bundle verification',
            'member_count': 36,
            'total_bytes': 1,
            'contract_sha256': contract_hash,
            'commit_sha': self.commit,
            'run_id': '12345',
        }
        source_gate = {
            'status': 'passed',
            'scope': 'source and package input commitment verification only',
            'source': source_summary,
        }
        origin = {
            'status': 'passed',
            'scope': 'successful source-proof origin commitment',
            'run_id': 12345,
            'job_id': 7,
            'artifact_id': 8,
            'artifact_digest': 'sha256:' + 'f' * 64,
            'artifact_size': 1,
            'contract_sha256': contract_hash,
        }

        def read_regular(path):
            return self.preflight.read_regular(Path(path))

        return {
            'temporary': temporary,
            'root': root,
            'bundle': bundle,
            'directory': directory,
            'preflight': {'read_regular': read_regular},
            'source_gate': source_gate,
            'origin': origin,
            'manifest_raw': self.manifest_raw,
            'matrix': matrix,
            'matrix_raw': matrix_raw,
            'contract': contract,
            'contract_raw': contract_raw,
            'contract_hash': contract_hash,
            'originals': originals,
        }

    def invoke(self, fixture, **kwargs):
        values = {
            'preflight': fixture['preflight'],
            'bundle': fixture['bundle'],
            'directory': fixture['directory'],
            'source_gate': fixture['source_gate'],
            'origin': fixture['origin'],
            'manifest_raw': fixture['manifest_raw'],
            'application': PurePosixPath(APPLICATION),
            'fork': PurePosixPath(FORK),
        }
        values.update(kwargs)
        return self.control.prepare_matrix(**values)

    def independent_generated(self, fixture):
        generated = {}
        loader = source_text(fixture['originals'][SOURCE_INPUTS[1]])
        self.assertEqual(loader.count(OLD_LOADER_ROOT), 1)
        loader = loader.replace(OLD_LOADER_ROOT, 'root = Path(' + repr(FORK) + ').resolve()')
        generated['source-loader.py'] = loader.encode('utf-8')
        by_name = dict(fixture['originals'])
        for name, probe, _fault in PHASES + INTERFACES:
            relative = 'work/' + probe
            text = source_text(by_name[relative])
            expected_app = 1 if probe == 'runtime-served-probe.py' else 0
            expected_fork = 0 if probe == 'runtime-probe.py' else 1
            self.assertEqual(text.count(OLD_APPLICATION), expected_app)
            self.assertEqual(text.count(OLD_FORK), expected_fork)
            self.assertEqual(text.count(OLD_GUARD), 1 if probe == 'runtime-probe.py' else 0)
            text = text.replace(OLD_APPLICATION, APPLICATION).replace(OLD_FORK, FORK)
            if probe == 'runtime-probe.py':
                text = text.replace(OLD_GUARD, 'if workspace != Path(' + repr(FORK) + '):')
            self.assertNotIn(OLD_APPLICATION, text)
            self.assertNotIn(OLD_FORK, text)
            self.assertNotIn(OLD_GUARD, text)
            generated[name + '.py'] = text.encode('utf-8')
        return generated

    def rewire_matrix(self, fixture, matrix):
        matrix_raw = json_bytes(matrix) + b'\n'
        os.chmod(fixture['bundle'] / 'source-matrix-receipt.json', 0o600)
        (fixture['bundle'] / 'source-matrix-receipt.json').write_bytes(matrix_raw)
        os.chmod(fixture['bundle'] / 'source-matrix-receipt.json', 0o400)
        contract = copy.deepcopy(fixture['contract'])
        contract['source_matrix_receipt_sha256'] = sha(matrix_raw)
        contract_raw = json_bytes(contract) + b'\n'
        os.chmod(fixture['bundle'] / 'contract.json', 0o600)
        (fixture['bundle'] / 'contract.json').write_bytes(contract_raw)
        os.chmod(fixture['bundle'] / 'contract.json', 0o400)
        fixture['contract'] = contract
        fixture['contract_raw'] = contract_raw
        fixture['contract_hash'] = sha(contract_raw)
        fixture['source_gate']['source']['contract_sha256'] = fixture['contract_hash']
        fixture['origin']['contract_sha256'] = fixture['contract_hash']

    def assert_rejected_without_outputs(self, fixture, **kwargs):
        with self.assertRaises((RuntimeError, ValueError)):
            self.invoke(fixture, **kwargs)
        self.assertEqual(list(fixture['directory'].iterdir()), [])

    def test_valid_matrix_matches_independent_transforms_and_is_unexecuted(self):
        fixture = self.make_fixture()
        try:
            result = self.invoke(fixture)
            expected = self.independent_generated(fixture)
            expected_hashes = {name: sha(raw) for name, raw in sorted(expected.items())}
            expected_inventory = sha(json_bytes(expected_hashes))
            self.assertEqual(result['status'], 'prepared_not_executed')
            self.assertIs(result['executed'], False)
            self.assertEqual(result['prepared_file_sha256'], expected_hashes)
            self.assertEqual(result['prepared_inventory_sha256'], expected_inventory)
            self.assertEqual(result['receipt_sha256'], sha(result['receipt_path'].read_bytes()))
            self.assertEqual({path.name for path in fixture['directory'].iterdir()},
                             set(expected_hashes) | {'prepared-result.json'})
            for name, raw in expected.items():
                self.assertEqual((fixture['directory'] / name).read_bytes(), raw)
            receipt = json.loads(result['receipt_path'].read_text(encoding='utf-8'))
            self.assertEqual(receipt['status'], 'prepared_not_executed')
            self.assertIs(receipt['executed'], False)
            self.assertEqual(receipt['application'], APPLICATION)
            self.assertEqual(receipt['fork'], FORK)
            self.assertEqual([row['name'] for row in receipt['phases']], [row[0] for row in PHASES])
            self.assertEqual([row['name'] for row in receipt['interfaces']], [row[0] for row in INTERFACES])
            self.assertEqual(self.control.verify_prepared(fixture['preflight'], fixture['directory'], result),
                             expected_inventory)
        finally:
            fixture['temporary'].cleanup()

    def test_manifest_controller_and_path_bindings_fail_closed_before_writes(self):
        fixture = self.make_fixture()
        try:
            bad_manifest = bytearray(fixture['manifest_raw'])
            bad_manifest[-2] ^= 1
            self.assert_rejected_without_outputs(fixture, manifest_raw=bytes(bad_manifest))
        finally:
            fixture['temporary'].cleanup()
        fixture = self.make_fixture()
        try:
            controller = fixture['bundle'] / 'files' / SOURCE_INPUTS[0]
            os.chmod(controller, 0o600)
            controller.write_bytes(controller.read_bytes().replace(b"run('materialization'", b"run('tampered'", 1))
            self.assert_rejected_without_outputs(fixture)
        finally:
            fixture['temporary'].cleanup()
        for field, value in (('application', '/var/tmp/wrong-binding'),
                             ('fork', '/var/tmp/wrong-fork')):
            fixture = self.make_fixture()
            try:
                kwargs = {field: value}
                self.assert_rejected_without_outputs(fixture, **kwargs)
            finally:
                fixture['temporary'].cleanup()

    def test_contract_origin_and_source_summary_bindings_fail_closed(self):
        cases = ('contract_sha256', 'run_id', 'commit_sha')
        for case in cases:
            fixture = self.make_fixture()
            try:
                if case == 'contract_sha256':
                    fixture['source_gate']['source'][case] = '0' * 64
                elif case == 'run_id':
                    fixture['source_gate']['source'][case] = '54321'
                else:
                    fixture['source_gate']['source'][case] = '1' * 40
                self.assert_rejected_without_outputs(fixture)
            finally:
                fixture['temporary'].cleanup()
        fixture = self.make_fixture()
        try:
            fixture['origin']['contract_sha256'] = '0' * 64
            self.assert_rejected_without_outputs(fixture)
        finally:
            fixture['temporary'].cleanup()
        fixture = self.make_fixture()
        try:
            fixture['source_gate']['source']['source_matrix_receipt_sha256'] = 'd' * 64
            self.assert_rejected_without_outputs(fixture)
        finally:
            fixture['temporary'].cleanup()
        fixture = self.make_fixture()
        try:
            fixture['contract']['producer']['shim_sha256'] = 'a' * 64
            contract_raw = json_bytes(fixture['contract']) + b'\n'
            os.chmod(fixture['bundle'] / 'contract.json', 0o600)
            (fixture['bundle'] / 'contract.json').write_bytes(contract_raw)
            os.chmod(fixture['bundle'] / 'contract.json', 0o400)
            fixture['source_gate']['source']['contract_sha256'] = sha(contract_raw)
            fixture['origin']['contract_sha256'] = sha(contract_raw)
            self.assert_rejected_without_outputs(fixture)
        finally:
            fixture['temporary'].cleanup()

    def test_occupied_output_and_nonregular_source_members_fail_before_writes(self):
        fixture = self.make_fixture()
        try:
            (fixture['directory'] / 'preexisting').write_bytes(b'x')
            with self.assertRaises((RuntimeError, ValueError)):
                self.invoke(fixture)
            self.assertEqual([path.name for path in fixture['directory'].iterdir()], ['preexisting'])
        finally:
            fixture['temporary'].cleanup()
        fixture = self.make_fixture()
        try:
            controller = fixture['bundle'] / 'files' / SOURCE_INPUTS[0]
            os.chmod(controller, 0o600)
            controller.unlink()
            controller.mkdir()
            self.assert_rejected_without_outputs(fixture)
        finally:
            fixture['temporary'].cleanup()

    def test_matrix_fault_schema_and_counts_do_not_get_normalized(self):
        mutations = (
            ('smtp', lambda matrix: matrix['child'].__setitem__('actual_smtp', None)),
            ('phase-count', lambda matrix: matrix['child'].__setitem__('phase_count', 9)),
            ('interface-count', lambda matrix: matrix['child'].__setitem__('interface_count', 3)),
            ('policy', lambda matrix: matrix.__setitem__('parent_policy', 'wrong')),
            ('status', lambda matrix: matrix.__setitem__('status', 'prepared_not_executed')),
            ('duplicate-shape', lambda matrix: matrix.__setitem__('extra', True)),
        )
        for name, mutate in mutations:
            fixture = self.make_fixture()
            try:
                matrix = copy.deepcopy(fixture['matrix'])
                mutate(matrix)
                self.rewire_matrix(fixture, matrix)
                with self.subTest(case=name):
                    self.assert_rejected_without_outputs(fixture)
            finally:
                fixture['temporary'].cleanup()

    def test_prepared_verification_rejects_tampered_missing_and_extra_members(self):
        fixture = self.make_fixture()
        try:
            result = self.invoke(fixture)
            generated = fixture['directory'] / 'codec.py'
            original = generated.read_bytes()
            os.chmod(generated, 0o600)
            generated.write_bytes(original + b'\n')
            with self.assertRaises((RuntimeError, ValueError)):
                self.control.verify_prepared(fixture['preflight'], fixture['directory'], result)
            generated.write_bytes(original)
            os.chmod(generated, 0o400)
            os.chmod(generated, 0o600)
            generated.write_bytes(b'x' * (1024 * 1024 + 1))
            os.chmod(generated, 0o400)
            with self.assertRaises((RuntimeError, ValueError)):
                self.control.verify_prepared(fixture['preflight'], fixture['directory'], result)
            os.chmod(generated, 0o600)
            generated.write_bytes(original)
            os.chmod(generated, 0o400)

            receipt_path = fixture['directory'] / 'prepared-result.json'
            original_receipt = receipt_path.read_bytes()
            for field, value in (('executed', True), ('status', 'executed')):
                mutated = json.loads(original_receipt)
                mutated['phases'][0][field] = value
                mutated_raw = json.dumps(mutated, sort_keys=True, indent=2, separators=(',', ': ')).encode('utf-8') + b'\n'
                os.chmod(receipt_path, 0o600)
                receipt_path.write_bytes(mutated_raw)
                os.chmod(receipt_path, 0o400)
                caller_result = dict(result, receipt_sha256=sha(mutated_raw))
                with self.subTest(receipt_field=field), self.assertRaises((RuntimeError, ValueError)):
                    self.control.verify_prepared(fixture['preflight'], fixture['directory'], caller_result)
                os.chmod(receipt_path, 0o600)
                receipt_path.write_bytes(original_receipt)
                os.chmod(receipt_path, 0o400)

            (fixture['directory'] / 'unexpected.py').write_bytes(b'x')
            with self.assertRaises((RuntimeError, ValueError)):
                self.control.verify_prepared(fixture['preflight'], fixture['directory'], result)
            (fixture['directory'] / 'unexpected.py').unlink()
            os.chmod(fixture['directory'] / 'codec.py', 0o600)
            (fixture['directory'] / 'codec.py').unlink()
            with self.assertRaises((RuntimeError, ValueError)):
                self.control.verify_prepared(fixture['preflight'], fixture['directory'], result)
        finally:
            fixture['temporary'].cleanup()


class LinuxRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'posix' or os.geteuid() != 0:
            raise RuntimeError('LinuxRootTests requires a root Linux runner')
        PureTests.setUpClass()
        cls.pure = PureTests()

    def test_sealed_output_is_root_private_and_directory_is_nobody_owned(self):
        fixture = self.pure.make_fixture()
        try:
            os.chown(fixture['directory'], 65534, 65534)
            os.chmod(fixture['directory'], 0o700)
            result = self.pure.invoke(fixture)
            directory_info = fixture['directory'].stat()
            self.assertEqual((directory_info.st_uid, directory_info.st_gid, directory_info.st_mode & 0o777),
                             (65534, 65534, 0o700))
            for path in fixture['directory'].iterdir():
                info = path.lstat()
                self.assertEqual((info.st_uid, info.st_gid, info.st_mode & 0o777, info.st_nlink),
                                 (0, 0, 0o400, 1))
            self.assertEqual(self.pure.control.verify_prepared(fixture['preflight'], fixture['directory'], result),
                             result['prepared_inventory_sha256'])
        finally:
            fixture['temporary'].cleanup()


if __name__ == '__main__':
    unittest.main()
