"""Actual app one-shot transaction fault checks for stock_topology_app_http."""
from datetime import datetime, timedelta
import json
import os
import secrets
import urllib.error
import urllib.request
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
        raw = error.read(65537)
        try:
            envelope = json.loads(raw)
        except (ValueError, UnicodeError):
            envelope = {'ok': False, 'non_json_error': True,
                        'error_content_type': error.headers.get('Content-Type', '').split(';', 1)[0].strip(),
                        'error_text': raw.decode('utf-8', errors='replace') if len(raw) <= 65536 else None}
        return error.code, envelope
    except (OSError, urllib.error.URLError):
        return 0, {'ok': False, 'transport_lost': True}


def result(envelope):
    data = envelope.get('data')
    return data.get('result') if isinstance(data, dict) else None


def ingress_events(workspace):
    events = []
    for log in sorted(workspace.glob('gateway-*.log'), key=lambda p: int(p.stem.split('-')[-1])):
        for line in log.read_text(errors='replace').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get('kind') == 'mlocal_ingress_failure':
                events.append(event)
    return events


def lost_mutation_response(status, envelope, events, operation):
    """Match fixed plaintext failure plus a fresh, redacted gateway classification."""
    if envelope.get('ok') is not False:
        return False
    if status == 0:
        return envelope.get('transport_lost') is True
    code = {502: 'UPSTREAM_FAILURE', 503: 'SERIALIZATION_CLOSED'}.get(status)
    message = 'M-Local is starting or unavailable. Ask the host to check the launcher, then reload.'
    return (code is not None and envelope.get('non_json_error') is True and
            envelope.get('error_content_type') == 'text/plain' and envelope.get('error_text') == message and
            any(event.get('code') == code and event.get('route') == operation and
                event.get('status') == status for event in events))


def verify_actual_faults(workspace, merchant, student, public, rows, durable,
                         restart_both, check, receipt):
    recorded = receipt.setdefault('actual_app_faults', [])
    published, redeemed_claims = [], []
    modes = (('rollback', '57P01'), ('rollback', '40001'), ('rollback', '08006'),
             ('transport_loss_before_commit', '08006'),
             ('accepted_ack_loss', '08006'))
    all_modes = (*modes, ('process_death_before_commit', ''), ('process_death_after_commit', ''))

    def count(arch, field, value):
        return int(rows("SELECT COUNT(*) FROM anchors WHERE arch_type=:arch AND props->'archetype'->>:field=:value",
                        dict(arch=arch, field=field, value=value))[0][0])

    def arm(arch, field, value, mode, sqlstate, target_id=None):
        control = workspace / 'fault-arm.json'
        fd = os.open(control, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(dict(arch_type=arch, field=field, value=value, mode=mode,
                           sqlstate=sqlstate, target_id=target_id), stream)
        return control

    def observed_fault(mode, row):
        event = json.loads((workspace / 'fault-events.json').read_text())[-1]
        check(event['mode'] == mode, 'actual mutation records the consumed fault mode')
        if mode == 'transport_loss_before_commit':
            check(event.get('observed_exception_type') == 'PgWireError' and
                  event.get('observed_sqlstate') == '08006',
                  'physical TCP interruption observes stock PgWireError08006')
            row['observed_sqlstate'] = event['observed_sqlstate']

    def offer(title):
        now = datetime.now(ZoneInfo('America/Detroit'))
        return dict(offer_id='', create_key=secrets.token_hex(16), title=title,
            description='Fictional actual transaction fault fixture', price='3.00', regular_price='5.00',
            start_local=(now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M'),
            end_local=(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'), quantity='1',
            eligibility='Fixture student ID', terms='Synthetic test only', dietary='', menu_item='')

    for mode, sqlstate in all_modes:
        title = 'Stock actual publish fault ' + secrets.token_hex(8)
        post = offer(title)
        event_offset = len(ingress_events(workspace))
        control = arm('Offer', 'title', title, mode, sqlstate)
        status, envelope = rpc(merchant, 'save_offer', **post)
        check(not control.exists(), 'actual publication flush consumes its one-shot fault')
        committed = count('Offer', 'title', title)
        row = dict(operation='save_offer', mode=mode, expected_sqlstate=sqlstate, http_status=status,
                   response_ok=envelope.get('ok'), durable_offers_after_response=committed)
        recorded.append(row)
        observed_fault(mode, row)
        row['gateway_failure_events'] = ingress_events(workspace)[event_offset:]
        if mode.startswith('process_death'):
            check(lost_mutation_response(status, envelope, row['gateway_failure_events'], 'save_offer'), 'actual native process death loses the publication response')
            check(committed == (1 if mode == 'process_death_after_commit' else 0),
                  'independent database observes correct publication before/after process death')
            closed_status, closed_envelope = rpc(public, 'home_feed')
            check(closed_status == 503 and lost_mutation_response(closed_status, closed_envelope,
                  ingress_events(workspace)[event_offset:], 'home_feed'),
                  'uncertain native process death closes the serialized ingress')
            row['gateway_failure_events'] = ingress_events(workspace)[event_offset:]
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
        row['offer_id'] = retry['code']
        published.append((post, retry['code']))

    restart_both()
    for post, offer_id in published:
        check(merchant.call('save_offer', **post)['code'] == offer_id and
              count('Offer', 'title', post['title']) == 1 and
              public.call('get_offer', offer_id=offer_id)['title'] == post['title'],
              'each fault-reconciled publication preserves its original durable ID after restart')

    for mode, sqlstate in all_modes:
        title = 'Stock actual claim fault ' + secrets.token_hex(8)
        made = merchant.call('save_offer', **offer(title))
        check(made.get('ok'), 'created a distinct actual claim fault fixture offer')
        offer_id = made['code']
        event_offset = len(ingress_events(workspace))
        control = arm('Redemption', 'offer_title_snapshot', title, mode, sqlstate)
        status, envelope = rpc(student, 'claim_offer', offer_id=offer_id)
        check(not control.exists(), 'actual claim flush consumes its one-shot fault')
        committed = count('Redemption', 'offer_title_snapshot', title)
        row = dict(operation='claim_offer', mode=mode, expected_sqlstate=sqlstate, http_status=status,
                   response_ok=envelope.get('ok'), durable_claims_after_response=committed)
        recorded.append(row)
        observed_fault(mode, row)
        row['gateway_failure_events'] = ingress_events(workspace)[event_offset:]
        if mode.startswith('process_death'):
            check(lost_mutation_response(status, envelope, row['gateway_failure_events'], 'claim_offer'), 'actual native process death loses the claim response')
            check(committed == (1 if mode == 'process_death_after_commit' else 0),
                  'independent database observes correct held claim before/after process death')
            closed_status, closed_envelope = rpc(public, 'home_feed')
            check(closed_status == 503 and lost_mutation_response(closed_status, closed_envelope,
                  ingress_events(workspace)[event_offset:], 'home_feed'),
                  'uncertain claim process death closes the serialized ingress')
            row['gateway_failure_events'] = ingress_events(workspace)[event_offset:]
            restart_both()
        else:
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
        if committed:
            check(retry['claim_id'] == view['my_claim_id'] and retry['qr_payload'] == view['my_qr_payload'],
                  'lost-response or committed claim retry preserves the already durable claim and QR')
        stable = student.call('claim_offer', offer_id=offer_id)
        check(stable.get('ok') and stable['claim_id'] == retry['claim_id'] and stable['qr_payload'] == retry['qr_payload'],
              'reconciled actual claim keeps its original claim and QR')
        row['offer_id'], row['claim_id'] = offer_id, retry['claim_id']
        restart_both()
        restarted = student.call('get_offer', offer_id=offer_id)
        stored = durable(retry['claim_id']).props['archetype']
        check(restarted['my_status'] == 'claimed' and restarted['my_claim_id'] == retry['claim_id'] and
              restarted['my_qr_payload'] == retry['qr_payload'] and restarted['remaining'] == 0 and
              stored['status'] == 'claimed' and stored['qr_payload'] == retry['qr_payload'] and
              stored['offer_title_snapshot'] == title,
              'each fault-reconciled held claim and QR survive backend plus gateway restart')
        check(student.call('cancel_claim', offer_id=offer_id)['ok'],
              'actual fault fixture cleanup releases the legitimate held claim')
        check(public.call('get_offer', offer_id=offer_id)['remaining'] == 1,
              'cancelled actual fault fixture restores one stock unit')
        row['durable_claims_after_retry'] = count('Redemption', 'offer_title_snapshot', title)

    for mode, sqlstate in all_modes:
        title = 'Stock actual redemption fault ' + secrets.token_hex(8)
        made = merchant.call('save_offer', **offer(title))
        check(made.get('ok'), 'created a distinct actual redemption fault fixture offer')
        offer_id = made['code']
        held = student.call('claim_offer', offer_id=offer_id)
        check(held.get('ok'), 'created one held claim for the actual redemption fault')
        claim_id = held['claim_id']
        before = durable(claim_id).props['archetype']
        check(before['status'] == 'claimed', 'independent database observes original held redemption status')
        event_offset = len(ingress_events(workspace))
        control = arm('Redemption', 'status', 'redeemed', mode, sqlstate, target_id=claim_id)
        status, envelope = rpc(merchant, 'redeem_claim', qr_payload=held['qr_payload'])
        check(not control.exists(), 'actual redeemed-status flush consumes its one-shot targeted fault')
        stored = durable(claim_id).props['archetype']
        row = dict(operation='redeem_claim', mode=mode, expected_sqlstate=sqlstate,
                   http_status=status, response_ok=envelope.get('ok'), offer_id=offer_id,
                   claim_id=claim_id, durable_status_after_response=stored['status'])
        recorded.append(row)
        observed_fault(mode, row)
        row['gateway_failure_events'] = ingress_events(workspace)[event_offset:]
        if mode.startswith('process_death'):
            check(lost_mutation_response(status, envelope, row['gateway_failure_events'], 'redeem_claim'), 'actual native process death loses the redemption response')
            check(stored['status'] == ('redeemed' if mode == 'process_death_after_commit' else 'claimed'),
                  'independent database observes correct redemption before/after process death')
            closed_status, closed_envelope = rpc(public, 'home_feed')
            check(closed_status == 503 and lost_mutation_response(closed_status, closed_envelope,
                  ingress_events(workspace)[event_offset:], 'home_feed'),
                  'uncertain redemption process death closes the serialized ingress')
            row['gateway_failure_events'] = ingress_events(workspace)[event_offset:]
            restart_both()
        else:
            check(status in (200, 409, 500), 'actual redemption fault returns a complete bounded native response')
            value = result(envelope)
            succeeded = status == 200 and envelope.get('ok') and isinstance(value, dict) and value.get('ok')
            if mode == 'accepted_ack_loss' or succeeded:
                check(stored['status'] == 'redeemed' and stored['redeemed_ts'] > 0,
                      'accepted or successful actual redemption has one durable redeemed state')
            else:
                check(stored['status'] == 'claimed' and stored['redeemed_ts'] == 0,
                      'failed actual redemption preserves the original legitimate held claim')
        preview = merchant.call('resolve_claim', qr_payload=held['qr_payload'])
        view = student.call('get_offer', offer_id=offer_id)
        check(preview['claim_id'] == claim_id and preview['status'] == stored['status'] and
              view['my_claim_id'] == claim_id and view['my_status'] == stored['status'],
              'first actual redemption readback agrees with independent committed state')
        retry = merchant.call('redeem_claim', qr_payload=held['qr_payload'])
        check(bool(retry.get('ok')) == (stored['status'] == 'claimed'),
              'actual redemption retry consumes only an uncommitted prior attempt')
        final = durable(claim_id).props['archetype']
        check(final['status'] == 'redeemed' and final['redeemed_ts'] > 0 and
              final['qr_payload'] == held['qr_payload'] and final['offer_title_snapshot'] == title,
              'actual redemption reconciliation preserves one original claim QR and snapshot')
        check(not merchant.call('redeem_claim', qr_payload=held['qr_payload'])['ok'],
              'reconciled actual redemption stays single use')
        row['durable_status_after_retry'] = final['status']
        redeemed_claims.append((offer_id, held, title))

    restart_both()
    for offer_id, held, title in redeemed_claims:
        persisted = durable(held['claim_id']).props['archetype']
        view = student.call('get_offer', offer_id=offer_id)
        check(persisted['status'] == 'redeemed' and persisted['offer_title_snapshot'] == title and
              persisted['qr_payload'] == held['qr_payload'] and view['my_status'] == 'redeemed' and
              view['my_claim_id'] == held['claim_id'] and
              not merchant.call('redeem_claim', qr_payload=held['qr_payload'])['ok'],
              'each fault-reconciled redemption stays durable and single use after restart')
    receipt['actual_app_fault_restart_readbacks'] = dict(publications=len(published), held_claims=len(all_modes),
                                                       redemptions=len(redeemed_claims))
    receipt['actual_app_fault_events'] = json.loads((workspace / 'fault-events.json').read_text())
