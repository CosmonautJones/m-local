from pathlib import Path
import inspect
import json
import os
import tempfile
from jaclang.compiler.types.stubcat.writer import CatalogWriter
from jaclang.compiler.types.stubcat.reader import StubCatalog
from jaclang.compiler.types.types import ModuleType

os.umask(0o077)
fork=Path('/var/tmp/m-local-runtime-fork-01a1050e/jac')
for declaration in (CatalogWriter,StubCatalog,ModuleType):
    assert Path(inspect.getmodule(declaration).__file__).resolve().is_relative_to(fork)
root=Path(tempfile.mkdtemp(prefix='m-local-interface-codec-controls-',dir='/var/tmp'))
original=root/'original/site/jaclang'
relocated=root/'relocated/site/jaclang'
original.mkdir(parents=True)
relocated.mkdir(parents=True)
paths=[('package root',original,relocated),('site parent',original.parent,relocated.parent),
    ('bundled sibling',original.parent/'watchdog/observers/api.py',relocated.parent/'watchdog/observers/api.py'),
    ('inner relative path',original/'runtime/context.jac',relocated/'runtime/context.jac'),
    ('legacy plain filename',original/'api.py',Path('api.py')),
    ('stub filename',original/'api.pyi',relocated/'api.pyi')]
writer=CatalogWriter(evaluator=None,pkg_dir=str(original))
ids=[writer.ref_type(ModuleType(mod_name=name,file_uri=path,symbol_table=None,is_external=True)) for name,path,_ in paths]
writer.force_all()
reader=StubCatalog(buf=writer.emit('',{}),pkg_dir=str(relocated))
rows=[]
for type_id,(name,_,expected) in zip(ids,paths):
    actual=reader.type_of(type_id).file_uri
    passed=actual==expected if name=='legacy plain filename' else actual.resolve()==expected.resolve()
    rows.append(dict(name=name,status='passed' if passed else 'failed',actual=str(actual),expected=str(expected)))
result=dict(status='passed' if all(r['status']=='passed' for r in rows) else 'failed',
    scope='Real ModuleType catalog roundtrip after relocation, plus unchanged plain-name behavior',cases=rows,
    writer_module_path=str(Path(inspect.getmodule(CatalogWriter).__file__).resolve()),
    reader_module_path=str(Path(inspect.getmodule(StubCatalog).__file__).resolve()))
Path(OUTPUT_PATH).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
raise SystemExit(0 if result['status']=='passed' else 1)
