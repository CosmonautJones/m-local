"""Download an exact declared public artifact before allowing execution."""
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import hashlib
import os
import urllib.request


HOSTS = {'github.com', 'release-assets.githubusercontent.com', 'repo.maven.apache.org', 'repo1.maven.org'}


def public_url(url, initial=False):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname not in HOSTS or parts.username or parts.password or
            parts.port not in (None, 443) or parts.fragment or (initial and parts.query)):
        raise RuntimeError('Public download URL guard')
    return parts


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        public_url(new_url)
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def download(entry, destination):
    public_url(entry['url'], initial=True)
    expected_hash = entry['sha256']
    expected_bytes = entry['bytes']
    if (not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes <= 0 or
            not isinstance(expected_hash, str) or len(expected_hash) != 64 or
            any(character not in '0123456789abcdef' for character in expected_hash)):
        raise RuntimeError('Pinned download identity guard')
    destination = Path(destination)
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise RuntimeError('Fresh download path guard')
    if destination.parent.stat().st_uid != os.geteuid() or destination.parent.stat().st_mode & 0o777 != 0o700:
        raise RuntimeError('Private download directory guard')
    for parent in destination.parents:
        if parent.is_symlink():
            raise RuntimeError('Download parent path guard')
    opener = urllib.request.build_opener(PublicRedirect())
    digest = hashlib.sha256()
    received = 0
    created = False
    try:
        with opener.open(entry['url'], timeout=60) as response:
            final = public_url(response.geturl())
            if response.status != 200:
                raise RuntimeError('Download HTTP status guard')
            with destination.open('xb') as stream:
                created = True
                os.chmod(destination, 0o600)
                while chunk := response.read(65536):
                    received += len(chunk)
                    if received > expected_bytes:
                        raise RuntimeError('Download length guard')
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if received != expected_bytes or digest.hexdigest() != expected_hash:
                raise RuntimeError('Download content identity guard')
    except BaseException:
        if created:
            destination.unlink()
        raise
    return {'sha256': digest.hexdigest(), 'bytes': received, 'url': entry['url'],
            'resolved_public_path': urlunsplit((final.scheme, final.netloc, final.path, '', '')),
            'redirect_query_values_retained': False}
