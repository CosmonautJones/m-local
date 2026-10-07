"""TEST ONLY: inject database acknowledgement faults into stock Jac native HTTP.

Never imported by M-Local. The harness copies this helper into a private minimal
application. Only PgStore.commit is wrapped; Session, request replay, cache,
authorization and the installed runtime payload stay unchanged. The injection
performs a real PostgreSQL COMMIT or ROLLBACK before raising a PgWireError.
"""
import json
import os
from pathlib import Path
import threading

from jaclang import JacRuntimeInterface as JacRI
from jaclang.data.pgwire import PgWireError
from jaclang.data.store import PgStore
from tests.integration.stock_topology_models import ProofRecord

_lock = threading.Lock()
_original_commit = PgStore.commit
_fault = None
_events = []


def _receipt(event):
    _events.append(event)
    Path(os.environ['STOCK_PROOF_EVENTS']).write_text(json.dumps(_events, indent=2) + '\n')


def _commit(store):
    global _fault
    with _lock:
        fault, _fault = _fault, None
    if fault is None or not store.in_txn():
        return _original_commit(store)
    mode, sqlstate = fault
    if mode == 'process_death_before_commit':
        _receipt(dict(mode=mode, real_database_action='NO_COMMIT_PROCESS_EXIT', exit_code=77))
        os._exit(77)
    if mode == 'process_death_after_commit':
        _original_commit(store)
        _receipt(dict(mode=mode, real_database_action='COMMIT_THEN_PROCESS_EXIT', exit_code=78))
        os._exit(78)
    if mode == 'accepted_ack_loss':
        _original_commit(store)
    else:
        store.rollback()
    _receipt(dict(mode=mode, sqlstate=sqlstate, real_database_action=(
        'COMMIT' if mode == 'accepted_ack_loss' else 'ROLLBACK')))
    raise PgWireError({'C': sqlstate, 'M': 'TEST ONLY injected database fault'})


PgStore.commit = _commit


def ready() -> str:
    return 'stock native HTTP transaction probe'


def create_probe(value: str) -> str:
    record = ProofRecord(value=value)
    JacRI.save(record)
    return str(record.__jac__.id)


def write_probe(record_id: str, value: str, mode: str, sqlstate: str) -> str:
    global _fault
    record = JacRI.get_object(record_id)
    if not isinstance(record, ProofRecord):
        raise ValueError('Unknown disposable probe record')
    record.value = value
    with _lock:
        _fault = (mode, sqlstate)
    return value


def read_probe(record_id: str) -> str:
    record = JacRI.get_object(record_id)
    if not isinstance(record, ProofRecord):
        return 'MISSING'
    return record.value
