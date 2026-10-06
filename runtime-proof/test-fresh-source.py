import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent


def runner_function(name, namespace):
    tree = ast.parse((ROOT / 'run-fresh-source.py').read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / 'run-fresh-source.py'), 'exec'), namespace)
    return namespace[name]


class FreshSourceTests(unittest.TestCase):
    def test_source_fork_diffs_have_separate_outputs(self):
        values = {'old-fork': b'old patch\n', 'current-fork': b'current patch\n'}
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            workspace = Path(directory)

            def scoped_command(label, command, *, cwd, environment, workspace, timeout):
                self.assertEqual(command, ['/usr/bin/git', 'diff', '--binary'])
                self.assertEqual(timeout, 60)
                log = workspace / (label.replace(' ', '-') + '-scope.log')
                with log.open('ab') as stream:
                    stream.write(values[cwd.name])
                return {'log_path': str(log)}

            read_diff = runner_function('git_diff_bytes', {'Path': Path, 'scoped_command': scoped_command,
                                                         'minimal_environment': lambda: {}})
            self.assertEqual(read_diff(workspace / 'old-fork', workspace), values['old-fork'])
            self.assertEqual(read_diff(workspace / 'current-fork', workspace), values['current-fork'])

    def mount_register(self, new_mounts, *, wrong_backing=None, symlink=None):
        root = Path('/var/tmp/owned-image')
        owned = set()

        def fail(label):
            raise RuntimeError(label)

        def metadata(path):
            inode = 1 if path == root else sum(path.name.encode())
            if path == wrong_backing:
                inode += 1
            return SimpleNamespace(st_uid=65534, st_mode=0o40700, st_dev=42, st_ino=inode)

        namespace = {'Path': Path, 'E_ROOT': root, 'OWNED_MOUNTS': owned, 'fail': fail,
                     'mounts': lambda: set(new_mounts), 'is_mount': lambda path: path == root or path in new_mounts}
        register = runner_function('register_stage_mounts', namespace)
        patches = [patch.object(Path, 'is_symlink', lambda path: path == symlink),
                   patch.object(Path, 'resolve', lambda path: path),
                   patch.object(Path, 'is_absolute', lambda path: path.as_posix().startswith('/')),
                   patch.object(Path, 'stat', metadata)]
        return root, owned, register, patches

    def test_cold_stage_retains_only_three_receipted_mounts(self):
        workspace = Path('/var/tmp/m-local-identity-type-compile-v7-123')
        phases = [{'name': name, 'workspace': '/var/tmp/m-local-identity-type-' + name + '-v7-123'}
                  for name in ['before', 'after']]
        expected = {workspace, *(Path(row['workspace']) for row in phases)}
        root, owned, register, patches = self.mount_register(expected)
        with patches[0], patches[1], patches[2], patches[3]:
            register('cold-compile', set(), {'workspace': str(workspace), 'phases': phases})
        self.assertEqual(owned, expected)

    def test_unknown_mount_is_never_adopted(self):
        workspace = Path('/var/tmp/m-local-identity-bootstrap-proof-v4-123')
        unknown = Path('/var/tmp/m-local-identity-bootstrap-proof-v4-unreported')
        root, owned, register, patches = self.mount_register({workspace, unknown})
        with self.assertRaisesRegex(RuntimeError, 'unidentified mounts'):
            register('bootstrap', set(), {'workspace': str(workspace)})
        self.assertEqual(owned, set())

    def test_replaced_backing_or_symlink_is_never_adopted(self):
        workspace = Path('/var/tmp/m-local-identity-bootstrap-proof-v4-123')
        backing = Path('/var/tmp/owned-image') / workspace.name
        for fault in [{'wrong_backing': backing}, {'symlink': workspace}]:
            with self.subTest(fault=fault):
                root, owned, register, patches = self.mount_register({workspace}, **fault)
                with patches[0], patches[1], patches[2], patches[3]:
                    with self.assertRaises(RuntimeError):
                        register('bootstrap', set(), {'workspace': str(workspace)})
                self.assertEqual(owned, set())

    def test_download_failure_reports_type_without_private_message(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            workspace = Path(directory)
            helper = workspace / 'private-helper.py'
            helper.write_text("raise PermissionError(13, 'private fixture address')\n")
            output = workspace / 'pinned-download-jac-scope.log'

            def fail(label):
                raise RuntimeError(label)

            def scoped_command(label, command, *, cwd, environment, workspace, timeout):
                result = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                output.write_bytes(result.stdout)
                if result.returncode:
                    fail(label + ' failed')
                return {'log_path': str(output)}

            download = runner_function('pinned_download', {'Path': Path, 'json': json, 'sys': sys,
                'DOWNLOAD_HELPER': workspace / 'unavailable-checkout' / helper.name,
                'scoped_command': scoped_command, 'minimal_environment': lambda: {},
                'fail': fail})
            with self.assertRaisesRegex(RuntimeError, '^pinned download jac PermissionError$'):
                download('jac', {}, workspace / 'jac.bin', workspace)
            self.assertEqual(json.loads(output.read_text()), {'failure_type': 'PermissionError', 'http_status': None})
            self.assertNotIn('private fixture address', output.read_text())


if __name__ == '__main__':
    unittest.main()
