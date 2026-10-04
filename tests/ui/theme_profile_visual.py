"""Synthetic RPC visual checks. No real email, claims, or business writes."""
import argparse
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright
from refresh_visual import analytics


def run(url, output):
    output.mkdir(parents=True, exist_ok=True)
    errors, shots, requests = [], [], []
    role, scenario = 'guest', 'normal'
    item = dict(id='visual-offer', title='Harvest bowl for $8', description='Roasted seasonal vegetables, warm grains and lemon tahini.',
                restaurant='Arbor Leaf Kitchen', cuisine='Seasonal bowls', price=8, regular_price=12,
                address='120 Example Street, Ann Arbor', neighborhood='Kerrytown', state='active', remaining=5, quantity=8,
                eligibility='Valid university ID', terms='One bowl per student. Takeout only.', menu_item='Harvest bowl',
                dietary=['vegan'], reasons=[], is_demo=False, time_label='Until 3:00 PM', my_status='claimed',
                my_claim_id='visual-claim', my_qr_payload='mlocal:v1:'+'A'*43, my_title='Harvest bowl for $8',
                my_price_cents=800, my_terms='One bowl per student. Takeout only.', my_eligibility='Valid university ID',
                my_expires='3:00 PM', my_expires_ts=time.time()+1200, entrance_note='Use the side entrance.',
                note_date='2026-09-27', start_input='2026-09-27 11:00', end_input='2026-09-27 15:00')
    business = dict(ok=True, message='', slug='arbor-leaf', name=item['restaurant'], cuisine='Seasonal bowls',
                    blurb='A small neighborhood kitchen making bright, seasonal lunches. Stop by for a warm bowl and a little time away from campus.',
                    address=item['address'], neighborhood='Kerrytown', entrance_note=item['entrance_note'],
                    note_date=item['note_date'], is_demo=False, offers=[item])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport=dict(width=390, height=844), reduced_motion='reduce')
        page.on('pageerror', lambda error: errors.append(str(error)))

        def rpc(route):
            name = route.request.url.rsplit('/', 1)[-1]
            requests.append(name)
            session = dict(authenticated=role!='guest', actor_id='visual-user', role=role,
                           restaurant_id='visual-node-id', display_name='Jordan Smith', is_demo=False, email_verified=role!='guest')
            tastes = dict(ok=True, message='', completed=True, signed_in=True, categories=[], diets=[], favorites=[], price_range='',
                          all_categories=[dict(key='bowls',label='Bowls')], all_diets=[dict(key='vegan',label='Vegan')],
                          all_price_ranges=[dict(key='5to8',label='$5 to $8')])
            draft = dict(ok=True,message='',status='draft',name='',cuisine='',description='',address='',website='',
                         menu_text='',menu_url='',image_url='',image_urls=[],menu_urls=[],sources=[])
            values = dict(current_session=session, get_business_profile=business, get_offer=item,
                          home_feed=dict(signed_in=True,personalized=True,completed=True,price_range='',favorites=[],show_samples=False,
                                         items=[dict(offer=item,place='arbor-leaf',place_labels=['Vegan'],categories=[],price_cents=800,
                                                     regular_cents=1200,price_range='',reasons=[],slot='more',is_favorite=False)],total_deals=1,note=''),
                          merchant_portal=dict(**{key:value for key,value in business.items() if key!='slug'},claims=[]),
                          get_account_profile=dict(ok=True,message='',display_name='Jordan Smith',email='jordan@example.test',role=role,email_verified=True,is_demo=False),
                          get_business_draft=draft,
                          request_email_code=dict(ok=True,challenge='synthetic-challenge',email='jordan@umich.edu',retry_after=60,message=''),
                          verify_email_code=dict(ok=False,message='That code is invalid or expired.'),
                          taste_choices=tastes,save_taste=tastes,toggle_favorite=tastes,
                          merchant_insights=analytics((route.request.post_data_json or {}).get('days',30)),
                          offer_defaults=['2026-09-27 11:00','2026-09-27 15:00'])
            if scenario=='empty-feed':
                values['home_feed']=dict(values['home_feed'],items=[],total_deals=0)
            if scenario=='profile-empty':
                values['get_business_profile']=dict(business,offers=[])
            if scenario=='profile-missing':
                values['get_business_profile']=dict(ok=False,message='Not found.')
            if scenario=='account-error':
                values['get_account_profile']=dict(ok=False,message='Could not load your account. Try again.')
            if scenario=='insights-empty':
                data=values['merchant_insights']
                for frame in data['frames']:
                    frame['totals']=dict.fromkeys(frame['totals'],0)
                    frame['daily']=dict.fromkeys(frame['daily'],0)
                    frame['offers']=[]
            if name not in values:
                errors.append('Unexpected RPC: '+name)
                route.fulfill(status=500,json=dict(error='Unexpected fixture request'))
            else:
                route.fulfill(json=dict(ok=True,type='response',data=dict(result=values[name],reports=[]),error=None))

        page.route('**/function/**', rpc)

        def load(next_role, theme, next_scenario='normal'):
            nonlocal role, scenario
            role, scenario = next_role, next_scenario
            page.goto(url)
            page.evaluate('([role,theme])=>{localStorage.clear();localStorage.setItem("mlocal_theme",theme);if(role!=="guest")localStorage.setItem("jac_token","synthetic-token")}', [role,theme])
            page.reload()
            page.get_by_test_id('theme-toggle').wait_for()
            page.evaluate('document.fonts.ready')
            assert page.locator('html').get_attribute('data-theme') == theme

        def capture(name):
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Page overflow: '+name
            assert not page.evaluate('''()=>[...document.querySelectorAll('input,select,textarea,button')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&(r.left< -1||r.right>innerWidth+1)}).map(el=>el.textContent)'''), 'Control overflow: '+name
            logo = page.get_by_role('img',name='M Local',exact=True).first
            assert logo.is_visible(), 'Logo missing: '+name
            assert page.get_by_test_id('theme-toggle').count()==1, 'Duplicate appearance control: '+name
            assert page.evaluate('''async()=>{const image=new Image();image.src='/static/assets/brand/logo-master.png';await image.decode();return image.naturalWidth>0;}'''), 'Logo mask failed: '+name
            assert page.evaluate('''()=>[...document.querySelectorAll('button,input,select,textarea')].filter(el=>el.getBoundingClientRect().width>0).every(el=>getComputedStyle(el).fontFamily.includes('Figtree'))'''), 'Inconsistent control typography: '+name
            page.screenshot(path=str(output/f'{name}.png'), full_page=True)
            shots.append(name)

        # Observe real CSS interpolation, then verify reduced-motion and the
        # reversed accent on the yellow card. No screenshot-only claim of motion.
        load('guest','light')
        page.emulate_media(reduced_motion='no-preference')
        logo=page.get_by_role('img',name='M Local',exact=True)
        before_box=logo.bounding_box()
        card=page.get_by_role('button',name='Find local deals')
        light_color=card.evaluate('(el)=>getComputedStyle(el).backgroundColor')
        assert card.evaluate('(el)=>getComputedStyle(el,"::after").backgroundColor')=='rgb(254, 200, 9)'
        page.get_by_role('button',name='Switch to dark mode',exact=True).click()
        page.wait_for_timeout(75)
        middle_color=card.evaluate('(el)=>getComputedStyle(el).backgroundColor')
        assert middle_color not in (light_color,'rgb(254, 200, 9)'), 'Theme colors did not interpolate'
        page.wait_for_timeout(250)
        assert card.evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(254, 200, 9)'
        assert card.evaluate('(el)=>getComputedStyle(el,"::after").backgroundColor')=='rgb(2, 48, 92)'
        assert before_box==logo.bounding_box(), 'Logo jumps when changing theme'
        assert page.locator('.ml-brand-ink').evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(249, 246, 240)'
        page.emulate_media(reduced_motion='reduce')
        page.get_by_role('button',name='Switch to light mode',exact=True).click()
        assert card.evaluate('(el)=>getComputedStyle(el).transitionDuration')=='0s'
        assert card.evaluate('(el)=>getComputedStyle(el).backgroundColor')==light_color
        assert page.locator('.ml-brand-ink').evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(2, 48, 92)'

        for width in (320,390,1440):
            page.set_viewport_size(dict(width=width,height=844 if width<700 else 1000))
            for theme in ('light','dark'):
                prefix=f'{width}-{theme}'
                load('guest',theme)
                capture(prefix+'-welcome')
                page.get_by_role('button',name='Find local deals').click()
                page.get_by_placeholder('Your name').wait_for()
                capture(prefix+'-signin')
                page.get_by_placeholder('Your name').fill('Jordan Smith')
                page.get_by_placeholder('uniqname').fill('jordan')
                page.get_by_role('button',name='Send verification code',exact=True).click()
                page.get_by_label('Verification code',exact=True).wait_for()
                capture(prefix+'-verification')
                page.get_by_label('Verification code',exact=True).fill('123456')
                page.get_by_role('button',name='Verify and continue',exact=True).click()
                page.get_by_text('That code is invalid or expired.',exact=True).wait_for()
                capture(prefix+'-verification-error')
                load('student',theme)
                page.get_by_text(item['title'],exact=True).wait_for()
                page.get_by_role('button',name='Edit my tastes',exact=True).click()
                page.get_by_role('button',name='Save my tastes',exact=True).wait_for()
                capture(prefix+'-tastes')
                page.get_by_role('button',name='Save my tastes',exact=True).click()
                page.get_by_text(item['title'],exact=True).wait_for()
                toolbar=page.locator('.ml-feed-toolbar')
                filter_button=toolbar.locator('button[aria-expanded]')
                refresh=toolbar.get_by_role('button',name='Refresh offers',exact=True)
                first,second=filter_button.bounding_box(),refresh.bounding_box()
                assert abs(first['y']-second['y'])<2 and first['x']+first['width']<=second['x'], 'Toolbar wraps'
                masthead=page.get_by_test_id('app-masthead')
                assert masthead.get_by_role('button',name='Log out',exact=True).count()==1
                capture(prefix+'-feed')
                filter_button.click()
                page.get_by_label('Maximum price',exact=True).focus()
                page.keyboard.press('Home')
                for _ in range(8): page.keyboard.press('ArrowRight')
                page.get_by_label('Vegan',exact=True).check()
                capture(prefix+'-filters')
                page.get_by_role('button',name='Show deals',exact=True).click()
                capture(prefix+'-filtered-feed')
                page.get_by_role('button',name='View Arbor Leaf Kitchen business profile',exact=True).click()
                page.get_by_role('heading',name='Arbor Leaf Kitchen',exact=True).wait_for()
                capture(prefix+'-business')
                page.get_by_role('button',name='Harvest bowl for $8',exact=False).click()
                page.get_by_test_id('claim-qr').wait_for()
                assert page.get_by_test_id('claim-qr').evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(255, 255, 255)'
                capture(prefix+'-claim')
                load('merchant',theme)
                page.get_by_text('Business insights',exact=True).wait_for()
                capture(prefix+'-insights')
                page.get_by_role('button',name='Manage',exact=True).click()
                page.get_by_role('button',name='View business page',exact=True).wait_for()
                assert page.get_by_placeholder('Restaurant name').count()==0
                capture(prefix+'-manage')
                page.get_by_role('button',name='Edit business details',exact=True).click()
                page.get_by_placeholder('Restaurant name').wait_for()
                capture(prefix+'-business-edit')
                page.get_by_role('button',name='Cancel profile changes',exact=True).click()
                page.get_by_role('button',name='New offer',exact=True).click()
                page.get_by_placeholder('Lunch bowl for $7').wait_for()
                capture(prefix+'-offer-editor')
                page.locator('summary').filter(has_text='More details (optional)').click()
                page.get_by_label('Vegan',exact=True).check()
                capture(prefix+'-offer-options')
                page.get_by_role('button',name='Cancel',exact=True).click()
                page.get_by_role('button',name='View business page',exact=True).click()
                page.get_by_role('heading',name='Arbor Leaf Kitchen',exact=True).wait_for()
                capture(prefix+'-owner-preview')
                page.get_by_role('button',name='Account',exact=True).click()
                page.get_by_test_id('theme-toggle').wait_for()
                capture(prefix+'-account')
                page.get_by_role('button',name='Redeem',exact=True).click()
                page.get_by_role('button',name='Start camera scan',exact=True).wait_for()
                capture(prefix+'-scanner')
                load('business',theme)
                business_trigger=page.get_by_role('button',name='Business profile',exact=True)
                if business_trigger.count(): business_trigger.click()
                page.get_by_placeholder('Business name').wait_for()
                capture(prefix+'-business-onboarding')
                assert not page.locator('details').evaluate('(el)=>el.open')
                page.locator('summary').filter(has_text='Photo and menu (optional)').focus()
                page.keyboard.press('Enter')
                assert page.get_by_placeholder('https://your-business.com/photo.jpg').is_visible()
                capture(prefix+'-business-options')
                load('student',theme,'empty-feed')
                page.get_by_text('Offers are on their way',exact=True).wait_for()
                capture(prefix+'-empty-feed')
                for state in ('profile-empty','profile-missing'):
                    load('student',theme,state)
                    page.get_by_role('button',name='View Arbor Leaf Kitchen business profile',exact=True).click()
                    page.get_by_text('No offers right now' if state=='profile-empty' else 'Business unavailable',exact=True).wait_for()
                    capture(prefix+'-'+state)
                load('merchant',theme,'insights-empty')
                page.get_by_text('Your next redemption starts the story.',exact=True).wait_for()
                capture(prefix+'-insights-empty')
                load('student',theme,'account-error')
                page.get_by_role('button',name='Account',exact=True).click()
                page.get_by_role('button',name='Retry account',exact=True).wait_for()
                capture(prefix+'-account-error')
        assert not errors, errors
        (output/'report.json').write_text(json.dumps(dict(url=url,screenshots=shots,page_errors=errors,rpc_count=len(requests)),indent=2))
        browser.close()
    print(json.dumps(dict(screenshots=len(shots),page_errors=errors,rpc_count=len(requests))))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://localhost:8155')
    parser.add_argument('--output',type=Path,default=Path('.jac/theme-profile-evidence'))
    args=parser.parse_args()
    run(args.url,args.output)
