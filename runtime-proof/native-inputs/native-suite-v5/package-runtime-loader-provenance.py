from pathlib import Path
import json
import os
import sys
import jaclang
from jaclang.data.serializer import Serializer
from jaclang.server.session import Session
from jaclang.data.store import PgStore
from jaclang.server.identity.identity_storage import PgIdentityStorage, IdentityStorage
from jaclang.server.identity.user_manager import UserManager
from jaclang.server.server import _run_function_with_occ
from jaclang.runtime.context import ExecutionContext
from jaclang.scale.memory.context import JScaleExecutionContext

root = Path(os.environ['JAC_CACHE_HOME']).resolve()
assert os.environ.get('JAC_NO_DEV_SOURCE') == '1' and not os.environ.get('JAC_DEV_SOURCE')
parts = {'PgStore._main': PgStore._main, 'PgStore._run': PgStore._run, 'PgStore._discard_main': PgStore._discard_main,
    'PgStore.begin': PgStore.begin, 'PgStore.commit': PgStore.commit, 'PgStore.rollback': PgStore.rollback,
    'PgIdentityStorage.ensure_indexes': PgIdentityStorage.ensure_indexes, 'PgIdentityStorage._store_user': PgIdentityStorage._store_user,
    'IdentityStorage.create_user': IdentityStorage.create_user, 'UserManager.ensure_internal_user': UserManager.ensure_internal_user,
    'Serializer._deserialize_anchor': Serializer._deserialize_anchor,
    'Session._materialize': Session._materialize, 'Session.commit': Session.commit,
    'served._run_function_with_occ': _run_function_with_occ,
    'JScaleExecutionContext.__init__': JScaleExecutionContext.__init__}
for name in ('__post_init__', 'postinit'):
    method = getattr(ExecutionContext, name, None)
    if method is not None and hasattr(method, '__code__'):
        parts['ExecutionContext.' + name] = method
assert len(parts) >= 16
modules = {name: str(Path(sys.modules[method.__module__].__file__).resolve()) for name, method in parts.items()}
assert all(Path(value).is_relative_to(root) for value in modules.values())
runtime_roots = [str(Path(value).resolve()) for value in jaclang.__path__]
assert runtime_roots and all(Path(value).is_relative_to(root) for value in runtime_roots)
receipt = dict(status='passed', sdk_roots=runtime_roots, declaring_module_files=modules,
    method_debug_filenames={name: method.__code__.co_filename for name, method in parts.items()},
    debug_filename_scope='Historical code metadata; not live source-loader location', source_override=False)
Path(OUTPUT_PATH).write_text(json.dumps(receipt, indent=2) + '\n')
