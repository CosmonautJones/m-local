#!/usr/bin/env python3
"""Bind the corrected receipt adapters using the hash-pinned strict v8 verifier."""
from pathlib import Path
import hashlib
import os
import stat


BASE = Path(__file__).absolute().with_name('verify-source-handoff-v8.py')
BASE_SHA = 'b8c92532e99a095f40b718a4a068330def7b47b31a78f00b8c09ff981b0a04fe'
MANIFEST_SHA = '91a9b2f303a57b0178f1ff0c3b876f4d13a84913ce7270b8eb883f144056a81e'
OLD_PATHS = (
    'work/identity-runtime-v7/run-source-cold-compile-v7.py',
    'work/identity-runtime-v7/run-source-bootstrap-v7.py',
    'work/identity-runtime-v8/run-source-matrix-v8.py',
    'work/identity-runtime-v8/run-source-stage-v8.py',
)
NEW_PATHS = OLD_PATHS[:2] + (
    'work/identity-runtime-v9/run-source-matrix-v9.py',
    'work/identity-runtime-v9/run-source-stage-v9.py',
) + OLD_PATHS[2:]


def load_program(path):
    path = Path(path).absolute()
    info = path.lstat()
    if path.resolve() != path or any(item.is_symlink() for item in (path, *path.parents)) or \
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or \
            not 0 < info.st_size < 1024 ** 2 or (os.name == 'posix' and info.st_mode & 0o022):
        raise RuntimeError('v9 verifier predecessor type')
    with path.open('rb') as stream:
        raw = stream.read(1024 ** 2)
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise RuntimeError('v9 verifier predecessor hash')
    text = raw.decode('utf-8')
    paths = lambda values: 'ADAPTER_PATHS = (\n' + ''.join("    '" + value + "',\n" for value in values) + ')'
    changes = (
        ("ADAPTER_MANIFEST_SHA = 'dc8a0e3f50f01d43d0e1654e94648d581c54b064b1a9b18ce204c467a7ccb7a8'",
         "ADAPTER_MANIFEST_SHA = '" + MANIFEST_SHA + "'"),
        ("'v8-adapter-manifest.json'", "'v9-adapter-manifest.json'"),
        (paths(OLD_PATHS), paths(NEW_PATHS)),
        ("len(adapter_manifest['files']) != 4", "len(adapter_manifest['files']) != 6"),
        ("'run-source-matrix-v8'", "'run-source-matrix-v9'"),
    )
    for before, after in changes:
        if text.count(before) != 1:
            raise RuntimeError('v9 verifier adaptation marker')
        text = text.replace(before, after)
    return text


PROGRAM = load_program(BASE)
exec(compile(PROGRAM, __file__, 'exec'), globals())
