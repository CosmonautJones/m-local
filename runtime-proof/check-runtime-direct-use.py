#!/usr/bin/env python3
"""Check the predeclared Jac runtime input scope against a reviewed Git commit."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import stat
import subprocess


ROOT = Path(__file__).absolute().parents[1]
PREFLIGHT_SHA = 'd47b342bea74d64fa3575673a07b90d5595fdabe0e87a93f714cc6d7caa7c635'


def trusted_preflight():
    path = ROOT / 'runtime-proof/verify-package-preflight.py'
    if path.resolve() != path or any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('trusted preflight path')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= 1024 ** 2 or
            (os.name == 'posix' and info.st_mode & 0o022)):
        raise ValueError('trusted preflight type')
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'st_nlink')
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if any(getattr(opened, key) != getattr(info, key) for key in fields):
            raise ValueError('trusted preflight descriptor')
        raw = stream.read(1024 ** 2 + 1)
        after = os.fstat(stream.fileno())
        if len(raw) != info.st_size or any(getattr(after, key) != getattr(opened, key) for key in fields):
            raise ValueError('trusted preflight changed')
    if hashlib.sha256(raw).hexdigest() != PREFLIGHT_SHA:
        raise ValueError('trusted preflight hash')
    trusted = {'__file__': str(path), '__name__': 'trusted_runtime_direct_use'}
    exec(compile(raw, str(path), 'exec'), trusted)
    return trusted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-commit', required=True)
    args = parser.parse_args()
    try:
        trusted = trusted_preflight()
        trusted['require_pattern'](args.expected_commit, r'[0-9a-f]{40}', 'direct-use commit format')
        trusted['committed_file'](ROOT, args.expected_commit, 'runtime-proof/check-runtime-direct-use.py')
        result = trusted['verify_direct_use_inputs'](ROOT, args.expected_commit)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        result = dict(status='failed', error='runtime direct-use input check failed')
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['status'] == 'declaration_verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
