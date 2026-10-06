#!/usr/bin/env python3
"""Offline archive and private source-handoff boundary tests."""

from pathlib import Path
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
import struct
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
DOWNLOAD_SPEC = importlib.util.spec_from_file_location(
    'download_source_handoff', ROOT / 'download-source-handoff.py')
DOWNLOAD = importlib.util.module_from_spec(DOWNLOAD_SPEC)
DOWNLOAD_SPEC.loader.exec_module(DOWNLOAD)


EXPECTED_FILES = tuple(['contract.json', 'JAC-LICENSE.txt'] +
                       ['files/source/member-{0:02d}.txt'.format(index) for index in range(36)])


def archive_bytes(members=None, *, compression=zipfile.ZIP_DEFLATED, duplicate=None):
    members = members or {name: ('fixture:' + name).encode('ascii') for name in EXPECTED_FILES}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=compression) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
        if duplicate is not None:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                archive.writestr(duplicate, b'duplicate')
    return stream.getvalue()


def invalid_archive(name, *, external_attr=None, flag_bits=0, compression=zipfile.ZIP_DEFLATED):
    members = {path: ('fixture:' + path).encode('utf-8') for path in EXPECTED_FILES}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for path, payload in members.items():
            if path == 'files/source/member-00.txt':
                info = zipfile.ZipInfo(name)
                info.compress_type = compression
                info.flag_bits = flag_bits
                if external_attr is not None:
                    info.create_system = 3
                    info.external_attr = external_attr
                archive.writestr(info, payload)
            else:
                archive.writestr(path, payload)
    return stream.getvalue()


def renamed_archive(name):
    original = b'files/source/member-00.txt'
    replacement = name.encode('utf-8')
    if len(original) != len(replacement):
        raise AssertionError('raw archive name fixture length')
    return archive_bytes().replace(original, replacement)


def encrypted_archive():
    raw = bytearray(archive_bytes())
    for signature, offset in ((b'PK\x03\x04', 6), (b'PK\x01\x02', 8)):
        cursor = 0
        while True:
            cursor = raw.find(signature, cursor)
            if cursor < 0:
                break
            raw[cursor + offset:cursor + offset + 2] = struct.pack('<H', 1)
            cursor += 4
    return bytes(raw)


def malformed_deflate_archive():
    raw = bytearray(archive_bytes())
    local = raw.find(b'PK\x03\x04')
    name_length, extra_length = struct.unpack_from('<HH', raw, local + 26)
    data_start = local + 30 + name_length + extra_length
    raw[data_start] = 0x07
    return bytes(raw)


def bundle_archive(bundle):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(path for path in Path(bundle).rglob('*') if path.is_file()):
            archive.write(path, path.relative_to(bundle).as_posix())
    return stream.getvalue()


class SourceArchiveTests(unittest.TestCase):
    def extract(self, raw, destination, expected_files=EXPECTED_FILES, **bindings):
        return DOWNLOAD.extract_archive(raw, destination, set(expected_files), **bindings)

    def digest(self, raw):
        return 'sha256:' + hashlib.sha256(raw).hexdigest()

    def test_valid_archive_extracts_exact_private_members_and_safe_modes(self):
        raw = archive_bytes()
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            destination = Path(temporary) / 'private'
            self.extract(raw, destination, expected_digest=self.digest(raw),
                         expected_size=len(raw))
            self.assertEqual(
                {path.relative_to(destination).as_posix() for path in destination.rglob('*') if path.is_file()},
                set(EXPECTED_FILES))
            for relative in EXPECTED_FILES:
                self.assertEqual((destination / relative).read_bytes(), ('fixture:' + relative).encode('ascii'))
            if os.name == 'posix':
                self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
                self.assertTrue(all((destination / relative).stat().st_mode & 0o777 == 0o600
                                    for relative in EXPECTED_FILES))

    def test_digest_size_and_destination_guards_happen_before_writes(self):
        raw = archive_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            for label, payload, size in (
                    ('digest', raw, len(raw) + 1),
                    ('size', raw, len(raw) + 1),
                    ('tamper', raw + b'tamper', len(raw) + 6)):
                destination = root / label
                with self.subTest(label=label), self.assertRaises(RuntimeError):
                    self.extract(payload, destination, expected_digest='sha256:' + digest, expected_size=size)
                self.assertFalse(destination.exists())
            existing = root / 'existing'
            existing.mkdir()
            marker = existing / 'keep.bin'
            marker.write_bytes(b'keep')
            with self.assertRaises(RuntimeError):
                self.extract(raw, existing, expected_digest='sha256:' + digest, expected_size=len(raw))
            self.assertEqual(marker.read_bytes(), b'keep')

    def test_member_set_path_and_file_type_guards_reject_without_escape_writes(self):
        raw = archive_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        cases = {
            'missing': archive_bytes({name: ('fixture:' + name).encode('ascii')
                                      for name in EXPECTED_FILES[:-1]}),
            'extra': archive_bytes(dict(
                {name: ('fixture:' + name).encode('ascii') for name in EXPECTED_FILES},
                **{'files/source/unknown.txt': b'unknown'})),
            'duplicate': archive_bytes(duplicate='contract.json'),
            'traversal': invalid_archive('../escape.txt'),
            'absolute': invalid_archive('/absolute.txt'),
            'backslash': renamed_archive('files\\source\\member-00.txt'),
            'colon': invalid_archive('C:member.txt'),
            'nul-member': invalid_archive('bad\x00member.txt'),
            'symlink': invalid_archive('files/source/member-00.txt',
                                       external_attr=(stat.S_IFLNK | 0o777) << 16),
            'device': invalid_archive('files/source/member-00.txt',
                                      external_attr=stat.S_IFCHR << 16),
            'encrypted': encrypted_archive(),
            'unsupported': invalid_archive('files/source/member-00.txt', compression=zipfile.ZIP_BZIP2),
            'unknown-directory': invalid_archive('unknown/'),
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            for label, payload in cases.items():
                destination = root / label
                with self.subTest(label=label), self.assertRaises(RuntimeError):
                    self.extract(payload, destination, expected_digest=self.digest(payload),
                                 expected_size=len(payload))
                self.assertFalse(destination.exists())
            self.assertFalse((root.parent / 'escape.txt').exists())

    def test_uncompressed_total_limit_and_symlink_destination_are_rejected(self):
        members = {name: ('fixture:' + name).encode('ascii') for name in EXPECTED_FILES}
        members['files/source/member-00.txt'] = b'x' * (1024 * 1024 + 1)
        raw = archive_bytes(members, compression=zipfile.ZIP_STORED)
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            destination = root / 'too-large'
            with self.assertRaises(RuntimeError):
                self.extract(raw, destination, expected_digest=self.digest(raw),
                             expected_size=len(raw))
            self.assertFalse(destination.exists())
            if os.name == 'posix':
                target = root / 'outside'
                target.write_bytes(b'outside')
                link = root / 'linked'
                link.symlink_to(target)
                with self.assertRaises(RuntimeError):
                    linked_raw = archive_bytes()
                    self.extract(linked_raw, link, expected_digest=self.digest(linked_raw),
                                 expected_size=len(archive_bytes()))
                self.assertEqual(target.read_bytes(), b'outside')

    def test_malformed_deflate_stream_is_rejected_before_destination_creation(self):
        raw = malformed_deflate_archive()
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            destination = Path(temporary) / 'malformed'
            with self.assertRaisesRegex(RuntimeError, '^source archive rejected$'):
                self.extract(raw, destination, expected_digest=self.digest(raw), expected_size=len(raw))
            self.assertFalse(destination.exists())

    def test_stage_handoff_authenticates_and_cleans_only_its_new_destination(self):
        spec = importlib.util.spec_from_file_location(
            'package_preflight_fixture_for_archive', ROOT / 'test-package-preflight.py')
        fixture_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture_module)
        fixture_module.PackagePreflightTests.setUpClass()
        fixture = fixture_module.PackagePreflightTests('test_valid_distinct_producer_consumer_commits_return_exact_inventory_shape').fixture()
        try:
            raw = bundle_archive(fixture['bundle'])
            contract_sha = hashlib.sha256((fixture['bundle'] / 'contract.json').read_bytes()).hexdigest()
            identity = {
                'status': 'passed', 'scope': 'successful source-proof origin commitment',
                'run_id': 1, 'job_id': 101, 'artifact_id': 202,
                'artifact_name': 'm-local-source-handoff-' + fixture['source_commit'] + '-1',
                'artifact_digest': self.digest(raw), 'artifact_size': len(raw),
                'contract_sha256': contract_sha,
            }
            real_trusted = DOWNLOAD.trusted_helpers
            cached = [None]
            endpoints = []

            def trusted(package_checkout, expected_package_commit):
                if cached[0] is None:
                    with patch.object(
                            DOWNLOAD, '__file__', str(fixture['package'] / 'runtime-proof/download-source-handoff.py')):
                        cached[0] = list(real_trusted(package_checkout, expected_package_commit))
                    cached[0][0]['__file__'] = str(fixture['package'] / 'runtime-proof/verify-package-preflight.py')
                    cached[0][1]['authenticate_origin'] = lambda commit, run: dict(identity)

                    def read_bytes(endpoint, limit):
                        endpoints.append((endpoint, limit))
                        return raw

                    cached[0][1]['gh_read_bytes'] = read_bytes
                return tuple(cached[0])

            destination = fixture['root'] / 'downloaded'
            with patch.object(DOWNLOAD, 'trusted_helpers', side_effect=trusted):
                result = DOWNLOAD.stage_handoff(
                    destination, fixture['source'], fixture['package'],
                    expected_source_commit=fixture['source_commit'],
                    expected_package_commit=fixture['package_commit'], expected_run_id='1')
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['scope'], 'authenticated source bundle and package commitments only')
            self.assertEqual(result['origin'], identity)
            self.assertEqual(result['preflight']['package']['input_count'], 12)
            self.assertEqual(endpoints, [
                ('repos/CosmonautJones/m-local/actions/artifacts/202/zip', len(raw))])
            self.assertEqual(
                {path.relative_to(destination).as_posix(): path.read_bytes()
                 for path in destination.rglob('*') if path.is_file()},
                {path.relative_to(fixture['bundle']).as_posix(): path.read_bytes()
                 for path in fixture['bundle'].rglob('*') if path.is_file()})

            occupied = fixture['root'] / 'occupied'
            occupied.mkdir()
            marker = occupied / 'keep.bin'
            marker.write_bytes(b'keep')
            with patch.object(DOWNLOAD, 'trusted_helpers', side_effect=trusted), \
                    self.assertRaises(RuntimeError):
                DOWNLOAD.stage_handoff(
                    occupied, fixture['source'], fixture['package'],
                    expected_source_commit=fixture['source_commit'],
                    expected_package_commit=fixture['package_commit'], expected_run_id='1')
            self.assertEqual(marker.read_bytes(), b'keep')

            original_preflight = cached[0][0]['verify_preflight']

            def rejected_preflight(*args, **kwargs):
                raise RuntimeError('synthetic preflight rejection')

            cached[0][0]['verify_preflight'] = rejected_preflight
            failed_destination = fixture['root'] / 'failed'
            with patch.object(DOWNLOAD, 'trusted_helpers', side_effect=trusted), \
                    self.assertRaisesRegex(RuntimeError, '^synthetic preflight rejection$'):
                DOWNLOAD.stage_handoff(
                    failed_destination, fixture['source'], fixture['package'],
                    expected_source_commit=fixture['source_commit'],
                    expected_package_commit=fixture['package_commit'], expected_run_id='1')
            self.assertFalse(failed_destination.exists())
            cached[0][0]['verify_preflight'] = original_preflight
        finally:
            fixture['temporary'].cleanup()

    def test_cli_emits_finite_success_or_generic_failure_only(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            arguments = ['--destination', str(root / 'destination'),
                         '--trusted-source-checkout', str(root / 'source'),
                         '--trusted-package-checkout', str(root / 'package'),
                         '--expected-source-commit', 'a' * 40,
                         '--expected-package-commit', 'b' * 40,
                         '--expected-run-id', '1']
            summary = {'status': 'passed', 'scope': 'authenticated source bundle and package commitments only',
                       'origin': {'artifact_id': 1}, 'preflight': {'status': 'passed'}}
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(DOWNLOAD, 'stage_handoff', return_value=summary), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = DOWNLOAD.main(arguments)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue()), summary)
            self.assertEqual(stderr.getvalue(), '')

            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(DOWNLOAD, 'stage_handoff',
                              side_effect=RuntimeError('RAW_PRIVATE_ARCHIVE_SENTINEL')), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = DOWNLOAD.main(arguments)
            self.assertEqual(code, 1)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue(), 'source handoff download verification failed\n')
            self.assertNotIn('RAW_PRIVATE_ARCHIVE_SENTINEL', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
