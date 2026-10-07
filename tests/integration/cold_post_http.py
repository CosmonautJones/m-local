#!/usr/bin/env python3
"""Require one published offer from the first save_offer after server restart.

Run against a disposable local app with provisioned demo accounts. Restart its
server immediately before this check and do not call save_offer first. Jac's
read-only writer detection is per process, so a warm request misses this bug.
Creates one clearly labeled fictional offer; never prints credentials.
"""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import secrets
from zoneinfo import ZoneInfo

from qr_http import Api, provision, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', type=provision.local_api, required=True)
    parser.add_argument('--accounts', type=Path, required=True)
    args = parser.parse_args()
    account = json.loads(args.accounts.read_text())['merchant_leaf']
    session = provision.post(args.api, '/user/login', {
        'identity': {'type': 'email', 'value': account['email']},
        'credential': {'type': 'password', 'password': account['password']},
    })
    merchant = Api(args.api, session['token'])
    public = Api(args.api)
    marker = 'Cold publication fixture ' + secrets.token_hex(6)
    now = datetime.now(ZoneInfo('America/Detroit'))
    post = dict(
        offer_id='', create_key=secrets.token_hex(16), title=marker, description='Fictional cold-start acceptance offer',
        price='3.50', regular_price='5.00',
        start_local=(now - timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M'),
        end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'),
        quantity='8', eligibility='Show test student ID', terms='Synthetic test only',
        dietary='vegetarian', menu_item='Cold fixture item ' + marker,
    )
    saved = merchant.call('save_offer', **post)
    require(saved['ok'], 'cold merchant publication succeeds')
    offer_id = saved['code']

    def check_unique():
        matches = [offer for offer in public.call('list_offers')
                   if marker in offer['title']]
        require([offer['id'] for offer in matches] == [offer_id],
                f'one request produced exactly one public offer (found {len(matches)})')

    check_unique()
    post['offer_id'] = offer_id
    post['title'] = marker + ' edited'
    edited = merchant.call('save_offer', **post)
    require(edited['ok'] and edited['code'] == offer_id,
            'edit keeps the original published offer ID')
    check_unique()
    require(public.call('get_offer', offer_id=offer_id)['title'] == post['title'],
            'edited title is visible on the original offer')
    print('Cold publication HTTP acceptance passed.')


if __name__ == '__main__':
    main()
