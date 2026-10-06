from pathlib import Path
from functools import partial
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch
import json
import tempfile

from jaclang import JacRuntimeInterface as JacRI, JacRuntime
from jaclang.data.serializer import Serializer
from jaclang.data.store import AnchorRow, PgStore
from jaclang.data.pgembed import PgRuntime
from jaclang.server.session import Session, _persist_hash
from jaclang.runtime.archetype import NodeAnchor, EdgeAnchor, AccessLevel
from jaclang.runtime.context import ExecutionContext
from services.models import Restaurant, Location, HasLocation

assert Path.cwd().resolve() == Path('/var/tmp/m-local-runtime-fork-01a1050e')
directory = Path(tempfile.mkdtemp(prefix='m-local-materialization-', dir='/var/tmp'))
runtime = PgRuntime(data_dir=str(directory / 'pg'), database='materialization')
stores = []
results = []
previous = JacRuntime.exec_ctx
receipt = {'scope': 'Owned native PG materialization regression; source fork, not sealed package or capacity', 'cases': results}

def case(name, operation):
    try:
        operation()
        results.append({'case': name, 'passed': True})
    except Exception as error:
        results.append({'case': name, 'passed': False, 'error_type': type(error).__name__, 'error': str(error)})

try:
    info = runtime.ensure()
    def new_store():
        value = PgStore(conninfo=info, auto_schema=True)
        stores.append(value)
        return value

    seed = Session(_store=new_store())
    restaurant = Restaurant(slug='hash-fixture', name='Hash fixture')
    location = Location(address='Fixture')
    for item in (restaurant, location):
        item.__jac__.persistent = True
        seed.put(item.__jac__)
    edge = EdgeAnchor(archetype=HasLocation(), source=restaurant.__jac__, target=location.__jac__, is_undirected=False)
    edge.persistent = True
    seed.put(edge)
    with patch.object(JacRI, 'check_write_access', return_value=True):
        seed.commit()
    rows = new_store().load_full([restaurant.__jac__.id, edge.id])

    def standalone(row):
        anchor = Serializer.deserialize(row.props)
        assert anchor.hash != 0
        assert anchor.hash == Serializer._compute_hash(anchor)

    def materialize(row):
        session = Session(_store=new_store())
        expected = Serializer.deserialize(row.props)
        if isinstance(expected, NodeAnchor):
            expected.__dict__.pop('edges', None)
            expected.__dict__['_edge_loader'] = partial(session._load_edges, expected)
            expected.version = row.version
        expected_hash = _persist_hash(expected)
        with patch.object(Serializer, 'serialize', wraps=Serializer.serialize) as calls:
            actual = session._materialize(row)
        assert actual is not None and actual.hash != 0
        assert actual.hash == expected_hash == session._flushed_hash[row.id]
        assert session.__mem__[row.id] is actual
        assert calls.call_count == 1, f'Expected one final serialization, observed {calls.call_count}'

    def lazy_edges():
        session = Session(_store=new_store())
        first = session.get(restaurant.__jac__.id)
        assert '_edge_loader' in first.__dict__ and 'edges' not in first.__dict__
        assert [e.id for e in first.edges] == [edge.id]
        session.abort()
        second = session.get(restaurant.__jac__.id)
        assert second is not first
        assert [e.id for e in second.edges] == [edge.id]
        assert second.hash == session._flushed_hash[second.id] != 0

    def bad_payload(props, default_dispatch):
        store = new_store()
        session = Session(_store=store)
        row = AnchorRow(id=uuid4(), kind='node', props=props)
        with patch.object(store, 'quarantine') as quarantine:
            with patch.object(Serializer, 'deserialize', wraps=Serializer.deserialize) as dispatch:
                assert session._materialize(row) is None
        quarantine.assert_called_once_with(row.id, None, row.kind)
        assert row.id not in session.__mem__ and row.id not in session._flushed_hash
        if default_dispatch:
            dispatch.assert_called_once_with(props)

    def access_hash():
        session = Session(_store=new_store())
        loaded = session.get(restaurant.__jac__.id)
        assert loaded.persistent and loaded.hash != 0
        with patch.object(JacRI, 'get_context', return_value=SimpleNamespace(user_root=None)):
            assert JacRI.check_access_level(loaded) == AccessLevel.NO_ACCESS
        foreign = SimpleNamespace(user_root=SimpleNamespace(id=uuid4()), system_root=SimpleNamespace(id=uuid4()))
        def custom_access(item):
            assert item.__jac__.hash != 0
            return AccessLevel.NO_ACCESS
        with patch.object(JacRI, 'get_context', return_value=foreign):
            with patch.object(Restaurant, '__jac_access__', side_effect=custom_access, autospec=True) as custom:
                assert JacRI.check_access_level(loaded) == AccessLevel.NO_ACCESS
                custom.assert_called_once_with(loaded.archetype)

    for label, row in zip(('node', 'edge'), rows.values()):
        case('standalone nonzero full hash ' + label, lambda row=row: standalone(row))
        case('one serialization and unchanged final baseline ' + label, lambda row=row: materialize(row))
    case('lazy edges reload after abort', lazy_edges)
    case('malformed anchor quarantined', lambda: bad_payload({'__type__': 'NodeAnchor', 'id': 'invalid'}, False))
    case('unknown legacy payload retains default dispatch', lambda: bad_payload({'__type__': 'UnknownLegacyPayload'}, True))
    case('null payload quarantined through public dispatch', lambda: bad_payload(None, True))
    case('list payload quarantined through public dispatch', lambda: bad_payload([], True))
    case('string payload quarantined through public dispatch', lambda: bad_payload('corrupt', True))
    case('materialized persisted anchor cannot take zero-hash WRITE shortcut', access_hash)
finally:
    JacRuntime.exec_ctx = previous
    for store in stores:
        store.close()
    runtime.stop()
    receipt['postgres_stopped'] = not runtime.is_running()
    receipt['workspace'] = str(directory)
    receipt['source'] = Session._materialize.__code__.co_filename
    receipt['status'] = 'passed' if len(results) == 11 and all(row['passed'] for row in results) and receipt['postgres_stopped'] else 'failed'
    (directory / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)
assert receipt['status'] == 'passed'
