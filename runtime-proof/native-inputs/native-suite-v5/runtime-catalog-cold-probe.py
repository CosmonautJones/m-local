from pathlib import Path
import hashlib
import inspect
import json
import os
import runpy
import sys
import jaclang
from jaclang.compiler.types.stubcat.reader import StubCatalog
from jaclang.compiler.types.types import ModuleType

cache = Path(os.environ['JAC_CACHE_HOME']).resolve()
package = Path(PACKAGE_PATH).resolve()
assert os.environ.get('JAC_NO_DEV_SOURCE') == '1' and not os.environ.get('JAC_DEV_SOURCE')
roots = [Path(value).resolve() for value in jaclang.__path__]
assert len(roots) == 1 and roots[0].is_relative_to(cache)
for declaration in (StubCatalog, ModuleType):
    assert Path(inspect.getmodule(declaration).__file__).resolve().is_relative_to(roots[0])
metadata = json.loads((package / 'result.json').read_text())
binary = package / 'jac'
assert hashlib.sha256(binary.read_bytes()).hexdigest() == metadata['candidate_binary_sha256']
raw = binary.read_bytes()
payload_start = len(raw) - 80 - int.from_bytes(raw[-72:-64], 'little')
descriptor = raw[payload_start-32:payload_start]
assert descriptor[:8] == b'JSCATRG1'
offset, length = int.from_bytes(descriptor[8:16], 'little'), int.from_bytes(descriptor[16:24], 'little')
assert offset + length + 32 == payload_start
data = raw[offset:offset+length]
assert hashlib.sha256(data).hexdigest() == metadata['stub_catalog_sha256']
catalog = Path(OUTPUT_PATH).parent / 'packed-catalog.bin'
catalog.write_bytes(data)
audit_result = Path(OUTPUT_PATH).parent / 'catalog-path-audit.json'
audit = Path(AUDIT_PATH)
assert hashlib.sha256(audit.read_bytes()).hexdigest() == 'ce6951fde1842b46cf1c1e26787367118953ff51c819f85728d8d7bd3aa4050e'
before = list(sys.argv)
sys.argv = [str(audit), str(catalog), str(roots[0]), str(package / 'classifier-roots.json'), str(audit_result)]
try:
    runpy.run_path(str(audit), run_name='__main__')
finally:
    sys.argv = before
checked = json.loads(audit_result.read_text())
assert checked['status'] == 'passed' and checked['catalog_sha256'] == metadata['stub_catalog_sha256']
reader = StubCatalog(buf=data, pkg_dir=str(roots[0]))
module_count = 0
for row in checked['module_records']:
    if row['encoded']:
        actual = Path(reader.module_path(row['name'].split('.'))).resolve()
        assert actual == (roots[0] / row['encoded']).resolve() and actual.is_file()
        module_count += 1
for row in checked['module_types']:
    actual = reader.type_of(row['index'])
    assert isinstance(actual, ModuleType) and actual.mod_name == row['name']
    rel = row['encoded']
    if rel in ('.', '..') or '/' in rel or rel.endswith('.pyi'):
        assert actual.file_uri.resolve() == (roots[0] / rel).resolve() and actual.file_uri.exists()
    else:
        assert actual.file_uri == Path(rel)
assert module_count == 587 and len(checked['module_types']) == 161
result = dict(status='passed', scope='Exact packed catalog decoded and hydrated by the sealed reader at a fresh relocated cache; enclosing suite verifies hidden build sources and zero traced build-path operations',
              candidate_binary_sha256=metadata['candidate_binary_sha256'], catalog_sha256=metadata['stub_catalog_sha256'],
              module_path_records_verified=module_count, module_type_records_verified=161,
              complete_physical_path_audit_sha256=hashlib.sha256(audit_result.read_bytes()).hexdigest(),
              executed_audit_sha256=hashlib.sha256(audit.read_bytes()).hexdigest(),
              executed_probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              sdk_roots=[str(value) for value in roots],
              reader_declaring_module=str(Path(inspect.getmodule(StubCatalog).__file__).resolve()))
Path(OUTPUT_PATH).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
