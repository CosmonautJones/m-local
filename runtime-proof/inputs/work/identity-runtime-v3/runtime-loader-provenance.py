from pathlib import Path
import json
import jaclang
from jaclang.data.serializer import Serializer
from jaclang.server.session import Session
from jaclang.data.store import PgStore
from jaclang.server.identity.identity_storage import PgIdentityStorage, IdentityStorage
from jaclang.server.identity.user_manager import UserManager
from jaclang.server.server import _run_function_with_occ
from jaclang.runtime.context import ExecutionContext
from jaclang.scale.memory.context import JScaleExecutionContext

root = Path('/var/tmp/m-local-build-e-drive-01a1050e/identity-type-source-v3-6c9r0m6y/fork').resolve()
parts = {'PgStore._main': PgStore._main, 'PgStore._run': PgStore._run, 'PgStore._discard_main': PgStore._discard_main,
    'PgStore.begin': PgStore.begin, 'PgStore.commit': PgStore.commit, 'PgStore.rollback': PgStore.rollback,
    'PgIdentityStorage.ensure_indexes': PgIdentityStorage.ensure_indexes, 'PgIdentityStorage._store_user': PgIdentityStorage._store_user,
    'IdentityStorage.create_user': IdentityStorage.create_user, 'UserManager.ensure_internal_user': UserManager.ensure_internal_user,
    'Serializer._deserialize_anchor': Serializer._deserialize_anchor,
         'Session._materialize': Session._materialize,
         'Session.commit': Session.commit,
         'served._run_function_with_occ': _run_function_with_occ,
         'JScaleExecutionContext.__init__': JScaleExecutionContext.__init__}
for name in ('__post_init__', 'postinit'):
    method = getattr(ExecutionContext, name, None)
    if method is not None and hasattr(method, '__code__'):
        parts['ExecutionContext.' + name] = method
paths = {name: str(Path(method.__code__.co_filename).resolve()) for name, method in parts.items()}
assert len(paths) >= 16, 'Context initialization implementation provenance missing'
assert all(Path(value).is_relative_to(root) for value in paths.values()), paths
runtime_roots = [str(Path(value).resolve()) for value in jaclang.__path__]
assert runtime_roots and all(Path(value).is_relative_to(root) for value in runtime_roots)
receipt = dict(status='passed', runtime_roots=runtime_roots, implementation_files=paths)
Path(OUTPUT_PATH).write_text(json.dumps(receipt, indent=2) + '\n')
