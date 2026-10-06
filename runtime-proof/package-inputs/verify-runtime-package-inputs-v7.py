from pathlib import Path
import hashlib
import json
import sys

package = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2])
assert package.parent == Path('/var/tmp') and package.name.startswith('m-local-runtime-package-')
metadata = json.loads((package / 'result.json').read_text())
assert metadata['runtime_base'] == '58cb97eb75cdff8b5ee78f4094ca2be16376601c'
assert metadata['runtime_patch_sha256'] == 'd3630dfc5d9942e2b7ac6edf0ee1dd10bdb7a0f0919865e543220a27b27fe366'
assert metadata['executed_recipe_sha256'] == 'ec820c414d5a83d498f894eddcee105d5eb3e287a030c2d6b87045fe7d32129f'
assert metadata['executed_classifier_sha256'] == '33dd3dbe88aadb16317f60bd518430225a7a8ef466596c70271b16371006f363'
assert metadata['diagnostic_policy_sha256'] == '6d08330483ae7569153701c4eb5d211c838bb7ab6909452aa54bd5ad9e401e5d'
assert metadata['executed_catalog_probe_sha256'] == '8849263964617d4fda67bfbab436402440dbb12755cf5ce534100c94d8421f03'
assert metadata['official_binary_sha256'] == '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad'
assert metadata['launcher_sha256'] == 'c6cdf1cf60abba6a64d2b8b06a22b9ba9c8392ab24d8a5bda3cf45efc64c9ce8'
assert metadata['resumed_build'] is False and metadata['source_override_in_payload'] is False
assert metadata['inherited_python_and_dependencies_byte_matched'] and not metadata['fork_path_reference_files']
assert metadata['official_extracted_cache_byte_matched'] is True
assert metadata['diagnostic_path_classification_passed'] and metadata['final_packed_payload_byte_matches_frozen_stage']
assert metadata['child_precompile_source_override'] is False and metadata['catalog_relocation_verified']
files = [('assembled-inputs.json', 'assembled_input_manifest_sha256'), ('inherited-inputs.json', 'inherited_input_manifest_sha256'),
         ('transaction.patch', 'runtime_patch_sha256'), ('executed-recipe.py', 'executed_recipe_sha256'),
         ('payload-build-references.json', 'build_reference_manifest_sha256'), ('executed-classifier.py', 'executed_classifier_sha256'),
         ('diagnostic-policy.json', 'diagnostic_policy_sha256'), ('stage-path-classification.json', 'stage_classification_sha256'),
         ('final-payload-path-classification.json', 'final_payload_classification_sha256'),
         ('frozen-stage-files.json', 'frozen_stage_manifest_sha256'), ('catalog-relocation.json', 'catalog_relocation_receipt_sha256'),
         ('executed-catalog-probe.py', 'executed_catalog_probe_sha256'), ('stubcat.bin', 'stub_catalog_sha256'),
         ('launcher', 'launcher_sha256'), ('runtime.tar.zst', 'payload_sha256'), ('jac', 'candidate_binary_sha256')]
hashes = {}
for name, key in files:
    hashes[name] = hashlib.sha256((package / name).read_bytes()).hexdigest()
    assert hashes[name] == metadata[key], name
raw = (package / 'jac').read_bytes()
assert raw[-80:-72] == b'JACBIN01'
start = len(raw) - 80 - int.from_bytes(raw[-72:-64], 'little')
assert raw[start:-80] == (package / 'runtime.tar.zst').read_bytes()
assert hashlib.sha256(raw[start:-80]).hexdigest() == raw[-64:].decode() == metadata['payload_sha256']
descriptor = raw[start-32:start]
assert descriptor[:8] == b'JSCATRG1'
offset, length = int.from_bytes(descriptor[8:16], 'little'), int.from_bytes(descriptor[16:24], 'little')
launcher, catalog = (package / 'launcher').read_bytes(), (package / 'stubcat.bin').read_bytes()
assert offset + length + 32 == start and length == len(catalog)
assert raw[:len(launcher)] == launcher and raw[len(launcher):offset] == b'\0' * (offset - len(launcher))
assert raw[offset:offset+length] == catalog
stage = json.loads((package / 'stage-path-classification.json').read_text())
final = json.loads((package / 'final-payload-path-classification.json').read_text())
frozen = json.loads((package / 'frozen-stage-files.json').read_text())
assembled = json.loads((package / 'assembled-inputs.json').read_text())
policy = json.loads((package / 'diagnostic-policy.json').read_text())
roots = json.loads((package / 'classifier-roots.json').read_text())
raw_references = json.loads((package / 'payload-build-references.json').read_text())
inventory_sha = hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
assert inventory_sha == metadata['frozen_stage_inventory_sha256']
for receipt in (stage, final):
    assert receipt['status'] == 'passed' and receipt['errors'] == []
    assert receipt['roots'] == roots and receipt['stage_files'] == frozen
    assert receipt['stage_inventory_sha256'] == inventory_sha
    assert receipt['raw_build_reference_files'] == raw_references == metadata['build_path_reference_files']
    assert receipt['executed_classifier_sha256'] == metadata['executed_classifier_sha256']
    assert receipt['policy_sha256'] == metadata['diagnostic_policy_sha256']
    assert receipt['assembled_input_manifest_sha256'] == metadata['assembled_input_manifest_sha256']
    assert receipt['sealed_manifest_sha256'] == metadata['sealed_manifest_sha256']
    assert receipt['counts']['verified_layout_units'] == 31 and receipt['counts']['verified_manifest_jirs'] == 814
assert not raw_references['fork'] and not raw_references['official_cache'] and not raw_references['packaging_cache']
for root in (package / 'stage', package / 'unpacked-final-payload'):
    assert root.is_dir() and not any(path.is_symlink() for path in root.rglob('*'))
    actual = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(root.rglob('*')) if path.is_file()}
    assert actual == frozen, str(root)
    assert hashlib.sha256((root / 'site/jaclang/_precompiled/MANIFEST.json').read_bytes()).hexdigest() == metadata['sealed_manifest_sha256']
catalog_check = json.loads((package / 'catalog-relocation.json').read_text())
assert catalog_check['status'] == 'passed' and catalog_check['catalog_sha256'] == metadata['stub_catalog_sha256']
assert catalog_check['module_path_records_verified'] == 587 and catalog_check['module_type_records_verified'] == 161
assert len(catalog_check['codec_controls']) == 6 and all(row['status'] == 'passed' for row in catalog_check['codec_controls'])
assert catalog_check['executed_probe_sha256'] == metadata['executed_catalog_probe_sha256']
assert not any(catalog_check['build_root_occurrences'].values())
result = dict(status='passed', scope='Independent frozen package input, packed-region and exact classifier-receipt binding; cold runtime acceptance remains a separate gate',
              candidate_binary_sha256=metadata['candidate_binary_sha256'], payload_sha256=metadata['payload_sha256'],
              runtime_patch_sha256=metadata['runtime_patch_sha256'], sealed_manifest_sha256=metadata['sealed_manifest_sha256'],
              package_metadata_sha256=hashlib.sha256((package / 'result.json').read_bytes()).hexdigest(),
              frozen_stage_inventory_sha256=inventory_sha, classifier_sha256=metadata['executed_classifier_sha256'],
              policy_sha256=metadata['diagnostic_policy_sha256'], stage_classification_sha256=metadata['stage_classification_sha256'],
              final_payload_classification_sha256=metadata['final_payload_classification_sha256'],
              file_hashes=hashes, executed_verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
