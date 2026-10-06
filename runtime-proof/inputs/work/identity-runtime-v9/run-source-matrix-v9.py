"""Persist the source-only SMTP scope using the hash-pinned v8 matrix."""
from pathlib import Path
import hashlib
import os
import stat


BASE = Path(__file__).absolute().parents[1] / 'identity-runtime-v8/run-source-matrix-v8.py'
BASE_SHA = '4d5c18547af9cbec44a712eb0b59373d11da9c7adccf0920f6459a6126e57c89'
BEFORE = "swap_max=0, private_log=str(work / 'matrix.log'))"
AFTER = "swap_max=0, actual_smtp=False, private_log=str(work / 'matrix.log'))"


def load_program(path):
    path = Path(path).absolute()
    info = path.lstat()
    if path.resolve() != path or any(item.is_symlink() for item in (path, *path.parents)) or \
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or \
            not 0 < info.st_size < 1024 ** 2 or (os.name == 'posix' and info.st_mode & 0o022):
        raise RuntimeError('v9 matrix predecessor type')
    with path.open('rb') as stream:
        raw = stream.read(1024 ** 2)
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise RuntimeError('v9 matrix predecessor hash')
    text = raw.decode('utf-8')
    if text.count(BEFORE) != 1:
        raise RuntimeError('v9 matrix receipt marker')
    return text.replace(BEFORE, AFTER)


PROGRAM = load_program(BASE)
exec(compile(PROGRAM, __file__, 'exec'), globals())
