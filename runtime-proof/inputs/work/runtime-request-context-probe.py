from pathlib import Path
from uuid import UUID
from unittest.mock import patch
import asyncio
import json
import tempfile

from jaclang import JacRuntimeInterface as JacRI, JacRuntime
from jaclang.server.session import Session
from jaclang.server.middleware import request_context_middleware
from jaclang.server.server import ExecutionManager
from jaclang.server.serving.datatypes import Request, URL, JSONResponse
from jaclang.runtime.archetype import Root
from jaclang.runtime.constants import Constants as Con
from jaclang.data.pgembed import PgRuntime
from jaclang.data.store import PgStore
from services.models import Restaurant

assert Path.cwd().resolve() == Path('/var/tmp/m-local-runtime-fork-01a1050e')
directory = Path(tempfile.mkdtemp(prefix='m-local-runtime-context-', dir='/var/tmp'))
runtime = PgRuntime(data_dir=str(directory / 'pg'), database='request_contexts')
stores = []
previous = JacRuntime.exec_ctx
result = None
try:
    info = runtime.ensure()
    def new_store():
        store = PgStore(conninfo=info, auto_schema=True)
        stores.append(store)
        return store
    seed = Session(_store=new_store())
    system = Root().__jac__
    system.id = UUID(Con.SUPER_ROOT_UUID)
    system.persistent = True
    seed.put(system)
    user = Root().__jac__
    user.persistent = True
    seed.put(user)
    ids = []
    with patch.object(JacRI, 'check_write_access', return_value=True):
        for suffix in ('a', 'b'):
            item = Restaurant(slug='concurrent-' + suffix, name='Original ' + suffix)
            item.__jac__.persistent = True
            seed.put(item.__jac__)
            ids.append(item.__jac__.id)
        seed.commit()

    # Only database binding is substituted; the production context factory,
    # request middleware and served execution manager run unchanged.
    original_factory = JacRuntime.create_j_context
    def factory(user_root=None):
        ctx = original_factory(user_root, base_path_dir=str(Path.cwd()),
                               full_target_path=str(Path.cwd() / 'main.jac'))
        assert isinstance(ctx.mem, Session)
        ctx.mem.store = new_store()
        return ctx
    class Users:
        async def aget_root_id(self, username):
            return str(user.id)

    async def run():
        entered = 0
        ready = asyncio.Event()
        outer = []
        inner = []
        contexts = {}
        tracking = []
        async def call_next(request):
            nonlocal entered
            index = int(request.request_id)
            outer_ctx = JacRI.peek_context()
            outer.append((index, outer_ctx.mem))
            contexts[index] = outer_ctx
            manager = ExecutionManager(base_path=str(Path.cwd()), user_manager=Users())
            async def body():
                nonlocal entered
                ctx = JacRI.peek_context()
                assert ctx is not outer_ctx and ctx.mem is outer_ctx.mem
                inner.append((index, ctx.mem))
                item = ctx.mem.get(ids[index])
                ctx.note_traversal_reads([item])
                entered += 1
                if entered == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), timeout=5)
                assert JacRI.peek_context() is ctx
                peer = contexts[1 - index]
                tracking.append(ctx.read_ids is outer_ctx.read_ids and ctx.read_versions is outer_ctx.read_versions
                    and ctx.read_ids is not peer.read_ids and ctx.read_versions is not peer.read_versions
                    and ids[index] in ctx.read_ids and ids[index] in ctx.read_versions
                    and ids[1 - index] not in ctx.read_ids and ids[1 - index] not in ctx.read_versions)
                item.archetype.name = 'Committed request ' + str(index)
                return {'index': index}
            response = await manager.execute_function(body, {}, 'fixture')
            assert 'error' not in response
            return JSONResponse(response)
        middleware = request_context_middleware()
        return await asyncio.gather(*[
            middleware(Request(method='POST', url=URL(path='/function/fixture'), request_id=str(index)), call_next)
            for index in range(2)
        ]), outer, inner, contexts, tracking

    with patch.object(JacRuntime, 'create_j_context', side_effect=factory), patch.object(JacRI, 'check_write_access', return_value=True):
        before = JacRI.peek_context()
        responses, outer, inner, contexts, tracking = asyncio.run(run())
    rows = new_store().load_full(ids)
    result = {'scope': 'real request middleware and served manager; substituted disposable database binding; no HTTP socket',
              'separate_request_sessions': len(outer) == 2 and outer[0][1] is not outer[1][1],
              'nested_contexts_reuse_own_request_session': len(inner) >= 2 and all(dict(outer)[index] is mem for index, mem in inner),
              'served_body_attempts': len(inner),
              'both_responses_successful': all(response.status_code == 200 for response in responses),
              'distinct_writes_committed': all(rows[ident].props['archetype']['name'] == 'Committed request ' + str(index) for index, ident in enumerate(ids)),
              'own_session_shares_tracking_without_cross_request_reads': bool(tracking) and all(tracking),
              'tracking_cleared_at_request_completion': all(not ctx.read_ids and not ctx.read_versions and not ctx.mem.__mem__ for ctx in contexts.values()),
              'request_context_restored_after_completion': JacRI.peek_context() is before,
              'source': Session.commit.__code__.co_filename}
finally:
    JacRuntime.exec_ctx = previous
    for store in stores:
        store.close()
    runtime.stop()
    if result is not None:
        result['postgres_stopped'] = not runtime.is_running()
        result['workspace'] = str(directory)
        (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
assert result is not None and all(result[key] for key in ('separate_request_sessions', 'nested_contexts_reuse_own_request_session', 'both_responses_successful', 'distinct_writes_committed', 'own_session_shares_tracking_without_cross_request_reads', 'tracking_cleared_at_request_completion', 'request_context_restored_after_completion', 'postgres_stopped'))
