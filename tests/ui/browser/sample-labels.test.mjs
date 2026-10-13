import test from 'node:test';
import assert from 'node:assert/strict';
import {app,offer,held,home,rpc,until} from './harness.mjs';

const note='Sample deal for a local simulation. Confirm real offers directly with the business.';
test('samples are consistently identified in discovery detail and saved QR views without false redemption claims',async()=>{
 for(const item of [offer({is_demo:true}),held({is_demo:true})]){
  const ui=await app({item,verified:true,intercept(name){if(name==='home_feed')return rpc(home([item],{show_samples:true,signed_in:true}));}});
  try{
   assert.ok(ui.find('Sample'));
   ui.click(item.my_title||item.title);await until(()=>ui.text().includes(note));
   assert.ok(ui.find('Sample'));
   if(item.my_claim_id){assert.ok(ui.text().includes('Sample claim for a local simulation.'));assert.ok(ui.document.querySelector('[data-testid="claim-qr"]'));}
   else assert.ok(ui.find('Claim this sample'));
   assert.equal(ui.text().includes('will not be accepted'),false);
   assert.equal(ui.text().includes('not redeemable'),false);
  }finally{ui.close();}
 }
});
