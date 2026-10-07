#!/usr/bin/env python3
"""Local-only integration proof. Injects test codes into an isolated private store.

No email is sent. Never run this against a shared or public demo store.
"""
import json
from pathlib import Path
import secrets
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.email_codes import CodeStore, business_revision


def post(name, body, token=''):
    request = urllib.request.Request('http://127.0.0.1:8240/function/' + name,
        json.dumps(body).encode(), {'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + token} if token else {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if not result.get('ok'):
        raise AssertionError(f'{name} failed: {result.get("error", {}).get("code", "unknown")}')
    return result['data']['result']


def main():
    directory = Path.cwd().resolve()
    if directory.name != 'onboarding-check':
        raise SystemExit('Run only from the isolated onboarding-check workspace.')
    state = CodeStore(directory / '.jac/onboarding')
    unavailable = post('request_email_code', {'value': 'fixture', 'kind': 'student', 'name': 'Test'})
    assert not unavailable['ok'] and not unavailable['challenge']
    users = []
    for kind in ('student', 'business', 'business'):
        codes = []
        value = 'fixture' + secrets.token_hex(3)
        value = value if kind == 'student' else value + '@example.test'
        challenge = state.request(value, kind, 'Isolated test user', lambda email, code: codes.append(code))
        reply = post('verify_email_code', {'challenge': challenge['challenge'], 'code': codes[0]})
        assert reply['ok'], reply['message']
        token = reply['token']
        assert token
        session = post('current_session', {}, token)
        assert session['authenticated'] and session['email_verified'] and session['role'] == kind, session
        replay = post('verify_email_code', {'challenge': challenge['challenge'], 'code': codes[0]})
        assert not replay['ok'] and not replay['token']
        users.append(token)
    offers = post('list_offers', {})
    active = next(o for o in offers if o['state'] == 'active' and o['remaining'] > 0)
    assert not post('claim_offer', {'offer_id': active['id']}, users[1])['ok']
    assert post('claim_offer', {'offer_id': active['id']}, users[0])['ok']
    draft = dict(name='Isolated Fixture Cafe', cuisine='Test', description='Fictional test only', address='123 Fixture St',
                 website='https://example.com', menu_text='Soup $8', menu_url='', image_url='', confirmed=True)
    saved = post('save_business_draft', draft, users[1])
    assert saved['ok'] and saved['status'] == 'pending_review'
    assert not post('merchant_portal', {}, users[1])['ok']
    actor = post('current_session', {}, users[1])['actor_id']
    state.approve_business(actor, 'HTTP fixture reviewer', 'Verified fictional business authority', business_revision(state.draft(actor)))
    saved = post('save_business_draft', draft, users[1])
    assert saved['ok'] and saved['status'] == 'active'
    assert post('get_business_draft', {}, users[1])['name'] == draft['name']
    assert post('get_business_draft', {}, users[2])['name'] == ''
    assert post('merchant_portal', {}, users[1])['ok']
    assert post('current_session', {}, users[1])['role'] == 'merchant'
    assert not post('merchant_portal', {}, users[2])['ok']
    denied = post('import_business_website', {'website': 'https://127.0.0.1'}, users[1])
    assert not denied['ok']
    try:
        post('get_business_draft', {})
    except urllib.error.HTTPError as error:
        assert error.code == 401
    else:
        raise AssertionError('Anonymous draft access must fail')
    print('PASS: real Jac OTP/session, replay denial, student claim, business claim denial, private drafts, self-service merchant setup, account isolation, anonymous denial, unsafe URL denial. No real email or model call.')


if __name__ == '__main__':
    main()
