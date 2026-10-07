"""Actual app one-shot transaction fault checks for stock_topology_app_http."""
from datetime import datetime, timedelta
import json
import os
import secrets
import urllib.error
import urllib.request
from uuid import UUID
from zoneinfo import ZoneInfo


def rpc(api, function, **params):
    headers = {'Content-Type': 'application/json'}
    if api.token:
        headers['Authorization'] = 'Bearer ' + api.token
    request = urllib.request.Request(api.origin + '/function/' + function,
        json.dumps(params).encode(), headers, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            envelope = json.load(error)
        except (ValueError, OSError):
            envelope = {'ok': False, 'non_json_error': True}
        return error.code, envelope
    except (OSError, urllib.error.URLError):
        return 0, {'ok': False, 'transport_lost': True}


def result(envelope):
    data = envelope.get('data')
    return data.get('result') if isinstance(data, dict) else None


def verify_actual_faults(workspace, merchant, student, public, rows, durable,
                         restart_both, check, receipt):
    recorded = receipt.setdefault('actual_app_faults', [])
    modes = (('rollback', '57P01'), ('rollback', '40001'), ('rollback', '08006'),
             ('accepted_ack_loss', '08006'))

    def count(arch, field, value):
        return int(rows("SELECT COUNT(*) FROM anchors WHERE arch_type=:arch AND props->'archetype'->>:field=:value",
                        dict(arch=arch, field=field, value=value))[0][0])

    def arm(arch, field, value, mode, sqlstate):
        control = workspace / 'fault-arm.json'
        fd = os.open(control, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(dict(arch_type=arch, field=field, value=value, mode=mode, sqlstate=sqlstate), stream)
        return control

    def offer(title):
        now = datetime.now(ZoneInfo('America/Detroit'))
        return dict(offer_id='', create_key=secrets.token_hex(16), title=title,
            description='Fictional actual transaction fault fixture', price='3.00', regular_price='5.00',
            start_local=(now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M'),
            end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='1',
            eligibility='Fixture student ID', terms='Synthetic test only', dietary='', menu_item='')

    for mode, sqlstate in (*modes, ('process_death_before_commit', ''), ('process_death_after_commit', '')):
        title = 'Stock actual publish fault ' + secrets.token_hex(8)
        post = offer(title)
        control = arm('Offer', 'title', title, mode, sqlstate)
        status, envelope = rpc(merchant, 'save_offer', **post)
        check(not control.exists(), 'actual publication flush consumes its one-shot fault')
        committed = count('Offer', 'title', title)
        row = dict(operation='save_offer', mode=mode, sqlstate=sqlstate, http_status=status,
                   response_ok=envelope.get('ok'), durable_offers_after_response=committed)
        recorded.append(row)
        if mode.startswith('process_death'):
            check(status in (0, 503), 'actual native process death loses the publication response')
            check(committed == (1 if mode == 'process_death_after_commit' else 0),
                  'independent database observes correct publication before/after process death')
            closed_status, _ = rpc(public, 'home_feed')
            check(closed_status == 503, 'uncertain native process death closes the serialized ingress')
            restart_both()
        else:
            check(status in (200, 409, 500), 'actual publication fault returns a complete bounded native response')
            value = result(envelope)
            if status == 200 and envelope.get('ok') and isinstance(value, dict) and value.get('ok'):
                check(committed == 1 and durable(value['code']).props['archetype']['title'] == title,
                      'successful actual publication response names exactly one durable offer')
            else:
                check(committed == 0, 'failed actual publication does not secretly persist its offer')
            visible = [entry for entry in public.call('list_offers') if entry['title'] == title]
            check(len(visible) == committed,
                  'first read after complete publication fault agrees with independent durable state')
        retry = merchant.call('save_offer', **post)
        check(retry.get('ok') and count('Offer', 'title', title) == 1,
              'actual publication key retry reconciles to one durable offer')
        stable = merchant.call('save_offer', **post)
        check(stable.get('ok') and stable['code'] == retry['code'],
              'reconciled actual publication keeps its original offer ID')
        row['durable_offers_after_retry'] = count('Offer', 'title', title)

    for mode, sqlstate in modes:
        title = 'Stock actual claim fault ' + secrets.token_hex(8)
        made = merchant.call('save_offer', **offer(title))
        check(made.get('ok'), 'created a distinct actual claim fault fixture offer')
        offer_id = made['code']
        control = arm('Redemption', 'offer_title_snapshot', title, mode, sqlstate)
        status, envelope = rpc(student, 'claim_offer', offer_id=offer_id)
        check(not control.exists(), 'actual claim flush consumes its one-shot fault')
        committed = count('Redemption', 'offer_title_snapshot', title)
        row = dict(operation='claim_offer', mode=mode, sqlstate=sqlstate, http_status=status,
                   response_ok=envelope.get('ok'), durable_claims_after_response=committed)
        recorded.append(row)
        check(status in (200, 409, 500), 'actual claim fault returns a complete bounded native response')
        value = result(envelope)
        succeeded = status == 200 and envelope.get('ok') and isinstance(value, dict) and value.get('ok')
        if succeeded:
            persisted = durable(value['claim_id']).props['archetype']
            check(committed == 1 and persisted['status'] == 'claimed' and persisted['offer_title_snapshot'] == title,
                  'successful actual claim response names one durable held claim')
        else:
            check(committed == 0, 'failed actual claim leaves no durable hidden hold')
        view = student.call('get_offer', offer_id=offer_id)
        check(view['remaining'] == 1 - committed and bool(view['my_claim_id']) == bool(committed),
              'first read after complete claim fault reports committed stock and private claim only')
        retry = student.call('claim_offer', offer_id=offer_id)
        check(retry.get('ok') and count('Redemption', 'offer_title_snapshot', title) == 1,
              'actual claim retry reconciles to one durable held claim')
        stable = student.call('claim_offer', offer_id=offer_id)
        check(stable.get('ok') and stable['claim_id'] == retry['claim_id'] and stable['qr_payload'] == retry['qr_payload'],
              'reconciled actual claim keeps its original claim and QR')
        check(student.call('cancel_claim', offer_id=offer_id)['ok'],
              'actual fault fixture cleanup releases the legitimate held claim')
        check(public.call('get_offer', offer_id=offer_id)['remaining'] == 1,
              'cancelled actual fault fixture restores one stock unit')
        row['durable_claims_after_retry'] = count('Redemption', 'offer_title_snapshot', title)
    receipt['actual_app_fault_events'] = json.loads((workspace / 'fault-events.json').read_text())
