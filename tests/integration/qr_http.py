#!/usr/bin/env python3
"""Opt-in real HTTP QR acceptance, using freshly provisioned local demo accounts.
Creates isolated test offers in the configured fictional merchant's catalog.
Never prints passwords, tokens or QR credentials. Requires a running local Jac API.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import re
import secrets
import threading
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('provision', ROOT / 'scripts/provision-demo.py')
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)


class Api:
    def __init__(self, origin, token=''):
        self.origin, self.token = origin, token

    def call(self, endpoint, **params):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        request = urllib.request.Request(self.origin + '/function/' + endpoint,
                                         json.dumps(params).encode(), headers, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                envelope = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                return {'ok': False, 'http_status': error.code}
            raise AssertionError(f'{endpoint}: unexpected HTTP {error.code}') from None
        assert envelope.get('ok'), f'{endpoint}: runtime returned an error'
        return envelope['data']['result']


def require(value, message):
    assert value, message
    print('PASS ' + message)


def parallel_pair(first, second):
    barrier = threading.Barrier(2)
    def invoke(fn):
        barrier.wait(timeout=10)
        return fn()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke, fn) for fn in (first, second)]
        return [future.result() for future in futures]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', type=provision.local_api, default='http://localhost:8001')
    parser.add_argument('--accounts', type=Path, default=ROOT / '.jac/qr-demo-accounts.json')
    args = parser.parse_args()
    try:
        with urllib.request.urlopen(args.api + '/graph/data', timeout=10) as response:
            # Jac's no-dev web server falls back to the SPA shell for unknown
            # GET routes. A 200 shell is not a graph-data response; require it
            # to be byte-identical to the anonymous app shell before accepting.
            body = response.read()
            with urllib.request.urlopen(args.api + '/', timeout=10) as home:
                shell = home.read()
            require(response.headers.get_content_type() == 'text/html' and body == shell,
                    'graph route serves only the anonymous application shell')
    except urllib.error.HTTPError as error:
        require(error.code in (401, 403, 404), 'graph inspector does not expose private claims')
    accounts = json.loads(args.accounts.read_text())
    clients = {}
    for role in ('student_a', 'student_b', 'merchant_leaf', 'merchant_noodle'):
        account = accounts[role]
        result = provision.post(args.api, '/user/login', {
            'identity': {'type': 'email', 'value': account['email']},
            'credential': {'type': 'password', 'password': account['password']},
        })
        clients[role] = Api(args.api, result['token'])
    student_a, student_b = clients['student_a'], clients['student_b']
    merchant, wrong = clients['merchant_leaf'], clients['merchant_noodle']
    require(merchant.call('current_session')['role'] == 'merchant', 'trusted merchant membership loaded')
    require(wrong.call('current_session')['role'] == 'merchant', 'second merchant membership loaded')
    require(student_a.call('current_session')['role'] == 'student', 'student role loaded')
    now = datetime.now(ZoneInfo('America/Detroit'))
    run = secrets.token_hex(6)
    offer = dict(offer_id='', create_key=secrets.token_hex(16), title='QR acceptance ' + run, description='Fictional test offer',
                 price='3.00', regular_price='5.00', start_local=(now-timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M'),
                 end_local=(now+timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='1',
                 eligibility='Show student ID', terms='One fictional test meal', dietary='', menu_item='')
    saved = merchant.call('save_offer', **offer)
    require(saved['ok'], 'created dedicated one-unit test offer')
    offer_id = saved['code']
    ids_a = {item['id'] for item in student_a.call('list_offers')}
    ids_b = {item['id'] for item in student_b.call('list_offers')}
    require(offer_id in ids_a & ids_b, 'two authenticated roots share the catalog')
    require(not Api(args.api).call('claim_offer', offer_id=offer_id)['ok'], 'guest claim rejected')
    results = parallel_pair(lambda: student_a.call('claim_offer', offer_id=offer_id),
                            lambda: student_b.call('claim_offer', offer_id=offer_id))
    require(sum(bool(r['ok']) for r in results) == 1, 'simultaneous last-unit claims have one winner')
    winner_index = 0 if results[0]['ok'] else 1
    winner = (student_a, student_b)[winner_index]
    loser = (student_b, student_a)[winner_index]
    claim = results[winner_index]
    payload = claim['qr_payload']
    require(bool(re.fullmatch(r'mlocal:v1:[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]', payload)), 'opaque versioned QR format')
    retry = winner.call('claim_offer', offer_id=offer_id)
    require(retry['ok'] and retry['qr_payload'] == payload and retry['claim_id'] == claim['claim_id'],
            'claim retry preserves credential and claim')
    other_view = loser.call('get_offer', offer_id=offer_id)
    guest_view = Api(args.api).call('get_offer', offer_id=offer_id)
    require(other_view.get('id') == offer_id and not other_view.get('my_qr_payload'),
            'other student sees offer without private credential')
    require(guest_view.get('id') == offer_id and not guest_view.get('my_qr_payload'),
            'guest sees offer without private credential')
    require(not wrong.call('resolve_claim', qr_payload=payload)['ok'], 'wrong merchant preview rejected')
    require(not wrong.call('redeem_claim', qr_payload=payload)['ok'], 'wrong merchant redemption rejected')
    require(not winner.call('resolve_claim', qr_payload=payload)['ok'], 'student preview rejected')
    require(not merchant.call('resolve_claim', qr_payload='https://example.invalid/')['ok'], 'URL QR rejected')
    preview = merchant.call('resolve_claim', qr_payload=payload)
    require(preview['ok'] and preview['price_cents'] == 300, 'merchant resolves original terms without mutation')
    require(winner.call('get_offer', offer_id=offer_id)['my_status'] == 'claimed', 'preview does not redeem')
    offer.update(offer_id=offer_id, price='9.00', regular_price='12.00', title='Edited ' + run, terms='Different future terms')
    require(merchant.call('save_offer', **offer)['ok'], 'merchant edits future offer terms')
    unchanged = merchant.call('resolve_claim', qr_payload=payload)
    require(all(unchanged[k] == preview[k] for k in ('title_snapshot', 'price_cents', 'terms', 'eligibility', 'expires_ts')),
            'held claim retains original terms price and deadline')
    redemption = parallel_pair(lambda: merchant.call('redeem_claim', qr_payload=payload),
                               lambda: merchant.call('redeem_claim', qr_payload=payload))
    require(sum(bool(r['ok']) for r in redemption) == 1, 'simultaneous redemptions have one winner')
    require(not merchant.call('redeem_claim', qr_payload=payload)['ok'], 'repeat redemption rejected')
    require(winner.call('get_offer', offer_id=offer_id)['my_status'] == 'redeemed', 'student sees redeemed state')
    print('HTTP acceptance passed. Restart persistence, expiry boundary and physical camera remain separate checks.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, AssertionError) as error:
        raise SystemExit('FAIL ' + str(error))
