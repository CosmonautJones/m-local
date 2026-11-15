import contextlib
import importlib.util
import io
import json
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('hosted_backup_destination', ROOT / 'scripts' / 'hosted-backup.py')
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

INVALID_ORIGINS = (
    'http://127.0.0.1.attacker.invalid', 'http://127.0.0.10',
    'http://127.0.0.1@attacker.invalid', 'http://localhost', 'http://[::1]',
    'http://public.example.test', 'ftp://127.0.0.1',
    'https://user:private-marker@example.test', 'https://example.test/path',
    'https://example.test//', 'https://example.test?private-marker',
    'https://example.test#private-marker', 'https://example.test?', 'https://example.test#',
    ' https://example.test', 'https://example.test ', 'https://exam\nple.test',
    'https://example.test\t', 'https://exam\x00ple.test', 'https://exam\x7fple.test',
    'https://exam\u0085ple.test', 'https://', 'https:///example.test',
    'https://example.test:', 'https://example.test:wrong', 'https://example.test:65536',
    'https://example.test:-1', 'https://example.test:443:80',
    'https://[::1', 'https://[not-ipv6]', 'https://[::1]suffix', 'https://::1',
    'https://example.test\\other', 'https://example%2etest', None, 42,
)
VALID_ORIGINS = (
    'https://host.fixture.test', 'https://host.fixture.test/',
    'https://host.fixture.test:8443/', 'https://[::1]:8443/',
    'http://127.0.0.1', 'http://127.0.0.1:8000/',
)


class HostedBackupDestinationTests(unittest.TestCase):
    def test_setup_rejects_invalid_origins_before_filesystem_writes(self):
        for url in INVALID_ORIGINS:
            with self.subTest(url=url), patch.object(Path, 'mkdir') as mkdir, \
                 patch.object(tool, '_write_secret') as write, \
                 patch.object(tool, 'TOKEN', Mock()), patch.object(tool, 'PASSPHRASE', Mock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                args = SimpleNamespace(url=url, backup_dir='/unused-fixture', keep_days=14, show_token=False)
                with self.assertRaises(tool.BackupError) as raised:
                    tool.setup(args)
                self.assertEqual(str(raised.exception), 'Pass an HTTPS origin or an HTTP origin at 127.0.0.1.')
                mkdir.assert_not_called()
                write.assert_not_called()

    def test_setup_accepts_https_and_exact_loopback_origins(self):
        for url in VALID_ORIGINS:
            with self.subTest(url=url), patch.object(Path, 'mkdir'), \
                 patch.object(tool, '_write_secret') as write, \
                 patch.object(tool, 'TOKEN', Mock()), patch.object(tool, 'PASSPHRASE', Mock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                args = SimpleNamespace(url=url, backup_dir='/unused-fixture', keep_days=14, show_token=False)
                self.assertEqual(tool.setup(args), 0)
                stored = json.loads(write.call_args_list[0].args[1])
                self.assertEqual(stored['url'], url.removesuffix('/'))

    def test_pull_rejects_invalid_saved_origins_before_token_or_network(self):
        for url in INVALID_ORIGINS:
            token = Mock()
            token.read_text.side_effect = AssertionError('Invalid origin reached token read')
            with self.subTest(url=url), patch.object(tool, '_config', return_value={'url': url}), \
                 patch.object(tool, 'TOKEN', token), patch.object(tool.urllib.request, 'Request') as request, \
                 patch.object(tool.urllib.request, 'urlopen') as open_url:
                with self.assertRaises(tool.BackupError) as raised:
                    tool.pull(None)
                self.assertEqual(str(raised.exception), 'Pass an HTTPS origin or an HTTP origin at 127.0.0.1.')
                token.read_text.assert_not_called()
                request.assert_not_called()
                open_url.assert_not_called()

    def test_pull_rejects_missing_saved_origin_before_token_read(self):
        token = Mock()
        token.read_text.side_effect = AssertionError('Missing origin reached token read')
        with patch.object(tool, '_config', return_value={}), patch.object(tool, 'TOKEN', token), \
             patch.object(tool.urllib.request, 'urlopen') as open_url:
            with self.assertRaises(tool.BackupError):
                tool.pull(None)
            token.read_text.assert_not_called()
            open_url.assert_not_called()

    def test_pull_uses_valid_origin_without_duplicate_slash(self):
        for url in VALID_ORIGINS:
            token = Mock()
            token.read_text.return_value = 'fixture-token'
            with self.subTest(url=url), patch.object(tool, '_config', return_value={'url': url}), \
                 patch.object(tool, 'TOKEN', token), \
                 patch.object(tool.urllib.request, 'urlopen', side_effect=urllib.error.URLError('fixture unavailable')) as open_url:
                with self.assertRaises(tool.BackupError):
                    tool.pull(None)
                token.read_text.assert_called_once_with()
                self.assertEqual(open_url.call_args.args[0].full_url, url.removesuffix('/') + '/function/download_backup')


if __name__ == '__main__':
    unittest.main()
