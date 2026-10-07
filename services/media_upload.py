import base64
import binascii
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 1024 * 1024


def require_actor(actor: str) -> str:
    if not actor:
        raise ValueError('Sign in with a business account to upload a photo.')
    return actor


def photo_directory() -> Path:
    # Mount assets/photos on persistent storage when deploying the single-host app.
    directory = Path(__file__).resolve().parents[1] / 'assets' / 'photos'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def photo_registry() -> sqlite3.Connection:
    private = Path(os.environ.get('MLOCAL_ONBOARDING_DIR', str(Path(__file__).resolve().parents[1] / '.jac/onboarding')))
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = private / 'photo-ownership.sqlite3'
    db = sqlite3.connect(path)
    os.chmod(path, 0o600)
    db.execute('CREATE TABLE IF NOT EXISTS photos (filename TEXT PRIMARY KEY, actor TEXT NOT NULL, digest TEXT NOT NULL, bytes INTEGER NOT NULL, created REAL NOT NULL, UNIQUE(actor,digest))')
    return db


def owned_photo(value: str, actor: str) -> str:
    require_actor(actor)
    if not re.fullmatch(r'/static/photos/[a-f0-9]{32}\.jpg', value):
        raise ValueError('Choose a photo uploaded by this business, or use a public website photo.')
    path = photo_directory() / value.rsplit('/', 1)[-1]
    if path.is_symlink() or not path.is_file():
        raise ValueError('That uploaded photo is unavailable. Upload it again.')
    db = photo_registry()
    try:
        row = db.execute('SELECT actor FROM photos WHERE filename=?', (path.name,)).fetchone()
        if not row or row[0] != actor:
            raise ValueError('Choose a photo uploaded by this business.')
    finally:
        db.close()
    return value


def save_photo(payload: str, actor: str) -> str:
    require_actor(actor)
    if not isinstance(payload, str) or not payload.startswith('data:image/jpeg;base64,') or len(payload) > (MAX_BYTES * 4 // 3 + 28):
        raise ValueError('Choose a JPG, PNG or WebP photo. The upload must be under 1 MB after resizing.')
    try:
        data = base64.b64decode(payload.split(',', 1)[1], validate=True)
        if not data or len(data) > MAX_BYTES:
            raise ValueError('This photo is too large. Choose a smaller photo.')
        return save_image_bytes(data, actor, ('JPEG',))
    except binascii.Error:
        raise ValueError('This photo could not be read. Try a JPG, PNG or WebP photo.') from None


def save_image_bytes(data: bytes, actor: str, formats: tuple[str, ...] = ('JPEG', 'PNG', 'WEBP')) -> str:
    require_actor(actor)
    if not data or len(data) > MAX_BYTES:
        raise ValueError('This photo is too large. Upload a smaller photo.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in formats or image.width * image.height > 12000000 or min(image.size) < 16:
                    raise ValueError('Choose a regular photo, at least 16 pixels wide and tall.')
                image.load()
                normalized = ImageOps.exif_transpose(image).convert('RGB')
                normalized.thumbnail((1600, 1600))
                # Rebuild pixels: discard EXIF, GPS, ICC and trailing payloads.
                clean = Image.new('RGB', normalized.size)
                clean.paste(normalized)
                output = BytesIO()
                clean.save(output, format='JPEG', quality=82, optimize=True)
                image_bytes = output.getvalue()
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('This photo could not be read. Try a JPG, PNG or WebP photo.') from None
    directory = photo_directory()
    digest = hashlib.sha256(image_bytes).hexdigest()
    db = photo_registry()
    try:
        with db:
            same = db.execute('SELECT filename FROM photos WHERE actor=? AND digest=?', (actor, digest)).fetchone()
            if same and (directory / same[0]).is_file() and not (directory / same[0]).is_symlink():
                return '/static/photos/' + same[0]
            recent = db.execute('SELECT COUNT(*) FROM photos WHERE actor=? AND created>?', (actor,time.time()-86400)).fetchone()[0]
            total = db.execute('SELECT COALESCE(SUM(bytes),0) FROM photos WHERE actor=?', (actor,)).fetchone()[0]
            if recent >= 30 or total + len(image_bytes) > 32 * 1024 * 1024:
                raise ValueError('This business has reached its photo upload limit. Contact the host for help.')
            if sum(path.stat().st_size for path in directory.glob('*.jpg')) + len(image_bytes) > 512 * 1024 * 1024:
                raise ValueError('Photo storage is full. Contact the host for help.')
            filename = same[0] if same else secrets.token_hex(16) + '.jpg'
            fd = os.open(directory / filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(image_bytes);stream.flush();os.fsync(stream.fileno())
                db.execute('INSERT OR REPLACE INTO photos VALUES (?,?,?,?,?)', (filename,actor,digest,len(image_bytes),time.time()))
            except BaseException:
                (directory / filename).unlink(missing_ok=True)
                raise
    finally:
        db.close()
    return '/static/photos/' + filename
