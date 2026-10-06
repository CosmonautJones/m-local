from jaclang.server.session import Session
from jaclang.data.pgembed import PgRuntime
from jaclang.data.store import PgStore
from jaclang.data.pgwire import PgWireError
from jaclang.runtime.exceptions import WriteConflict
from jaclang import JacRuntimeInterface as JacRI
from services.models import Restaurant
from unittest.mock import patch
from pathlib import Path
import json
import tempfile

workspace = Path.cwd().resolve()
assert workspace == Path('/var/tmp/m-local-runtime-fork-01a1050e')
directory = Path(tempfile.mkdtemp(prefix='m-local-runtime-boundary-', dir='/var/tmp'))
runtime = PgRuntime(data_dir=str(directory / 'pg'), database='runtime_boundaries')
stores = []
results = []
try:
    info = runtime.ensure()

    def new_store(cls=PgStore):
        store = cls(conninfo=info, auto_schema=True)
        stores.append(store)
        return store

    def seed(name):
        store = new_store()
        session = Session(_store=store)
        item = Restaurant(slug=name, name='Original value')
        item.__jac__.persistent = True
        session.put(item.__jac__)
        session.commit()
        return item.__jac__.id

    def run(name, body):
        try:
            body()
            results.append({'case': name, 'passed': True})
        except Exception as error:
            results.append({'case': name, 'passed': False, 'error': str(error)})

    with patch.object(JacRI, 'check_write_access', return_value=True):
        def aborted_delete():
            ident = seed('aborted-delete')
            session = Session(_store=new_store())
            session.get(ident)
            session.delete(ident)
            session.flush()
            session.abort()
            assert ident not in session._version_seen, 'Aborted deletion retains a cached version'
            assert ident not in session._flushed_hash
            assert session.get(ident).archetype.name == 'Original value'
            session.get(ident).archetype.name = 'Updated after abort'
            session.commit()
            assert new_store().load_full([ident])[ident].props['archetype']['name'] == 'Updated after abort'

        def multiple_flushes():
            ident = seed('multiple-flushes')
            session = Session(_store=new_store())
            item = session.get(ident)
            initial = session._version_seen[ident]
            item.archetype.name = 'First uncommitted value'
            session.flush(full=True)
            item.archetype.name = 'Second uncommitted value'
            session.flush(full=True)
            assert session._txn_expected_versions[ident] == initial
            session._recover_conflict()
            assert session._version_seen[ident] == initial
            assert item.version == initial
            session.commit()
            row = new_store().load_full([ident])[ident]
            assert row.props['archetype']['name'] == 'Second uncommitted value'
            assert row.version == initial + 1
            assert not session._txn_expected_versions

        class BeforeUpsertStore(PgStore):
            attempts = 0

            def upsert(self, rows):
                self.attempts += 1
                if self.attempts == 1:
                    raise PgWireError({'C': '40001', 'M': 'Injected before any upsert lands'})
                return super().upsert(rows)

        def failed_upsert():
            ident = seed('before-upsert')
            store = new_store(BeforeUpsertStore)
            session = Session(_store=store)
            session.get(ident).archetype.name = 'Retried unchanged baseline'
            session.commit()
            assert store.attempts == 2
            assert new_store().load_full([ident])[ident].props['archetype']['name'] == 'Retried unchanged baseline'

        run('abort flushed deletion; reload and update', aborted_delete)
        run('multiple flushes retain original CAS version', multiple_flushes)
        run('upsert failure before landing retries unchanged baseline', failed_upsert)

    receipt = {'source': Session.commit.__code__.co_filename, 'cases': results}
    (directory / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))
    print('Retained boundary diagnostic:', directory)
    assert all(case['passed'] for case in results), 'Runtime boundary regressions failed'
finally:
    for store in stores:
        store.close()
    runtime.stop()
