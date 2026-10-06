#!/usr/bin/env python3
"""Run three classifier controls on a disposable copy of the fresh package.

Run with the fresh stage's Python 3.14 in its bounded worker. The package and
its original manifest are never changed by the controls.
"""
from pathlib import Path
import dis
import hashlib
import json
import marshal
import os
import shutil
import struct
import sys
import types


CLASSIFIER_SHA = '33dd3dbe88aadb16317f60bd518430225a7a8ef466596c70271b16371006f363'
POLICY_SHA = '6d08330483ae7569153701c4eb5d211c838bb7ab6909452aa54bd5ad9e401e5d'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        assert not path.is_symlink() and (path.is_file() or path.is_dir())
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def change_consumer(raw, stage_root):
    changed = False

    def mutate(code):
        nonlocal changed
        if changed:
            return code
        instructions = list(dis.get_instructions(code))
        for index, item in enumerate(instructions):
            if item.opname == 'LOAD_CONST' and isinstance(item.argval, str) and stage_root in item.argval:
                following = next(row for row in instructions[index + 1:] if row.opname != 'EXTENDED_ARG')
                assert following.opname == 'CALL' and following.arg == 1
                bytecode = bytearray(code.co_code)
                bytecode[following.offset] = dis.opmap['RETURN_VALUE']
                bytecode[following.offset + 1] = 0
                changed = True
                return code.replace(co_code=bytes(bytecode))
        return code.replace(co_consts=tuple(mutate(value) if isinstance(value, types.CodeType) else value
                                             for value in code.co_consts))

    position = raw.find(b'JIRX', 32)
    assert raw[:4] == b'JIR\0' and position >= 32
    position += 4
    parts = [raw[:position]]
    while position < len(raw):
        assert position + 5 <= len(raw)
        tag, size = raw[position], struct.unpack_from('<I', raw, position + 1)[0]
        position += 5
        assert size <= len(raw) - position
        part = raw[position:position + size]
        position += size
        if tag == 2:
            part = marshal.dumps(mutate(marshal.loads(part)))
        if tag == 255:
            assert size == 0 and position == len(raw)
        parts.append(bytes([tag]) + struct.pack('<I', len(part)) + part)
    assert changed
    return b''.join(parts)


def main():
    assert sys.version_info[:2] == (3, 14) and len(sys.argv) == 3
    package, directory = map(Path, sys.argv[1:])
    e_root = Path('/var/tmp/m-local-build-e-drive-v2-01a1050e')
    for path in (package, directory):
        assert path.parent == Path('/var/tmp') and path.resolve() == path and not path.is_symlink()
        assert path.is_mount() and path.stat().st_dev == e_root.stat().st_dev
        assert path.stat().st_uid == 65534 and path.stat().st_mode & 0o777 == 0o700
    assert package.name.startswith('m-local-runtime-package-')
    assert directory.name.startswith('m-local-package-verifier-v1-')
    assert Path('/proc/self/cgroup').read_text().strip().endswith('/m-local-' + directory.name + '.scope')
    os.umask(0o077)
    frozen = json.loads((package / 'frozen-stage-files.json').read_bytes())
    assert inventory(package / 'stage') == frozen
    stage = directory / 'stage-copy'
    assert not stage.exists() and not stage.is_symlink()
    shutil.copytree(package / 'stage', stage)
    assert inventory(stage) == frozen
    classifier = package / 'executed-classifier.py'
    raw = classifier.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CLASSIFIER_SHA
    policy = package / 'diagnostic-policy.json'
    assert digest(policy) == POLICY_SHA
    module = {'__file__': str(classifier), '__name__': 'trusted_classifier_control'}
    exec(compile(raw, str(classifier), 'exec'), module)
    roots = json.loads((package / 'classifier-roots.json').read_bytes())

    def classify(name):
        return module['classify'](stage, roots, package / 'assembled-inputs.json', policy,
                                   directory / (name + '.json'))

    baseline = classify('fresh-stage-baseline')
    assert baseline['status'] == 'passed' and baseline['errors'] == []
    assert baseline['counts']['verified_layout_units'] == 31 and baseline['counts']['verified_manifest_jirs'] == 814
    assert baseline['stage_files'] == frozen
    cases = [dict(name='fresh-stage-baseline', status='passed')]
    target = stage / 'site/jaclang/_precompiled/cpython-314/byllm/config_loader.jir'
    manifest_path = stage / 'site/jaclang/_precompiled/MANIFEST.json'
    original, manifest_raw = target.read_bytes(), manifest_path.read_bytes()
    try:
        target.write_bytes(change_consumer(original, roots['stage']))
        manifest = json.loads(manifest_raw)
        manifest['modules']['byllm/config_loader.jac']['sha256'] = digest(target)
        manifest_path.write_text(json.dumps(manifest))
        wrong = classify('wrong-consumer-with-updated-manifest')
        assert wrong['status'] == 'rejected' and len(wrong['errors']) == 1
        assert 'forbidden path consumer' in wrong['errors'][0]
        cases.append(dict(name='wrong-consumer-with-updated-manifest', status='passed'))
    finally:
        target.write_bytes(original)
        manifest_path.write_bytes(manifest_raw)
    try:
        target.write_bytes(original + roots['stage'].encode())
        rejected = False
        try:
            classify('trailing-jir-bytes')
        except AssertionError:
            rejected = True
        assert rejected
        cases.append(dict(name='trailing-jir-bytes', status='passed'))
    finally:
        target.write_bytes(original)
        manifest_path.write_bytes(manifest_raw)
    assert inventory(stage) == frozen == inventory(package / 'stage')
    receipt = dict(status='passed', scope='fresh disposable classifier controls; no application acceptance',
                   classifier_sha256=CLASSIFIER_SHA, policy_sha256=POLICY_SHA,
                   executed_controls_sha256=digest(Path(__file__)), cases=cases,
                   package_metadata_sha256=digest(package / 'result.json'),
                   original_stage_classification_sha256=digest(package / 'stage-path-classification.json'))
    with (directory / 'controls.json').open('x') as stream:
        stream.write(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
