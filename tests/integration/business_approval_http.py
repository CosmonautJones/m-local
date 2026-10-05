"""One-time approval through the real local operator command and HTTP API.

Use a fresh /var/tmp/m-local-release-approval.* workspace on loopback port 8252.
No real email is sent. Test receipts stay private in that disposable workspace.
"""
import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.email_codes import CodeStore, business_revision
from qr_http import Api, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-restart', action='store_true')
    args = parser.parse_args()
    if (Path.cwd().resolve() != ROOT or ROOT.parent != Path('/var/tmp')
            or not ROOT.name.startswith('m-local-release-approval.')):
        parser.error('Run only from the isolated /var/tmp/m-local-release-approval.* workspace.')
    api = 'http://127.0.0.1:8252'
    receipt_path = ROOT / '.jac/approval-http.json'
    state = CodeStore(ROOT / '.jac/onboarding')
    if args.verify_restart:
        receipt = json.loads(receipt_path.read_text())
        owner = Api(api, receipt['token'])
        require(owner.call('current_session')['role'] == 'merchant', 'approved authority survives restart')
        require(owner.call('get_business_profile')['name'] == receipt['name'], 'published profile survives restart')
        require(any(o['id'] == receipt['offer'] for o in owner.call('merchant_portal')['offers']),
                'self-managed offer survives restart')
        require(state.business_approved(receipt['actor']), 'private approval survives restart')
        return
    anonymous = Api(api)
    run = secrets.token_hex(4)

    def verify(kind):
        codes = []
        value = 'ap' + run + kind[0] + ('@example.test' if kind == 'business' else '')
        challenge = state.request(value, kind, 'Approval fixture', lambda _email, code: codes.append(code))
        result = anonymous.call('verify_email_code', challenge=challenge['challenge'], code=codes[0])
        require(result['ok'] and result.get('token'), f'{kind} verifies through real HTTP')
        return Api(api, result['token'])

    owner, student = verify('business'), verify('student')
    actor = owner.call('current_session')['actor_id']
    slug = 'business-' + actor
    fields = dict(name='Approval Cafe ' + run, cuisine='Cafe', description='Fictional acceptance profile',
                  address='123 Fixture Street', website='', menu_text='Soup $5', menu_url='',
                  image_url='https://example.com/cafe.png', confirmed=True)
    pending = owner.call('save_business_draft', **fields)
    require(pending['ok'] and pending['status'] == 'pending_review', 'business save submits a private review')
    require(owner.call('current_session')['role'] == 'business', 'submission does not confer merchant authority')
    require(not owner.call('merchant_portal')['ok'], 'unapproved business cannot manage offers')
    require(not student.call('get_business_profile', slug=slug)['ok'], 'unapproved profile is invisible to students')
    require(not student.call('save_business_draft', **fields)['ok'], 'student cannot submit a business')
    request = urllib.request.Request(api + '/function/approve_business', b'{}',
        {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + owner.token}, method='POST')
    try:
        urllib.request.urlopen(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code in (403, 404, 405), 'approval has no callable client RPC')
    else:
        raise AssertionError('Approval must not be exposed to the browser')

    def approve():
        result = subprocess.run(['bash', 'scripts/review-business.sh', 'approve', '--actor', actor,
                                 '--by', 'Fixture operator', '--note', 'Confirmed fictional authority',
                                 '--submission', business_revision(state.draft(actor))],
                                cwd=ROOT, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise AssertionError('Local review command failed: ' + result.stderr[-3000:])
        require('Business approved. The owner can continue to offers.' in result.stdout, 'local operator command records approval')

    approve()
    require(owner.call('get_business_draft')['status'] == 'approved', 'owner sees approval without premature public activation')
    require(owner.call('save_business_draft', **fields)['status'] == 'active', 'owner continues setup after approval')
    session = owner.call('current_session')
    require(session['role'] == 'merchant' and session['restaurant_id'], 'approved activation enables merchant access')
    first_id = session['restaurant_id']
    public = student.call('get_business_profile', slug=slug)
    require(public['ok'] and public['image_url'] == fields['image_url'], 'approved profile and image become visible')
    require('menu_text' not in public and 'owner_actor_id' not in public, 'public projection keeps private fields private')
    approve()
    require(owner.call('current_session')['restaurant_id'] == first_id, 'repeated operator command keeps one business')
    fields['description'] = 'Edited description ' + run
    edited = owner.call('save_business_draft', **fields)
    require(edited['ok'] and edited['status'] == 'active', 'routine profile edit needs no second review')
    original_name = fields['name']
    fields['name'] = 'Renamed Approval Cafe ' + run
    require(owner.call('save_business_draft', **fields)['status'] == 'pending_review', 'name change requires review')
    require(student.call('get_business_profile', slug=slug)['name'] == original_name, 'pending change leaves approved public identity intact')
    require(owner.call('current_session')['role'] == 'merchant', 'pending identity review preserves offer-management authority')
    portal = owner.call('merchant_portal')
    require(not owner.call('update_profile', name=fields['name'], cuisine=portal['cuisine'], blurb=portal['blurb'],
        address=portal['address'], neighborhood=portal['neighborhood'], entrance_note=portal['entrance_note'],
        note_date=portal['note_date'])['ok'], 'legacy profile RPC cannot bypass identity review')
    fields['description'] = 'Routine edit while identity awaits review ' + run
    require(owner.call('update_profile', name=original_name, cuisine='Bakery', blurb=fields['description'],
        address=portal['address'], neighborhood=portal['neighborhood'], entrance_note=portal['entrance_note'],
        note_date=portal['note_date'])['ok'], 'routine legacy edit remains self-service during identity review')
    draft = owner.call('get_business_draft')
    require(draft['name'] == fields['name'] and draft['status'] == 'pending_review' and
            draft['description'] == fields['description'] and draft['cuisine'] == 'Bakery',
            'business form retains pending identity and latest routine edits')
    fields['cuisine'] = 'Bakery'
    approve()
    require(owner.call('save_business_draft', **fields)['status'] == 'active', 'reviewed name change publishes through owner activation')
    require(owner.call('current_session')['restaurant_id'] == first_id, 'identity review retains business and offers identity')
    now = datetime.now(ZoneInfo('America/Detroit'))
    offer = owner.call('save_offer', offer_id='', create_key=secrets.token_hex(16), title='Approved lunch ' + run, description='Fixture offer',
        price='5', regular_price='7', start_local=(now - timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M'),
        end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='2',
        eligibility='Valid U-M ID', terms='One per student', dietary='', menu_item='')
    require(offer['ok'], 'approved owner publishes an offer without another review')
    require(any(item['offer']['id'] == offer['code'] for item in student.call('home_feed')['items']),
            'approved offer appears in student discovery')
    receipt = dict(token=owner.token, actor=actor, name=fields['name'], offer=offer['code'])
    fd = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(receipt, stream)


if __name__ == '__main__':
    main()
