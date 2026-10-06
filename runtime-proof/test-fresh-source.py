import ast
import hashlib
import json
import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath
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

    def test_extracted_postgres_root_is_readable_by_restricted_process(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            workspace = Path(directory)
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode='w:xz') as archive:
                entry = tarfile.TarInfo('bin')
                entry.type, entry.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(entry)
                for name in ['postgres', 'pg_ctl']:
                    entry = tarfile.TarInfo('bin/' + name)
                    entry.size, entry.mode = 1, 0o755
                    archive.addfile(entry, io.BytesIO(b'x'))
            jar = workspace / 'postgres.jar'
            with zipfile.ZipFile(jar, 'w') as archive:
                archive.writestr('postgres.txz', payload.getvalue())

            def fail(label):
                raise RuntimeError(label)

            extract = runner_function('safe_extract_jar', {'Path': Path, 'PurePosixPath': PurePosixPath,
                'io': io, 'os': os, 'shutil': shutil, 'stat': stat, 'tarfile': tarfile, 'zipfile': zipfile, 'fail': fail})
            modes = []
            original_chmod = Path.chmod

            def chmod(path, mode, *args, **kwargs):
                modes.append((path, mode))
                return original_chmod(path, mode, *args, **kwargs)

            target = workspace / 'runtime/postgres'
            with patch.object(Path, 'chmod', chmod):
                self.assertEqual(extract(jar, target), target)
            self.assertIn((target, 0o755), modes)
            if os.name == 'posix':
                self.assertEqual(target.stat().st_mode & 0o777, 0o755)

    def test_patch_apply_reads_verified_task_copies(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            workspace = Path(directory)
            task, image = workspace / 'task', workspace / 'image'
            image.mkdir()
            copies = [task / 'outputs/identity-bootstrap-source-v2/source-inputs/runtime.patch',
                      task / 'work/identity-runtime-v3/runtime.patch']
            for path, value in zip(copies, [b'old patch', b'current patch']):
                path.parent.mkdir(parents=True)
                path.write_bytes(value)
            applied = []
            configured = []
            stop_after_apply = True

            class AppliedBoth(Exception):
                pass

            def scoped_command(label, command, **kwargs):
                if command[1] == 'clone':
                    Path(command[-1]).mkdir()
                if command[-1] == 'HEAD':
                    log = workspace / 'revision.log'
                    log.write_text('base\n')
                    return {'log_path': str(log)}
                if 'config' in command:
                    configured.append((Path(command[2]).name, command[4:]))
                if 'apply' in command:
                    self.assertEqual(configured, [
                        ('identity-type-source-old-v7', ['core.abbrev', '7']),
                        ('identity-type-source-v3-v7', ['core.abbrev', '7'])])
                    self.assertEqual(Path(command[-1]), copies[len(applied)])
                    applied.append(Path(command[-1]))
                    if len(applied) == 2 and stop_after_apply:
                        raise AppliedBoth()

            namespace = {'Path': Path, 'E_ROOT': image, 'CANONICAL_TASK': task,
                'INPUTS': workspace / 'unavailable-checkout', 'os': SimpleNamespace(chown=lambda *args: None),
                'minimal_environment': lambda: {}, 'scoped_command': scoped_command,
                'JAC_REPOSITORY': 'public-fixture', 'JAC_BASE': 'base',
                'PATCH_BEFORE': hashlib.sha256(copies[0].read_bytes()).hexdigest(),
                'PATCH_AFTER': hashlib.sha256(copies[1].read_bytes()).hexdigest(),
                'digest': lambda path: hashlib.sha256(path.read_bytes()).hexdigest()}
            prepare = runner_function('prepare_forks', namespace)
            with self.assertRaises(AppliedBoth):
                prepare(workspace, {}, workspace / 'private.log')
            self.assertEqual(applied, copies)
            stop_after_apply = False
            applied.clear()
            configured.clear()
            namespace.update(chown_tree=lambda path: None,
                git_diff_bytes=lambda *args: b'index 123456789..abcdefghi 100644\nprivate fixture body\n',
                hashlib=hashlib, fail=lambda label: self.fail(label))
            namespace['E_ROOT'] = image / 'second'
            namespace['E_ROOT'].mkdir()
            with self.assertRaisesRegex(AssertionError, r'source fork patch diff guard old .* index_widths=9$') as error:
                prepare(workspace, {}, workspace / 'private.log')
            self.assertNotIn('private fixture body', str(error.exception))

    def test_pinned_patch_fingerprints_require_seven_digit_git_format(self):
        inputs = ROOT / 'inputs'
        manifest = json.loads((inputs / 'public-source-manifest.json').read_text())
        current = inputs / 'work/identity-runtime-v3/runtime.patch'
        old = inputs / 'outputs/identity-bootstrap-source-v2/source-inputs/runtime.patch'
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            workspace = Path(directory).resolve()
            self.assertTrue(workspace.is_relative_to(ROOT.resolve()))

            def git(*args):
                return subprocess.check_output(['git', '-c', 'core.autocrlf=false', '-c', 'core.safecrlf=false',
                    '-c', 'commit.gpgsign=false', '-c', 'user.name=Runtime proof fixture',
                    '-c', 'user.email=fixture@example.invalid', *args], cwd=workspace, stderr=subprocess.PIPE)

            git('init', '--quiet')
            for relative in manifest['files']:
                if relative.startswith('source/jac/'):
                    destination = workspace / relative[len('source/'):]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(inputs / relative, destination)
            git('apply', '-R', '--binary', str(current))
            git('add', '--all')
            git('commit', '--quiet', '-m', 'Tiny public-source base fixture')
            for source in [old, current]:
                git('reset', '--hard', '--quiet', 'HEAD')
                git('apply', '--binary', str(source))
                git('config', 'core.abbrev', '9')
                longer = git('diff', '--binary')
                self.assertNotEqual(longer, source.read_bytes())
                if source == old:
                    self.assertEqual(hashlib.sha256(longer).hexdigest(),
                        '89065f64af2e6489f4ed957ea68cb6606d9c29d845af05c6e38bf8b82afdbf7d')
                git('config', 'core.abbrev', '7')
                self.assertEqual(git('diff', '--binary'), source.read_bytes())

    def test_fresh_typeshed_completes_matching_metadata_without_replacing_conflicts(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            workspace = Path(directory).resolve()
            self.assertTrue(workspace.is_relative_to(ROOT.resolve()))
            official = workspace / 'official'
            site = official / 'cache/test/site'
            typeshed = site / 'jaclang/vendor/typeshed'
            typeshed.mkdir(parents=True)
            metadata = ['LICENSE', 'PIN', 'PROVENANCE.md', 'TARBALL_SHA256']
            for name in metadata:
                (typeshed / name).write_bytes(('fixture ' + name).encode())
            (typeshed / 'stdlib').mkdir()
            for index in range(745):
                (typeshed / 'stdlib' / ('stub' + str(index) + '.pyi')).write_bytes(b'fixture')
            shim = site / 'jaclang/compiler/backends/native/llvm/libjacllvm.so'
            shim.parent.mkdir(parents=True)
            shim.write_bytes(b'fixture shim')
            current, old = workspace / 'current', workspace / 'old'
            for fork in [current, old]:
                destination = fork / 'jac/jaclang/vendor/typeshed'
                destination.mkdir(parents=True)
                for name in metadata:
                    shutil.copyfile(typeshed / name, destination / name)

            def fail(label):
                raise RuntimeError(label)

            namespace = {'Path': Path, 'os': SimpleNamespace(chown=lambda *args: None),
                'shutil': shutil, 'json': json, 'hashlib': hashlib, 'fail': fail,
                'scoped_command': lambda *args, **kwargs: None,
                'digest': lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                'SHIM_SHA': hashlib.sha256(shim.read_bytes()).hexdigest()}
            inspect = runner_function('inventory', namespace)
            expected = inspect(typeshed)
            self.assertEqual(len(expected), 749)
            namespace['TYPESHED_SHA'] = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
            materialize = runner_function('materialize_shim_typeshed', namespace)
            result = materialize(current, old, official, workspace)
            self.assertEqual(result['typeshed_files'], 749)
            for fork in [current, old]:
                self.assertEqual(inspect(fork / 'jac/jaclang/vendor/typeshed'), expected)
            destination = current / 'jac/jaclang/vendor/typeshed'
            for name in metadata:
                self.assertEqual((destination / name).read_bytes(), (typeshed / name).read_bytes())
            for name in ['PIN', 'extra-private-input']:
                with self.subTest(fault=name):
                    (official / 'cache/source-materialize.jac').unlink()
                    target = destination / name
                    target.write_bytes(b'conflicting fixture')
                    with self.assertRaisesRegex(RuntimeError, 'fork typeshed identity guard'):
                        materialize(current, old, official, workspace)
                    self.assertEqual(target.read_bytes(), b'conflicting fixture')
                    if name == 'PIN':
                        target.write_bytes((typeshed / name).read_bytes())

    def test_dependency_target_diagnostic_stays_bound_to_owned_runtime(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            workspace = Path(directory).resolve()
            image, runtime = workspace / 'image', workspace / 'official'
            image.mkdir()
            target = runtime / 'runtime/jacpython'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'fixture interpreter')
            target.chmod(0o755)
            python = image / 'dependency-candidate-v7/.jac/venv/bin/python'

            def copy_app_tree(source, destination):
                python.parent.mkdir(parents=True)
                (python.parent.parent / 'pyvenv.cfg').write_text('fixture')
                if os.name == 'posix':
                    python.symlink_to(target)
                else:
                    python.write_bytes(b'fixture interpreter')

            def fail(label):
                raise RuntimeError(label)

            original_stat, original_resolve, original_symlink = Path.stat, Path.resolve, Path.is_symlink

            def metadata(path, *args, **kwargs):
                result = original_stat(path, *args, **kwargs)
                if os.name != 'posix' and path in (python, target):
                    return SimpleNamespace(st_mode=result.st_mode | 0o111)
                return result

            namespace = {'Path': Path, 'E_ROOT': image, 'os': SimpleNamespace(chown=lambda *args: None),
                'copy_app_tree': copy_app_tree, 'chown_tree': lambda path: None,
                'scoped_command': lambda *args, **kwargs: {}, 'fail': fail,
                'digest': lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()}
            prime = runner_function('dependency_priming', namespace)
            with patch.object(Path, 'stat', metadata), \
                    patch.object(Path, 'resolve', lambda path, *args, **kwargs: target if path == python else original_resolve(path, *args, **kwargs)), \
                    patch.object(Path, 'is_symlink', lambda path: path == python or original_symlink(path)):
                with self.assertRaisesRegex(RuntimeError,
                        '^declared dependency target official-runtime sha256=' + hashlib.sha256(target.read_bytes()).hexdigest() + '$'):
                    prime(workspace / 'app', runtime, workspace, workspace / 'private.log')
                namespace['E_ROOT'] = image / 'outside-test'
                namespace['E_ROOT'].mkdir()
                python = namespace['E_ROOT'] / 'dependency-candidate-v7/.jac/venv/bin/python'
                target = workspace / 'outside-python'
                target.write_bytes(b'private fixture content')
                target.chmod(0o755)
                namespace['digest'] = lambda path: self.fail('outside interpreter bytes must not be read')
                with self.assertRaisesRegex(RuntimeError, '^declared dependency target outside-approved-roots$'):
                    prime(workspace / 'app', runtime, workspace, workspace / 'private.log')

    def test_bundled_dependency_interpreter_requires_pinned_payload_and_target(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            workspace = Path(directory).resolve()
            image, runtime = workspace / 'image', workspace / 'official'
            image.mkdir()
            cache = image / 'dependency-cache-v7'
            payload = b'fixture runtime payload'
            payload_hash = hashlib.sha256(payload).hexdigest()
            trailer = b'JACBIN01' + len(payload).to_bytes(8, 'little') + payload_hash.encode()
            binary = b'fixture launcher' + payload + trailer
            jac = runtime / 'runtime/jac'
            jac.parent.mkdir(parents=True)
            jac.write_bytes(binary)
            target = cache / 'rt' / payload_hash[:16] / 'python/bin/python3.14'
            marker = target.parents[2] / '.ok'
            python = image / 'dependency-candidate-v7/.jac/venv/bin/python'
            pillow_calls = []

            def scoped_command(label, command, **kwargs):
                if label == 'declared dependency priming':
                    target.parent.mkdir(parents=True)
                    target.write_bytes(b'fixture bundled interpreter')
                    target.chmod(0o755)
                    marker.write_bytes(b'')
                    python.parent.mkdir(parents=True)
                    (python.parent.parent / 'pyvenv.cfg').write_text('fixture')
                    if os.name == 'posix':
                        python.symlink_to(target)
                    else:
                        python.write_bytes(b'fixture symlink')
                else:
                    self.assertEqual(label, 'Pillow dependency guard')
                    pillow_calls.append(command)
                return {'log_path': str(workspace / 'private.log')}

            def fail(label):
                raise RuntimeError(label)

            original_stat, original_resolve, original_symlink = Path.stat, Path.resolve, Path.is_symlink
            metadata_overrides, symlink_paths = {}, set()

            def metadata(path, *args, **kwargs):
                result = original_stat(path, *args, **kwargs)
                if path == python or path.is_relative_to(cache):
                    mode = (0o40700 if path == cache else 0o40755 if stat.S_ISDIR(result.st_mode)
                            else 0o100755 if path in (python, target) else 0o100644)
                    values = dict(st_mode=mode, st_uid=65534, st_size=result.st_size)
                    values.update(metadata_overrides.get(path, {}))
                    return SimpleNamespace(**values)
                return result

            namespace = {'Path': Path, 'E_ROOT': image, 'os': SimpleNamespace(chown=lambda *args: None),
                'copy_app_tree': lambda *args: None, 'chown_tree': lambda path: None,
                'scoped_command': scoped_command, 'fail': fail, 'stat': stat,
                'digest': lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                'JAC_SHA': hashlib.sha256(binary).hexdigest(),
                'BUNDLED_PYTHON_SHA': hashlib.sha256(b'fixture bundled interpreter').hexdigest()}
            namespace['dependency_interpreter_provenance'] = lambda *args: runner_function('dependency_interpreter_provenance', namespace)(*args)
            prime = runner_function('dependency_priming', namespace)
            with patch.object(Path, 'stat', metadata), \
                    patch.object(Path, 'resolve', lambda path, *args, **kwargs: target if path == python else original_resolve(path, *args, **kwargs)), \
                    patch.object(Path, 'is_symlink', lambda path: path == python or path in symlink_paths or original_symlink(path)):
                result = prime(workspace / 'app', runtime, workspace, workspace / 'private.log')
                self.assertEqual(result['interpreter']['interpreter_target_class'], 'bundled_runtime_cache')
                self.assertEqual(result['interpreter']['interpreter_target_relative'], target.relative_to(cache).as_posix())
                self.assertEqual(len(pillow_calls), 1)
                check = runner_function('dependency_interpreter_provenance', namespace)
                target.write_bytes(b'tampered interpreter')
                with self.assertRaisesRegex(RuntimeError, 'bundled dependency interpreter'):
                    check(runtime, cache, target)
                target.write_bytes(b'fixture bundled interpreter')
                marker.unlink()
                with self.assertRaisesRegex(RuntimeError, 'bundled dependency interpreter'):
                    check(runtime, cache, target)
                marker.write_bytes(b'')
                with self.assertRaisesRegex(RuntimeError, 'bundled dependency interpreter'):
                    check(runtime, cache, workspace / 'outside-interpreter')
                jac.write_bytes(b'tampered launcher')
                with self.assertRaisesRegex(RuntimeError, 'bundled dependency interpreter'):
                    check(runtime, cache, target)
                jac.write_bytes(binary)
                for path, fields in [(cache, {'st_mode': 0o40755}), (target.parent, {'st_mode': 0o40777}),
                                     (target, {'st_mode': 0o100644}), (target, {'st_uid': 0}),
                                     (marker, {'st_mode': 0o100666}), (marker, {'st_mode': 0o100755}),
                                     (marker, {'st_uid': 0})]:
                    with self.subTest(path=path.name, fields=fields):
                        metadata_overrides[path] = fields
                        with self.assertRaisesRegex(RuntimeError, 'bundled dependency interpreter'):
                            check(runtime, cache, target)
                        metadata_overrides.clear()
                for path in [cache / 'rt', target, marker]:
                    with self.subTest(symlink=path.name):
                        symlink_paths.add(path)
                        with self.assertRaisesRegex(RuntimeError, 'bundled dependency interpreter'):
                            check(runtime, cache, target)
                        symlink_paths.clear()
                overlay = b'fixture overlay'
                overlay_binary = binary + overlay + b'JABOVL01' + len(overlay).to_bytes(8, 'little') + hashlib.sha256(overlay).hexdigest().encode()
                jac.write_bytes(overlay_binary)
                namespace['JAC_SHA'] = hashlib.sha256(overlay_binary).hexdigest()
                self.assertEqual(check(runtime, cache, target)['runtime_payload_sha256'], payload_hash)
                for malformed in [b'short', b'UNKNOWN1' + trailer[8:],
                                  b'JACBIN01' + (0).to_bytes(8, 'little') + trailer[16:],
                                  b'JACBIN01' + (9999).to_bytes(8, 'little') + trailer[16:],
                                  b'JACBIN01' + trailer[8:16] + b'z' * 64,
                                  b'JABOVL01' + (1).to_bytes(8, 'little') + trailer[16:]]:
                    with self.subTest(trailer=malformed[:8]):
                        jac.write_bytes(malformed)
                        namespace['JAC_SHA'] = hashlib.sha256(malformed).hexdigest()
                        with self.assertRaisesRegex(RuntimeError, 'bundled dependency interpreter trailer'):
                            check(runtime, cache, target)


if __name__ == '__main__':
    unittest.main()
