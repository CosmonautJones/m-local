"""TEST ONLY one-shot faults at actual M-Local Offer/Redemption commit flushes.

Imported solely by an entry appended to a disposable application copy. Never
imported by production main.jac; never edits installed Jac or its private methods.
The unchanged stock Session executes the normal app body/replay/abort paths.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
from uuid import UUID

from jaclang.data.pgwire import PgWireError
from jaclang.data.store import PgStore

_installed = False


def install_fault_hook() -> None:
    global _installed
    if _installed:
        return
    configured = os.environ.get('STOCK_APP_PROOF_ROOT', '')
    if not configured:
        raise RuntimeError('Actual app fault hook requires a private disposable proof directory')
    workspace = Path(configured).resolve()
    if workspace.parent != Path('/var/tmp') or not workspace.name.startswith('m-local-stock-app.'):
        raise RuntimeError('Actual app fault hook refuses non-disposable state')
    control, events = workspace / 'fault-arm.json', workspace / 'fault-events.json'
    original = PgStore.commit

    def commit(store):
        if not control.exists() or not store.in_txn():
            return original(store)
        fault = json.loads(control.read_text())
        arch, field = fault['arch_type'], fault['field']
        if (arch, field) not in (('Offer', 'title'), ('Redemption', 'offer_title_snapshot'),
                                ('Redemption', 'status')):
            raise RuntimeError('Fault target is not an allowlisted disposable app record')
        if field == 'status' and (fault['value'] != 'redeemed' or not fault.get('target_id')):
            raise RuntimeError('Redemption update fault requires one claimed anchor transitioning to redeemed')
        # Read this same transaction AFTER stock Session.flush. The initial
        # app lock commit sees no new target, so only the actual mutation flush
        # consumes this one-shot fault. This query does not mutate any state.
        query = "SELECT COUNT(*) FROM anchors WHERE arch_type=:arch AND props->'archetype'->>:field=:value"
        params = dict(arch=arch, field=field, value=fault['value'])
        if fault.get('target_id'):
            params['target_id'] = str(UUID(fault['target_id']))
            query += ' AND id=CAST(:target_id AS uuid)'
        hits = store.rows(query, params)
        if int(hits[0][0]) == 0:
            return original(store)
        control.unlink()
        mode = fault['mode']
        if mode == 'transport_loss_before_commit':
            # TEST ONLY physical transport interruption. Keep stock PgWire and
            # PgStore error classification/reconnection logic intact; their own
            # COMMIT attempt now observes the closed TCP socket and emits08006.
            store._conn._sock.shutdown(socket.SHUT_RDWR)
            store._conn._sock.close()
            action = 'TCP_SOCKET_CLOSED_BEFORE_COMMIT'
        elif mode in ('accepted_ack_loss', 'process_death_after_commit'):
            original(store)
            action = 'COMMIT'
        elif mode == 'process_death_before_commit':
            action = 'NO_COMMIT_PROCESS_EXIT'
        else:
            store.rollback()
            action = 'ROLLBACK'
        receipt = dict(mode=mode, requested_sqlstate=fault.get('sqlstate', ''), arch_type=arch,
                       field=field,
                       target_sha256=hashlib.sha256(fault['value'].encode()).hexdigest(),
                       real_database_action=action)
        previous = json.loads(events.read_text()) if events.exists() else []
        previous.append(receipt)
        events.write_text(json.dumps(previous, indent=2) + '\n')
        if mode == 'transport_loss_before_commit':
            try:
                return original(store)
            except PgWireError as error:
                fields = error.args[0] if error.args and isinstance(error.args[0], dict) else {}
                receipt['observed_exception_type'] = type(error).__name__
                receipt['observed_sqlstate'] = fields.get('C', '')
                previous[-1] = receipt
                events.write_text(json.dumps(previous, indent=2) + '\n')
                raise
        if mode.startswith('process_death'):
            os._exit(77 if mode == 'process_death_before_commit' else 78)
        raise PgWireError({'C': fault['sqlstate'], 'M': 'TEST ONLY actual app commit fault'})

    PgStore.commit = commit
    _installed = True
