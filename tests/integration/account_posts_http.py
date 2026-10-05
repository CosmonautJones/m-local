#!/usr/bin/env python3
"""Account/profile/post acceptance against an explicitly isolated local Jac app.

Run from a disposable directory named onboarding-check on port 8240, after
provision-demo.py and a restart with its qr-demo.env. Challenges are injected
locally; no email is sent. --verify-restart checks the same persisted records.
"""
import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.email_codes import CodeStore, business_revision
from qr_http import Api, provision, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-restart', action='store_true')
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT or ROOT.name != 'onboarding-check':
        raise SystemExit('Run only from the isolated onboarding-check workspace.')
    api = 'http://127.0.0.1:8240'
    receipt_path = ROOT / '.jac/account-post-check.json'
    if args.verify_restart:
        saved = json.loads(receipt_path.read_text())
        student = Api(api, saved['student_token'])
        business = Api(api, saved['business_token'])
        require(student.call('get_account_profile')['display_name'] == saved['name'],
                'edited account profile survives server restart')
        require(student.call('current_session')['display_name'] == saved['name'],
                'session name survives server restart')
        require(business.call('get_business_draft')['name'] == saved['business_name'],
                'business profile edits survive server restart')
        require(business.call('current_session')['role'] == 'merchant'
                and business.call('current_session')['restaurant_id'] == saved['business_restaurant_id'],
                'self-service restaurant ownership survives server restart')
        require(Api(api).call('get_offer', offer_id=saved['offer_id'])['title'] == saved['title'],
                'published and edited offer survives server restart')
        return

    run = secrets.token_hex(5)

    def verify(value, kind, name, *, clock=time.time):
        codes = []
        local_state = CodeStore(ROOT / '.jac/onboarding', clock=clock)
        challenge = local_state.request(value, kind, name, lambda _email, code: codes.append(code))
        return Api(api).call('verify_email_code', challenge=challenge['challenge'], code=codes[0])

    users = []
    for index, kind in enumerate(('student', 'student', 'business', 'business')):
        value = f'profile{run}{index}' + ('@example.test' if kind == 'business' else '')
        result = verify(value, kind, 'Initial fixture name')
        require(result['ok'], f'{kind} account created through verified OTP')
        users.append((Api(api, result['token']), value))
    (student, student_value), (other_student, _), (business, _), (other_business, _) = users
    before = student.call('get_account_profile')
    require(before['email_verified'] and before['role'] == 'student', 'account profile shows verified identity')
    renamed = 'Updated fixture ' + run
    result = student.call('save_account_profile', display_name=renamed)
    require(result['ok'] and result['display_name'] == renamed, 'student can edit display name')
    require(student.call('current_session')['display_name'] == renamed, 'current session reflects account edit')
    require(other_student.call('get_account_profile')['display_name'] == 'Initial fixture name',
            'account edit does not change another account')
    for bad in ('', '   ', 'x' * 81, 'bad\nname'):
        require(not student.call('save_account_profile', display_name=bad)['ok'], 'invalid account name is rejected')
    unchanged = student.call('get_account_profile')
    require(unchanged['display_name'] == renamed and unchanged['email'] == before['email']
            and unchanged['role'] == 'student', 'invalid edit preserves name and immutable identity')
    require(not Api(api).call('get_account_profile')['ok'], 'anonymous profile read is denied')
    require(not Api(api).call('save_account_profile', display_name='Intruder')['ok'], 'anonymous profile edit is denied')

    # Advance only the injected request clock to avoid waiting for the send cooldown.
    login = verify(student_value, 'student', '', clock=lambda: time.time() + 61)
    require(login['ok'], 'returning email sign-in needs no repeated name')
    require(Api(api, login['token']).call('current_session')['display_name'] == renamed,
            'returning sign-in preserves edited name')
    unknown = verify('missing' + run, 'student', '')
    require(not unknown['ok'] and 'Create account' in unknown['message'],
            'verified unknown sign-in clearly routes to signup')

    draft = dict(name='Fixture Company ' + run, cuisine='Cafe', description='Fictional acceptance data',
                 address='123 Fictional Way', website='', menu_text='Soup $5', menu_url='', image_url='', confirmed=True)
    require(not business.call('merchant_portal')['ok'], 'business must finish a profile before posting')
    # An older saved application stays private until the owner explicitly saves.
    actor = business.call('current_session')['actor_id']
    CodeStore(ROOT / '.jac/onboarding').save_draft(actor, {**draft, 'status': 'pending_review'})
    require(business.call('get_business_draft')['status'] == 'pending_review', 'legacy application loads before activation')
    require(not business.call('merchant_portal')['ok'], 'reading a legacy application does not publish it')
    require(not business.call('save_business_draft', **{**draft, 'confirmed': False})['ok'],
            'business still confirms representation before activation')
    activated = business.call('save_business_draft', **draft)
    require(activated['ok'] and activated['status'] == 'pending_review', 'company submission waits for host approval')
    require(not business.call('merchant_portal')['ok'], 'submission does not grant publishing authority')
    state = CodeStore(ROOT / '.jac/onboarding')
    state.approve_business(actor, 'HTTP fixture reviewer', 'Verified fictional business authority', business_revision(state.draft(actor)))
    activated = business.call('save_business_draft', **draft)
    require(activated['ok'] and activated['status'] == 'active', 'approved company activates on save')
    business_restaurant_id = business.call('current_session')['restaurant_id']
    require(business.call('current_session')['role'] == 'merchant' and business_restaurant_id,
            'approved profile owner becomes a merchant without restart')
    require(business.call('merchant_portal')['name'] == draft['name'], 'activated business owns its new profile')
    draft['name'] = 'Edited Fixture Company ' + run
    require(business.call('save_business_draft', **draft)['status'] == 'pending_review', 'name change waits for review')
    state.approve_business(actor, 'HTTP fixture reviewer', 'Verified changed fictional business name', business_revision(state.draft(actor)))
    require(business.call('save_business_draft', **draft)['status'] == 'active', 'reviewed company name publishes')
    require(business.call('current_session')['restaurant_id'] == business_restaurant_id,
            'repeated company saves preserve restaurant identity')
    require(business.call('merchant_portal')['name'] == draft['name'], 'company edits update its live restaurant')
    require(business.call('get_business_draft')['name'] == draft['name'], 'company edit persists on reopen')
    require(other_business.call('get_business_draft')['name'] == '', 'company drafts stay private to their owner')
    require(not student.call('save_business_draft', **draft)['ok'], 'student cannot create company profile')
    require(not student.call('get_business_draft')['ok'], 'student cannot open company draft API')
    require(not student.call('import_business_website', website='https://127.0.0.1')['ok'],
            'student cannot use company website import')
    require(not other_business.call('merchant_portal')['ok'], 'another incomplete business has no merchant authority')

    accounts = json.loads((ROOT / '.jac/qr-demo-accounts.json').read_text())
    merchants = []
    for role in ('merchant_leaf', 'merchant_noodle'):
        account = accounts[role]
        session = provision.post(api, '/user/login', {
            'identity': {'type': 'email', 'value': account['email']},
            'credential': {'type': 'password', 'password': account['password']}})
        merchants.append(Api(api, session['token']))
    merchant, other_merchant = merchants
    demo_profile = merchant.call('save_account_profile', display_name='Demo owner ' + run)
    require(demo_profile['ok'] and demo_profile['email'] == '' and not demo_profile['email_verified']
            and demo_profile['role'] == 'merchant', 'demo profile edit preserves unverified email and server role')
    profile = merchant.call('merchant_portal')
    require(profile['ok'], 'provisioned merchant can manage its business')
    editable = ('name', 'cuisine', 'blurb', 'address', 'neighborhood', 'entrance_note', 'note_date')
    fields = {key: profile[key] for key in editable}
    require(not merchant.call('update_profile', **{**fields, 'name': ''})['ok'],
            'invalid restaurant profile returns failure')
    require(merchant.call('merchant_portal')['name'] == fields['name'], 'invalid restaurant edit leaves saved profile intact')
    fields['blurb'] = 'Updated company profile ' + run
    require(merchant.call('update_profile', **fields)['ok'], 'approved company profile edit saves')
    require(merchant.call('merchant_portal')['blurb'] == fields['blurb'], 'approved company profile edit persists')

    now = datetime.now(ZoneInfo('America/Detroit'))
    post = dict(offer_id='', create_key=secrets.token_hex(16), title='Published fixture ' + run, description='Fictional local offer',
                price='3.50', regular_price='5.00', start_local=(now-timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M'),
                end_local=(now+timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='8',
                eligibility='Valid U-M ID', terms='One per person', dietary='vegetarian', menu_item='Fixture soup')
    require(not other_business.call('save_offer', **post)['ok'], 'incomplete business cannot publish a post')
    own_post = business.call('save_offer', **{**post, 'title': 'Self-service fixture ' + run})
    require(own_post['ok'], 'newly registered company can publish immediately')
    public_items = Api(api).call('home_feed')['items']
    matching = [item['offer'] for item in public_items if item['offer']['id'] == own_post['code']]
    require(len(matching) == 1 and not matching[0]['is_demo'] and matching[0]['state'] == 'active',
            'real business publication appears exactly once in the public home feed')
    require(not merchant.call('save_offer', **{**post, 'offer_id': own_post['code']})['ok'],
            'provisioned merchant cannot edit the new company post')
    require(other_business.call('save_business_draft', **draft)['ok'], 'second company can also activate')
    other_actor = other_business.call('current_session')['actor_id']
    state.approve_business(other_actor, 'HTTP fixture reviewer', 'Verified second fictional business authority', business_revision(state.draft(other_actor)))
    require(other_business.call('save_business_draft', **draft)['status'] == 'active', 'second approved business activates')
    require(other_business.call('current_session')['restaurant_id'] != business_restaurant_id,
            'identical business names never share ownership')
    require(not other_business.call('save_offer', **{**post, 'offer_id': own_post['code']})['ok'],
            'second self-service merchant cannot edit the first company post')
    claim = student.call('claim_offer', offer_id=own_post['code'])
    require(claim['ok'], 'student can claim a self-service business offer')
    require(business.call('set_offer_status', offer_id=own_post['code'], status='paused')['ok'],
            'business pauses an offer with a saved student claim')
    held_items = student.call('home_feed', price_range='8to12', diets='vegan')['items']
    held = [item['offer'] for item in held_items if item['offer']['id'] == own_post['code']]
    require(len(held) == 1 and held[0]['my_status'] == 'claimed'
            and held[0]['my_qr_payload'] == claim['qr_payload'],
            'saved QR stays reachable after pausing and nonmatching discovery filters')
    for visitor in (Api(api), other_student):
        require(not any(item['offer']['id'] == own_post['code'] for item in visitor.call('home_feed')['items']),
                'paused claimed offer stays hidden from other visitors')
    require(business.call('set_offer_status', offer_id=own_post['code'], status='active')['ok'],
            'business resumes the offer without changing its claim')
    require(business.call('resolve_claim', qr_payload=claim['qr_payload'])['ok'],
            'self-service owner can access its private claim')
    require(not other_business.call('redeem_claim', qr_payload=claim['qr_payload'])['ok'],
            'other self-service company cannot redeem the private claim')
    require(business.call('redeem_claim', qr_payload=claim['qr_payload'])['ok'],
            'self-service owner can redeem the offer')
    require(business.call('save_business_draft', **draft)['ok']
            and any(offer['id'] == own_post['code'] for offer in business.call('merchant_portal')['offers']),
            'resaving company profile preserves published offers')
    require(not student.call('save_offer', **post)['ok'], 'student cannot publish a merchant post')
    require(not merchant.call('save_offer', **{**post, 'price': 'NaN'})['ok'], 'invalid post rejected before creation')
    published = merchant.call('save_offer', **post)
    require(published['ok'], 'merchant creates a real offer post')
    post['offer_id'] = published['code']
    listed = [offer for offer in merchant.call('merchant_portal')['offers'] if run in offer['title']]
    require(len(listed) == 1 and listed[0]['id'] == post['offer_id'], 'publication creates exactly one post')
    public = Api(api).call('get_offer', offer_id=post['offer_id'])
    require(public['state'] == 'active' and public['title'] == post['title'], 'new post is publicly discoverable')
    require(not other_merchant.call('save_offer', **post)['ok'], 'another company cannot edit the post')
    require(not merchant.call('save_offer', **{**post, 'quantity': '0'})['ok'], 'invalid post edit rejected')
    require(Api(api).call('get_offer', offer_id=post['offer_id'])['quantity'] == 8,
            'rejected post edit leaves prior data intact')
    post['title'] = 'Edited fixture ' + run
    require(merchant.call('save_offer', **post)['ok'], 'published post can be edited')
    require(Api(api).call('get_offer', offer_id=post['offer_id'])['title'] == post['title'],
            'post edits reach the public offer view')
    listed = [offer for offer in merchant.call('merchant_portal')['offers'] if run in offer['title']]
    require(len(listed) == 1 and listed[0]['id'] == post['offer_id'], 'editing retains the single original post')
    require(merchant.call('set_offer_status', offer_id=post['offer_id'], status='paused')['ok'], 'merchant can pause post')
    require(Api(api).call('get_offer', offer_id=post['offer_id']) is None, 'paused public get returns nothing')
    require(any(offer['id'] == post['offer_id'] for offer in merchant.call('merchant_portal')['offers']),
            'merchant still sees a paused offer')
    require(merchant.call('set_offer_status', offer_id=post['offer_id'], status='active')['ok'], 'merchant can resume post')
    browser_business = verify('browser' + run + '@example.test', 'business', 'Browser fixture owner')
    require(browser_business['ok'], 'fresh business session prepared for real browser activation')
    receipt = dict(student_token=student.token, business_token=business.token,
                   new_business_token=browser_business['token'], name=renamed,
                   business_name=draft['name'], business_restaurant_id=business_restaurant_id,
                   offer_id=post['offer_id'], title=post['title'])
    descriptor = os.open(receipt_path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(receipt, stream)
    print('Account, company profile and post HTTP acceptance passed. Restart and run --verify-restart next.')


if __name__ == '__main__':
    main()
