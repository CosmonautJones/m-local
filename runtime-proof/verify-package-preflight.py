#!/usr/bin/env python3
"""Check source and package input commitments without running their code.

The caller supplies identities and the contract hash from a successful trusted
source job. This check does not establish that job's success or build a package.
Copied inputs must be rebound before the later runtime launch.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys


MAX_FILE_BYTES = 1024 ** 2
VERIFIER_SHA = '6829da3ab0a6897e168c8c7efc2384330a04a5a036e53da02653f6ff07b317f3'
BASE_VERIFIER_SHA = 'b8c92532e99a095f40b718a4a068330def7b47b31a78f00b8c09ff981b0a04fe'
SOURCE_MANIFEST_SHA = 'f0ade58e7b59cc49eb5c3c3d0a6c8ca08c4f5b9804dc49ad5ea4f171cc4be037'
ADAPTER_MANIFEST_SHA = '91a9b2f303a57b0178f1ff0c3b876f4d13a84913ce7270b8eb883f144056a81e'
PACKAGE_MANIFEST_SHA = '681d3cc0713d196d29f0e335a3454ed34e9cc6fa860afc0dbd30713681b81888'
POLICY_MANIFEST_SHA = '9221e3af38924d04cc72f204512890dc3864697ac8ac40bf8eb9fa0843556ce0'
SELF_PATH = 'runtime-proof/verify-package-preflight.py'
BASE_VERIFIER_PATH = 'runtime-proof/verify-source-handoff-v8.py'
CONSUMER_HELPERS = ('runtime-proof/verify-source-origin.py', 'runtime-proof/download-source-handoff.py', BASE_VERIFIER_PATH)
VERIFIER_PATH = 'runtime-proof/verify-source-handoff-v9.py'
PACKAGE_PATH = 'runtime-proof/package-inputs/'
SOURCE_CRITICAL = (
    'runtime-proof/run-fresh-source.py',
    'runtime-proof/kali-build-resources-v2.py',
    VERIFIER_PATH,
    BASE_VERIFIER_PATH,
    'runtime-proof/public-download-pins.json',
    'runtime-proof/JAC-LICENSE.txt',
    'runtime-proof/inputs/public-source-manifest.json',
    'runtime-proof/inputs/v9-adapter-manifest.json',
)


class PreflightError(ValueError):
    pass


def fail(label):
    raise PreflightError(label)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require_pattern(value, pattern, label):
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        fail(label)


def no_links(path):
    if path.resolve() != path or any(item.is_symlink() for item in (path, *path.parents)):
        fail('linked input path')


def read_regular(path):
    no_links(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            not 0 < info.st_size <= MAX_FILE_BYTES or
            (os.name == 'posix' and info.st_mode & 0o022)):
        fail('input file type or bounds')
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_nlink')
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if any(getattr(opened, key) != getattr(info, key) for key in fields):
            fail('input descriptor identity')
        raw = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
        if len(raw) != info.st_size or any(getattr(after, key) != getattr(opened, key) for key in fields):
            fail('input changed during read')
    return raw


def git(checkout, arguments):
    environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_NO_REPLACE_OBJECTS='1', GIT_OPTIONAL_LOCKS='0')
    result = subprocess.run(['git', '--no-replace-objects', '-C', str(checkout), *arguments],
                            env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=30)
    if result.returncode or len(result.stdout) > MAX_FILE_BYTES:
        fail('Git input inspection')
    return result.stdout


def checked_checkout(value, expected_commit):
    path = Path(value).absolute()
    no_links(path)
    if not path.is_dir():
        fail('checkout directory')
    top = Path(git(path, ['rev-parse', '--show-toplevel']).decode('utf-8').strip())
    if top != path or git(path, ['rev-parse', '--verify', 'HEAD']).decode('ascii').strip() != expected_commit:
        fail('checkout commit binding')
    return path


def committed_file(checkout, commit, relative):
    item = PurePosixPath(relative)
    if (item.is_absolute() or str(item) != relative or '\\' in relative or ':' in relative or
            any(part in ('', '.', '..') for part in item.parts)):
        fail('input relative path')
    raw = read_regular(checkout / Path(*item.parts))
    reference = commit + ':' + relative
    size = git(checkout, ['cat-file', '-s', reference]).decode('ascii').strip()
    if not size.isascii() or not size.isdecimal() or not 0 < int(size) <= MAX_FILE_BYTES:
        fail('committed input bounds')
    if git(checkout, ['show', reference]) != raw:
        fail('committed input byte binding')
    return raw


def inventory_hash(files):
    return sha(json.dumps({name: dict(bytes=len(raw), sha256=sha(raw)) for name, raw in files.items()},
                          sort_keys=True, separators=(',', ':')).encode('utf-8'))


def verify_preflight(bundle, source_checkout, package_checkout, *, expected_source_commit,
                     expected_package_commit, expected_run_id, expected_contract_sha256):
    require_pattern(expected_source_commit, r'[0-9a-f]{40}', 'source commit format')
    require_pattern(expected_package_commit, r'[0-9a-f]{40}', 'package commit format')
    require_pattern(expected_run_id, r'[1-9][0-9]*', 'run ID format')
    require_pattern(expected_contract_sha256, r'[0-9a-f]{64}', 'contract hash format')
    source = checked_checkout(source_checkout, expected_source_commit)
    package = checked_checkout(package_checkout, expected_package_commit)
    if Path(__file__).absolute() != package / SELF_PATH:
        fail('preflight checkout binding')
    consumer = {SELF_PATH: committed_file(package, expected_package_commit, SELF_PATH),
                VERIFIER_PATH: committed_file(package, expected_package_commit, VERIFIER_PATH)}
    consumer.update({name: committed_file(package, expected_package_commit, name) for name in CONSUMER_HELPERS})
    if sha(consumer[VERIFIER_PATH]) != VERIFIER_SHA or sha(consumer[BASE_VERIFIER_PATH]) != BASE_VERIFIER_SHA:
        fail('trusted verifier pin')
    producer = {name: committed_file(source, expected_source_commit, name) for name in SOURCE_CRITICAL}
    if (sha(producer[VERIFIER_PATH]) != VERIFIER_SHA or
            sha(producer[BASE_VERIFIER_PATH]) != BASE_VERIFIER_SHA or
            sha(producer['runtime-proof/inputs/public-source-manifest.json']) != SOURCE_MANIFEST_SHA or
            sha(producer['runtime-proof/inputs/v9-adapter-manifest.json']) != ADAPTER_MANIFEST_SHA):
        fail('trusted source pins')
    for manifest_name in ('public-source-manifest.json', 'v9-adapter-manifest.json'):
        manifest = json.loads(producer['runtime-proof/inputs/' + manifest_name])
        for relative, metadata in manifest['files'].items():
            name = 'runtime-proof/inputs/' + relative
            raw = committed_file(source, expected_source_commit, name)
            if len(raw) != metadata['bytes'] or sha(raw) != metadata['sha256']:
                fail('source input commitment')
            producer[name] = raw
    manifest_name = PACKAGE_PATH + 'public-package-manifest-v7.json'
    manifest_raw = committed_file(package, expected_package_commit, manifest_name)
    if sha(manifest_raw) != PACKAGE_MANIFEST_SHA:
        fail('package manifest pin')
    consumer[manifest_name] = manifest_raw
    manifest = json.loads(manifest_raw)
    policy_name = PACKAGE_PATH + 'public-policy-manifest-v7.json'
    consumer[policy_name] = committed_file(package, expected_package_commit, policy_name)
    if sha(consumer[policy_name]) != POLICY_MANIFEST_SHA:
        fail('policy manifest pin')
    folder = package / PACKAGE_PATH
    no_links(folder)
    expected_names = set(manifest['files']) | {'public-package-manifest-v7.json', 'public-policy-manifest-v7.json'}
    if {item.name for item in folder.iterdir()} != expected_names:
        fail('package input inventory')
    for relative, metadata in manifest['files'].items():
        name = PACKAGE_PATH + relative
        raw = committed_file(package, expected_package_commit, name)
        if len(raw) != metadata['bytes'] or sha(raw) != metadata['sha256']:
            fail('package input commitment')
        consumer[name] = raw
    artifact = Path(bundle).absolute()
    no_links(artifact)
    verifier = {'__file__': str(package / VERIFIER_PATH), '__name__': 'trusted_package_source_verifier'}
    exec(compile(consumer[VERIFIER_PATH], str(package / VERIFIER_PATH), 'exec'), verifier)
    try:
        verified = verifier['verify_bundle'](artifact, source, expected_commit=expected_source_commit,
                                             expected_run_id=expected_run_id,
                                             expected_contract_sha256=expected_contract_sha256)
    except (ValueError, OSError, subprocess.SubprocessError):
        fail('source handoff binding')
    return dict(status='passed', scope='source and package input commitment verification only',
                source=verified, source_input_count=len(producer),
                source_inventory_sha256=inventory_hash(producer),
                package=dict(commit_sha=expected_package_commit, manifest_sha256=PACKAGE_MANIFEST_SHA,
                             input_count=len(consumer), inventory_sha256=inventory_hash(consumer)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--trusted-source-checkout', type=Path, required=True)
    parser.add_argument('--trusted-package-checkout', type=Path, required=True)
    parser.add_argument('--expected-source-commit', required=True)
    parser.add_argument('--expected-package-commit', required=True)
    parser.add_argument('--expected-run-id', required=True)
    parser.add_argument('--expected-contract-sha256', required=True)
    args = parser.parse_args()
    try:
        result = verify_preflight(args.bundle, args.trusted_source_checkout, args.trusted_package_checkout,
                                  expected_source_commit=args.expected_source_commit,
                                  expected_package_commit=args.expected_package_commit,
                                  expected_run_id=args.expected_run_id,
                                  expected_contract_sha256=args.expected_contract_sha256)
    except PreflightError as error:
        result = dict(status='failed', error=str(error))
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        result = dict(status='failed', error='package preflight aborted')
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
