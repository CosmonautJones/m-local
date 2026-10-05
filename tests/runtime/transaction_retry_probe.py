from jaclang.server.session import Session
from jaclang.data.pgembed import PgRuntime
from jaclang.data.store import PgStore, ConnInfo
from jaclang.data.pgwire import PgWireError
from jaclang.runtime.exceptions import WriteConflict
from jaclang import JacRuntimeInterface as JacRI
from services.models import Restaurant
from unittest.mock import patch
from pathlib import Path
from uuid import UUID
import json
import os
import subprocess
import sys
import tempfile

# Diagnostic only: permission checks are outside this transaction test's scope.
# Real pinned Session/PgStore serialize and persist all writes in a disposable PG.
workspace = Path.cwd().resolve()
if workspace.parent != Path('/var/tmp') or not workspace.name.startswith(('m-local-release-readiness-', 'm-local-runtime-fork-', 'm-local-runtime-proof.')):
    raise ValueError('Run only from a retained disposable diagnostic workspace')
if len(sys.argv) > 1 and sys.argv[1] != '--competitor':
    raise ValueError('Unknown diagnostic mode; refusing to start another database')
if len(sys.argv) > 1 and sys.argv[1] == '--competitor':
    info = ConnInfo(**json.loads(sys.argv[2]))
    db = PgStore(conninfo=info, auto_schema=True)
    session = Session(_store=db)
    try:
        anchor = session.get(UUID(sys.argv[3]))
        with patch.object(JacRI, 'check_write_access', return_value=True):
            anchor.archetype.name = 'Competing committed value'
            session.commit()
        print(json.dumps({'competitor_committed': True, 'version': session._version_seen[anchor.id]}))
    finally:
        db.close()
    raise SystemExit(0)

directory = Path(tempfile.mkdtemp(prefix='m-local-runtime-conflict-', dir='/var/tmp'))
assert directory.resolve().parent == Path('/var/tmp')
runtime = PgRuntime(data_dir=str(directory / 'pg'), database='runtime_probe')
stores = []
try:
    info = runtime.ensure()
    connection = {key: getattr(info, key) for key in ('host', 'port', 'user', 'password', 'database', 'unix_socket_dir')}
    seed_store = PgStore(conninfo=info, auto_schema=True)
    stores.append(seed_store)
    seed = Session(_store=seed_store)
    restaurant = Restaurant(slug='runtime-conflict-fixture', name='Original value')
    anchor = restaurant.__jac__
    anchor.persistent = True
    seed.put(anchor)
    with patch.object(JacRI, 'check_write_access', return_value=True):
        seed.commit()
    seed_store.close()

    class FaultStore(PgStore):
        failures = 0
        commit_calls = 0

        def commit(self):
            self.commit_calls += 1
            if self.failures == 0:
                self.failures += 1
                if os.environ.get('MLOCAL_PROBE_ACCEPTED_COMMIT') == '1':
                    super().commit()
                else:
                    super().rollback()
                application = str(Path(sys.modules[Restaurant.__module__].__file__).parent.parent)
                command = [sys.executable, '-c', 'import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); path=sys.argv.pop(1); runpy.run_path(path,run_name="__main__")', application, __file__, '--competitor', json.dumps(connection), str(anchor.id)]
                # run_path retains its script path as argv[0].
                competitor = subprocess.run(command, text=True, capture_output=True, timeout=30)
                if competitor.returncode:
                    raise RuntimeError(competitor.stderr or competitor.stdout)
                self.competitor = json.loads(competitor.stdout.strip().splitlines()[-1])
                raise PgWireError({'C': os.environ.get('MLOCAL_PROBE_SQLSTATE', '40001'), 'M': 'Injected transaction failure after flush'})
            return super().commit()

    fault_store = FaultStore(conninfo=info, auto_schema=True)
    stores.append(fault_store)
    stale = Session(_store=fault_store)
    loaded = stale.get(anchor.id)
    original_version = stale._version_seen[anchor.id]
    commit_error = ''
    with patch.object(JacRI, 'check_write_access', return_value=True):
        loaded.archetype.name = 'Stale request value'
        try:
            stale.commit()
        except WriteConflict:
            commit_error = 'WriteConflict'
        except PgWireError:
            if os.environ.get('MLOCAL_PROBE_SQLSTATE') != '08006':
                raise
            commit_error = 'CommitUncertain'
    observer = PgStore(conninfo=info, auto_schema=True)
    stores.append(observer)
    final = observer.load_full([anchor.id])[anchor.id]
    final_name = final.props['archetype']['name']
    stale.abort()
    after_abort = stale.get(anchor.id).archetype.name
    result = {'runtime': '0.37.23', 'session_source': Session.commit.__code__.co_filename, 'database': 'disposable PostgreSQL', 'original_version': original_version, 'competitor': fault_store.competitor, 'commit_calls': fault_store.commit_calls, 'commit_error': commit_error, 'final_name': final_name, 'final_version': final.version, 'after_abort': after_abort, 'lost_competing_write': final_name == 'Stale request value'}
    print(json.dumps(result))
    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Retained diagnostic workspace:', directory)
    assert not result['lost_competing_write'], 'Pinned internal commit retry overwrote a competing committed value'
    expected_error = 'CommitUncertain' if os.environ.get('MLOCAL_PROBE_SQLSTATE') == '08006' else 'WriteConflict'
    assert commit_error == expected_error, 'A failed transaction must escape without unsafe internal replay'
    assert fault_store.commit_calls == 1, 'A failed commit must not be repeated internally'
    assert after_abort == 'Competing committed value', 'Abort must discard the mutated cached anchor'
finally:
    for db in stores:
        db.close()
    runtime.stop()
