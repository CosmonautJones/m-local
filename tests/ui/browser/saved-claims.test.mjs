import test from 'node:test';
import assert from 'node:assert/strict';
import {app,held,home,offer,rpc,until,setMaximumPrice} from './harness.mjs';

test('student can reopen a held QR in one obvious tap after boot, filters, and refresh',async()=>{
 const saved=held();
 const ui=await app({verified:true,item:saved,intercept(name){if(name==='home_feed')return rpc(home([saved],{signed_in:true}));}});
 try{
  await until(()=>ui.find('My claims'));
  assert.ok(ui.find('Show QR for Saved bowl'));
  await setMaximumPrice(ui,5);
  ui.click('Refresh offers');
  await until(()=>ui.calls.filter(call=>call.name==='home_feed').length>=3);
  ui.click('Show QR for Saved bowl');
  await until(()=>ui.document.querySelector('[data-testid="claim-qr"]'));
  assert.ok(ui.text().includes('Saved meal terms'));
  assert.deepEqual(ui.calls.find(call=>call.name==='get_offer').body,{offer_id:saved.id,max_price:'5',window:'any',diets:''});
  ui.click('Log out');await until(()=>ui.find('Find local deals'));
  assert.equal(ui.find('My claims')===undefined,true);
  assert.equal(ui.document.querySelector('[data-testid="claim-qr"]'),null);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('expired and redeemed claims do not promise a usable QR shortcut',async()=>{
 const ui=await app({verified:true,item:offer(),intercept(name){if(name==='home_feed')return rpc(home([
  held({id:'expired',my_status:'expired',my_qr_payload:'',my_title:'Expired bowl'}),
  held({id:'redeemed',my_status:'redeemed',my_qr_payload:'',my_title:'Redeemed bowl'}),offer()
 ],{signed_in:true}));}});
 try{
  await until(()=>ui.find('Current bowl'));
  assert.equal(ui.find('My claims')===undefined,true);
  assert.equal(ui.find('Show QR for Expired bowl')===undefined,true);
  assert.equal(ui.find('Show QR for Redeemed bowl')===undefined,true);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
