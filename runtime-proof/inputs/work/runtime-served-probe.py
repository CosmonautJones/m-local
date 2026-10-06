from jaclang.server.session import Session
from jaclang.server.server import ExecutionManager
from jaclang.data.pgembed import PgRuntime
from jaclang.data.store import PgStore
from jaclang.data.pgwire import PgWireError
from jaclang import JacRuntimeInterface as JacRI, JacRuntime
from jaclang.runtime.context import ExecutionContext
from jaclang.runtime.archetype import Root, EdgeAnchor, GenericEdge
from jaclang.runtime.constants import Constants as Con
from services.models import Restaurant, Location, HasLocation
from unittest.mock import patch
from pathlib import Path
from uuid import UUID
import asyncio
import json
import hashlib
import subprocess
import tempfile

assert Path.cwd().resolve() == Path('/var/tmp/m-local-runtime-fork-01a1050e')
directory = Path(tempfile.mkdtemp(prefix='m-local-runtime-served-', dir='/var/tmp'))
runtime = PgRuntime(data_dir=str(directory / 'pg'), database='served_replay')
stores = []
previous = JacRuntime.exec_ctx
results = []
try:
    info = runtime.ensure()
    def new_store(cls=PgStore):
        store = cls(conninfo=info, auto_schema=True)
        stores.append(store)
        return store

    seed = Session(_store=new_store())
    system = Root().__jac__
    system.id = UUID(Con.SUPER_ROOT_UUID)
    user = Root().__jac__
    shared = Root().__jac__
    for root in (system, user, shared):
        root.persistent = True
        seed.put(root)
    with patch.object(JacRI, 'check_write_access', return_value=True):
        seed.commit()

    class Users:
        async def aget_root_id(self, username):
            return str(user.id)

    async def run_case(name, change_writer, edge_read=False, root_read=False, fault_at='commit', nested=False, sqlstate='40001', always_fail=False, accepted_commit=False, wrapped=False):
        reader = Restaurant(slug=name + '-read', name='Original read')
        writer = Restaurant(slug=name + '-write', name='Original write')
        for item in (reader, writer):
            item.__jac__.persistent = True
            seed.put(item.__jac__)
        reader_id = reader.__jac__.id
        if edge_read:
            location = Location(address='Fixture')
            location.__jac__.persistent = True
            seed.put(location.__jac__)
            edge = EdgeAnchor(archetype=HasLocation(), source=reader.__jac__, target=location.__jac__, is_undirected=False)
            edge.persistent = True
            seed.put(edge)
            reader_id = edge.id
        seed.commit()
        observed = []
        inject_enabled = [True]
        class FaultStore(PgStore):
            failed = False
            def inject(self):
                if self.failed and always_fail:
                    super().rollback()
                    raise PgWireError({'C': sqlstate, 'M': 'Injected repeated query conflict'})
                if not self.failed and inject_enabled[0]:
                    self.failed = True
                    if accepted_commit:
                        super().commit()
                        raise PgWireError({'C': '08006', 'M': 'Injected lost COMMIT acknowledgement'})
                    super().rollback()
                    competitor = Session(_store=new_store())
                    if root_read:
                        root = competitor.get(system.id)
                        target = competitor.get(writer.__jac__.id)
                        link = EdgeAnchor(archetype=GenericEdge(), source=root, target=target, is_undirected=False)
                        link.persistent = True
                        competitor.put(link)
                    if edge_read:
                        competitor.get(reader_id).is_undirected = True
                    else:
                        competitor.get(reader_id).archetype.name = 'Fresh competing read'
                    if change_writer:
                        competitor.get(writer.__jac__.id).archetype.name = 'Competing write'
                    competitor.commit()
                    error = PgWireError({'C': sqlstate, 'M': 'Injected served transaction conflict'})
                    if wrapped:
                        raise RuntimeError('Wrapped query failure') from error
                    raise error
            def commit(self):
                if fault_at == 'commit':
                    self.inject()
                return super().commit()
            def upsert(self, rows):
                if fault_at == 'barrier':
                    self.inject()
                return super().upsert(rows)
            def existing(self, ids):
                if fault_at == 'has':
                    self.inject()
                return super().existing(ids)
            def load_full(self, ids):
                if fault_at == 'batch' and UUID(int=42) in ids:
                    self.inject()
                return super().load_full(ids)
            def rows(self, sql, params):
                if fault_at == 'query':
                    self.inject()
                return super().rows(sql, params)

        session = Session(_store=new_store(FaultStore))
        parent = ExecutionContext()
        parent.mem = session
        JacRuntime.exec_ctx = parent
        JacRuntime.set_shared_root_resolver(lambda: str(shared.id))
        session.get(reader_id)  # A populated clean cache entry from an earlier request.
        manager = ExecutionManager(base_path=str(Path.cwd()), user_manager=Users())
        def body():
            ctx = JacRI.get_context()
            if nested:
                def nested_body():
                    assert JacRI.peek_context() is ctx
                    loaded = ctx.mem.get(reader_id)
                    assert reader_id in ctx.read_ids
                    return loaded
                # The nested read commits before the outer write, so inject later.
                inject_enabled[0] = False
                try:
                    loaded = ctx.mem.run_request(nested_body)
                finally:
                    inject_enabled[0] = True
            else:
                loaded = ctx.mem.get(reader_id)
            value = str(len(ctx.system_root.edges)) if root_read else str(loaded.is_undirected) if edge_read else loaded.archetype.name
            observed.append(value)
            ctx.mem.get(writer.__jac__.id).archetype.name = value
            if fault_at == 'barrier':
                ctx.mem.read_barrier()
            elif fault_at == 'has':
                assert not ctx.mem.has(UUID(int=42))
            elif fault_at == 'batch':
                assert not ctx.mem.batch_get([UUID(int=42)])
            elif fault_at == 'query':
                assert ctx.mem.store.rows('SELECT 1', {}) == [(1,)]
            assert JacRuntime.get_shared_root() is not None
            assert ctx.system_root.id == system.id and ctx.user_root.id == user.id
            return {'read': value, 'attempt': len(observed)}
        response = await manager.execute_function(body, {}, 'synthetic-user')
        row = new_store().load_full([writer.__jac__.id])[writer.__jac__.id]
        expected = ['0', '1'] if root_read else ['False', 'True'] if edge_read else ['Original read', 'Fresh competing read']
        passed = observed == expected and row.props['archetype']['name'] == expected[-1]
        if sqlstate == '08006':
            passed = (len(observed) == 1 and response.get('http_status') == 503 and
                      response.get('error_code') == 'commit_uncertain' and
                      row.props['archetype']['name'] == ('False' if accepted_commit else 'Original write'))
        elif always_fail:
            passed = (len(observed) == 5 and response.get('http_status') == 409 and
                      response.get('error_code') == 'write_conflict' and row.props['archetype']['name'] == 'Original write')
        elif sqlstate == '23505':
            passed = (len(observed) == 1 and response.get('error_code') == 'execution_error' and
                      row.props['archetype']['name'] == 'Original write')
        if root_read:
            next_response = await manager.execute_function(body, {}, 'synthetic-user')
            passed = passed and next_response['result']['read'] == '1'
        results.append({'case': name, 'passed': passed, 'observed': observed, 'response': response, 'final': row.props['archetype']['name']})

    with patch.object(JacRI, 'check_write_access', return_value=True):
        asyncio.run(run_case('served conflict invalidates clean reads and refreshes roots', True))
        asyncio.run(run_case('served SQLSTATE replays body even when write row did not compete', False))
        asyncio.run(run_case('served conflict refreshes a clean edge read', True, True))
        asyncio.run(run_case('system-root pointer refreshes on replay and the next request', True, root_read=True))
        asyncio.run(run_case('read barrier conflict replays a body that observed a clean edge', False, True, fault_at='barrier'))
        asyncio.run(run_case('has conflict replays a body that observed a clean edge', False, True, fault_at='has'))
        asyncio.run(run_case('batch lookup conflict replays a body that observed a clean edge', False, True, fault_at='batch'))
        asyncio.run(run_case('commit SQLSTATE replays noncompeting writes derived from a clean edge', False, True))
        asyncio.run(run_case('nested run_request reads belong to the outer served replay', False, True, nested=True))
        for code in ('40001', '40P01', '55P03', '08006'):
            asyncio.run(run_case('raw graph query ' + code + ' has bounded safe failure behavior', False, True, fault_at='query', sqlstate=code))
        asyncio.run(run_case('lost COMMIT acknowledgement returns uncertain 503 without body replay', False, True, sqlstate='08006', accepted_commit=True))
        asyncio.run(run_case('wrapped graph query serialization conflict replays the body', False, True, fault_at='query', wrapped=True))
        asyncio.run(run_case('persistent raw query conflict stops after five attempts with 409', False, True, fault_at='query', always_fail=True))
        asyncio.run(run_case('nonretryable raw query failure is not replayed', False, True, fault_at='query', sqlstate='23505'))
    receipt = {'source': Session.commit.__code__.co_filename, 'cases': results,
               'runtime_base_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
               'runtime_patch_sha256': hashlib.sha256(subprocess.check_output(['git', 'diff', '--binary'])).hexdigest(),
               'executed_proof_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'application_model_jac_sha256': hashlib.sha256(Path('/var/tmp/m-local-release-readiness-01a1050e/services/models.jac').read_bytes()).hexdigest(),
               'scope': 'Real PostgreSQL served-manager diagnostic; permission admission substituted; source override; not HTTP or capacity'}
    (directory / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))
    print('Retained served-loop diagnostic:', directory)
    assert all(case['passed'] for case in results), 'Served replay regression failed'
finally:
    JacRuntime.set_shared_root_resolver(None)
    JacRuntime.exec_ctx = previous
    for store in stores:
        store.close()
    runtime.stop()
