#!/usr/bin/env python3
"""Real business-profile HTTP acceptance in a disposable local Jac app.

Start a fresh /tmp/m-local-theme-profile.* app on loopback port 8155 with
MLOCAL_ONBOARDING_DIR=<workspace>/.jac/onboarding, MLOCAL_MERCHANT_OWNERS={},
MLOCAL_DEMO_STUDENTS=[] and MLOCAL_DEMO_MODE=0. Run this script from any directory
with --workspace <workspace> through bash scripts/python.sh so Jac service imports
use the pinned runtime. Never point the server at a shared data store.

OTP challenges are inserted only into the named isolated private store. Email
verification, activation, reads, publication and claims use real HTTP. No email
is sent; tokens, codes, actor identifiers and QR credentials are never printed.
The fixture records remain in that disposable app for diagnosis.
"""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import secrets
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.email_codes import CodeStore, business_revision
from qr_http import Api, require


def local_api(value):
    if value not in ('http://127.0.0.1:8155', 'http://localhost:8155'):
        raise argparse.ArgumentTypeError('Use only the disposable loopback API on port 8155.')
    return value


def isolated_workspace(value):
    workspace = Path(value).resolve()
    if (workspace.parent != Path('/tmp').resolve()
            or not workspace.name.startswith('m-local-theme-profile.')
            or not (workspace / 'services/business_profile.jac').is_file()):
        raise argparse.ArgumentTypeError('Use the disposable /tmp/m-local-theme-profile.* app directory.')
    if not (workspace / '.jac/onboarding').resolve().is_relative_to(workspace):
        raise argparse.ArgumentTypeError('The private onboarding store must stay inside the disposable app.')
    return workspace


def assert_public_profile(profile, private_values=()):
    forbidden = {'actor_id', 'owner_actor_id', 'merchant_key', 'claims', 'token',
                 'qr_payload', 'claim_id', 'student_id', 'code', 'email', 'password'}

    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value), 'Profile serialization contains a private identity or credential field.'
            for key, item in value.items():
                if key.startswith('my_'):
                    assert not item, 'Profile serialization contains caller claim data.'
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(profile)
    require(True, 'serialized profile has no private identity fields and all caller claim fields are empty')
    encoded = json.dumps(profile)
    require(all(value not in encoded for value in private_values if value),
            'profile serialization excludes private draft text, tokens and actual held QR credentials')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', type=local_api, default='http://127.0.0.1:8155')
    parser.add_argument('--workspace', type=isolated_workspace, required=True)
    args = parser.parse_args()
    anonymous = Api(args.api)
    require(anonymous.call('get_business_profile').get('http_status') == 401,
            'anonymous business-profile HTTP request is rejected by authentication')
    state = CodeStore(args.workspace / '.jac/onboarding')
    run = secrets.token_hex(5)

    def verified(kind):
        codes = []
        value = 'bp' + run + kind[0] + ('@example.test' if kind == 'business' else '')
        challenge = state.request(value, kind, 'HTTP fixture ' + kind,
                                  lambda _email, code: codes.append(code))
        result = anonymous.call('verify_email_code', challenge=challenge['challenge'], code=codes[0])
        require(result['ok'] and result.get('token'), f'{kind} account verified over real HTTP without email')
        client = Api(args.api, result['token'])
        session = client.call('current_session')
        require(session['authenticated'] and session['email_verified'] and session['role'] == kind,
                f'{kind} HTTP session has verified server-owned identity')
        return client, session

    member, member_session = verified('student')
    owner, owner_session = verified('business')
    require(not owner.call('get_business_profile')['ok'], 'unactivated business has no implicit public profile')
    private_menu = 'Private setup note ' + run
    draft = dict(name='HTTP Profile Cafe ' + run, cuisine='Cafe', description='Fictional profile acceptance data',
                 address='123 Fixture Street', website='', menu_text=private_menu, menu_url='', image_url='', confirmed=True)
    activated = owner.call('save_business_draft', **draft)
    require(activated['ok'] and activated['status'] == 'pending_review', 'verified business submits a private profile over HTTP')
    require(not member.call('get_business_profile', slug='business-' + owner_session['actor_id'])['ok'],
            'unapproved profile is hidden from other members')
    state.approve_business(owner_session['actor_id'], 'HTTP fixture reviewer', 'Verified fictional business authority', business_revision(state.draft(owner_session['actor_id'])))
    activated = owner.call('save_business_draft', **draft)
    require(activated['ok'] and activated['status'] == 'active', 'approved business activates its own profile over HTTP')
    owner_session = owner.call('current_session')
    require(owner_session['role'] == 'merchant', 'activation gives the business its own merchant membership')
    profile = owner.call('get_business_profile')
    require(profile['ok'] and profile['name'] == draft['name'] and profile['offers'] == [],
            'merchant no-argument preview works before publishing any offers')
    slug = profile['slug']
    require(slug and owner_session['restaurant_id'] != slug, 'merchant graph id and public slug remain distinct')
    require(not owner.call('get_business_profile', slug=owner_session['restaurant_id'])['ok'],
            'a graph id is never mistaken for a public slug')
    public = member.call('get_business_profile', slug=slug)
    require(public['ok'] and public['name'] == draft['name'] and public['address'] == draft['address'],
            'a different authenticated member can read the public business profile')
    require(not member.call('get_business_profile')['ok'], 'a member without ownership gets no implicit merchant preview')
    require(not member.call('merchant_portal')['ok'], 'viewing a business grants no merchant authority')
    assert_public_profile(public, (private_menu, member.token, owner.token, member_session['actor_id']))

    now = datetime.now(ZoneInfo('America/Detroit'))
    offer = dict(offer_id='', create_key=secrets.token_hex(16), title='HTTP profile lunch ' + run, description='Synthetic local offer',
                 price='3.50', regular_price='5.00', start_local=(now - timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M'),
                 end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='3',
                 eligibility='Valid U-M ID', terms='Fixture terms', dietary='vegetarian', menu_item='')
    saved = owner.call('save_offer', **offer)
    require(saved['ok'], 'profile owner publishes a dedicated fixture offer')
    offer_id = saved['code']
    linked = member.call('get_business_profile', offer_id=offer_id)
    require(linked['ok'] and linked['slug'] == slug and [o['id'] for o in linked['offers']] == [offer_id],
            'offer-id lookup returns its graph-linked business and published offer')
    claim = member.call('claim_offer', offer_id=offer_id)
    require(claim['ok'] and claim.get('qr_payload'), 'verified member obtains a real held QR credential')
    detail = member.call('get_offer', offer_id=offer_id)
    require(detail['my_qr_payload'] == claim['qr_payload'], 'existing offer detail still returns the owner-scoped held credential')
    for client in (member, owner):
        viewed = client.call('get_business_profile', slug=slug)
        require(viewed['ok'] and len(viewed['offers']) == 1, 'public profile remains readable after a real claim')
        assert_public_profile(viewed, (private_menu, member.token, owner.token,
                                       member_session['actor_id'], claim['qr_payload'], claim['claim_id']))
    require(owner.call('set_offer_status', offer_id=offer_id, status='paused')['ok'], 'fixture offer is paused over HTTP')
    require(member.call('get_business_profile', slug=slug)['offers'] == [], 'paused offers are excluded from public profile')
    require(member.call('get_offer', offer_id=offer_id)['my_qr_payload'] == claim['qr_payload'],
            'pausing does not change the existing saved claim or its detail flow')
    missing = member.call('get_business_profile', slug='unknown-' + run)
    require(not missing['ok'] and not missing['name'] and not missing['offers'], 'unknown slug returns a safe empty result')
    print('Business profile HTTP acceptance passed with two verified accounts and real graph ownership. No email or shared data used.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, AssertionError) as error:
        raise SystemExit('FAIL ' + str(error))
