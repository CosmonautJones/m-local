"""Prepare the committed browser-test dependencies on live private storage."""
from pathlib import Path
import ast
import hashlib
import importlib.util
import json
import os
import re
import stat
import time


ROOT = Path(__file__).absolute().parents[1]
GENERATOR = 'runtime-proof/generate-ui-dependency-lock.py'
GENERATOR_SHA = 'ca736a8bdf433efd8e5c49bad022c7da5d6598b87beabfd9e42e1c2215f649be'
NODE_CONTROL = 'runtime-proof/run-fresh-node-client-control.py'
NODE_CONTROL_SHA = '79097e21e7f8f1647fa6984b85903d470824cb6f240bb0b82d1e8c435dfa15f5'
INPUT_DIRECTORY = 'runtime-proof/ui-dependency-inputs/v1/'
INPUTS = {
    'package.json': (128, 'f1e64f1c622aecd2ef34d348bb871f272c5ad8688e22a43c52d01bb339b2429c'),
    'package-lock.json': (17873, '0c775bf70def454618101b2d18ac8818beb6fbbf8245867adf5e38a65630567d'),
    'dependency-inputs.json': (17424, '03ff15b78906b2271a8dabc25a2c1a0cab40374ce0d7914b7f843811c95b37b5'),
}
PREFIX = 'm-local-ui-dependency-control-v1-'
SCHEMA = 'm-local-prepared-ui-dependencies-v1'


def fail(label):
    raise ValueError(label)


def load_inputs(preflight, commit):
    preflight['checked_checkout'](ROOT, commit)
    code = {}
    for relative, pin in ((GENERATOR, GENERATOR_SHA), (NODE_CONTROL, NODE_CONTROL_SHA)):
        raw = preflight['committed_file'](ROOT, commit, relative)
        if hashlib.sha256(raw).hexdigest() != pin:
            fail('UI dependency code pin')
        code[relative] = raw
    files = {}
    for name, (length, pin) in INPUTS.items():
        raw = preflight['committed_file'](ROOT, commit, INPUT_DIRECTORY + name)
        if len(raw) != length or hashlib.sha256(raw).hexdigest() != pin:
            fail('UI dependency input pin')
        files[name] = raw
    if sorted(path.name for path in (ROOT / INPUT_DIRECTORY).iterdir()) != sorted(INPUTS):
        fail('UI dependency input inventory')
    modules = []
    for relative in (GENERATOR, NODE_CONTROL):
        spec = importlib.util.spec_from_file_location('prepared_ui_' + Path(relative).stem, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        exec(compile(code[relative], str(ROOT / relative), 'exec'), vars(module))
        modules.append(module)
    tools, control = modules
    rows = tools.parse_lock(files['package-lock.json'])
    receipt = tools._json(files['dependency-inputs.json'], 'dependency receipt')
    if (files['package.json'] != tools.PACKAGE_RAW or len(rows) != 39 or
            receipt['status'] != 'generated_and_offline_verified' or
            receipt['evidence_scope'] != 'dependency_preparation_only' or
            receipt['node_version'] != '22.16.0' or receipt['npm_version'] != '10.9.2' or
            receipt['package_sha256'] != INPUTS['package.json'][1] or
            receipt['lock_sha256'] != INPUTS['package-lock.json'][1] or
            len(receipt['tarballs']) != len(rows)):
        fail('UI dependency frozen receipt')
    for row, tarball in zip(rows, receipt['tarballs']):
        if set(tarball) != set(row) | {'bytes', 'sha256'} or {key: tarball[key] for key in row} != row:
            fail('UI dependency frozen tarball')
    tree = ast.parse(code[GENERATOR])
    assignments = [item for item in ast.walk(tree) if isinstance(item, ast.Assign) and
                   any(isinstance(target, ast.Name) and target.id == 'smoke_command' for target in item.targets)]
    if len(assignments) != 1:
        fail('UI dependency smoke source')
    smoke = ast.literal_eval(assignments[0].value.args[0].elts[2])
    if type(smoke) is not str:
        fail('UI dependency smoke source')
    return tools, control, files, receipt, smoke


def mount_identity(runner, directory):
    directory, e_root = Path(directory), Path(runner['E_ROOT'])
    suffix = directory.name[len(PREFIX):] if directory.name.startswith(PREFIX) else ''
    if (directory.parent != Path('/var/tmp') or not re.fullmatch(r'[A-Za-z0-9_]{8}', suffix) or
            directory.resolve() != directory or directory.is_symlink() or not directory.is_mount() or
            e_root.resolve() != e_root or e_root.is_symlink() or not e_root.is_mount()):
        fail('UI dependency mount path')
    mounted, root, backing = directory.stat(), e_root.stat(), (e_root / directory.name).lstat()
    if (not stat.S_ISDIR(backing.st_mode) or (e_root / directory.name).is_symlink() or
            any(item.st_uid != 65534 or item.st_gid != 65534 or stat.S_IMODE(item.st_mode) != 0o700
                for item in (mounted, root, backing)) or root.st_dev == Path('/var/tmp').stat().st_dev or
            mounted.st_dev != root.st_dev or
            (mounted.st_dev, mounted.st_ino) != (backing.st_dev, backing.st_ino)):
        fail('UI dependency mount identity')
    return [mounted.st_dev, mounted.st_ino]


def node_binding(tools, control, node, frozen):
    clients = Path(node['clients_directory'])
    binding = tools._verify_node_bindings(control, clients, node)
    if (binding['extracted_inventory_sha256'] != frozen['node_client_inventory_sha256'] or
            binding['tool_binary_sha256'].get('bin/node') != frozen['node_binary_sha256']):
        fail('UI dependency Node input binding')
    return clients, binding


def check_tarballs(tools, directory, frozen):
    downloads = directory / 'workspace/downloads'
    expected = ['package-' + str(index) + '.tgz' for index in range(len(frozen['tarballs']))]
    if sorted(path.name for path in downloads.iterdir()) != sorted(expected):
        fail('UI dependency download inventory')
    for index, row in enumerate(frozen['tarballs']):
        path = downloads / ('package-' + str(index) + '.tgz')
        info = path.lstat()
        if info.st_uid != 65534 or info.st_gid != 65534 or stat.S_IMODE(info.st_mode) != 0o400:
            fail('UI dependency download identity')
        raw = tools._read_bounded(path, tools.MAX_TARBALL_BYTES)
        if len(raw) != row['bytes'] or tools._sha(raw) != row['sha256']:
            fail('UI dependency download binding')
        tools.validate_tarball(raw, row['integrity'])


def check_workspace(directory):
    workspace = directory / 'workspace'
    device = directory.stat().st_dev
    for path in (workspace, *(workspace / name for name in ('install', 'offline-cache', 'home', 'downloads'))):
        info = path.lstat()
        if (path.resolve() != path or path.is_symlink() or not stat.S_ISDIR(info.st_mode) or
                info.st_dev != device or info.st_uid != 65534 or info.st_gid != 65534 or
                stat.S_IMODE(info.st_mode) != 0o700):
            fail('UI dependency workspace identity')
    if sorted(path.name for path in workspace.iterdir()) != ['downloads', 'home', 'install', 'offline-cache']:
        fail('UI dependency workspace inventory')
    install = workspace / 'install'
    if sorted(path.name for path in install.iterdir()) != ['node_modules', 'package-lock.json', 'package.json']:
        fail('UI dependency install inventory')
    for name in ('package.json', 'package-lock.json'):
        info = (install / name).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_dev != device or
                info.st_uid != 65534 or info.st_gid != 65534 or stat.S_IMODE(info.st_mode) != 0o600):
            fail('UI dependency install input identity')


def prepare_dependencies(preflight, runner, directory, expected_commit, node, timeout):
    if type(timeout) is not int or not 0 < timeout <= 360:
        fail('UI dependency deadline')
    deadline = time.monotonic() + timeout
    tools, control, files, frozen, smoke_source = load_inputs(preflight, expected_commit)
    directory = Path(directory)
    identity = mount_identity(runner, directory)
    if any(directory.iterdir()):
        fail('UI dependency pre-existing workspace')
    clients, binding = node_binding(tools, control, node, frozen)
    workspace = tools._owned_dir(directory / 'workspace')
    install = tools._owned_dir(workspace / 'install')
    cache = tools._owned_dir(workspace / 'offline-cache')
    home = tools._owned_dir(workspace / 'home')
    downloads = tools._owned_dir(workspace / 'downloads')
    tools._write_bytes(install / 'package.json', files['package.json'])
    tools._write_bytes(install / 'package-lock.json', files['package-lock.json'])
    total = [0]
    for index, row in enumerate(frozen['tarballs']):
        length, digest, _ = tools._download(row['url'], row['integrity'],
            downloads / ('package-' + str(index) + '.tgz'), deadline, total)
        if length != row['bytes'] or digest != row['sha256']:
            fail('UI dependency downloaded input changed')
    check_tarballs(tools, directory, frozen)
    environment = tools._safe_env(runner, cache=cache, home=home, folder=clients, offline=True)
    logs = []

    def run(label, command):
        if mount_identity(runner, directory) != identity:
            fail('UI dependency mount changed')
        log = directory / (label + '.log')
        if log.exists() or log.is_symlink():
            fail('UI dependency pre-existing log')
        runner['run_command'](label, command, cwd=install, env=environment,
                              timeout=tools._remaining(deadline), log=log)
        tools._private_log(log)
        logs.append(log.name)
        if mount_identity(runner, directory) != identity:
            fail('UI dependency mount changed')

    npm = clients / 'bin/npm'
    for index in range(len(frozen['tarballs'])):
        run('ui-cache-' + str(index), [str(npm), 'cache', 'add',
            str(downloads / ('package-' + str(index) + '.tgz')), '--offline', '--cache', str(cache)])
    run('ui-offline-ci', [str(npm), 'ci', '--offline', '--ignore-scripts', '--no-audit',
                         '--no-fund', '--bin-links=false', '--cache', str(cache)])
    run('ui-dom-smoke', [str(clients / 'bin/node'), '-e', smoke_source])
    smoke = tools._parse_smoke(tools._private_log(directory / 'ui-dom-smoke.log', maximum=64 * 1024, allow_empty=False))
    if (tools._read_bounded(install / 'package.json', 64 * 1024) != files['package.json'] or
            tools._read_bounded(install / 'package-lock.json', tools.MAX_LOCK_BYTES) != files['package-lock.json']):
        fail('UI dependency installed input changed')
    inventory, count, size = tools._inventory(install / 'node_modules')
    if (inventory, count, size) != (frozen['installed_inventory_sha256'],
                                   frozen['installed_file_count'], frozen['installed_file_bytes']):
        fail('UI dependency installed inventory')
    check_tarballs(tools, directory, frozen)
    if node_binding(tools, control, node, frozen)[1] != binding:
        fail('UI dependency Node input changed')
    tools._remaining(deadline)
    receipt = dict(schema=SCHEMA, status='dependencies_prepared', application_tests_executed=False,
                   package_commit=expected_commit, mount_identity=identity,
                   frozen_inputs_sha256={name: pin for name, (_, pin) in INPUTS.items()},
                   generator_sha256=GENERATOR_SHA, node_control_sha256=NODE_CONTROL_SHA,
                   installed_inventory_sha256=inventory, installed_file_count=count, installed_file_bytes=size,
                   node_binding=binding, uid=smoke['uid'], gid=smoke['gid'],
                   euid=smoke['euid'], egid=smoke['egid'], supplementary_groups=smoke['groups'],
                   smoke={'status': 'passed', 'ok': smoke['ok']}, logs=logs)
    raw = json.dumps(receipt, sort_keys=True, indent=2).encode() + b'\n'
    path = directory / 'prepared-ui-inputs.json'
    tools._write_bytes(path, raw, mode=0o400, owner=(0, 0))
    prepared = dict(receipt, receipt_path=path, receipt_sha256=tools._sha(raw),
                    install_directory=install, modules_directory=install / 'node_modules')
    verify_prepared(preflight, runner, directory, prepared, expected_commit, node)
    return prepared


def verify_prepared(preflight, runner, directory, prepared, expected_commit, node):
    tools, control, files, frozen, _ = load_inputs(preflight, expected_commit)
    directory = Path(directory)
    install = directory / 'workspace/install'
    if (type(prepared) is not dict or prepared.get('schema') != SCHEMA or
            prepared.get('status') != 'dependencies_prepared' or prepared.get('application_tests_executed') is not False or
            prepared.get('package_commit') != expected_commit or
            prepared.get('mount_identity') != mount_identity(runner, directory) or
            prepared.get('receipt_path') != directory / 'prepared-ui-inputs.json' or
            prepared.get('install_directory') != install or prepared.get('modules_directory') != install / 'node_modules'):
        fail('UI dependency prepared binding')
    raw = tools._private_receipt(prepared['receipt_path'], prepared['receipt_sha256'], 'dependency consumer receipt')
    receipt = tools._json(raw, 'dependency consumer receipt')
    extra = {'receipt_path', 'receipt_sha256', 'install_directory', 'modules_directory'}
    if receipt != {key: value for key, value in prepared.items() if key not in extra}:
        fail('UI dependency receipt changed')
    if (prepared['frozen_inputs_sha256'] != {name: pin for name, (_, pin) in INPUTS.items()} or
            prepared['generator_sha256'] != GENERATOR_SHA or prepared['node_control_sha256'] != NODE_CONTROL_SHA or
            any(type(prepared[key]) is not int or prepared[key] != 65534 for key in ('uid', 'gid', 'euid', 'egid')) or
            prepared['supplementary_groups'] != [] or prepared['smoke'] != {'status': 'passed', 'ok': 1}):
        fail('UI dependency prepared scope')
    check_workspace(directory)
    if (tools._read_bounded(install / 'package.json', 64 * 1024) != files['package.json'] or
            tools._read_bounded(install / 'package-lock.json', tools.MAX_LOCK_BYTES) != files['package-lock.json']):
        fail('UI dependency installed input changed')
    inventory = tools._inventory(install / 'node_modules')
    expected = (frozen['installed_inventory_sha256'], frozen['installed_file_count'], frozen['installed_file_bytes'])
    if inventory != expected or inventory != (prepared['installed_inventory_sha256'],
                                               prepared['installed_file_count'], prepared['installed_file_bytes']):
        fail('UI dependency installed inventory')
    check_tarballs(tools, directory, frozen)
    if node_binding(tools, control, node, frozen)[1] != prepared['node_binding']:
        fail('UI dependency Node input changed')
    expected_logs = ['ui-cache-' + str(index) + '.log' for index in range(39)] + ['ui-offline-ci.log', 'ui-dom-smoke.log']
    if prepared['logs'] != expected_logs or sorted(path.name for path in directory.iterdir()) != sorted(['workspace', 'prepared-ui-inputs.json', *expected_logs]):
        fail('UI dependency private inventory')
    for name in expected_logs:
        tools._private_log(directory / name)
    return prepared
