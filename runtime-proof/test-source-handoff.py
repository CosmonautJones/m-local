#!/usr/bin/env python3
"""Focused filesystem/schema tests for verify-source-handoff.py."""

from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('verify_source_handoff', ROOT / 'verify-source-handoff.py')
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class SourceHandoffTests(unittest.TestCase):
    def setUp(self):
        self.checkout = ROOT.parent
        self.manifest = VERIFY._read_json(self.checkout / 'runtime-proof/inputs/public-source-manifest.json')
        self.adapters = VERIFY._read_json(self.checkout / 'runtime-proof/inputs/v7-adapter-manifest.json')
        self.commit = subprocess.check_output(['git', '-C', str(self.checkout), 'rev-parse', 'HEAD'], text=True).strip()
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.bundle = Path(self.temp.name) / 'bundle'
        self._make_bundle()

    def tearDown(self):
        self.temp.cleanup()

    def _make_bundle(self):
        if self.bundle.exists():
            shutil.rmtree(self.bundle)
        files = self.bundle / 'files'
        for relative in self.manifest['files']:
            destination = files / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.checkout / 'runtime-proof/inputs' / relative, destination)
        shutil.copyfile(self.checkout / 'runtime-proof/JAC-LICENSE.txt', self.bundle / 'JAC-LICENSE.txt')
        cold_hash = 'c' * 64
        bootstrap_result = 'a' * 64
        matrix_result = 'b' * 64
        cleanup = {'cgroup_empty': True, 'unit_state': {'ActiveState': 'inactive', 'SubState': 'dead', 'Result': 'success'},
                   'cgroup_kill_fallback_used': False, 'launcher_stopped': True}
        cold = {
            'status': 'passed', 'phase_count': 2,
            'phase_patches': [VERIFY.PATCH_BEFORE, VERIFY.PATCH_AFTER],
            'phase_statuses': ['expected_failure', 'passed'],
            'expected_e1030': {'status': 'expected_failure', 'exit_code': -1,
                               'diagnostic': 'E1030 IdentityStorage/store expected mismatch',
                               'compiler_log_sha256': 'd' * 64, 'patch_sha256': VERIFY.PATCH_BEFORE},
            'corrected_compile': {'status': 'passed', 'exit_code': 0,
                                  'compiler_log_sha256': 'e' * 64, 'patch_sha256': VERIFY.PATCH_AFTER},
            'leaf_controls': [{'controls_confirmed_before_workload': True, 'cleanup': cleanup},
                              {'controls_confirmed_before_workload': True, 'cleanup': dict(cleanup)}],
        }
        bootstrap = self._receipt('run-source-bootstrap-v7', bootstrap_result, cold_hash,
                                  checks=53, phase_count=None, interface_count=None,
                                  jacpython=VERIFY.JACPYTHON_SHA, source_override=True,
                                  cold_compile=cold_hash)
        matrix = self._receipt('run-source-matrix-v7', matrix_result, None,
                               checks=None, phase_count=10, interface_count=2,
                               jacpython=None, source_override=None, cold_compile=None,
                               source_gate=bootstrap_result)
        (self.bundle / 'source-bootstrap-receipt.json').write_bytes(json.dumps(bootstrap, sort_keys=True).encode() + b'\n')
        (self.bundle / 'source-matrix-receipt.json').write_bytes(json.dumps(matrix, sort_keys=True).encode() + b'\n')
        self._write_contract(cold)
        self._set_fixture_modes()

    def _set_fixture_modes(self):
        if os.name != 'posix':
            return
        self.bundle.chmod(0o700)
        for directory in self.bundle.rglob('*'):
            if directory.is_dir():
                directory.chmod(0o755)
            else:
                directory.chmod(0o644)
        (self.bundle / 'contract.json').chmod(0o600)
        (self.bundle / 'source-bootstrap-receipt.json').chmod(0o600)
        (self.bundle / 'source-matrix-receipt.json').chmod(0o600)

    def _receipt(self, stage, result, cold_hash, *, checks, phase_count, interface_count,
                 jacpython, source_override, cold_compile, source_gate=None):
        adapter_path = {'run-source-bootstrap-v7': VERIFY.ADAPTER_PATHS[1],
                        'run-source-matrix-v7': VERIFY.ADAPTER_PATHS[2]}[stage]
        return {'status': 'passed', 'stage': stage,
                'wrapper_sha256': self.adapters['files'][adapter_path]['sha256'],
                'result_sha256': result, 'child_result_sha256': result,
                'elapsed_seconds': 0.25,
                'parent_policy': VERIFY.PARENT_POLICY,
                'source_gate_sha256': source_gate,
                'cold_compile_receipt_sha256': cold_hash,
                'child': {'status': 'passed', 'checks': checks,
                          'phase_count': phase_count, 'interface_count': interface_count,
                          'runtime_patch_sha256': VERIFY.PATCH_AFTER,
                          'official_binary_sha256': VERIFY.JAC_SHA,
                          'jacpython_sha256': jacpython,
                          'source_override_explicit': source_override,
                          'cold_compile_receipt_sha256': cold_compile,
                          'actual_smtp': False}}

    def _write_contract(self, cold):
        entries = []
        for relative, metadata in self.manifest['files'].items():
            path = self.bundle / 'files' / relative
            entries.append({'path': 'files/' + relative, 'bytes': path.stat().st_size, 'sha256': sha(path.read_bytes())})
        for name in VERIFY.RECEIPT_NAMES:
            path = self.bundle / name
            entries.append({'path': name, 'bytes': path.stat().st_size, 'sha256': sha(path.read_bytes())})
        contract = {
            'status': 'prepared_not_uploaded', 'member_count': 36,
            'total_bytes': sum(entry['bytes'] for entry in entries),
            'source_manifest_sha256': VERIFY.SOURCE_MANIFEST_SHA,
            'runtime_patch_sha256': VERIFY.PATCH_AFTER,
            'source_bootstrap_receipt_sha256': entries[-2]['sha256'],
            'source_matrix_receipt_sha256': entries[-1]['sha256'],
            'members': entries,
            'cold_compile_provenance': cold,
            'jac_license_notice': {
                'path': 'JAC-LICENSE.txt', 'bytes': VERIFY.LICENSE_BYTES, 'sha256': VERIFY.LICENSE_SHA,
                'origin': VERIFY.LICENSE_ORIGIN,
                'text': (self.checkout / 'runtime-proof/JAC-LICENSE.txt').read_text(encoding='utf-8')},
            'forbidden': VERIFY.FORBIDDEN,
            'producer': {
                'commit_sha': self.commit, 'run_id': '1',
                'source_runner_sha256': sha((self.checkout / 'runtime-proof/run-fresh-source.py').read_bytes()),
                'adapter_manifest_sha256': VERIFY.ADAPTER_MANIFEST_SHA,
                'application_revision': VERIFY.APP_REVISION, 'application_digest': VERIFY.APP_SHA,
                'jac_base': VERIFY.JAC_BASE, 'official_binary_sha256': VERIFY.JAC_SHA,
                'jacpython_sha256': VERIFY.JACPYTHON_SHA,
                'helper_sha256': sha((self.checkout / 'runtime-proof/kali-build-resources-v2.py').read_bytes()),
                'entrypoint_policy': 'source_only_via_pinned_adapters',
                'evidence_scope': 'sanitized_commitments_only'},
        }
        self._write_raw_contract(contract)

    def _write_raw_contract(self, contract_bytes_or_value):
        if isinstance(contract_bytes_or_value, bytes):
            (self.bundle / 'contract.json').write_bytes(contract_bytes_or_value)
        else:
            (self.bundle / 'contract.json').write_bytes(json.dumps(contract_bytes_or_value, sort_keys=True, indent=2).encode() + b'\n')

    def _contract(self):
        return json.loads((self.bundle / 'contract.json').read_text())

    def _refresh_contract(self, contract=None):
        contract = self._contract() if contract is None else contract
        for entry in contract['members']:
            path = self.bundle / entry['path']
            entry['bytes'] = path.stat().st_size
            entry['sha256'] = sha(path.read_bytes())
        contract['total_bytes'] = sum(entry['bytes'] for entry in contract['members'])
        contract['source_bootstrap_receipt_sha256'] = sha((self.bundle / VERIFY.RECEIPT_NAMES[0]).read_bytes())
        contract['source_matrix_receipt_sha256'] = sha((self.bundle / VERIFY.RECEIPT_NAMES[1]).read_bytes())
        self._write_raw_contract(contract)

    def _verify(self, expected_run='1', expected_commit=None, expected_hash=None):
        return VERIFY.verify_bundle(self.bundle, self.checkout,
                                    expected_commit=expected_commit or self.commit,
                                    expected_run_id=expected_run,
                                    expected_contract_sha256=expected_hash or sha((self.bundle / 'contract.json').read_bytes()))

    def _mutate_receipt(self, name, change):
        path = self.bundle / name
        value = json.loads(path.read_text())
        change(value)
        path.write_bytes(json.dumps(value, sort_keys=True).encode() + b'\n')
        self._refresh_contract()

    def test_valid_synthetic_commitment_bundle(self):
        result = self._verify()
        self.assertEqual(result['scope'], 'sanitized commitment bundle verification')
        self.assertEqual(result['member_count'], 36)

    def test_tamper_missing_extra_and_traversal_are_rejected(self):
        (self.bundle / 'files' / 'source/jac/jaclang/runtime/context.jac').unlink()
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()
        self._make_bundle()
        (self.bundle / 'unexpected.txt').write_bytes(b'fixture')
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()
        self._make_bundle()
        contract = self._contract()
        contract['members'][0]['path'] = 'files/../JAC-LICENSE.txt'
        self._write_raw_contract(contract)
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()

    def test_source_hash_and_receipt_member_hash_mismatch_are_rejected(self):
        source = self.bundle / 'files/source/jac/jaclang/runtime/context.jac'
        source.write_bytes(source.read_bytes() + b'fixture tamper')
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()
        self._make_bundle()
        receipt = self.bundle / 'source-bootstrap-receipt.json'
        receipt.write_bytes(receipt.read_bytes() + b'fixture tamper')
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()

    def test_duplicate_json_unknown_nested_and_type_changes_are_rejected(self):
        contract = self._contract()
        raw = json.dumps(contract, sort_keys=True, indent=2).encode() + b'\n'
        duplicate = raw.rstrip()[:-1] + b',\n  "status": "prepared_not_uploaded"\n}\n'
        self._write_raw_contract(duplicate)
        with self.assertRaises(VERIFY.VerificationError):
            self._verify(expected_hash=sha(duplicate))
        self._make_bundle()
        self._mutate_receipt('source-bootstrap-receipt.json', lambda value: value['child'].update(extra='fixture'))
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()
        self._make_bundle()
        contract = self._contract()
        contract['member_count'] = True
        self._write_raw_contract(contract)
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()

    def test_nonfinite_elapsed_wrong_role_and_matrix_binding_are_rejected(self):
        self._mutate_receipt('source-bootstrap-receipt.json', lambda value: value.update(elapsed_seconds=float('nan')))
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()
        self._make_bundle()
        self._mutate_receipt('source-bootstrap-receipt.json', lambda value: value['child'].update(source_override_explicit=False))
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()
        self._make_bundle()
        self._mutate_receipt('source-matrix-receipt.json', lambda value: value.update(source_gate_sha256='f' * 64))
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()

    def test_wrong_external_producer_binding_and_missing_license_are_rejected(self):
        with self.assertRaises(VERIFY.VerificationError):
            self._verify(expected_run='2')
        self._make_bundle()
        contract = self._contract()
        contract['producer']['application_digest'] = 'f' * 64
        self._write_raw_contract(contract)
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()
        self._make_bundle()
        (self.bundle / 'JAC-LICENSE.txt').unlink()
        with self.assertRaises(VERIFY.VerificationError):
            self._verify()

    def _simulated_lstat(self, target, transform):
        original = VERIFY.os.lstat

        def fake(path):
            info = original(path)
            if Path(path) == target:
                return transform(info)
            mode = stat.S_IFDIR | 0o755 if stat.S_ISDIR(info.st_mode) else stat.S_IFREG | 0o644
            values = list(info)
            values[0] = mode
            values[3] = 1
            return os.stat_result(values)

        return fake

    def _metadata_rejected(self, relative, transform):
        target = self.bundle / relative
        if os.name == 'posix':
            transform(target)
            with self.assertRaises(VERIFY.VerificationError):
                self._verify()
            return
        fake = self._simulated_lstat(target, transform)
        with patch.object(VERIFY, 'POSIX_MODES', True), patch.object(VERIFY.os, 'lstat', side_effect=fake):
            with self.assertRaises(VERIFY.VerificationError):
                self._verify()

    def test_mode_boundaries_and_links_are_rejected_without_platform_skip(self):
        source = self.bundle / 'files/source/jac/jaclang/runtime/context.jac'
        if os.name == 'posix':
            source.unlink()
            source.symlink_to(self.checkout / 'runtime-proof/inputs/source/jac/jaclang/runtime/context.jac')
            with self.assertRaises(VERIFY.VerificationError):
                self._verify()
        else:
            self._metadata_rejected(source.relative_to(self.bundle), lambda info: os.stat_result(
                [stat.S_IFLNK | 0o777, *list(info)[1:]]))
        self._make_bundle()
        source = self.bundle / 'files/source/jac/jaclang/runtime/context.jac'
        if os.name == 'posix':
            source.unlink()
            os.link(self.checkout / 'runtime-proof/inputs/source/jac/jaclang/runtime/context.jac', source)
            with self.assertRaises(VERIFY.VerificationError):
                self._verify()
        else:
            self._metadata_rejected(source.relative_to(self.bundle), lambda info: os.stat_result(
                [stat.S_IFREG | 0o644, *list(info)[1:3], 2, *list(info)[4:]]))
        self._make_bundle()
        receipt = self.bundle / 'source-bootstrap-receipt.json'
        if os.name == 'posix':
            receipt.chmod(0o755)
            with self.assertRaises(VERIFY.VerificationError):
                self._verify()
        else:
            self._metadata_rejected(receipt.relative_to(self.bundle), lambda info: os.stat_result(
                [stat.S_IFREG | 0o755, *list(info)[1:]]))
        self._make_bundle()
        receipt = self.bundle / 'source-bootstrap-receipt.json'
        if os.name == 'posix':
            receipt.chmod(0o666)
            with self.assertRaises(VERIFY.VerificationError):
                self._verify()
        else:
            self._metadata_rejected(receipt.relative_to(self.bundle), lambda info: os.stat_result(
                [stat.S_IFREG | 0o666, *list(info)[1:]]))
        self._make_bundle()
        directory = self.bundle / 'files'
        if os.name == 'posix':
            directory.chmod(0o777)
            with self.assertRaises(VERIFY.VerificationError):
                self._verify()
        else:
            self._metadata_rejected(directory.relative_to(self.bundle), lambda info: os.stat_result(
                [stat.S_IFDIR | 0o777, *list(info)[1:]]))

    def test_mode_boundaries_accept_600_644_files_and_700_755_directories(self):
        if os.name == 'posix':
            self.bundle.chmod(0o700)
            for directory in self.bundle.rglob('*'):
                if directory.is_dir():
                    directory.chmod(0o755)
                else:
                    directory.chmod(0o644)
            (self.bundle / 'contract.json').chmod(0o600)
            (self.bundle / 'source-bootstrap-receipt.json').chmod(0o600)
            (self.bundle / 'source-matrix-receipt.json').chmod(0o600)
            self._verify()
            return
        original = VERIFY.os.lstat

        def safe(path):
            info = original(path)
            mode = stat.S_IFDIR | 0o755 if stat.S_ISDIR(info.st_mode) else stat.S_IFREG | 0o644
            values = list(info)
            values[0] = mode
            values[3] = 1
            return os.stat_result(values)

        with patch.object(VERIFY, 'POSIX_MODES', True), patch.object(VERIFY.os, 'lstat', side_effect=safe):
            self._verify()

    def test_numeric_aliases_and_boolean_aliases_are_rejected(self):
        cases = [
            ('contract member_count float', 'contract', lambda value: value.update(member_count=36.0)),
            ('license bytes float', 'contract', lambda value: value['jac_license_notice'].update(bytes=float(VERIFY.LICENSE_BYTES))),
            ('cold phase_count float', 'contract', lambda value: value['cold_compile_provenance'].update(phase_count=2.0)),
            ('corrected exit float', 'contract', lambda value: value['cold_compile_provenance']['corrected_compile'].update(exit_code=0.0)),
        ]
        for label, kind, mutate in cases:
            with self.subTest(label=label):
                self._make_bundle()
                contract = self._contract()
                mutate(contract)
                self._write_raw_contract(contract)
                with self.assertRaises(VERIFY.VerificationError):
                    self._verify()
        receipt_cases = [
            ('bootstrap checks float', 'source-bootstrap-receipt.json', lambda value: value['child'].update(checks=53.0)),
            ('matrix phase_count float', 'source-matrix-receipt.json', lambda value: value['child'].update(phase_count=10.0)),
            ('matrix interface_count float', 'source-matrix-receipt.json', lambda value: value['child'].update(interface_count=2.0)),
            ('bootstrap source override integer', 'source-bootstrap-receipt.json', lambda value: value['child'].update(source_override_explicit=1)),
            ('bootstrap smtp integer', 'source-bootstrap-receipt.json', lambda value: value['child'].update(actual_smtp=0)),
            ('matrix smtp integer', 'source-matrix-receipt.json', lambda value: value['child'].update(actual_smtp=0)),
        ]
        for label, name, mutate in receipt_cases:
            with self.subTest(label=label):
                self._make_bundle()
                self._mutate_receipt(name, mutate)
                with self.assertRaises(VERIFY.VerificationError):
                    self._verify()

    def test_root_directory_mode_boundaries(self):
        if os.name == 'posix':
            self.bundle.chmod(0o700)
            self._verify()
            self.bundle.chmod(0o755)
            self._verify()
            self.bundle.chmod(0o777)
            with self.assertRaises(VERIFY.VerificationError):
                self._verify()
            return

        original = VERIFY.os.lstat

        def safe(root_mode):
            def metadata(path):
                info = original(path)
                values = list(info)
                values[0] = stat.S_IFDIR | root_mode if Path(path) == self.bundle else (
                    stat.S_IFDIR | 0o755 if stat.S_ISDIR(info.st_mode) else stat.S_IFREG | 0o644)
                values[3] = 1
                return os.stat_result(values)
            return metadata

        for root_mode in (0o700, 0o755):
            with self.subTest(root_mode=oct(root_mode)):
                with patch.object(VERIFY, 'POSIX_MODES', True), patch.object(VERIFY.os, 'lstat', side_effect=safe(root_mode)):
                    self._verify()

        def unsafe_root(path):
            info = original(path)
            values = list(info)
            if Path(path) == self.bundle:
                values[0] = stat.S_IFDIR | 0o777
            else:
                values[0] = stat.S_IFDIR | 0o755 if stat.S_ISDIR(info.st_mode) else stat.S_IFREG | 0o644
            values[3] = 1
            return os.stat_result(values)

        with patch.object(VERIFY, 'POSIX_MODES', True), patch.object(VERIFY.os, 'lstat', side_effect=unsafe_root):
            with self.assertRaises(VERIFY.VerificationError):
                self._verify()

    def test_unit_state_values_reject_non_string_types(self):
        for field in ('ActiveState', 'SubState', 'Result'):
            for bad in ([], {}, True, 1):
                with self.subTest(field=field, value_type=type(bad).__name__):
                    self._make_bundle()
                    contract = self._contract()
                    contract['cold_compile_provenance']['leaf_controls'][0]['cleanup']['unit_state'][field] = bad
                    self._write_raw_contract(contract)
                    with self.assertRaises(VERIFY.VerificationError):
                        self._verify()


if __name__ == '__main__':
    unittest.main()
