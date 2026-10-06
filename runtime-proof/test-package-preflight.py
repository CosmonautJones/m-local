#!/usr/bin/env python3
"""Commitment-only tests for the package preflight trust boundary."""

from pathlib import Path
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
HANDOFF_TEST = ROOT / 'test-source-handoff.py'
PREFLIGHT_SOURCE = ROOT / 'verify-package-preflight.py'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(path, *arguments):
    environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_TERMINAL_PROMPT='0')
    return subprocess.run(['git', '--no-replace-objects', '-C', str(path), *arguments],
                          env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True).stdout


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackagePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handoff = load_module(HANDOFF_TEST, 'source_handoff_fixture')

    def make_repo(self, path, files):
        path.mkdir(parents=True)
        git(path, 'init', '--quiet')
        git(path, 'config', 'user.email', 'fixture@example.invalid')
        git(path, 'config', 'user.name', 'preflight fixture')
        (path / '.gitattributes').write_text('** -text\n', encoding='utf-8')
        for relative in files:
            destination = path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            raw = PREFLIGHT_SOURCE.read_bytes() if relative == 'runtime-proof/verify-package-preflight.py' \
                else git(REPO, 'show', ':' + relative)
            destination.write_bytes(raw)
        git(path, 'add', '--all')
        git(path, 'commit', '--quiet', '-m', 'fixture inputs')
        return git(path, 'rev-parse', 'HEAD').decode('ascii').strip()

    def fixture(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT)
        root = Path(temporary.name)
        source = root / 'producer'
        package = root / 'consumer'
        source_manifest = json.loads((REPO / 'runtime-proof/inputs/public-source-manifest.json').read_text())
        adapter_manifest = json.loads((REPO / 'runtime-proof/inputs/v8-adapter-manifest.json').read_text())
        source_files = {
            'runtime-proof/run-fresh-source.py',
            'runtime-proof/kali-build-resources-v2.py',
            'runtime-proof/verify-source-handoff-v8.py',
            'runtime-proof/public-download-pins.json',
            'runtime-proof/JAC-LICENSE.txt',
            'runtime-proof/inputs/public-source-manifest.json',
            'runtime-proof/inputs/v8-adapter-manifest.json',
        }
        source_files.update('runtime-proof/inputs/' + relative for relative in source_manifest['files'])
        source_files.update('runtime-proof/inputs/' + relative for relative in adapter_manifest['files'])
        source_commit = self.make_repo(source, sorted(source_files))

        package_manifest = json.loads((REPO / 'runtime-proof/package-inputs/public-package-manifest-v7.json').read_text())
        package_files = {
            'runtime-proof/verify-package-preflight.py',
            'runtime-proof/verify-source-handoff-v8.py',
            'runtime-proof/package-inputs/public-package-manifest-v7.json',
            'runtime-proof/package-inputs/public-policy-manifest-v7.json',
        }
        package_files.update('runtime-proof/package-inputs/' + relative for relative in package_manifest['files'])
        package_commit = self.make_repo(package, sorted(package_files))

        handoff = object.__new__(self.handoff.SourceHandoffTests)
        handoff.checkout = source
        handoff.manifest = self.handoff.VERIFY._read_json(source / 'runtime-proof/inputs/public-source-manifest.json')
        handoff.adapters = self.handoff.VERIFY._read_json(source / 'runtime-proof/inputs/v8-adapter-manifest.json')
        handoff.commit = source_commit
        handoff.bundle = root / 'bundle'
        handoff._make_bundle()
        preflight = load_module(package / 'runtime-proof/verify-package-preflight.py',
                                'verify_package_preflight_' + source_commit[:8])
        return dict(temporary=temporary, root=root, source=source, package=package,
                    bundle=handoff.bundle, source_commit=source_commit,
                    package_commit=package_commit, preflight=preflight)

    def verify(self, fixture, **overrides):
        values = dict(expected_source_commit=fixture['source_commit'],
                      expected_package_commit=fixture['package_commit'],
                      expected_run_id='1',
                      expected_contract_sha256=sha((fixture['bundle'] / 'contract.json').read_bytes()))
        values.update(overrides)
        return fixture['preflight'].verify_preflight(fixture['bundle'], fixture['source'],
                                                      fixture['package'], **values)

    def assert_rejected(self, fixture, **overrides):
        with self.assertRaises((fixture['preflight'].PreflightError, OSError, ValueError,
                                subprocess.SubprocessError)):
            self.verify(fixture, **overrides)

    def test_valid_distinct_producer_consumer_commits_return_exact_inventory_shape(self):
        fixture = self.fixture()
        try:
            self.assertNotEqual(fixture['source_commit'], fixture['package_commit'])
            result = self.verify(fixture)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['scope'], 'source and package input commitment verification only')
            self.assertEqual(result['source_input_count'], 45)
            self.assertEqual(len(result['source_inventory_sha256']), 64)
            self.assertEqual(result['package'], dict(
                commit_sha=fixture['package_commit'],
                manifest_sha256='681d3cc0713d196d29f0e335a3454ed34e9cc6fa860afc0dbd30713681b81888',
                input_count=9, inventory_sha256=result['package']['inventory_sha256']))
        finally:
            fixture['temporary'].cleanup()

    def test_wrong_external_bindings_are_rejected(self):
        cases = {
            'source': dict(expected_source_commit='0' * 40),
            'package': dict(expected_package_commit='f' * 40),
            'run': dict(expected_run_id='2'),
            'run-format': dict(expected_run_id='0'),
            'contract': dict(expected_contract_sha256='a' * 64),
        }
        fixture = self.fixture()
        try:
            for name, overrides in cases.items():
                with self.subTest(binding=name):
                    self.assert_rejected(fixture, **overrides)
        finally:
            fixture['temporary'].cleanup()

    def test_source_critical_and_manifest_worktree_tampering_is_rejected(self):
        fixture = self.fixture()
        try:
            for relative in ('runtime-proof/run-fresh-source.py',
                             'runtime-proof/inputs/public-source-manifest.json',
                             'runtime-proof/inputs/v8-adapter-manifest.json'):
                path = fixture['source'] / relative
                original = path.read_bytes()
                path.write_bytes(path.read_bytes() + b'\nfixture tamper')
                self.assert_rejected(fixture)
                path.write_bytes(original)
        finally:
            fixture['temporary'].cleanup()

    def test_consumer_self_verifier_manifest_and_package_tampering_is_rejected(self):
        cases = ('runtime-proof/verify-package-preflight.py',
                 'runtime-proof/verify-source-handoff-v8.py',
                 'runtime-proof/package-inputs/public-package-manifest-v7.json',
                 'runtime-proof/package-inputs/package-runtime-candidate-v7.py')
        fixture = self.fixture()
        try:
            for relative in cases:
                with self.subTest(relative=relative):
                    path = fixture['package'] / relative
                    original = path.read_bytes()
                    path.write_bytes(path.read_bytes() + b'\nfixture tamper')
                    self.assert_rejected(fixture)
                    path.write_bytes(original)
        finally:
            fixture['temporary'].cleanup()

    def test_package_inventory_rejects_extra_and_uncommitted_input(self):
        fixture = self.fixture()
        try:
            extra = fixture['package'] / 'runtime-proof/package-inputs/extra.py'
            extra.write_text('open(r"' + str(fixture['root'] / 'marker') + '", "w").write("ran")\n', encoding='utf-8')
            self.assert_rejected(fixture)
            extra.unlink()
            target = fixture['package'] / 'runtime-proof/package-inputs/package-runtime-candidate-v7.py'
            target.write_bytes(target.read_bytes() + b'\nworking tree change')
            self.assert_rejected(fixture)
        finally:
            fixture['temporary'].cleanup()

    def test_symlink_and_hardlink_metadata_are_rejected_without_platform_skip(self):
        fixture = self.fixture()
        target = fixture['package'] / 'runtime-proof/package-inputs/package-runtime-candidate-v7.py'
        original = target.read_bytes()
        try:
            if os.name == 'posix':
                target.unlink()
                target.symlink_to(fixture['package'] / 'runtime-proof/verify-source-handoff-v8.py')
                self.assert_rejected(fixture)
            else:
                with patch.object(fixture['preflight'].Path, 'is_symlink',
                                  lambda path: path == target):
                    self.assert_rejected(fixture)
            target.unlink()
            target.write_bytes(original)
            if os.name == 'posix':
                source = fixture['package'] / 'runtime-proof/verify-source-handoff-v8.py'
                target.unlink()
                os.link(source, target)
                self.assert_rejected(fixture)
            else:
                original_lstat = fixture['preflight'].Path.lstat

                def fake_lstat(path):
                    info = original_lstat(path)
                    if path == target:
                        return os.stat_result((info.st_mode, info.st_ino, info.st_dev,
                                               2, info.st_uid, info.st_gid, info.st_size,
                                               info.st_atime, info.st_mtime, info.st_ctime))
                    return info

                with patch.object(fixture['preflight'].Path, 'lstat', fake_lstat):
                    self.assert_rejected(fixture)
        finally:
            fixture['temporary'].cleanup()

    def test_bundle_extra_code_and_bad_receipt_are_rejected_without_execution(self):
        fixture = self.fixture()
        try:
            marker = fixture['root'] / 'artifact-executed'
            (fixture['bundle'] / 'artifact.py').write_text(
                'from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("ran")\n', encoding='utf-8')
            self.assert_rejected(fixture)
            self.assertFalse(marker.exists())
            (fixture['bundle'] / 'artifact.py').unlink()
            self.verify(fixture)
            receipt = fixture['bundle'] / 'source-matrix-receipt.json'
            original = receipt.read_bytes()
            receipt.write_bytes(original.replace(b'"status": "passed"', b'"status": "failed"', 1))
            self.assert_rejected(fixture)
            receipt.write_bytes(original)
        finally:
            fixture['temporary'].cleanup()

    def test_cli_failure_is_finite_and_does_not_leak_checkout_paths(self):
        fixture = self.fixture()
        try:
            module_path = fixture['package'] / 'runtime-proof/verify-package-preflight.py'
            command = [sys.executable, '-I', '-B', str(module_path), '--bundle', str(fixture['bundle']),
                       '--trusted-source-checkout', str(fixture['source']),
                       '--trusted-package-checkout', str(fixture['package']),
                       '--expected-source-commit', '0' * 40,
                       '--expected-package-commit', fixture['package_commit'],
                       '--expected-run-id', '1',
                       '--expected-contract-sha256', sha((fixture['bundle'] / 'contract.json').read_bytes())]
            result = subprocess.run(command, cwd=fixture['root'], env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout), {'error': 'checkout commit binding', 'status': 'failed'})
            self.assertNotIn(str(fixture['root']), result.stdout)
            self.assertEqual(result.stderr, '')
        finally:
            fixture['temporary'].cleanup()


if __name__ == '__main__':
    unittest.main()
