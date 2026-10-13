import test from 'node:test';
import assert from 'node:assert/strict';
import {app,held,home,rpc,until} from './harness.mjs';

test('suspended merchant claim remains reachable with its saved QR and explicit support guidance',async()=>{
 const support='Redemption is paused while this business is suspended. Contact M-Local support for help.';
 const saved=held({state:'suspended',claim_support_message:support});
 const ui=await app({verified:true,item:saved,intercept(name){
  if(name==='home_feed')return rpc(home([saved],{signed_in:true}));
 }});
 try{
  await until(()=>ui.find('Show QR for Saved bowl'));
  ui.click('Show QR for Saved bowl');
  await until(()=>ui.document.querySelector('[data-testid="claim-qr"]'));
  assert.ok(ui.text().includes(support),'saved claim must explain the redemption pause and support path');
  assert.ok(ui.text().includes('Saved meal terms'));
  assert.ok(ui.text().includes('Saved ID condition'));
  assert.equal(ui.calls.filter(call=>call.name==='claim_offer').length,0,'reopening must preserve the original claim');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
