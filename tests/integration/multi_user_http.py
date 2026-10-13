#!/usr/bin/env python3
"""Concurrent account and shared-catalog acceptance in a disposable local app.

Run from an isolated directory named onboarding-check. The only allowed API
origins are loopback port 8240 (Jac) and 8241 (its public gateway). Four local
OTP challenges are injected without SMTP; verification and all app operations
use real HTTP. No credentials or QR payloads are printed. Run --verify-restart
after restarting the same server/store to check the private persisted receipt.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import sys
import threading
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.email_codes import CodeStore, business_revision
from qr_http import Api, require


def local_api(value):
    allowed = {f'http://{host}:{port}' for host in ('127.0.0.1', 'localhost')
               for port in (8240, 8241)}
    if value not in allowed:
        raise argparse.ArgumentTypeError('Use only the disposable loopback API on port 8240 or 8241.')
    return value


def parallel(actions):
    """Release independent HTTP callers together, preserving input order."""
    barrier = threading.Barrier(len(actions))

    def invoke(action):
        barrier.wait(timeout=10)
        return action()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        futures = [pool.submit(invoke, action) for action in actions]
        return [future.result() for future in futures]


def write_receipt(path, receipt):
    descriptor = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(receipt, stream)


def assert_identity(client, user):
    session = client.call('current_session')
    profile = client.call('get_account_profile')
    role = 'merchant' if user.get('restaurant_id') else user['kind']
    require(session['actor_id'] == user['actor_id'] and session['display_name'] == user['name']
            and session['role'] == role and session['email_verified'],
            f"{user['kind']} session keeps its own actor, name and role")
    require(profile['ok'] and profile['display_name'] == user['name']
            and profile['email'] == user['email'] and profile['email_verified'],
            f"{user['kind']} account profile keeps its own verified identity")
    if user.get('restaurant_id'):
        require(session['restaurant_id'] == user['restaurant_id'], 'merchant keeps its own restaurant identity')


def assert_public_offers(client, receipt):
    items = client.call('home_feed')['items']
    for expected in receipt['offers']:
        matches = [item['offer'] for item in items if item['offer']['id'] == expected['id']]
        require(len(matches) == 1 and matches[0]['title'] == expected['title']
                and not matches[0]['is_demo'], 'shared home feed lists each real business offer exactly once')


def verify_restart(api, receipt):
    require(receipt.get('stage') == 'complete', 'receipt records a completed multi-user acceptance run')
    clients = [Api(api, user['token']) for user in receipt['users']]
    parallel([lambda client=client, user=user: assert_identity(client, user)
              for client, user in zip(clients, receipt['users'])])
    for client, user in zip(clients, receipt['users']):
        if user['kind'] == 'business':
            draft = client.call('get_business_draft')
            require(draft['ok'] and draft['status'] == 'active' and draft['name'] == user['business_name']
                    and draft['menu_text'] == user['menu_text'], 'owned business draft survives restart privately')
            portal = client.call('merchant_portal')
            own_id = receipt['offers'][receipt['users'].index(user) - 2]['id']
            portal_ids = {offer['id'] for offer in portal['offers']}
            other_ids = set(receipt['published_offer_ids']) - {own_id}
            require(portal['ok'] and portal['name'] == user['business_name']
                    and own_id in portal_ids and not portal_ids.intersection(other_ids),
                    'merchant retains only its own published offer after restart')
        else:
            taste = client.call('taste_choices')
            require(taste['completed'] and all(taste[key] == value for key, value in user['taste'].items()),
                    'student tastes survive restart without crossing accounts')
        assert_public_offers(client, receipt)
    winner = next(client for client, user in zip(clients, receipt['users'])
                  if user['actor_id'] == receipt['winner_actor_id'])
    final = winner.call('get_offer', offer_id=receipt['published_offer_ids'][0])
    require(final['my_status'] == 'redeemed' and final['remaining'] == 0 and not final['my_qr_payload'],
            'one-unit redemption and consumed stock survive restart')
    print('Multi-user restart acceptance passed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', type=local_api, default='http://127.0.0.1:8240')
    parser.add_argument('--verify-restart', action='store_true')
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT or ROOT.name != 'onboarding-check':
        raise SystemExit('Run only from the isolated onboarding-check workspace.')
    configured_store = Path(os.environ.get('MLOCAL_ONBOARDING_DIR', ROOT / '.jac/onboarding')).resolve()
    if configured_store != ROOT / '.jac/onboarding':
        raise SystemExit('Use only this disposable workspace onboarding store.')
    receipt_path = ROOT / '.jac/multi-user-check.json'
    if args.verify_restart:
        verify_restart(args.api, json.loads(receipt_path.read_text()))
        return

    run = secrets.token_hex(5)
    receipt = {'run': run, 'users': [], 'published_offer_ids': [], 'offers': [], 'stage': 'accounts'}
    state = CodeStore(ROOT / '.jac/onboarding')
    for index, kind in enumerate(('student', 'student', 'business', 'business')):
        name = f'Multi {kind} {index + 1} {run}'
        value = f'multi{run}{index}' + ('@example.test' if kind == 'business' else '')
        codes = []
        challenge = state.request(value, kind, name, lambda _email, code: codes.append(code))
        verified = Api(args.api).call('verify_email_code', challenge=challenge['challenge'], code=codes[0])
        require(verified['ok'], f'{kind} account verifies through the HTTP ingress')
        client = Api(args.api, verified['token'])
        session = client.call('current_session')
        receipt['users'].append(dict(kind=kind, name=name, token=verified['token'],
                                     actor_id=session['actor_id'], email=challenge['email']))
    users = receipt['users']
    clients = [Api(args.api, user['token']) for user in users]
    require(len({user['actor_id'] for user in users}) == 4, 'four verified users have four distinct actors')
    require(len({user['token'] for user in users}) == 4, 'four sessions have distinct credentials')
    write_receipt(receipt_path, receipt)

    for user in users:
        user['name'] = 'Edited ' + user['name']
    edited = parallel([lambda client=client, user=user: client.call('save_account_profile', display_name=user['name'])
                       for client, user in zip(clients, users)])
    require(all(result['ok'] and result['display_name'] == user['name'] for result, user in zip(edited, users)),
            'four simultaneous account edits save their respective names')
    parallel([lambda client=client, user=user: assert_identity(client, user)
              for client, user in zip(clients, users)])

    drafts = [dict(name=f'Multi Cafe {index + 1} {run}', cuisine='Cafe',
                   description='Fictional multi-user acceptance company', address=f'{101 + index} Fictional Way',
                   website='', menu_text=f'Private menu {index + 1} {run}', menu_url='', image_url='', confirmed=True)
              for index in range(2)]
    activated = parallel([lambda client=client, draft=draft: client.call('save_business_draft', **draft)
                          for client, draft in zip(clients[2:], drafts)])
    require(all(result['ok'] and result['status'] == 'pending_review' for result in activated),
            'two simultaneous submissions remain private until approval')
    state = CodeStore(ROOT / '.jac/onboarding')
    for user in users[2:]:
        state.approve_business(user['actor_id'], 'HTTP fixture reviewer', 'Verified fictional business authority', business_revision(state.draft(user['actor_id'])))
    activated = parallel([lambda client=client, draft=draft: client.call('save_business_draft', **draft)
                          for client, draft in zip(clients[2:], drafts)])
    require(all(result['ok'] and result['status'] == 'active' for result in activated),
            'two approved businesses activate concurrently')
    for client, user, draft in zip(clients[2:], users[2:], drafts):
        user.update(restaurant_id=client.call('current_session')['restaurant_id'],
                    business_name=draft['name'], menu_text=draft['menu_text'])
        private = client.call('get_business_draft')
        require(private['name'] == draft['name'] and private['menu_text'] == draft['menu_text'],
                'each business reads only its own saved draft')
    require(len({user['restaurant_id'] for user in users[2:]}) == 2, 'businesses receive distinct owned restaurants')
    repeated = parallel([lambda client=client, draft=draft: client.call('save_business_draft', **draft)
                         for client, draft in zip(clients[2:], drafts)])
    require(all(result['ok'] for result in repeated), 'repeated concurrent business saves succeed')
    for client, user in zip(clients[2:], users[2:]):
        assert_identity(client, user)
    for student in clients[:2]:
        require(not student.call('get_business_draft')['ok'], 'student cannot read a business draft')

    tastes = [dict(categories=['pizza'], diets=['vegetarian'], price_range='under5'),
              dict(categories=['coffee'], diets=['vegan'], price_range='8to12')]
    saved_tastes = parallel([
        lambda client=client, taste=taste: client.call('save_taste', categories=','.join(taste['categories']),
                                                     diets=','.join(taste['diets']), price_range=taste['price_range'])
        for client, taste in zip(clients[:2], tastes)])
    require(all(result['ok'] for result in saved_tastes), 'students save distinct tastes concurrently')
    for student, user, taste in zip(clients[:2], users[:2], tastes):
        user['taste'] = taste
        actual = student.call('taste_choices')
        require(actual['completed'] and all(actual[key] == value for key, value in taste.items()),
                'student tastes are private to each session')

    now = datetime.now(ZoneInfo('America/Detroit'))
    posts = [dict(offer_id='', create_key=secrets.token_hex(16), title=f'Multi-user lunch {index + 1} {run}', description='Fictional concurrent acceptance offer',
                  price='4.00', regular_price='6.00',
                  start_local=(now - timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M'),
                  end_local=(now + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M'),
                  quantity='1' if index == 0 else '3', eligibility='Valid test U-M ID',
                  terms='One fictional lunch per person', dietary='vegetarian', menu_item='') for index in range(2)]
    published = parallel([lambda client=client, post=post: client.call('save_offer', **post)
                          for client, post in zip(clients[2:], posts)])
    require(all(result['ok'] for result in published), 'two businesses publish offers concurrently')
    for result, post in zip(published, posts):
        post['offer_id'] = result['code']
        receipt['published_offer_ids'].append(result['code'])
        receipt['offers'].append(dict(id=result['code'], title=post['title']))
    require(len(set(receipt['published_offer_ids'])) == 2, 'concurrent posts receive distinct offer identities')
    receipt['stage'] = 'published'
    write_receipt(receipt_path, receipt)
    parallel([lambda client=client: assert_public_offers(client, receipt) for client in [Api(args.api), *clients]])
    for index, business in enumerate(clients[2:]):
        portal = business.call('merchant_portal')
        require({offer['id'] for offer in portal['offers']} == {posts[index]['offer_id']},
                'merchant management lists only its own post')
        require(not business.call('save_offer', **{**posts[1 - index], 'title': 'Forbidden cross-owner edit'})['ok'],
                'merchant cannot edit the other business offer')

    offer_id = posts[0]['offer_id']
    claims = parallel([lambda student=student: student.call('claim_offer', offer_id=offer_id)
                       for student in clients[:2]])
    require(sum(bool(result['ok']) for result in claims) == 1, 'simultaneous one-unit claims produce exactly one winner')
    winner_index = next(index for index, result in enumerate(claims) if result['ok'])
    winner, loser = clients[winner_index], clients[1 - winner_index]
    claim = claims[winner_index]
    payload = claim['qr_payload']
    require(bool(payload) and bool(claim['claim_id']), 'winner receives its private QR and claim identity')
    held = winner.call('get_offer', offer_id=offer_id)
    require(held['my_qr_payload'] == payload and held['my_status'] == 'claimed' and held['remaining'] == 0,
            'winner alone owns the last-unit hold')
    for visitor in (loser, Api(args.api), *clients[2:]):
        public = visitor.call('get_offer', offer_id=offer_id)
        require(not public['my_qr_payload'] and not public['my_claim_id'] and not public['my_status'],
                'other sessions see the offer without student claim credentials')
        matches = [item['offer'] for item in visitor.call('home_feed')['items'] if item['offer']['id'] == offer_id]
        require(len(matches) == 1 and not matches[0]['my_qr_payload'] and not matches[0]['my_claim_id'],
                'shared home feed never exposes another student QR')
    require(not clients[3].call('resolve_claim', qr_payload=payload)['ok']
            and not clients[3].call('redeem_claim', qr_payload=payload)['ok'],
            'other business cannot inspect or redeem the winning claim')
    require(clients[2].call('resolve_claim', qr_payload=payload)['ok'], 'owning business resolves the winning claim')
    redeemed = parallel([lambda: clients[2].call('redeem_claim', qr_payload=payload)] * 2)
    require(sum(bool(result['ok']) for result in redeemed) == 1, 'simultaneous owner redemptions consume the claim once')
    require(not clients[2].call('redeem_claim', qr_payload=payload)['ok'], 'duplicate redemption is rejected')
    require(winner.call('get_offer', offer_id=offer_id)['my_status'] == 'redeemed', 'winner sees its redeemed state')
    require(not loser.call('claim_offer', offer_id=offer_id)['ok'], 'redeemed stock cannot be claimed again')
    receipt.update(stage='complete', winner_actor_id=users[winner_index]['actor_id'])
    write_receipt(receipt_path, receipt)
    print('Concurrent multi-user HTTP acceptance passed. Four private sessions saved for restart/browser checks.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, AssertionError) as error:
        raise SystemExit('FAIL ' + str(error))
