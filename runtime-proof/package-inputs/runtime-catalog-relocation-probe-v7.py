from pathlib import Path
import hashlib
import inspect
import json
import os
import struct
import tempfile
import jaclang
from jaclang.compiler.types.stubcat.writer import CatalogWriter
from jaclang.compiler.types.stubcat.reader import StubCatalog
from jaclang.compiler.types.types import ModuleType

os.umask(0o077)
site=Path(SITE_PATH).resolve()
assert not os.environ.get('JAC_DEV_SOURCE') and os.environ.get('JAC_NO_DEV_SOURCE')=='1'
assert all(Path(root).resolve().is_relative_to(site) for root in jaclang.__path__)
for declaration in (CatalogWriter,StubCatalog,ModuleType):
    assert Path(inspect.getmodule(declaration).__file__).resolve().is_relative_to(site)
catalog=Path(CATALOG_PATH)
data=catalog.read_bytes()
roots=json.loads(Path(ROOTS_PATH).read_text())
references={name:data.count(root.encode()) for name,root in roots.items()}
assert not any(references.values()), references
header=struct.unpack_from('<8sI6I8QII',data)
assert header[:2]==(b'JSCAT005',5)
strings=[]
for sid in range(header[2]):
    offset,length=struct.unpack_from('<II',data,header[8]+sid*8)
    strings.append(data[header[9]+offset:header[9]+offset+length].decode())
relocated=Path(RELOCATED_PKG).resolve()
reader=StubCatalog(buf=data,pkg_dir=str(relocated))
def record(table,index):
    offset=struct.unpack_from('<I',data,table+index*4)[0]
    cursor=header[15]+offset
    def read():
        nonlocal cursor
        value,shift=0,0
        while True:
            byte=data[cursor]
            cursor+=1
            value|=(byte&127)<<shift
            if byte<128:
                return value
            shift+=7
            assert shift<64
    return read
module_count=0
for index in range(header[3]):
    read=record(header[10],index)
    name,rel=read(),read()
    rel=strings[rel]
    if rel:
        expected=Path(rel) if Path(rel).is_absolute() else relocated/rel
        assert Path(reader.abs_path(rel)).resolve()==expected.resolve()
        module_count+=1
module_types=[]
for index in range(header[6]):
    read=record(header[13],index)
    tag=read()
    read()
    if tag!=3:
        continue
    name,rel=read(),read()
    name,rel=strings[name],strings[rel]
    actual=reader.type_of(index)
    assert isinstance(actual,ModuleType) and actual.mod_name==name
    if rel in ('.','..') or '/' in rel or rel.endswith('.pyi'):
        expected=Path(rel) if Path(rel).is_absolute() else relocated/rel
        assert actual.file_uri.resolve()==expected.resolve()
    else:
        expected=Path(rel)
        assert actual.file_uri==expected
    module_types.append(dict(name=name,encoded=rel,hydrated=str(actual.file_uri)))
fixture=Path(tempfile.mkdtemp(prefix='m-local-packed-catalog-codec-',dir='/var/tmp'))
original=fixture/'original/site/jaclang'
destination=fixture/'relocated/site/jaclang'
original.mkdir(parents=True)
destination.mkdir(parents=True)
paths=[('package root',original,destination),('site parent',original.parent,destination.parent),
    ('bundled sibling',original.parent/'watchdog/observers/api.py',destination.parent/'watchdog/observers/api.py'),
    ('inner relative path',original/'runtime/context.jac',destination/'runtime/context.jac'),
    ('legacy plain filename',original/'api.py',Path('api.py')),
    ('stub filename',original/'api.pyi',destination/'api.pyi')]
writer=CatalogWriter(evaluator=None,pkg_dir=str(original))
ids=[writer.ref_type(ModuleType(mod_name=name,file_uri=path,symbol_table=None,is_external=True)) for name,path,_ in paths]
writer.force_all()
codec=StubCatalog(buf=writer.emit('',{}),pkg_dir=str(destination))
controls=[]
for tid,(name,_,expected) in zip(ids,paths):
    actual=codec.type_of(tid).file_uri
    passed=actual==expected if name=='legacy plain filename' else actual.resolve()==expected.resolve()
    controls.append(dict(name=name,status='passed' if passed else 'failed',actual=str(actual),expected=str(expected)))
status='passed' if all(row['status']=='passed' for row in controls) else 'failed'
result=dict(status=status,scope='Exact standalone catalog decoded at a relocated package root and six codec controls using the sealed staged writer/reader',
    catalog_sha256=hashlib.sha256(data).hexdigest(),catalog_bytes=len(data),build_root_occurrences=references,
    module_path_records_verified=module_count,module_type_records_verified=len(module_types),module_types=module_types,
    codec_controls=controls,runtime_roots=[str(Path(root).resolve()) for root in jaclang.__path__],
    writer_module_path=str(Path(inspect.getmodule(CatalogWriter).__file__).resolve()),
    reader_module_path=str(Path(inspect.getmodule(StubCatalog).__file__).resolve()),
    executed_probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
Path(OUTPUT_PATH).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(status=status,catalog_sha256=result['catalog_sha256'],module_path_records_verified=module_count,
    module_type_records_verified=len(module_types),codec_controls=6)))
raise SystemExit(0 if status=='passed' else 1)
