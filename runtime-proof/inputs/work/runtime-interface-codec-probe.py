from pathlib import Path
import inspect
import json
import os
import tempfile
from jaclang.compiler.types.stubcat.writer import CatalogWriter
from jaclang.compiler.types.stubcat.reader import StubCatalog
from jaclang.compiler.types.types import ModuleType

os.umask(0o077)
fork = Path('/var/tmp/m-local-runtime-fork-01a1050e/jac')
for declaration in (CatalogWriter,StubCatalog,ModuleType):
    assert Path(inspect.getmodule(declaration).__file__).resolve().is_relative_to(fork)
root = Path(tempfile.mkdtemp(prefix='m-local-interface-codec-',dir='/var/tmp'))
original = root/'original/site/jaclang'
relocated = root/'relocated/site/jaclang'
original.mkdir(parents=True)
relocated.mkdir(parents=True)
writer = CatalogWriter(evaluator=None,pkg_dir=str(original))
paths = [original.parent,original.parent/'watchdog/observers/api.py']
ids = [writer.ref_type(ModuleType(mod_name=name,file_uri=path,symbol_table=None,is_external=True))
    for name,path in zip(('site','watchdog.observers.api'),paths)]
writer.force_all()
encoded = writer.emit('',{})
reader = StubCatalog(buf=encoded,pkg_dir=str(relocated))
rows = []
for type_id,path in zip(ids,paths):
    decoded = reader.type_of(type_id)
    actual = decoded.file_uri.resolve()
    expected = (relocated/Path(os.path.relpath(path,original))).resolve()
    rows.append(dict(name=decoded.mod_name,status='passed' if actual==expected else 'failed',actual=str(actual),expected=str(expected)))
result = dict(status='passed' if all(row['status']=='passed' for row in rows) else 'failed',
    scope='Real ModuleType SEC_IFACE catalog serialization and cold reader hydration at a relocated site root',
    writer_module_path=str(Path(inspect.getmodule(CatalogWriter).__file__).resolve()),
    reader_module_path=str(Path(inspect.getmodule(StubCatalog).__file__).resolve()),cases=rows)
Path(OUTPUT_PATH).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
raise SystemExit(0 if result['status']=='passed' else 1)
