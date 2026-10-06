"""Package the bounded transaction candidate using Jac's tagged payload tools.

Reuses the official launcher/CPython/dependency bytes; rebuilds the Jac compiler
identity, stub catalog and sealed JIR. Never writes to the installed runtime.
"""
import argparse
import hashlib
import io
import json
import os
import stat
import tarfile
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description='Assemble a fresh sealed runtime in an owned bounded workspace.')
parser.add_argument('--fork', type=Path, required=True)
parser.add_argument('--official-binary', type=Path, required=True)
parser.add_argument('--official-cache', type=Path, required=True)
parser.add_argument('--package-inputs', type=Path, required=True)
args = parser.parse_args()
OFFICIAL_BINARY_SHA256 = '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'

os.umask(0o077)
sys.dont_write_bytecode = True
os.environ['JAC_PRECOMPILE_JOBS'] = '1'
os.environ['JAC_PRECOMPILE_RECYCLE_MB'] = '1024'

def inventory(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file() and path.name not in ('.ok', '.used') and '__pycache__' not in path.parts}

def verify_official_cache(official, original):
    raw = official.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == OFFICIAL_BINARY_SHA256
    assert raw[-80:-72] == b'JACBIN01'
    size = int.from_bytes(raw[-72:-64], 'little')
    assert 0 < size <= len(raw) - 80
    payload = raw[-80-size:-80]
    payload_hash = hashlib.sha256(payload).hexdigest()
    assert payload_hash == raw[-64:].decode('ascii')
    assert original.parent.name == 'rt' and original.name == payload_hash[:16]
    marker = original / '.ok'
    assert marker.is_file() and not marker.is_symlink() and marker.stat().st_size == 0
    import compression.zstd
    expected = {}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(compression.zstd.decompress(payload)), mode='r:', ignore_zeros=True) as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts
            name = path.as_posix()
            assert name not in seen and (member.isfile() or member.isdir())
            seen.add(name)
            if member.isfile() and path.name not in ('.ok', '.used') and '__pycache__' not in path.parts:
                with archive.extractfile(member) as stream:
                    expected[name] = hashlib.sha256(stream.read()).hexdigest()
    assert expected and inventory(original) == expected, 'Official extracted cache byte mismatch'
    for path in original.rglob('*'):
        assert not path.is_symlink() and (path.is_file() or path.is_dir())
        if path.is_file():
            assert stat.S_ISREG(path.stat().st_mode) and path.stat().st_nlink == 1
    return payload_hash

# Validate write placement before importing the compiler/payload implementation.
e_root = Path('/var/tmp/m-local-build-e-drive-v2-01a1050e')
cache_root = Path(os.environ['JAC_CACHE_HOME'])
scratch_root = Path(os.environ['TMPDIR'])
wrapper = cache_root.parent
assert wrapper.parent == Path('/var/tmp') and wrapper.name.startswith('m-local-kali-package-wrapper-')
assert len(wrapper.name) == len('m-local-kali-package-wrapper-') + 8
assert wrapper.is_mount() and not wrapper.is_symlink() and wrapper.stat().st_dev == e_root.stat().st_dev
assert scratch_root.parent == wrapper and scratch_root.name == 'scratch' and cache_root.name == 'cache'
for path in (e_root, wrapper, cache_root, scratch_root):
    assert path.is_dir() and not path.is_symlink() and path.stat().st_dev == e_root.stat().st_dev
    assert path.stat().st_uid == 65534 and path.stat().st_mode & 0o777 == 0o700
unit = 'm-local-' + wrapper.name + '.scope'
assert Path('/proc/self/cgroup').read_text().strip().endswith('/' + unit)
group = Path('/sys/fs/cgroup/system.slice') / unit
assert int((group / 'memory.high').read_text()) == 7 * 1024 ** 3
assert int((group / 'memory.max').read_text()) == 8 * 1024 ** 3
assert int((group / 'memory.swap.max').read_text()) == 0

fork = args.fork
official = args.official_binary
original = args.official_cache
package_inputs = args.package_inputs
for path in (fork, original, package_inputs, official):
    assert path.is_absolute() and not path.is_symlink() and path.resolve() == path
    assert path.is_relative_to(e_root) and path.stat().st_dev == e_root.stat().st_dev
assert fork.is_dir() and original.is_dir() and package_inputs.is_dir() and official.is_file()
assert os.environ.get('JAC_DEV_SOURCE') == str(fork / 'jac') and not os.environ.get('JAC_NO_DEV_SOURCE')
assert Path.cwd().resolve() == fork
base = '58cb97eb75cdff8b5ee78f4094ca2be16376601c'
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == base
assert hashlib.sha256(official.read_bytes()).hexdigest() == OFFICIAL_BINARY_SHA256
expected_patch = 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
assert hashlib.sha256(subprocess.check_output(['git', 'diff', '--binary'], cwd=fork)).hexdigest() == expected_patch
assert not os.environ.get('MLOCAL_RUNTIME_PACKAGE_RESUME'), 'Partial stages are not accepted inputs'
official_payload_sha256 = verify_official_cache(official, original)

from jaclang.dist.payload.assemble import MkPayloadOpts, assemble_site, run_precompile_stage, tar_zst_dir
from jaclang.dist.payload.pack import pack
from jaclang.dist.fused.trailer import parse_trailer, parse_region_desc, MAGIC, TRAILER_LEN, REGION_DESC_LEN

directory = Path(os.environ['MLOCAL_RUNTIME_PACKAGE_WORKSPACE'])
assert directory.parent == Path('/var/tmp') and directory.name.startswith('m-local-runtime-package-')
assert len(directory.name) == len('m-local-runtime-package-') + 8
assert directory.is_mount() and not any(directory.iterdir())
assert directory.stat().st_dev == Path('/var/tmp/m-local-build-e-drive-v2-01a1050e').stat().st_dev
assert directory.stat().st_uid == 65534 and directory.stat().st_mode & 0o777 == 0o700
stage = directory / 'stage'
inputs = directory / 'python-input'
shutil.copytree(original, stage, ignore=shutil.ignore_patterns('.ok', '.used', '__pycache__'))
# This directory belongs exclusively to this invocation.
pre = stage / 'site/jaclang/_precompiled'
assert pre.is_relative_to(directory)
shutil.rmtree(pre)
inputs.mkdir()
(inputs / 'install').symlink_to(stage / 'python', target_is_directory=True)
assert (inputs / 'install').resolve() == (stage / 'python').resolve()
catalog = directory / 'stubcat.bin'
opts = MkPayloadOpts(shim_so=str(fork / 'jac/jaclang/compiler/backends/native/llvm/libjacllvm.so'),
                     bun_bin=str(original / 'site/jaclang/client/_bun/bun'),
                     seal=True, stubcat_out=str(catalog))
print('Retained packaging workspace:', directory, flush=True)
assemble_site(str(fork / 'jac'), str(stage / 'site'), opts)
assembled_inputs = directory / 'assembled-inputs.json'
assembled_inputs.write_text(json.dumps(inventory(stage), indent=2, sort_keys=True) + '\n')
assembled = json.loads(assembled_inputs.read_text())
for name in subprocess.check_output(['git','diff','--name-only'],cwd=fork,text=True).splitlines():
    assert name.startswith('jac/jaclang/')
    assert assembled.get('site/'+name.removeprefix('jac/')) == hashlib.sha256((fork/name).read_bytes()).hexdigest()
os.environ.pop('JAC_DEV_SOURCE', None)
os.environ['JAC_NO_DEV_SOURCE'] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
assert 'JAC_DEV_SOURCE' not in os.environ
run_precompile_stage(str(stage / 'python/bin/python3.14'), str(inputs), str(stage / 'site'), opts)
manifest = stage / 'site/jaclang/_precompiled/MANIFEST.json'
assert manifest.is_file(), 'Sealing must complete before packaging'
# Only this fresh invocation's staging cache is disposable.
for path in sorted(stage.rglob('__pycache__'), key=lambda p: len(p.parts), reverse=True):
    assert path.resolve().is_relative_to(stage.resolve()) and not path.is_symlink()
    shutil.rmtree(path)
for path in stage.rglob('*'):
    if path.name in ('jac_linked_source', 'code.key', 'jwt_secret') or path.suffix in ('.sqlite3', '.db'):
        raise AssertionError('Unexpected source link or private application state in payload')
    if path.is_symlink():
        raise AssertionError('Unexpected payload symlink: ' + str(path.relative_to(stage)))
inherited = {'python': inventory(original / 'python'),
             'dependencies': {name: inventory(original / 'site' / name) for name in ('tomlkit', 'tomlkit-0.15.1.dist-info', 'watchdog', 'watchdog-6.0.0.dist-info')}}
assert inventory(stage / 'python') == inherited['python']
for name, expected in inherited['dependencies'].items():
    assert inventory(stage / 'site' / name) == expected
(directory / 'inherited-inputs.json').write_text(json.dumps(inherited, sort_keys=True, indent=2) + '\n')
build_roots = {'fork': fork, 'package': directory, 'stage': stage, 'inputs': inputs, 'official_cache': original,
               'packaging_cache': Path(os.environ['JAC_CACHE_HOME']), 'scratch': Path(os.environ['TMPDIR'])}
build_references = {name: [] for name in build_roots}
for path in sorted(stage.rglob('*')):
    if path.is_file():
        content = path.read_bytes()
        for name, root in build_roots.items():
            if str(root).encode() in content:
                build_references[name].append(str(path.relative_to(stage)))
fork_references = build_references['fork']
(directory / 'payload-fork-references.json').write_text(json.dumps(fork_references, indent=2) + '\n')
(directory / 'payload-build-references.json').write_text(json.dumps(build_references, indent=2) + '\n')
assert not fork_references, 'Runtime source override references are forbidden'
classifier = directory / 'executed-classifier.py'
classifier.write_bytes((package_inputs / 'classify-runtime-build-paths-v7.py').read_bytes())
assert hashlib.sha256(classifier.read_bytes()).hexdigest() == '33dd3dbe88aadb16317f60bd518430225a7a8ef466596c70271b16371006f363'
policy = directory / 'diagnostic-policy.json'
policy.write_bytes((package_inputs / 'diagnostic-policy-v7.json').read_bytes())
assert hashlib.sha256(policy.read_bytes()).hexdigest() == '6d08330483ae7569153701c4eb5d211c838bb7ab6909452aa54bd5ad9e401e5d'
roots_file = directory / 'classifier-roots.json'
roots_file.write_text(json.dumps({name: str(root) for name,root in build_roots.items()},indent=2)+'\n')
catalog_probe = directory / 'executed-catalog-probe.py'
catalog_probe.write_bytes((package_inputs / 'runtime-catalog-relocation-probe-v7.py').read_bytes())
assert hashlib.sha256(catalog_probe.read_bytes()).hexdigest() == '8849263964617d4fda67bfbab436402440dbb12755cf5ce534100c94d8421f03'
catalog_receipt = directory / 'catalog-relocation.json'
catalog_cache = directory / 'catalog-codec-cache'
catalog_cache.mkdir(mode=0o700)
assert not any(catalog_cache.iterdir())
catalog_env = dict(PATH='/usr/bin:/bin', HOME=str(directory), LANG='C.UTF-8',
    PYTHONHOME=str(stage / 'python'), PYTHONPATH=str(stage / 'site'), PYTHONDONTWRITEBYTECODE='1',
    JAC_NO_DEV_SOURCE='1', JAC_CACHE_HOME=str(catalog_cache))
catalog_values = dict(SITE_PATH=str(stage / 'site'), CATALOG_PATH=str(catalog), ROOTS_PATH=str(roots_file),
    RELOCATED_PKG=str(directory / 'relocated-catalog/site/jaclang'), OUTPUT_PATH=str(catalog_receipt))
catalog_code = 'import runpy; runpy.run_path('+repr(str(catalog_probe))+',init_globals='+repr(catalog_values)+',run_name="__main__")'
subprocess.check_call([str(stage / 'python/bin/python3.14'), '-B', '-c', catalog_code],env=catalog_env,cwd=directory)
catalog_result = json.loads(catalog_receipt.read_text())
assert catalog_result['status'] == 'passed' and catalog_result['catalog_sha256'] == hashlib.sha256(catalog.read_bytes()).hexdigest()
assert catalog_result['executed_probe_sha256'] == hashlib.sha256(catalog_probe.read_bytes()).hexdigest()
assert not any(catalog_result['build_root_occurrences'].values()) and len(catalog_result['codec_controls']) == 6
classifier_env = dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LANG='C.UTF-8', PYTHONDONTWRITEBYTECODE='1')
def classify(root, result_path):
    subprocess.check_call([str(stage / 'python/bin/python3.14'), '-I', '-B', '-S', str(classifier),
        str(root), str(roots_file), str(assembled_inputs), str(policy), str(result_path)], env=classifier_env, cwd=directory)
    record = json.loads(result_path.read_text())
    assert record['status'] == 'passed'
    assert record['executed_classifier_sha256'] == hashlib.sha256(classifier.read_bytes()).hexdigest()
    return record
classification_path = directory / 'stage-path-classification.json'
classification = classify(stage, classification_path)
assert classification['raw_build_reference_files'] == build_references
frozen_files = inventory(stage)
assert frozen_files == classification['stage_files']
(directory / 'frozen-stage-files.json').write_text(json.dumps(frozen_files,sort_keys=True,indent=2)+'\n')
payload = directory / 'runtime.tar.zst'
tar_zst_dir(str(stage), str(payload), None)
raw = official.read_bytes()
trailer = parse_trailer(raw[-TRAILER_LEN:], MAGIC)
assert trailer is not None
start = len(raw) - TRAILER_LEN - trailer.payload_len
assert hashlib.sha256(raw[start:-TRAILER_LEN]).hexdigest() == trailer.hash_hex
region = parse_region_desc(raw[start-REGION_DESC_LEN:start])
assert region is not None
stub = directory / 'launcher'
stub.write_bytes(raw[:region.off])
os.chmod(stub, 0o755)
candidate = directory / 'jac'
pack(str(stub), str(payload), str(candidate), str(catalog))
packed = candidate.read_bytes()
packed_trailer = parse_trailer(packed[-TRAILER_LEN:], MAGIC)
assert packed_trailer is not None and packed_trailer.payload_len == payload.stat().st_size
packed_start = len(packed) - TRAILER_LEN - packed_trailer.payload_len
packed_region = parse_region_desc(packed[packed_start-REGION_DESC_LEN:packed_start])
assert packed_region is not None
launcher_bytes, catalog_bytes, payload_bytes = stub.read_bytes(), catalog.read_bytes(), payload.read_bytes()
assert packed[:len(launcher_bytes)] == launcher_bytes
assert packed[len(launcher_bytes):packed_region.off] == b'\0' * (packed_region.off - len(launcher_bytes))
assert packed_region.length == len(catalog_bytes)
assert packed[packed_region.off:packed_region.off+packed_region.length] == catalog_bytes
assert packed_start == packed_region.off + packed_region.length + REGION_DESC_LEN
assert packed[packed_start:-TRAILER_LEN] == payload_bytes
assert packed_trailer.hash_hex == hashlib.sha256(payload_bytes).hexdigest()
assert inventory(stage) == frozen_files, 'Frozen stage changed during packing'
assert hashlib.sha256(launcher_bytes).hexdigest() == 'c6cdf1cf60abba6a64d2b8b06a22b9ba9c8392ab24d8a5bda3cf45efc64c9ce8'
# Independently decode the final packed payload before any candidate execution.
unpacked = directory / 'unpacked-final-payload'
unpacked.mkdir(mode=0o700)
unpack_script = directory / 'executed-unpack.py'
unpack_script.write_text('''from pathlib import Path
import compression.zstd
import hashlib
import json
import sys
import tarfile
binary,output,expected=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
raw=binary.read_bytes()
assert raw[-80:-72]==b'JACBIN01'
size=int.from_bytes(raw[-72:-64],'little')
payload=raw[-80-size:-80]
assert hashlib.sha256(payload).hexdigest()==expected==raw[-64:].decode()
archive=output.parent/'decoded-final-payload.tar'
archive.write_bytes(compression.zstd.decompress(payload))
seen=set()
with tarfile.open(archive,mode='r:',ignore_zeros=True) as tar:
    for member in tar:
        name=Path(member.name)
        assert not name.is_absolute() and '..' not in name.parts and member.name not in seen
        assert member.isfile() or member.isdir()
        seen.add(member.name)
        target=output/name
        assert target.resolve().is_relative_to(output.resolve())
        if member.isdir():
            target.mkdir(parents=True,exist_ok=True)
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(member) as source,target.open('wb') as destination:
                destination.write(source.read())
            target.chmod(member.mode)
print(json.dumps(dict(status='decoded_final_payload',members=len(seen))))
''')
subprocess.check_call([str(stage / 'python/bin/python3.14'), '-I', '-B', '-S', str(unpack_script),
    str(candidate), str(unpacked), packed_trailer.hash_hex],env=classifier_env,cwd=directory)
assert inventory(unpacked) == frozen_files, 'Final packed payload differs from frozen stage'
final_classification_path = directory / 'final-payload-path-classification.json'
final_classification = classify(unpacked, final_classification_path)
assert final_classification['stage_inventory_sha256'] == classification['stage_inventory_sha256']
(directory / 'jacpython').symlink_to(candidate.name)
diff = subprocess.check_output(['git', 'diff', '--binary'], cwd=fork)
assert hashlib.sha256(diff).hexdigest() == expected_patch
(directory / 'transaction.patch').write_bytes(diff)
(directory / 'executed-recipe.py').write_bytes(Path(__file__).read_bytes())
result = {
    'scope': 'local Linux x86_64 sealed derivative; reused official launcher, CPython and bundled dependencies; not an upstream release or deployment',
    'resumed_build': False, 'precompile_workers': 1,
    'assembled_input_manifest_sha256': hashlib.sha256(assembled_inputs.read_bytes()).hexdigest(),
    'runtime_base': base,
    'official_binary_sha256': hashlib.sha256(raw).hexdigest(),
    'official_payload_sha256': official_payload_sha256,
    'official_extracted_cache_byte_matched': True,
    'runtime_patch_sha256': hashlib.sha256(diff).hexdigest(),
    'candidate_binary_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
    'candidate_binary_bytes': candidate.stat().st_size,
    'sealed_manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
    'payload_sha256': hashlib.sha256(payload.read_bytes()).hexdigest(),
    'candidate': str(candidate),
    'source_override_in_payload': False,
    'inherited_payload_origin': 'Fresh cache extraction from the exact hash-verified official binary during the official compiler control',
    'inherited_python_and_dependencies_byte_matched': True,
    'inherited_input_manifest_sha256': hashlib.sha256((directory / 'inherited-inputs.json').read_bytes()).hexdigest(),
    'fork_path_reference_files': fork_references,
    'build_path_reference_files': build_references,
    'launcher_sha256': hashlib.sha256(launcher_bytes).hexdigest(),
    'stub_catalog_sha256': hashlib.sha256(catalog_bytes).hexdigest(),
    'packed_trailer_region_and_payload_verified': True,
    'executed_recipe_sha256': hashlib.sha256((directory / 'executed-recipe.py').read_bytes()).hexdigest(),
    'build_reference_manifest_sha256': hashlib.sha256((directory / 'payload-build-references.json').read_bytes()).hexdigest(),
    'diagnostic_path_classification_passed': True,
    'diagnostic_policy_sha256': hashlib.sha256(policy.read_bytes()).hexdigest(),
    'executed_classifier_sha256': hashlib.sha256(classifier.read_bytes()).hexdigest(),
    'stage_classification_sha256': hashlib.sha256(classification_path.read_bytes()).hexdigest(),
    'final_payload_classification_sha256': hashlib.sha256(final_classification_path.read_bytes()).hexdigest(),
    'frozen_stage_inventory_sha256': classification['stage_inventory_sha256'],
    'frozen_stage_manifest_sha256': hashlib.sha256((directory / 'frozen-stage-files.json').read_bytes()).hexdigest(),
    'final_packed_payload_byte_matches_frozen_stage': True,
    'child_precompile_source_override': False,
    'catalog_relocation_verified': True,
    'catalog_relocation_receipt_sha256': hashlib.sha256(catalog_receipt.read_bytes()).hexdigest(),
    'executed_catalog_probe_sha256': hashlib.sha256(catalog_probe.read_bytes()).hexdigest(),
    'catalog_decoder_fresh_private_cache': True,
}
(directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
