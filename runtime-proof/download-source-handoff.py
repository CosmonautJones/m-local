#!/usr/bin/env python3
"""Download and verify a source handoff from its successful GitHub proof job.

Run only from the reviewed package checkout. Expected commits and run ID are
trusted caller inputs. No downloaded code is imported or executed; acceptance
is limited to the authenticated source bundle and committed package inputs.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
import zlib


ROOT = Path(__file__).absolute().parents[1]
SELF_PATH = 'runtime-proof/download-source-handoff.py'
ORIGIN_PATH = 'runtime-proof/verify-source-origin.py'
PREFLIGHT_PATH = 'runtime-proof/verify-package-preflight.py'
PREFLIGHT_SHA = 'd47b342bea74d64fa3575673a07b90d5595fdabe0e87a93f714cc6d7caa7c635'
SOURCE_MANIFEST = 'runtime-proof/inputs/public-source-manifest.json'
MAX_ZIP_BYTES = 2 * 1024 ** 2
MAX_BUNDLE_BYTES = 1024 ** 2


def fail(label):
    raise RuntimeError(label)


def no_links(path):
    if path.resolve() != path or any(item.is_symlink() for item in (path, *path.parents)):
        fail('source destination path')


def expected_paths(manifest):
    files = {'files/' + name for name in manifest['files']}
    files.update(('source-bootstrap-receipt.json', 'source-matrix-receipt.json', 'contract.json', 'JAC-LICENSE.txt'))
    if len(files) != 38:
        fail('source member count')
    return files


def extract_archive(raw, destination, expected_files, *, expected_digest, expected_size):
    if type(expected_size) is not int or not 0 < expected_size <= MAX_ZIP_BYTES or \
            type(raw) is not bytes or len(raw) != expected_size or \
            type(expected_digest) is not str or re.fullmatch(r'sha256:[0-9a-f]{64}', expected_digest) is None or \
            'sha256:' + hashlib.sha256(raw).hexdigest() != expected_digest:
        fail('source archive byte commitment')
    if type(expected_files) is not set or len(expected_files) != 38:
        fail('source expected inventory')
    directories = set()
    for name in expected_files:
        if type(name) is not str:
            fail('source expected path')
        path = PurePosixPath(name)
        if path.is_absolute() or str(path) != name or \
                any(part in ('', '.', '..') for part in path.parts) or '\\' in name or ':' in name or '\x00' in name:
            fail('source expected path')
        directories.update(str(parent) for parent in path.parents if str(parent) != '.')
    destination = Path(destination).absolute()
    no_links(destination)
    no_links(destination.parent)
    if not destination.parent.is_dir() or destination.exists() or destination.is_symlink():
        fail('source destination occupied or missing parent')
    if os.name == 'posix' and destination.parent.stat().st_mode & 0o022:
        fail('source destination parent writable')
    contents, seen, total = {}, set(), 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            rows = archive.infolist()
            if not 38 <= len(rows) <= 38 + len(directories):
                fail('source archive member count')
            for row in rows:
                name = row.filename
                if row.orig_filename != name or name in seen or '\\' in name or ':' in name or '\x00' in name or \
                        row.flag_bits & 1 or row.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    fail('source archive entry')
                seen.add(name)
                path = PurePosixPath(name[:-1] if row.is_dir() else name)
                if path.is_absolute() or str(path) != name.rstrip('/') or \
                        (row.is_dir() and name != str(path) + '/') or \
                        any(part in ('', '.', '..') for part in path.parts):
                    fail('source archive path')
                kind = stat.S_IFMT(row.external_attr >> 16)
                if row.is_dir():
                    if str(path) not in directories or kind not in (0, stat.S_IFDIR) or row.file_size != 0:
                        fail('source archive directory')
                    continue
                if name not in expected_files or kind not in (0, stat.S_IFREG) or \
                        not 0 < row.file_size < MAX_BUNDLE_BYTES:
                    fail('source archive file')
                total += row.file_size
                if total >= MAX_BUNDLE_BYTES:
                    fail('source archive uncompressed bounds')
                with archive.open(row) as stream:
                    value = stream.read(row.file_size + 1)
                if len(value) != row.file_size:
                    fail('source archive decompressed size')
                contents[name] = value
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, ValueError, EOFError, OSError, zlib.error):
        fail('source archive rejected')
    if set(contents) != expected_files:
        fail('source archive inventory')
    # Validate all entries and decompressed bounds before creating any output.
    destination.mkdir(mode=0o700)
    info = destination.lstat()
    try:
        for name in sorted(directories, key=lambda value: (value.count('/'), value)):
            (destination / name).mkdir(mode=0o700)
        for name, value in contents.items():
            target = destination / name
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0)
            with os.fdopen(os.open(target, flags, 0o600), 'wb') as stream:
                stream.write(value)
    except BaseException:
        remove_owned(destination, info)
        raise
    return destination


def remove_owned(destination, info):
    destination = Path(destination).absolute()
    no_links(destination)
    current = destination.lstat()
    if not stat.S_ISDIR(current.st_mode) or \
            (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
        fail('source cleanup identity')
    # Only the exact newly created, canonical destination can reach deletion.
    shutil.rmtree(destination)


def trusted_helpers(package_checkout, expected_package_commit):
    if type(expected_package_commit) is not str or re.fullmatch(r'[0-9a-f]{40}', expected_package_commit) is None:
        fail('package commit format')
    no_links(ROOT)
    path = ROOT / PREFLIGHT_PATH
    no_links(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_BUNDLE_BYTES:
        fail('trusted preflight type')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BUNDLE_BYTES + 1)
    if hashlib.sha256(raw).hexdigest() != PREFLIGHT_SHA:
        fail('trusted preflight hash')
    preflight = {'__file__': str(path), '__name__': 'trusted_source_preflight'}
    exec(compile(raw, str(path), 'exec'), preflight)
    package = preflight['checked_checkout'](package_checkout, expected_package_commit)
    if Path(__file__).absolute() != package / SELF_PATH:
        fail('download helper checkout binding')
    files = {name: preflight['committed_file'](package, expected_package_commit, name)
             for name in (SELF_PATH, ORIGIN_PATH, PREFLIGHT_PATH)}
    if files[PREFLIGHT_PATH] != raw:
        fail('preflight code commitment')
    origin = {'__file__': str(package / ORIGIN_PATH), '__name__': 'trusted_source_origin'}
    exec(compile(files[ORIGIN_PATH], str(package / ORIGIN_PATH), 'exec'), origin)
    return preflight, origin, package


def stage_handoff(destination, source_checkout, package_checkout, *, expected_source_commit,
                  expected_package_commit, expected_run_id):
    preflight, origin, package = trusted_helpers(package_checkout, expected_package_commit)
    preflight['require_pattern'](expected_source_commit, r'[0-9a-f]{40}', 'source commit format')
    preflight['require_pattern'](expected_run_id, r'[1-9][0-9]{0,19}', 'source run format')
    source = preflight['checked_checkout'](source_checkout, expected_source_commit)
    manifest_raw = preflight['committed_file'](source, expected_source_commit, SOURCE_MANIFEST)
    if preflight['sha'](manifest_raw) != preflight['SOURCE_MANIFEST_SHA']:
        fail('source manifest pin')
    files = expected_paths(json.loads(manifest_raw))
    # No destination is created until the exact successful job is authenticated.
    identity = origin['authenticate_origin'](expected_source_commit, expected_run_id)
    if identity.get('status') != 'passed' or identity.get('scope') != 'successful source-proof origin commitment' or \
            type(identity.get('run_id')) is not int or identity['run_id'] != int(expected_run_id) or \
            type(identity.get('artifact_id')) is not int or identity['artifact_id'] <= 0:
        fail('source origin result')
    size = identity.get('artifact_size')
    if type(size) is not int or not 0 < size <= MAX_ZIP_BYTES:
        fail('source archive size')
    raw = origin['gh_read_bytes']('repos/CosmonautJones/m-local/actions/artifacts/' +
                                 str(identity['artifact_id']) + '/zip', size)
    bundle = extract_archive(raw, destination, files,
                             expected_digest=identity.get('artifact_digest'), expected_size=size)
    info = bundle.lstat()
    try:
        result = preflight['verify_preflight'](bundle, source, package,
            expected_source_commit=expected_source_commit, expected_package_commit=expected_package_commit,
            expected_run_id=expected_run_id, expected_contract_sha256=identity['contract_sha256'])
    except BaseException:
        remove_owned(bundle, info)
        raise
    return {'status': 'passed', 'scope': 'authenticated source bundle and package commitments only',
            'origin': identity, 'preflight': result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--trusted-source-checkout', required=True, type=Path)
    parser.add_argument('--trusted-package-checkout', required=True, type=Path)
    parser.add_argument('--expected-source-commit', required=True)
    parser.add_argument('--expected-package-commit', required=True)
    parser.add_argument('--expected-run-id', required=True)
    args = parser.parse_args(argv)
    try:
        result = stage_handoff(args.destination, args.trusted_source_checkout, args.trusted_package_checkout,
            expected_source_commit=args.expected_source_commit, expected_package_commit=args.expected_package_commit,
            expected_run_id=args.expected_run_id)
    except (RuntimeError, OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        print('source handoff download verification failed', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
