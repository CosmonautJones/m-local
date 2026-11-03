import test from 'node:test';
import assert from 'node:assert/strict';
import {app, rpc, until} from './harness.mjs';

const token = 'A'.repeat(118);
const details = {ok: true, message: '', approved: false, name: 'Fixture Cafe', address: '1 Test St',
 email: 'owner@fixture.test', website: 'https://cafe.fixture.test', cuisine: 'Cafe', description: 'Soup and bread'};

test('an emailed review link shows the submission and approves it on a deliberate tap', async()=>{
 const ui = await app({role: 'guest', item: {title: 'Fixture Cafe'},
  configureWindow(w){ w.history.replaceState(null, '', '/#approve=' + token); },
  intercept(name, body){
   if(name === 'review_link_details') return rpc(details);
   if(name === 'approve_from_review_link') return rpc({...details, approved: true, message: 'Approved. The owner can now publish offers.'});
  }});
 try{
  await until(()=>ui.text().includes('Review a business') && ui.text().includes('1 Test St'));
  assert.equal(ui.window.location.hash, '', 'the token leaves the address bar');
  assert.equal(ui.calls.filter(c=>c.name === 'approve_from_review_link').length, 0, 'opening the link never approves');
  assert.deepEqual(ui.calls.find(c=>c.name === 'review_link_details').body, {token});
  ui.click('Approve this business');
  await until(()=>ui.text().includes('Approved. The owner can now publish offers.'));
  assert.equal(ui.calls.find(c=>c.name === 'approve_from_review_link').body.token, token);
  assert.equal(ui.find('Approve this business'), undefined);
  ui.click('Open M-Local');
  await until(()=>!ui.text().includes('Review a business'));
  assert.deepEqual(ui.errors, []);
 }finally{ui.close();}
});

test('a refused link explains itself and offers no approve button', async()=>{
 const ui = await app({role: 'guest', item: {title: 'Review a business'},
  configureWindow(w){ w.history.replaceState(null, '', '/#approve=' + token); },
  intercept(name){ if(name === 'review_link_details') return rpc({ok: false, message: 'This review link is not valid.'}); }});
 try{
  await until(()=>ui.text().includes('This review link is not valid.'));
  assert.equal(ui.find('Approve this business'), undefined);
 }finally{ui.close();}
});
