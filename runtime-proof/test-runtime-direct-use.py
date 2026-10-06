#!/usr/bin/env python3
"""Offline checks for predeclared runtime patch and assembly input bindings."""
from pathlib import Path
import contextlib
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('direct_use_preflight', ROOT / 'verify-package-preflight.py')
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
DECLARATION = (ROOT / 'runtime-direct-use-inputs-v1.json').read_bytes()
SOURCE = (ROOT / 'inputs/public-source-manifest.json').read_bytes()


class RuntimeDirectUseTests(unittest.TestCase):
    @contextlib.contextmanager
    def fresh_fork(self):
        declaration = json.loads(DECLARATION)
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            fork = Path(directory) / 'fork'
            fork.mkdir()
            for name, metadata in declaration['included_source_files'].items():
                destination = fork / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / 'inputs' / metadata['source_member']).read_bytes())
            replies = {
                ('rev-parse', '--show-toplevel'): (str(fork) + '\n').encode(),
                ('rev-parse', '--verify', 'HEAD'): (declaration['base_revision'] + '\n').encode(),
                ('diff', '--no-ext-diff', '--no-textconv', '--cached', '--binary'): b'',
                ('diff', '--no-ext-diff', '--no-textconv', '--binary'):
                    (ROOT / 'inputs/work/identity-runtime-v3/runtime.patch').read_bytes(),
                ('diff', '--no-ext-diff', '--no-textconv', '--name-only', '-z'):
                    b'\0'.join(name.encode() for name in declaration['included_source_files']) + b'\0',
                ('ls-files', '--others', '-z', '--', 'jac'): b'',
            }

            def git_reply(checkout, arguments):
                self.assertEqual(checkout, fork)
                return replies[tuple(arguments)]

            # Only Git metadata is synthetic; the actual regular source bytes,
            # declaration, patch and assembly binding functions are exercised.
            with patch.object(VERIFY, 'git', side_effect=git_reply):
                yield fork, declaration, replies

    def test_declaration_matches_all_real_sources_without_claiming_assembly(self):
        result = VERIFY.verify_direct_use_declaration(DECLARATION, SOURCE)
        self.assertEqual(result, dict(status='declaration_verified', declaration_sha256=VERIFY.sha(DECLARATION),
                                     input_count=17, jac_bytes=348363, denominator_bytes=348363,
                                     share_percent=100, direct_use_observed=False))

    def test_tampered_declaration_and_source_manifest_are_rejected(self):
        for raw, source in ((DECLARATION + b' ', SOURCE), (DECLARATION, SOURCE + b' ')):
            with self.subTest(source_changed=source != SOURCE), self.assertRaises(VERIFY.PreflightError):
                VERIFY.verify_direct_use_declaration(raw, source)

    def test_rehashed_declaration_cannot_omit_sources_or_change_denominator(self):
        for field in ('included_source_files', 'excluded_file_reasons', 'denominator_bytes', 'jac_bytes',
                      'share_percent', 'base_revision', 'runtime_patch_sha256'):
            declaration = json.loads(DECLARATION)
            if isinstance(declaration[field], dict):
                declaration[field].pop(next(iter(declaration[field])))
            else:
                declaration[field] = 0
            raw = json.dumps(declaration).encode()
            # A future reviewed pin rotation must still satisfy the unchanged
            # source inventory and arithmetic, not merely a new JSON hash.
            with self.subTest(field=field), patch.object(VERIFY, 'DIRECT_USE_SHA', VERIFY.sha(raw)), \
                    self.assertRaises(VERIFY.PreflightError):
                VERIFY.verify_direct_use_declaration(raw, SOURCE)

    def test_fork_requires_exact_base_unstaged_patch_and_changed_file_set(self):
        with self.fresh_fork() as (fork, declaration, replies):
            result = VERIFY.verify_direct_use_fork(fork, DECLARATION, SOURCE)
            self.assertEqual(result['status'], 'fresh_fork_verified')
            self.assertFalse(result['assembly_observed'])
            cases = {
                ('rev-parse', '--verify', 'HEAD'): b'0' * 40 + b'\n',
                ('diff', '--no-ext-diff', '--no-textconv', '--cached', '--binary'): b'staged changes',
                ('diff', '--no-ext-diff', '--no-textconv', '--binary'): b'wrong patch',
                ('diff', '--no-ext-diff', '--no-textconv', '--name-only', '-z'):
                    b'\0'.join(name.encode() for name in list(declaration['included_source_files'])[1:]) + b'\0',
            }
            for command, value in cases.items():
                original = replies[command]
                replies[command] = value
                try:
                    with self.subTest(command=command), self.assertRaises(VERIFY.PreflightError):
                        VERIFY.verify_direct_use_fork(fork, DECLARATION, SOURCE)
                finally:
                    replies[command] = original

    def test_fork_requires_real_regular_source_files_with_exact_bytes(self):
        with self.fresh_fork() as (fork, declaration, _replies):
            target = fork / next(iter(declaration['included_source_files']))
            original = target.read_bytes()
            target.write_bytes(original + b'changed')
            with self.assertRaises(VERIFY.PreflightError):
                VERIFY.verify_direct_use_fork(fork, DECLARATION, SOURCE)
            target.write_bytes(original)
            with patch.object(VERIFY.Path, 'is_symlink', lambda value: value == target), \
                    self.assertRaises(VERIFY.PreflightError):
                VERIFY.verify_direct_use_fork(fork, DECLARATION, SOURCE)
            target.unlink()
            with self.assertRaises(OSError):
                VERIFY.verify_direct_use_fork(fork, DECLARATION, SOURCE)

    def test_untracked_and_ignored_fork_inputs_are_rejected(self):
        with self.fresh_fork() as (fork, _declaration, replies):
            # ls-files without --exclude-standard includes ignored files too.
            command = ('ls-files', '--others', '-z', '--', 'jac')
            for name in ('jac/extra.jac', 'jac/.ignored.py', 'jac/unknown.bin',
                         'jac/jaclang/compiler/backends/native/llvm/libjacllvm.so',
                         'jac/jaclang/vendor/typeshed/stdlib/extra.pyi'):
                target = fork / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'unknown input')
                replies[command] = name.encode() + b'\0'
                with self.subTest(name=name), self.assertRaises(VERIFY.PreflightError):
                    VERIFY.verify_direct_use_fork(fork, DECLARATION, SOURCE)
                target.unlink()

    def test_inherited_empty_files_do_not_relax_normal_input_bounds(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            target = Path(directory) / 'empty.pyi'
            target.write_bytes(b'')
            with self.assertRaises(VERIFY.PreflightError):
                VERIFY.read_regular(target)
            self.assertEqual(VERIFY.read_regular(target, allow_empty=True), b'')
            target.write_bytes(b'x' * (VERIFY.MAX_FILE_BYTES + 1))
            with self.assertRaises(VERIFY.PreflightError):
                VERIFY.read_regular(target)

    def test_assembly_inventory_requires_external_commitment_and_every_source_hash(self):
        with self.fresh_fork() as (fork, declaration, _replies):
            target = fork.parent / 'assembled-inputs.json'
            assembled = {item['assembled_path']: item['sha256']
                         for item in declaration['included_source_files'].values()}
            raw = json.dumps(assembled).encode()
            target.write_bytes(raw)
            result = VERIFY.verify_direct_use_assembly(fork, target, DECLARATION, SOURCE,
                                                       expected_assembled_sha256=VERIFY.sha(raw))
            self.assertTrue(result['assembly_inventory_bound'])
            self.assertFalse(result['assembly_observed'])
            self.assertFalse(result['direct_use_observed'])
            with self.assertRaises(VERIFY.PreflightError):
                VERIFY.verify_direct_use_assembly(fork, target, DECLARATION, SOURCE,
                                                  expected_assembled_sha256='0' * 64)
            for missing in (False, True):
                bad = dict(assembled)
                name = next(iter(bad))
                if missing:
                    bad.pop(name)
                else:
                    bad[name] = '0' * 64
                raw = json.dumps(bad).encode()
                target.write_bytes(raw)
                with self.subTest(missing=missing), self.assertRaises(VERIFY.PreflightError):
                    VERIFY.verify_direct_use_assembly(fork, target, DECLARATION, SOURCE,
                                                      expected_assembled_sha256=VERIFY.sha(raw))


if __name__ == '__main__':
    unittest.main()
