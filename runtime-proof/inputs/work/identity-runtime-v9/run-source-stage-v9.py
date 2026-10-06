"""Select the corrected matrix using the hash-pinned v8 stage controller."""
from pathlib import Path
import hashlib
import os
import stat


BASE = Path(__file__).absolute().parents[1] / 'identity-runtime-v8/run-source-stage-v8.py'
BASE_SHA = 'a19cc86d4cb6a6e8861a6065a742950d5f061771490f3bb3e8ef77c02f3d4c2f'
BEFORE = "MATRIX = 'work/identity-runtime-v8/run-source-matrix-v8.py'"
AFTER = "MATRIX = 'work/identity-runtime-v9/run-source-matrix-v9.py'"


def load_program(path):
    path = Path(path).absolute()
    info = path.lstat()
    if path.resolve() != path or any(item.is_symlink() for item in (path, *path.parents)) or \
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or \
            not 0 < info.st_size < 1024 ** 2 or (os.name == 'posix' and info.st_mode & 0o022):
        raise RuntimeError('v9 stage predecessor type')
    with path.open('rb') as stream:
        raw = stream.read(1024 ** 2)
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise RuntimeError('v9 stage predecessor hash')
    text = raw.decode('utf-8')
    if text.count(BEFORE) != 1:
        raise RuntimeError('v9 stage matrix marker')
    return text.replace(BEFORE, AFTER)


PROGRAM = load_program(BASE)
exec(compile(PROGRAM, __file__, 'exec'), globals())
