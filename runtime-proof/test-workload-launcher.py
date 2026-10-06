"""Pure and root-identity tests for the bound workload launcher."""

from pathlib import Path
import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / 'bind-fresh-workload-launcher.py'
SOURCE = ROOT / 'kali-build-resources-v2.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class PureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control = load(CONTROL, 'workload_launcher_control')
        cls.raw = SOURCE.read_bytes()
        cls.original_hash = sha(cls.raw)

    def test_frozen_source_adapts_only_launcher_boundary_and_identity_guard(self):
        self.assertEqual(self.original_hash, self.control.SOURCE_SHA256)
        self.assertEqual(self.control.adapt_launch_source(self.raw),
                         self.control.adapt_launch_source(self.raw))
        adapted = self.control.adapt_launch_source(self.raw)
        tree = ast.parse(adapted.decode('utf-8'))
        self.assertEqual(len(tree.body), 1)
        self.assertIsInstance(tree.body[0], ast.FunctionDef)
        self.assertEqual(tree.body[0].name, 'launch_scope')
        self.assertNotIn('/usr/sbin/runuser', adapted.decode('utf-8'))
        self.assertIn('/usr/bin/setpriv', adapted.decode('utf-8'))
        self.assertIn(self.control.IDENTITY_BOOTSTRAP_FRAGMENT, adapted.decode('utf-8'))
        self.assertIn('os.getuid()==65534', adapted.decode('utf-8'))
        self.assertIn('os.geteuid()==65534', adapted.decode('utf-8'))
        self.assertIn('os.getgid()==65534', adapted.decode('utf-8'))
        self.assertIn('os.getegid()==65534', adapted.decode('utf-8'))
        self.assertIn('os.getgroups()==[]', adapted.decode('utf-8'))
        self.assertIn('/usr/sbin/runuser', self.raw.decode('utf-8'))

    def test_adaptation_rejects_tampered_source_and_missing_fixed_markers(self):
        tampered = self.raw[:-1] + bytes([self.raw[-1] ^ 1])
        with self.assertRaises(ValueError):
            self.control.adapt_launch_source(tampered)
        malformed = b'not python'
        with patch.object(self.control, 'SOURCE_SHA256', sha(malformed)):
            with self.assertRaises(ValueError):
                self.control.adapt_launch_source(malformed)
        missing_runuser = self.raw.replace(b"'/usr/sbin/runuser', '-u', 'nobody', '--'", b"'missing-runuser'", 1)
        with patch.object(self.control, 'SOURCE_SHA256', sha(missing_runuser)):
            with self.assertRaises(ValueError):
                self.control.adapt_launch_source(missing_runuser)
        missing_bootstrap = self.raw.replace(b'ready.unlink(); os.execvpe(', b'bootstrap-invalid(', 1)
        with patch.object(self.control, 'SOURCE_SHA256', sha(missing_bootstrap)):
            with self.assertRaises(ValueError):
                self.control.adapt_launch_source(missing_bootstrap)
        duplicate_runuser = self.raw.replace(b"'/usr/sbin/runuser', '-u', 'nobody', '--'",
                                              b"'/usr/sbin/runuser', '-u', 'nobody', '--', '/usr/sbin/runuser', '-u', 'nobody', '--'", 1)
        with patch.object(self.control, 'SOURCE_SHA256', sha(duplicate_runuser)):
            with self.assertRaises(ValueError):
                self.control.adapt_launch_source(duplicate_runuser)

    def binding(self, raw=None, helper=None, *, resource_error=None):
        raw = self.raw if raw is None else raw
        events = []

        def checked_checkout(checkout, commit):
            events.append(('checked_checkout', checkout, commit))

        def committed_file(checkout, commit, relative):
            events.append(('committed_file', relative))
            return raw

        def resource_helper():
            events.append(('resource_helper',))
            if resource_error is not None:
                raise resource_error
            return helper

        preflight = {'checked_checkout': checked_checkout, 'committed_file': committed_file}
        runner = {'resource_helper': resource_helper}
        return preflight, runner, events

    @staticmethod
    def helper_namespace():
        return {
            'launch_scope': lambda *args, **kwargs: None,
            'sample_scope': lambda *args, **kwargs: None,
            'stop_scope': lambda *args, **kwargs: None,
            'e_root': Path('/var/tmp/fake-e-root'),
        }

    def test_bind_launcher_validates_before_mutating_live_resource_helper(self):
        helper = self.helper_namespace()
        original = dict(helper)
        preflight, runner, events = self.binding(helper=helper)
        result = self.control.bind_launcher(preflight, runner, 'a' * 40)
        self.assertEqual(result['status'], 'prepared_not_executed')
        self.assertIs(result['executed'], False)
        self.assertEqual(result['source_helper_sha256'], self.control.SOURCE_SHA256)
        self.assertEqual(result['uid'], 65534)
        self.assertEqual(result['gid'], 65534)
        self.assertEqual(result['supplementary_groups'], [])
        self.assertIsNot(helper['sample_scope'], None)
        self.assertIsNot(helper['stop_scope'], None)
        self.assertIs(helper['sample_scope'], original['sample_scope'])
        self.assertIs(helper['stop_scope'], original['stop_scope'])
        self.assertIs(helper['e_root'], original['e_root'])
        self.assertIsNot(helper['launch_scope'], original['launch_scope'])
        self.assertIs(helper['launch_scope'].__globals__['sample_scope'], helper['sample_scope'])
        self.assertEqual(events[0][0], 'checked_checkout')
        self.assertEqual(events[1][0], 'committed_file')
        self.assertEqual(events[2], ('resource_helper',))

    def test_bind_launcher_rejects_commit_source_and_helper_failures_without_mutation(self):
        for expected_commit in ('bad', 'a' * 39, 'A' * 40):
            helper = self.helper_namespace()
            original = dict(helper)
            preflight, runner, _events = self.binding(helper=helper)
            with self.subTest(case='commit ' + expected_commit), self.assertRaises(ValueError):
                self.control.bind_launcher(preflight, runner, expected_commit)
            self.assertEqual(helper, original)

        helper = self.helper_namespace()
        original = dict(helper)
        preflight, runner, events = self.binding(raw=self.raw + b'\n', helper=helper)
        with self.assertRaises(ValueError):
            self.control.bind_launcher(preflight, runner, 'a' * 40)
        self.assertEqual(helper, original)
        self.assertNotIn(('resource_helper',), events)

        for missing in ('launch_scope', 'sample_scope', 'stop_scope', 'e_root'):
            helper = self.helper_namespace()
            helper.pop(missing)
            original = dict(helper)
            preflight, runner, _events = self.binding(helper=helper)
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                self.control.bind_launcher(preflight, runner, 'a' * 40)
            self.assertEqual(helper, original)

        helper = self.helper_namespace()
        original = dict(helper)
        preflight, runner, _events = self.binding(helper=helper, resource_error=RuntimeError('no helper'))
        with self.assertRaises(ValueError):
            self.control.bind_launcher(preflight, runner, 'a' * 40)
        self.assertEqual(helper, original)


class LinuxRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'posix' or os.geteuid() != 0:
            raise RuntimeError('LinuxRootTests requires a root Linux runner')
        cls.control = load(CONTROL, 'workload_launcher_root_control')

    def test_exact_adapted_setpriv_prefix_reports_dropped_identity(self):
        command = list(self.control.NEW_ARGV_PREFIX) + [sys.executable, '-c',
            'import json,os; print(json.dumps({"uid":os.getuid(),"gid":os.getgid(),'
            '"euid":os.geteuid(),"egid":os.getegid(),"groups":os.getgroups()}))']
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        identity = json.loads(completed.stdout)
        self.assertEqual(identity, {'uid': 65534, 'gid': 65534, 'euid': 65534, 'egid': 65534, 'groups': []})


if __name__ == '__main__':
    unittest.main()
