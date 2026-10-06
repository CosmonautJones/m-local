from pathlib import Path
from uuid import UUID
from unittest.mock import patch
import json
import tempfile

from jaclang import JacRuntimeInterface as JacRI, JacRuntime
from jaclang.server.session import Session
from jaclang.data.pgembed import PgRuntime
from jaclang.data.store import PgStore
from jaclang.data.pgwire import PgWireError
from jaclang.runtime.context import ExecutionContext
from jaclang.runtime.archetype import EdgeAnchor
from services.models import Restaurant, Location, HasLocation

assert Path.cwd().resolve() == Path('/var/tmp/m-local-runtime-fork-01a1050e')
directory = Path(tempfile.mkdtemp(prefix='m-local-runtime-lifecycle-', dir='/var/tmp'))
runtime = PgRuntime(data_dir=str(directory / 'pg'), database='lifecycle')
stores = []
results = []
previous = JacRuntime.exec_ctx
try:
    info = runtime.ensure()
    def new_store(cls=PgStore):
        store = cls(conninfo=info, auto_schema=True)
        stores.append(store)
        return store

    seed = Session(_store=new_store())
    restaurant = Restaurant(slug='lifecycle', name='Fixture')
    location = Location(address='Fixture')
    for item in (restaurant, location):
        item.__jac__.persistent = True
        seed.put(item.__jac__)
    edge = EdgeAnchor(archetype=HasLocation(), source=restaurant.__jac__, target=location.__jac__, is_undirected=False)
    edge.persistent = True
    seed.put(edge)
    with patch.object(JacRI, 'check_write_access', return_value=True):
        seed.commit()

    class CloseFaultStore(PgStore):
        def commit(self):
            raise RuntimeError('Injected fatal commit failure')

    class AbortFaultStore(PgStore):
        def rollback(self):
            super().rollback()
            raise PgWireError({'C': '08006', 'M': 'Injected rollback connection loss'})

    def case(name, action, cls):
        session = Session(_store=new_store(cls))
        ctx = ExecutionContext()
        ctx.mem = session
        JacRuntime.exec_ctx = ctx
        loaded = session.get(edge.id)
        # A clean cached edge is not a newly loaded snapshot read.
        session._snapshot_reads.clear()
        ctx.on_commit(lambda: None)
        caught = None
        try:
            action(session)
        except Exception as error:
            caught = type(error).__name__
        fresh = session.get(edge.id)
        passed = caught is not None and fresh is not loaded and not ctx.pending_effects
        results.append({'case': name, 'passed': passed, 'error_type': caught,
                        'fresh_anchor': fresh is not loaded, 'pending_effects': len(ctx.pending_effects)})

    def read_close(session):
        session._store.rollback()
        session.read_scope_enter()
        session.read_barrier()
        session.read_scope_exit()

    def unit_close(session):
        session.unit_enter()
        session.read_barrier()
        session.unit_exit()

    with patch.object(JacRI, 'check_write_access', return_value=True):
        case('snapshot close failure fails and invalidates clean reads', read_close, CloseFaultStore)
        case('unit close failure cannot report successful uncommitted work', unit_close, CloseFaultStore)
        case('rollback connection loss still clears touched reads and effects', lambda session: session.abort(), AbortFaultStore)
    receipt = {'source': Session.commit.__code__.co_filename, 'cases': results}
    (directory / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))
    print('Retained lifecycle diagnostic:', directory)
    assert all(case['passed'] for case in results), 'Lifecycle failure cleanup failed'
finally:
    JacRuntime.exec_ctx = previous
    for store in stores:
        store.close()
    runtime.stop()
