from pathlib import Path
from uuid import UUID
from unittest.mock import patch
import asyncio
import json
import tempfile

from jaclang import JacRuntimeInterface as JacRI, JacRuntime
from jaclang.server.session import Session
from jaclang.server.server import ExecutionManager
from jaclang.runtime.context import ExecutionContext
from jaclang.scale.memory.context import JScaleExecutionContext
from jaclang.runtime.archetype import Root, EdgeAnchor
from jaclang.runtime.constants import Constants as Con
from jaclang.data.pgembed import PgRuntime
from jaclang.data.pgwire import PgWireError
from jaclang.data.store import PgStore
from services.models import Restaurant, Location, HasLocation

assert Path.cwd().resolve() == Path('/var/tmp/m-local-runtime-fork-01a1050e')
directory = Path(tempfile.mkdtemp(prefix='m-local-runtime-nested-', dir='/var/tmp'))
runtime = PgRuntime(data_dir=str(directory / 'pg'), database='nested_contexts')
stores = []
results = []
previous = JacRuntime.exec_ctx
receipt = dict(scope='Native PG, real child context/served manager and scale constructor; fixture admission substituted; not HTTP, sealed or capacity', cases=results)

def case(name, operation):
    try:
        results.append(dict(case=name, passed=True, **operation()))
    except Exception as error:
        results.append(dict(case=name, passed=False, error_type=type(error).__name__, error=str(error)))

try:
    info = runtime.ensure()
    def new_store(cls=PgStore):
        value = cls(conninfo=info, auto_schema=True)
        stores.append(value)
        return value
    seed = Session(_store=new_store())
    system, user = Root().__jac__, Root().__jac__
    system.id = UUID(Con.SUPER_ROOT_UUID)
    for root in (system, user):
        root.persistent = True
        seed.put(root)
    with patch.object(JacRI, 'check_write_access', return_value=True):
        seed.commit()

    class Users:
        async def aget_root_id(self, username):
            return str(user.id)

    def new_parent(scale):
        return JScaleExecutionContext() if scale else ExecutionContext()

    def retry(fault_at, scale=False):
        reader = Restaurant(slug=f'nested-{fault_at}-{scale}-read', name='Reader')
        writer = Restaurant(slug=f'nested-{fault_at}-{scale}-write', name='Original write')
        location = Location(address='Fixture')
        for item in (reader, writer, location):
            item.__jac__.persistent = True
            seed.put(item.__jac__)
        edge = EdgeAnchor(archetype=HasLocation(), source=reader.__jac__, target=location.__jac__, is_undirected=False)
        edge.persistent = True
        seed.put(edge)
        seed.commit()
        observed, sharing, cleanups = [], [], []
        class FaultStore(PgStore):
            injected = False
            def inject(self):
                if self.injected:
                    return
                self.injected = True
                super().rollback()
                competitor = Session(_store=new_store())
                competitor.get(edge.id).is_undirected = True
                competitor.commit()
                raise PgWireError({'C': '40001', 'M': 'Injected outer conflict after real child read'})
            def commit(self):
                if fault_at == 'commit':
                    self.inject()
                return super().commit()
            def upsert(self, rows):
                if fault_at == 'barrier':
                    self.inject()
                return super().upsert(rows)
        class TrackedSession(Session):
            def abort(self):
                ctx = JacRI.peek_context()
                super().abort()
                cleanups.append(not ctx.read_ids and not ctx.read_versions and edge.id not in self.__mem__)
        session = TrackedSession(_store=new_store(FaultStore))
        parent = new_parent(scale)
        parent.mem = session
        JacRuntime.exec_ctx = parent
        session.get(edge.id)
        parent.read_ids.clear()
        manager = ExecutionManager(base_path=str(Path.cwd()), user_manager=Users())
        def body():
            outer = JacRI.get_context()
            child = ExecutionContext(_parent=outer)
            token = JacRuntime.push_request_context(child)
            try:
                loaded = child.mem.get(edge.id)
                child.note_traversal_reads([child.mem.get(reader.__jac__.id)])
                value = str(loaded.is_undirected)
                sharing.append(child.mem is outer.mem and child.read_ids is outer.read_ids
                    and child.read_versions is outer.read_versions and edge.id in outer.read_ids
                    and reader.__jac__.id in outer.read_versions)
                child.close()
            finally:
                JacRuntime.reset_request_context(token)
            assert JacRI.peek_context() is outer
            observed.append(value)
            outer.mem.get(writer.__jac__.id).archetype.name = value
            if fault_at == 'barrier':
                outer.mem.read_barrier()
            return {'value': value}
        response = asyncio.run(manager.execute_function(body, {}, 'fixture'))
        final = new_store().load_full([writer.__jac__.id])[writer.__jac__.id].props['archetype']['name']
        detail = dict(observed=observed, shared_tracking=sharing, abort_cleared_tracking=cleanups, final=final)
        assert observed == ['False', 'True'] and all(sharing) and cleanups == [True] and final == 'True' and 'error' not in response, detail
        return detail

    def isolation():
        contexts = [JScaleExecutionContext(), JScaleExecutionContext()]
        assert contexts[0].mem is not contexts[1].mem
        assert contexts[0].read_ids is not contexts[1].read_ids
        assert contexts[0].read_versions is not contexts[1].read_versions
        assert not any(ctx.read_ids or ctx.read_versions for ctx in contexts)
        contexts[0].read_ids.add(UUID(int=42))
        contexts[0].read_versions[UUID(int=42)] = 7
        assert UUID(int=42) not in contexts[1].read_ids and UUID(int=42) not in contexts[1].read_versions
        return dict(distinct_scale_sessions=True, distinct_tracking=True)

    with patch.object(JacRI, 'check_write_access', return_value=True):
        case('real child edge read refreshes after outer COMMIT conflict', lambda: retry('commit'))
        case('real child edge read refreshes after outer read barrier conflict', lambda: retry('barrier'))
        case('scale parent with real child refreshes after outer COMMIT conflict', lambda: retry('commit', True))
        case('independent scale constructors have independent read tracking', isolation)
finally:
    JacRuntime.exec_ctx = previous
    for store in stores:
        store.close()
    runtime.stop()
    receipt['postgres_stopped'] = not runtime.is_running()
    receipt['workspace'] = str(directory)
    receipt['status'] = 'passed' if len(results) == 4 and all(row['passed'] for row in results) and receipt['postgres_stopped'] else 'failed'
    (directory / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)
assert receipt['status'] == 'passed'
