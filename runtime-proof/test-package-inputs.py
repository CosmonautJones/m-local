#!/usr/bin/env python3
"""Synthetic tests for the bounded official package-input cache verifier."""

from pathlib import Path, PurePosixPath
import ast
import hashlib
import io
import json
import stat
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'package-inputs' / 'package-runtime-candidate-v7.py'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def load_functions():
    tree = ast.parse(TARGET.read_text(encoding='utf-8'))
    wanted = {'inventory', 'verify_official_cache'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {'Path': Path, 'PurePosixPath': PurePosixPath, 'hashlib': hashlib, 'io': io,
                 'stat': stat, 'tarfile': tarfile, 'OFFICIAL_BINARY_SHA256': ''}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(TARGET), 'exec'), namespace)
    return namespace


def tar_layer(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for entry in entries:
            name = entry[0]
            member = tarfile.TarInfo(name)
            if entry[1] == 'dir':
                member.type = tarfile.DIRTYPE
                member.mode = 0o755
                archive.addfile(member)
            elif entry[1] == 'file':
                payload = entry[2]
                member.size = len(payload)
                member.mode = 0o644
                archive.addfile(member, io.BytesIO(payload))
            else:
                member.type = entry[1]
                member.linkname = entry[2]
                archive.addfile(member)
    return stream.getvalue()


class PackageInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.namespace = load_functions()

    def decompressor_modules(self):
        package = types.ModuleType('compression')
        package.__path__ = []
        zstd = types.ModuleType('compression.zstd')
        zstd.decompress = lambda payload: payload
        package.zstd = zstd
        return {'compression': package, 'compression.zstd': zstd}

    def verify(self, official, original):
        actual_inventory = self.namespace['inventory']

        def posix_inventory(root):
            # Fixture-only namespace bridge: call the actual inventory, then normalize
            # Windows separators for the verifier's archive-defined POSIX keys.
            return {key.replace('\\', '/'): value for key, value in actual_inventory(root).items()}

        with patch.dict(self.namespace, {'inventory': posix_inventory}), \
                patch.dict(sys.modules, self.decompressor_modules()):
            return self.namespace['verify_official_cache'](official, original)

    def make_fixture(self, *, entries=None):
        temporary = tempfile.TemporaryDirectory(dir=ROOT)
        root = Path(temporary.name)
        if entries is None:
            entries = [
                [('site', 'dir'), ('site/first.txt', 'file', b'first layer')],
                [('site/second', 'dir'), ('site/second/second.txt', 'file', b'second layer')],
            ]
        payload = b''.join(tar_layer(layer) for layer in entries)
        payload_hash = digest(payload)
        raw = b'JAC launcher fixture\n' + payload + b'JACBIN01' + len(payload).to_bytes(8, 'little') + payload_hash.encode('ascii')
        official = root / 'official-jac'
        official.write_bytes(raw)
        original = root / 'cache' / 'rt' / payload_hash[:16]
        original.mkdir(parents=True)
        (original / '.ok').write_bytes(b'')
        (original / '.used').write_bytes(b'ignored marker')
        (original / '__pycache__').mkdir()
        (original / '__pycache__' / 'ignored.pyc').write_bytes(b'ignored cache')

        def fixture_destination(name):
            member = PurePosixPath(name)
            if not name or member.is_absolute() or member == PurePosixPath('.'):
                return None
            if any(part in ('.', '..') for part in member.parts):
                return None
            destination = original.joinpath(*member.parts)
            try:
                destination.resolve(strict=False).relative_to(original.resolve())
            except ValueError:
                return None
            return destination

        for layer in entries:
            for entry in layer:
                if entry[1] == 'file':
                    path = fixture_destination(entry[0])
                    if path is None:
                        continue
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(entry[2])
                elif entry[1] == 'dir':
                    path = fixture_destination(entry[0])
                    if path is not None:
                        path.mkdir(parents=True, exist_ok=True)
        self.namespace['OFFICIAL_BINARY_SHA256'] = digest(raw)
        return temporary, official, original, payload_hash

    def test_inventory_excludes_only_allowed_runtime_sentinels(self):
        temporary, official, original, payload_hash = self.make_fixture()
        try:
            result = {key.replace('\\', '/'): value for key, value in self.namespace['inventory'](original).items()}
            self.assertEqual(set(result), {'site/first.txt', 'site/second/second.txt'})
            self.assertEqual(result['site/first.txt'], digest(b'first layer'))
            self.assertEqual(result['site/second/second.txt'], digest(b'second layer'))
        finally:
            temporary.cleanup()

    def test_valid_binary_and_concatenated_layers_verify(self):
        temporary, official, original, payload_hash = self.make_fixture()
        try:
            self.assertEqual(self.verify(official, original), payload_hash)
        finally:
            temporary.cleanup()

    def test_cache_tamper_missing_and_extra_files_rejected(self):
        for mutation in ('tamper', 'missing', 'extra'):
            with self.subTest(mutation=mutation):
                temporary, official, original, _ = self.make_fixture()
                try:
                    target = original / 'site/first.txt'
                    if mutation == 'tamper':
                        target.write_bytes(b'tampered')
                    elif mutation == 'missing':
                        target.unlink()
                    else:
                        (original / 'extra.txt').write_bytes(b'extra')
                    with self.assertRaises(AssertionError):
                        self.verify(official, original)
                finally:
                    temporary.cleanup()

    def test_wrong_cache_key_and_completion_marker_rejected(self):
        temporary, official, original, payload_hash = self.make_fixture()
        try:
            wrong = original.parent / ('0' * 16)
            original.rename(wrong)
            with self.assertRaises(AssertionError):
                self.verify(official, wrong)
        finally:
            temporary.cleanup()

        for marker in ('missing', 'nonempty'):
            with self.subTest(marker=marker):
                temporary, official, original, _ = self.make_fixture()
                try:
                    marker_path = original / '.ok'
                    if marker == 'missing':
                        marker_path.unlink()
                    else:
                        marker_path.write_bytes(b'not empty')
                    with self.assertRaises(AssertionError):
                        self.verify(official, original)
                finally:
                    temporary.cleanup()

    def test_wrong_official_hash_and_malformed_trailer_rejected(self):
        temporary, official, original, _ = self.make_fixture()
        try:
            original_expected = self.namespace['OFFICIAL_BINARY_SHA256']
            self.namespace['OFFICIAL_BINARY_SHA256'] = '0' * 64
            with self.assertRaises(AssertionError):
                self.verify(official, original)
            self.namespace['OFFICIAL_BINARY_SHA256'] = original_expected
        finally:
            temporary.cleanup()

        for name, trailer in (
                ('magic', b'BADMAGIC' + b'\0' * 72),
                ('size', b'JACBIN01' + (0).to_bytes(8, 'little') + b'0' * 64),
                ('payload hash', b'JACBIN01' + (1).to_bytes(8, 'little') + b'0' * 64)):
            with self.subTest(trailer=name):
                temporary, official, original, _ = self.make_fixture()
                try:
                    raw = official.read_bytes()
                    official.write_bytes(raw[:-80] + trailer)
                    self.namespace['OFFICIAL_BINARY_SHA256'] = digest(official.read_bytes())
                    with self.assertRaises(AssertionError):
                        self.verify(official, original)
                finally:
                    temporary.cleanup()

    def test_archive_traversal_duplicate_links_and_devices_rejected_without_writes(self):
        cases = [
            ('traversal', [[('../escape.txt', 'file', b'x')]]),
            ('absolute', [[('/absolute.txt', 'file', b'x')]]),
            ('duplicate', [[('same.txt', 'file', b'a')], [('same.txt', 'file', b'b')]]),
            ('symlink', [[('link', tarfile.SYMTYPE, 'target')]]),
            ('hardlink', [[('link', tarfile.LNKTYPE, 'target')]]),
            ('device', [[('device', tarfile.CHRTYPE, '')]]),
        ]
        for name, entries in cases:
            with self.subTest(case=name):
                temporary, official, original, _ = self.make_fixture(entries=entries)
                try:
                    outside = original.parent / 'escape.txt'
                    self.assertFalse(outside.exists())
                    self.assertFalse((Path(temporary.name) / 'absolute.txt').exists())
                    outside.write_bytes(b'outside sentinel')
                    with self.assertRaises(AssertionError):
                        self.verify(official, original)
                    self.assertEqual(outside.read_bytes(), b'outside sentinel')
                    self.assertFalse((Path(temporary.name) / 'absolute.txt').exists())
                finally:
                    temporary.cleanup()


if __name__ == '__main__':
    unittest.main()
