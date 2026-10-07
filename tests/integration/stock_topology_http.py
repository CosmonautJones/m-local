"""Bounded stock-Jac native HTTP fault diagnostic, using private PostgreSQL.

This is a regression gate, not a passing release test. Nonzero is expected when
the official runtime exhibits a safety violation. A minimal test entry and
clearly marked acknowledgement hook preserve production sources and binaries.
No authentication is stubbed; native anonymous function access is used only to
create/read disposable app-owned probe nodes. This does not certify load,
the full M-Local app, public ingress, SMTP, or multi-host operation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
import urllib.error
import urllib.request
from uuid import UUID

from recovery_http import digest, private_dir, scrub_environment, stop_process

ROOT = Path(__file__).resolve().parents[2]


def verify_stock_binaries(jac):
    expected = {
        jac: '2c3c697616b08516caf01704571e7e7020f4b294cd2bef7f04e8ef1ceec9d6ad',
        Path(str(jac) + 'python'): '198225fb91707f48461f3fec1684d444ab0fd7b5a1e0913f0a0a8f11c9d02542',
    }
    for binary, checksum in expected.items():
        if digest(binary) != checksum:
            raise RuntimeError('Fixture requires the official Linux x86_64 Jac0.37.23 published binaries')


def rpc(origin, function, **params):
    req = urllib.request.Request(origin + '/function/' + function,
        json.dumps(params).encode(), {'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            payload = json.load(error)
        except (ValueError, OSError):
            payload = {'non_json_error': True}
        return error.code, payload
    except (OSError, urllib.error.URLError):
        return 0, {'ok': False, 'transport_lost': True}


def result(envelope):
    data = envelope.get('data')
    return data.get('result') if isinstance(data, dict) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18880)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    if args.evidence and args.evidence.exists():
        raise RuntimeError('Evidence receipt exists; preserve it and choose a new path')
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise RuntimeError('Use an unprivileged WSL/Linux user')
    if os.environ.get('JAC_DB_URL') or os.environ.get('JAC_DEV_SOURCE'):
        raise RuntimeError('Refusing inherited database/source override')
    jac = Path(os.environ['JAC_BIN']).resolve()
    version = subprocess.check_output([str(jac), '--version'], text=True, timeout=30).strip()
    if version.split()[:2] != ['jac', '0.37.23']:
        raise RuntimeError('Use official Jac 0.37.23')
    verify_stock_binaries(jac)
    os.umask(0o077)
    workspace = Path(tempfile.mkdtemp(prefix='m-local-stock-topology.', dir='/var/tmp'))
    app, cache = workspace / 'app', workspace / 'cache'
    private_dir(app)
    private_dir(cache)
    private_dir(cache / 'tmp')
    private_dir(app / 'tests')
    private_dir(app / 'tests/integration')
    for name in ('stock_topology_hook.py', 'stock_topology_hook.pyi', 'stock_topology_models.jac'):
        shutil.copy2(ROOT / 'tests/integration' / name, app / 'tests/integration' / name)
    shutil.copy2(ROOT / 'tests/integration/stock_topology_probe.jac', app / 'main.jac')
    (app / 'jac.toml').write_text('''[project]
name = "stock-topology-disposable-proof"
version = "0.0.1"
entry-point = "main"
jac-version = "0.37.23"
kind = "web-app"
[serve]
host = "127.0.0.1"
docs_enabled = false
graph_enabled = false
''')
    environment = scrub_environment(jac, cache, app / '.jac/onboarding')
    # Disable only the supported read-only optimization so each cold mutation
    # exercises the same full transaction. This does not disable stock retries.
    environment.update(STOCK_PROOF_EVENTS=str(workspace / 'events.json'), JAC_DB_RO_UNITS='0')
    from jaclang.data.pgembed import PgRuntime
    from jaclang.data.store import PgStore
    with socket.socket() as database_port:
        database_port.bind(('127.0.0.1', 0))
        postgres_port = database_port.getsockname()[1]
    runtime = PgRuntime(data_dir=str(workspace / 'postgres'), database='stock_topology_http',
                        tcp=True, port=postgres_port)
    processes = []
    cases = []
    receipt = dict(schema=1, verdict='INCOMPLETE', candidate_sha=subprocess.check_output(
        ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        version=version, jac_sha256=digest(jac), jacpython_sha256=digest(Path(str(jac) + 'python')),
        source_override=False, fixture_manifest={str(path.relative_to(app)): digest(path)
            for path in sorted(app.rglob('*')) if path.is_file()}, workspace=str(workspace),
        topology='one native API; requests issued serially; independent read-only PgStore observer',
        instrumentation='test-only PgStore.commit hook; real ROLLBACK or accepted COMMIT then PgWireError',
        cases=cases, limitations=['minimal native HTTP fixture, not full-app/ingress certification',
            'not sustained capacity, SMTP, deployment, or scaling evidence'])
    active = None

    def start():
        nonlocal active
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', args.port))
        log = workspace / ('api-' + str(len(processes)) + '.log')
        with log.open('wb') as stream:
            active = subprocess.Popen([str(jac), 'run', '--no-dev', '--no-client',
                '--host', '127.0.0.1', '--port', str(args.port)], cwd=app, env=environment,
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(active)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if active.poll() is not None:
                raise RuntimeError('Native proof API exited; inspect private API log')
            try:
                status, envelope = rpc(origin, 'probe_ready')
                if status == 200 and result(envelope) == 'stock native HTTP transaction probe':
                    return
            except (OSError, ValueError, urllib.error.URLError):
                pass
            time.sleep(.2)
        raise TimeoutError('Native proof readiness timeout')

    def observe(record_id):
        observer = PgStore(conninfo=connection, auto_schema=False)
        try:
            row = observer.load_full([UUID(record_id)]).get(UUID(record_id))
            return None if row is None else dict(value=row.props['archetype']['value'], version=row.version)
        finally:
            observer.close()

    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    origin = 'http://127.0.0.1:' + str(args.port)
    try:
        connection = runtime.ensure()
        environment['JAC_DB_URL'] = ('postgresql://' + quote(connection.user, safe='') + ':' +
            quote(connection.password, safe='') + '@127.0.0.1:' + str(connection.port) + '/' + connection.database)
        for mode, sqlstate in (('rollback', '57P01'), ('rollback', '40001'),
                               ('rollback', '08006'), ('accepted_ack_loss', '08006'),
                               ('process_death_before_commit', ''), ('process_death_after_commit', '')):
            start()
            status, created = rpc(origin, 'probe_create', value='Original durable value')
            record_id = result(created)
            if status != 200 or not isinstance(record_id, str):
                raise AssertionError('Native creation failed: ' + json.dumps(created))
            before = observe(record_id)
            if before is None or before['value'] != 'Original durable value':
                raise AssertionError('Creation must be durable before injection')
            status, written = rpc(origin, 'probe_write', record_id=record_id,
                value='Faulted request value', mode=mode, sqlstate=sqlstate)
            immediate = observe(record_id)
            read_status, cached = rpc(origin, 'probe_read', record_id=record_id)
            after_read = observe(record_id)
            row = dict(mode=mode, sqlstate=sqlstate, response_status=status,
                transport_lost=written.get('transport_lost', False),
                response_ok=written.get('ok'), response_result=result(written),
                response_error_code=written.get('error', {}).get('code') if isinstance(written.get('error'), dict) else None,
                before=before, durable_immediate=immediate,
                read_status=read_status, cached_read=result(cached), durable_after_read=after_read)
            row['http_success_without_durable_value'] = bool(written.get('ok') and
                result(written) == 'Faulted request value' and immediate['value'] != 'Faulted request value')
            row['cached_read_disagrees_with_durable_value'] = bool(cached.get('ok') and
                result(cached) != immediate['value'])
            row['read_request_persisted_failed_write'] = immediate != after_read
            row['unexpected_process_death_result'] = bool(mode.startswith('process_death') and (
                status != 0 or immediate['value'] != (
                    'Faulted request value' if mode == 'process_death_after_commit' else 'Original durable value')))
            cases.append(row)
            stop_process(active)
            active = None
            start()
            restart_status, restarted = rpc(origin, 'probe_read', record_id=record_id)
            row.update(restart_status=restart_status, restart_read=result(restarted))
            print(json.dumps(row), flush=True)
            stop_process(active)
            active = None
            if any(row[key] for key in ('http_success_without_durable_value',
                    'cached_read_disagrees_with_durable_value', 'read_request_persisted_failed_write',
                    'unexpected_process_death_result')):
                receipt['verdict'] = 'BLOCKED'
                receipt['blocking_case'] = len(cases)
                break
        else:
            receipt['verdict'] = 'BOUNDED_FAULT_CASES_PASS_NOT_CERTIFIED'
    except BaseException as error:
        receipt['failure_type'] = type(error).__name__
        receipt['failure'] = str(error)
        raise
    finally:
        for process in processes:
            stop_process(process)
        runtime.stop()
        receipt['cleanup'] = dict(owned_api_groups_stopped=True, private_postgres_stopped=True)
        receipt['events'] = json.loads((workspace / 'events.json').read_text()) if (workspace / 'events.json').exists() else []
        (workspace / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if args.evidence:
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(args.evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(json.dumps(receipt, indent=2) + '\n')
        print('Retained private diagnostic:', workspace, flush=True)
    if receipt['verdict'] == 'BLOCKED':
        raise SystemExit('BLOCKED: stock native HTTP response/cache violated durable-state invariant')


if __name__ == '__main__':
    main()
