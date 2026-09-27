#!/usr/bin/env python3
"""End-to-end integration test for the admin approval workflow.

Spawns a local Jac server, creates a test user via onboarding, submits a
business draft, runs the admin CLI to approve it, restarts the server,
and verifies the user is now a merchant who can create an offer.
"""
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    if os.name != 'posix':
        raise RuntimeError('Run this check in WSL/Linux/macOS with Jac 0.37.23.')

    ROOT = Path(__file__).resolve().parents[2]
    jac = os.environ.get('JAC_BIN', str(Path.home() / '.local/share/m-local/runtimes/0.37.23/jac'))
    
    cache = Path(os.environ.get('JAC_CACHE_HOME', str(Path.home() / '.cache/m-local')))
    (cache / 'test-runs').mkdir(parents=True, exist_ok=True)
    fixture = Path(tempfile.mkdtemp(prefix='admin-http-', dir=cache / 'test-runs'))
    print(f"Test fixture: {fixture}")

    # Copy files
    (fixture / 'services').mkdir()
    for source in (ROOT / 'services').glob('*.jac'):
        shutil.copy2(source, fixture / 'services' / source.name)
    for source in (ROOT / 'services').glob('*.py'):
        shutil.copy2(source, fixture / 'services' / source.name)

    (fixture / 'scripts').mkdir()
    for source in (ROOT / 'scripts').glob('*'):
        if source.is_file():
            shutil.copy2(source, fixture / 'scripts' / source.name)

    shutil.copy2(ROOT / 'jac.toml', fixture / 'jac.toml')
    shutil.copy2(ROOT / 'tests/integration/admin_probe.jac', fixture / 'main.jac')

    # Find free port
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    api = f'http://127.0.0.1:{port}'

    child = None
    stream = None

    def post(name, payload, token=''):
        req = urllib.request.Request(api + '/function/' + name,
                                     json.dumps(payload).encode(),
                                     {'Content-Type': 'application/json',
                                      **({'Authorization': 'Bearer ' + token} if token else {})})
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.load(response)
        if not res.get('ok'):
            raise RuntimeError(f"{name} failed: {res.get('error', {}).get('code', 'unknown')}")
        return res['data']['result']

    def start_server(env_additions=None):
        nonlocal child, stream
        env = dict(os.environ, JAC_PATH=str(fixture), MLOCAL_ONBOARDING_DIR=str(fixture / '.jac/onboarding'))
        if env_additions:
            env.update(env_additions)
        log_path = fixture / 'server.log'
        stream = open(log_path, 'a')
        child = subprocess.Popen([jac, 'run', '--serve', '--no-client', '--port', str(port)],
                                 cwd=fixture, env=env, stdout=stream, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                urllib.request.urlopen(api, timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            stream.flush()
            with open(log_path, 'r') as f:
                print(f.read())
            raise RuntimeError('Server failed to start.')

    def stop_server():
        nonlocal child, stream
        if child:
            child.send_signal(signal.SIGTERM)
            child.wait(timeout=5)
            child = None
        if stream:
            stream.close()
            stream = None

    try:
        start_server()

        # 1. Create a user via onboarding
        sys.path.insert(0, str(ROOT))
        from services.email_codes import CodeStore
        state = CodeStore(fixture / '.jac/onboarding')
        codes = []
        challenge = state.request('testbusiness@example.test', 'business', 'Test Business', lambda e, c: codes.append(c))
        
        reply = post('verify_email_code', {'challenge': challenge['challenge'], 'code': codes[0]})
        assert reply['ok'], "Failed to verify email code"
        token = reply['token']
        
        # Get actor ID using current_session
        sess = post('current_session', {}, token)
        actor_id = sess['actor_id']
        assert sess['role'] == 'business', "Should have business role"

        # 2. Submit a business draft
        draft = dict(name='Test Cafe', cuisine='Cafe', description='Testing', address='123 Test St',
                     website='https://example.com', menu_text='Coffee', menu_url='', image_url='', confirmed=True)
        res = post('save_business_draft', draft, token)
        assert res['ok'] and res['status'] == 'pending_review', "Failed to save draft"
        
        # Verify it shows up in list
        import sqlite3
        db = sqlite3.connect(fixture / '.jac/onboarding/onboarding.sqlite3')
        db.row_factory = sqlite3.Row
        print("DRAFTS:", [dict(r) for r in db.execute('SELECT * FROM drafts').fetchall()])
        print("ACCOUNTS:", [dict(r) for r in db.execute('SELECT * FROM accounts').fetchall()])
        
        admin_env = dict(os.environ, MLOCAL_ONBOARDING_DIR=str(fixture / '.jac/onboarding'), JAC_BIN=jac)
        list_out = subprocess.check_output([sys.executable, str(ROOT / 'scripts/admin.py'), 'list'], env=admin_env, text=True, stderr=subprocess.STDOUT)
        print("LIST OUT:\n", list_out)
        assert 'Test Cafe' in list_out, "Pending application not found in list"
        
        # 3. Approve via admin CLI (Skip graph because we don't have admin credentials set up in the test,
        # but wait, we CAN set up admin credentials, or we can just use --skip-graph and restart the server!)
        # Actually, if we just set MLOCAL_ADMIN_USER in the environment, we can let it create the graph!
        # Wait, the jac server doesn't use MLOCAL_ADMIN_USER to create root users automatically, 
        # so let's just use --skip-graph. The restaurant will be created via `qr_catalog._ensure_seed` if we seed it, 
        # OR we can just let `scripts/admin.py` run without `--skip-graph` but we'd need admin auth. 
        # For simplicity, let's just do --skip-graph, which means the restaurant IS NOT created in the graph by the script,
        # BUT wait! If it's not created in the graph, `current_session` won't find it when we restart!
        # Ah. `merchant_owner` will be in the env, but `root.shared -->[?:Restaurant]` won't exist because we didn't create it!
        # So we MUST create the restaurant in the graph. 
        # We can just register a user via `/user/register` and use them as the admin token!
        
        req = urllib.request.Request(api + '/user/register', json.dumps({
            'identities': [{'type': 'email', 'value': 'admin@test.local'}],
            'credential': {'type': 'password', 'password': 'admin_pass'}
        }).encode(), {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response: pass
        
        # Now approve WITH graph creation
        admin_env['MLOCAL_ADMIN_USER'] = 'admin@test.local'
        admin_env['MLOCAL_ADMIN_PASSWORD'] = 'admin_pass'
        # The admin script writes to .jac/merchant-owners.env IN THE CWD! So we must set CWD to fixture.
        
        try:
            approve_out = subprocess.check_output([sys.executable, str(ROOT / 'scripts/admin.py'), '--api', api, 'approve', actor_id], 
                                                  env=admin_env, cwd=fixture, text=True, stderr=subprocess.STDOUT)
            print("APPROVE OUT:\n", approve_out)
        except subprocess.CalledProcessError as e:
            print("APPROVE ERROR OUT:\n", e.output)
            raise
        assert 'Restaurant and location created in graph.' in approve_out, "Failed to create graph nodes"
        
        # 4. Restart server with the new env file
        stop_server()
        
        # Read the newly created env file
        owners_env = {}
        owners_path = fixture / '.jac/merchant-owners.env'
        if owners_path.exists():
            for line in owners_path.read_text().splitlines():
                if line.startswith('export MLOCAL_MERCHANT_OWNERS='):
                    val = line.split('=', 1)[1]
                    if val.startswith("'"): val = val[1:-1]
                    owners_env['MLOCAL_MERCHANT_OWNERS'] = val
                    
        start_server(env_additions=owners_env)
        
        # 5. Verify user is now a merchant and can create an offer
        sess2 = post('current_session', {}, token)
        assert sess2['role'] == 'merchant', f"Should be merchant, got {sess2['role']}"
        
        portal = post('merchant_portal', {}, token)
        assert portal['restaurant']['name'] == 'Test Cafe', "Should see the approved restaurant"
        
        # Create an offer
        offer = post('save_offer', {
            'offer_id': '',
            'title': 'Test Offer',
            'description': 'Description',
            'price': '5.00',
            'regular_price': '10.00',
            'start_local': '2026-01-01T12:00',
            'end_local': '2026-01-01T14:00',
            'quantity': '10',
            'eligibility': 'Everyone',
            'terms': 'Terms',
            'dietary': '',
            'menu_item': ''
        }, token)
        assert offer['ok'], "Should be able to save an offer"
        
        print("PASS: end-to-end admin approval to merchant offer creation.")
        
    finally:
        stop_server()
        shutil.rmtree(fixture, ignore_errors=True)

if __name__ == '__main__':
    main()
