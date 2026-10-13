"""Opt-in Chromium smoke test against the disposable account-post HTTP workspace.

Requires Python Playwright with Chromium installed, and the running isolated
onboarding-check app at port 8240 after account_posts_http.py. Uses real RPCs.
No mail is sent; the verified new-business session comes from the HTTP test receipt.
"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess

from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--screenshots', required=True, type=Path)
    args = parser.parse_args()
    if args.workspace.name != 'onboarding-check':
        raise SystemExit('Only the disposable onboarding-check workspace is supported.')
    receipt = json.loads((args.workspace / '.jac/account-post-check.json').read_text())
    args.screenshots.mkdir(parents=True, exist_ok=True)
    run = secrets.token_hex(4)
    origin = 'http://127.0.0.1:8240'
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin, wait_until='networkidle')
        expect(page.get_by_text('Welcome to M-Local', exact=True)).to_be_visible()
        page.get_by_role('button', name='List my business', exact=False).click()
        expect(page.get_by_placeholder('Your name')).to_be_visible()
        page.get_by_role('button', name='Sign in', exact=True).click()
        expect(page.get_by_placeholder('Your name')).to_have_count(0)
        page.screenshot(path=str(args.screenshots / 'business-signin-390.png'))
        expect(page.get_by_role('button', name='Existing restaurant sign-in', exact=True)).to_have_count(0)
        expect(page.get_by_role('button', name='Demo sign-in', exact=True)).to_have_count(0)
        expect(page.locator('input[type="password"]')).to_have_count(0)
        # Restore the real verified business session created by the HTTP OTP
        # acceptance test. This browser check does not send or intercept mail.
        page.evaluate('(token) => localStorage.setItem("jac_token", token)', receipt['business_token'])
        page.reload(wait_until='networkidle')
        expect(page.get_by_text('Manage', exact=True)).to_be_visible()
        page.get_by_text('Manage', exact=True).click()
        expect(page.get_by_text('New offer', exact=True)).to_be_visible()
        page.get_by_text('New offer', exact=True).click()
        title = 'Browser lunch ' + run
        page.get_by_placeholder('Lunch bowl for $7').fill(title)
        page.get_by_placeholder('7.00', exact=True).fill('6.50')
        page.get_by_placeholder('One per student. Dine-in only.').fill('One per student. Fictional browser test.')
        page.get_by_text('Offers', exact=True).click()
        page.get_by_text('Manage', exact=True).click()
        expect(page.get_by_placeholder('Lunch bowl for $7')).to_have_value(title)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Composer overflows phone width'
        page.get_by_placeholder('Lunch bowl for $7').scroll_into_view_if_needed()
        page.screenshot(path=str(args.screenshots / 'offer-composer-390.png'))
        page.get_by_role('button', name='Publish offer', exact=True).click()
        expect(page.get_by_placeholder('Lunch bowl for $7')).to_have_count(0)
        expect(page.get_by_text(title, exact=True)).to_have_count(1)
        page.get_by_text('Offers', exact=True).click()
        expect(page.get_by_text(title, exact=True)).to_have_count(1)
        page.reload(wait_until='networkidle')
        expect(page.get_by_text(title, exact=True)).to_have_count(1)
        page.get_by_text('Account', exact=True).click()
        name = 'Browser owner ' + run
        page.get_by_placeholder('Display name').fill(name)
        page.get_by_role('button', name='Save account', exact=True).click()
        expect(page.get_by_text('Profile saved.', exact=True)).to_be_visible()
        page.reload(wait_until='networkidle')
        expect(page.get_by_text(name, exact=True)).to_be_visible()
        print('PASS email-only sign-in UI, verified merchant session, retained offer draft, publication and profile persistence at 390px')
        context.close()

        context = browser.new_context(viewport={'width': 390, 'height': 844})
        context.add_init_script('localStorage.setItem("jac_token", ' + json.dumps(receipt['new_business_token']) +
                                '); localStorage.setItem("mlocal_audience", "business");')
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin, wait_until='networkidle')
        page.get_by_text('Business profile', exact=True).click()
        expect(page.get_by_placeholder('Business name')).to_have_value('')
        business_name = 'Browser self-service cafe ' + run
        description = 'Fictional business created in Chromium ' + run
        page.get_by_placeholder('Business name').fill(business_name)
        page.get_by_placeholder('Street address').fill('123 Fictional Browser Test Street')
        page.get_by_placeholder('About your business').fill(description)
        page.get_by_role('checkbox').check()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Business profile overflows phone width'
        page.get_by_placeholder('Business name').scroll_into_view_if_needed()
        page.screenshot(path=str(args.screenshots / 'business-profile-390.png'))
        page.get_by_role('button', name='Submit for review', exact=True).click()
        expect(page.get_by_role('button', name='Check approval', exact=True)).to_be_visible()
        expect(page.get_by_text('Manage', exact=True)).to_have_count(0)
        session = page.request.post(origin + '/function/current_session', data={},
            headers={'Authorization': 'Bearer ' + receipt['new_business_token']}).json()['data']['result']
        pending = subprocess.run(['bash', 'scripts/review-business.sh', 'list'], cwd=args.workspace,
                                 capture_output=True, text=True, timeout=180)
        assert pending.returncode == 0, 'Fixture review list failed'
        submission = next(item['submission'] for item in json.loads(pending.stdout) if item['actor'] == session['actor_id'])
        reviewed = subprocess.run(['bash', 'scripts/review-business.sh', 'approve', '--actor', session['actor_id'],
                                  '--by', 'Browser fixture reviewer', '--note', 'Verified fictional browser business',
                                  '--submission', submission],
                                 cwd=args.workspace, capture_output=True, text=True, timeout=180)
        assert reviewed.returncode == 0, 'Fixture operator review failed'
        page.get_by_role('button', name='Check approval', exact=True).click()
        expect(page.get_by_role('button', name='Continue to offers', exact=True)).to_be_visible()
        page.get_by_role('button', name='Continue to offers', exact=True).click()
        expect(page.get_by_text('Manage', exact=True)).to_be_visible()
        expect(page.get_by_text('New offer', exact=True)).to_be_visible()
        expect(page.get_by_placeholder('Business name')).to_have_count(0)
        expect(page.get_by_placeholder('Restaurant name')).to_have_value(business_name)
        expect(page.get_by_placeholder('Short description')).to_have_value(description)

        page.get_by_text('New offer', exact=True).click()
        business_offer = 'Self-service lunch ' + run
        page.get_by_placeholder('Lunch bowl for $7').fill(business_offer)
        page.get_by_placeholder('7.00', exact=True).fill('7.25')
        page.get_by_placeholder('One per student. Dine-in only.').fill('One per student. Fictional self-service test.')
        page.get_by_role('button', name='Publish offer', exact=True).click()
        expect(page.get_by_placeholder('Lunch bowl for $7')).to_have_count(0)
        expect(page.get_by_text(business_offer, exact=True)).to_have_count(1)
        page.get_by_text('Offers', exact=True).click()
        expect(page.get_by_text(business_offer, exact=True)).to_have_count(1)
        page.reload(wait_until='networkidle')
        expect(page.get_by_text(business_offer, exact=True)).to_have_count(1)

        page.get_by_text('Manage', exact=True).click()
        updated_description = 'Edited after activation in Chromium ' + run
        page.get_by_placeholder('Short description').fill(updated_description)
        page.get_by_text('Save profile', exact=True).click()
        expect(page.get_by_text('Profile saved.', exact=True)).to_be_visible()
        page.reload(wait_until='networkidle')
        page.get_by_text('Manage', exact=True).click()
        expect(page.get_by_placeholder('Restaurant name')).to_have_value(business_name)
        expect(page.get_by_placeholder('Short description')).to_have_value(updated_description)
        expect(page.get_by_text(business_offer, exact=True)).to_have_count(1)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Activated business management overflows phone width'
        page.get_by_placeholder('Restaurant name').scroll_into_view_if_needed()
        page.screenshot(path=str(args.screenshots / 'business-manage-390.png'))
        print('PASS real verified business setup, immediate Manage access, publication, and company profile edit/reload at 390px')
        context.close()
        browser.close()
        assert not errors, errors


if __name__ == '__main__':
    main()
