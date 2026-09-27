import test from 'node:test';
import assert from 'node:assert/strict';
import {app,offer,held,until,rpc} from './harness.mjs';

test('compiled student detail leads with saved claim terms after an offer edit',async()=>{
 const ui=await app({item:held()});
 try{assert.equal(ui.text().includes('Current bowl'),false);assert.equal(ui.text().includes('$9.00'),false);ui.click('Saved bowl');await until(()=>ui.text().includes('Your saved claim'),'claim detail');
 assert.equal(ui.text().includes('Current bowl'),false,'edited title must not lead a saved claim');
 assert.equal(ui.text().includes('$9.00'),false,'edited price must not compete with held price');
 assert.ok(ui.text().includes('Saved bowl')&&ui.text().includes('$3.00'));assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('student navigation hides merchant management and redemption controls',async()=>{
 const ui=await app();try{assert.equal(ui.text().includes('ManageMerchant'),false);assert.equal(ui.text().includes('RedeemMerchant'),false);}finally{ui.close();}
});

test('legacy entrance wording is visibly unverified',async()=>{
 const ui=await app({item:offer({entrance_note:'Fictional merchant note',note_date:'2026-01-01'})});
 try{ui.click('Current bowl');await until(()=>ui.text().includes('Fictional merchant note'));assert.ok(ui.text().includes('Unverified restaurant note'));assert.equal(ui.text().includes('Getting in'),false);}finally{ui.close();}
});

test('claim failure clears busy state and allows one explicit retry',async()=>{
 let attempts=0;
 const ui=await app({intercept(name){if(name==='claim_offer'&&attempts++===0)throw new Error('Synthetic offline');}});
 try{ui.click('Current bowl');await until(()=>ui.text().includes('Claim this offer'));ui.click('Claim this offer');await until(()=>ui.text().includes('Could not finish updating this claim'));assert.equal(ui.text().includes('Updating...'),false);ui.click('Claim this offer');await until(()=>ui.text().includes('Fixture claim accepted'));assert.equal(attempts,2);assert.deepEqual(ui.errors,[]);}finally{ui.close();}
});

test('offer and profile save failures keep values and enable retry',async()=>{
 const attempts={save_offer:0,update_profile:0};
 const ui=await app({role:'merchant',intercept(name){if(name in attempts&&attempts[name]++===0)throw new Error('Synthetic offline');}});
 try{ui.click('Manage');await until(()=>ui.text().includes('Restaurant profile'));ui.fill('Restaurant name','Edited fixture name');ui.click('Save profile');await until(()=>ui.text().includes('Profile could not be saved'));assert.equal(ui.document.querySelector('[placeholder="Restaurant name"]').value,'Edited fixture name');assert.equal(ui.text().includes('Saving...'),false);
 ui.click('Save profile');await until(()=>attempts.update_profile===2&&!ui.text().includes('Profile could not be saved')&&!ui.text().includes('Saving...'),'profile retry');
 ui.click('New offer');await until(()=>ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));ui.fill('Lunch bowl for $7','Unsaved fixture bowl');ui.click('Save offer');await until(()=>ui.text().includes('Could not save the offer.'));assert.equal(ui.document.querySelector('[placeholder="Lunch bowl for $7"]').value,'Unsaved fixture bowl');assert.equal(ui.text().includes('Saving...'),false);ui.click('Save offer');await until(()=>ui.text().includes('Fixture offer saved'),'offer retry');assert.equal(attempts.save_offer,2);assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('confirmed offer save survives a failed portal refresh and refresh can be retried',async()=>{
 let saved=false,portalReads=0;
 const ui=await app({role:'merchant',intercept(name){
  if(name==='save_offer')saved=true;
  if(name==='merchant_portal'){
   portalReads++;
   if(saved&&portalReads===2)throw new Error('Synthetic refresh failure after confirmed save');
  }
 }});
 try{
  ui.click('Manage');await until(()=>ui.text().includes('Restaurant profile'));
  ui.click('New offer');await until(()=>ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));
  ui.fill('Lunch bowl for $7','Confirmed fixture bowl');ui.click('Save offer');
  await until(()=>portalReads===2&&!ui.text().includes('Saving...'),'save completed and portal refresh failed');
  assert.ok(ui.text().includes('Fixture offer saved'),'retain the server-confirmed save outcome when only the subsequent refresh fails');
  assert.ok(ui.text().includes('restaurant list could not refresh'),'explain that the refresh failed after the successful save');
  assert.ok(ui.text().includes('Use Refresh restaurant'),'give an explicit retry action');
  assert.equal(ui.text().includes('Could not save the offer'),false,'do not invite a duplicate save after confirmed success');
  assert.equal(ui.document.querySelector('[placeholder="Lunch bowl for $7"]'),null,'close the editor after confirmed save');
  ui.click('Refresh restaurant');
  await until(()=>portalReads===3&&!ui.text().includes('Loading restaurant...')&&ui.text().includes('Restaurant profile'),'explicit refresh retry');
  assert.equal(ui.calls.filter(c=>c.name==='save_offer').length,1,'refresh retries must not resubmit the saved offer');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('the newest filter response wins even when an earlier request arrives last',async()=>{
 let release;const slow=new Promise(r=>{release=r;});
 const ui=await app({intercept:async(name,body)=>{if(name==='list_offers'&&body.max_price==='5'){await slow;return rpc([offer({title:'Old delayed result'})]);}if(name==='list_offers'&&body.max_price==='8')return rpc([offer({title:'Latest filter result'})]);}});
 try{ui.click('Under $5');await until(()=>ui.calls.some(c=>c.name==='list_offers'&&c.body.max_price==='5'));ui.click('Under $8');await until(()=>ui.text().includes('Latest filter result'));release();await new Promise(r=>setTimeout(r,80));assert.equal(ui.text().includes('Old delayed result'),false);assert.ok(ui.text().includes('Latest filter result'));assert.deepEqual(ui.errors,[]);}finally{release();ui.close();}
});

test('signout ignores a delayed private detail response',async()=>{
 let release;const slow=new Promise(r=>{release=r;});let first=true;
 const ui=await app({item:held(),intercept:async(name)=>{if(name==='get_offer'&&first){first=false;await slow;return rpc(held());}}});
 try{ui.click('Saved bowl');await until(()=>ui.calls.some(c=>c.name==='get_offer'));ui.click('Sign out');await until(()=>ui.find('Find local deals'));assert.ok(ui.find('List my business'));release();await new Promise(r=>setTimeout(r,80));assert.equal(ui.text().includes('Your saved claim'),false);assert.equal(ui.document.querySelector('svg[role="img"]')!==null,false);assert.deepEqual(ui.errors,[]);}finally{release();ui.close();}
});

test('actual scanner composition recovers from denied camera permission',async()=>{
 const ui=await app({role:'merchant'});
 try{Object.defineProperty(ui.window,'isSecureContext',{value:true,configurable:true});Object.defineProperty(ui.window.navigator,'mediaDevices',{value:{getUserMedia:async()=>{throw new ui.window.DOMException('Synthetic denial','NotAllowedError');}},configurable:true});ui.click('Redeem');await until(()=>ui.text().includes('Start camera scan'));ui.click('Start camera scan');await until(()=>ui.text().includes('Camera permission was denied'));assert.ok(ui.text().includes('Retry camera scan'));assert.equal(ui.calls.some(c=>c.name==='redeem_claim'),false);assert.deepEqual(ui.errors,[]);}finally{ui.close();}
});


test('signout removes an already visible claim QR and saved terms',async()=>{
 const ui=await app({item:held()});
 try{ui.click('Saved bowl');await until(()=>ui.document.querySelector('svg')&&ui.text().includes('Saved meal terms'),'visible claim QR');ui.click('Sign out');await until(()=>ui.find('Find local deals'));assert.ok(ui.find('List my business'));assert.equal(ui.document.querySelector('svg'),null);assert.equal(ui.text().includes('Saved meal terms'),false);assert.equal(ui.text().includes('Your QR is ready'),false);assert.deepEqual(ui.errors,[]);}finally{ui.close();}
});

test('a stale displayed hold hides its QR after the saved deadline',async()=>{
 const ui=await app({item:held({my_expires_ts:Date.now()/1000-5})});
 try{ui.click('Saved bowl');await until(()=>ui.text().includes('This hold has expired.'));assert.equal(ui.document.querySelector('svg'),null);assert.equal(ui.calls.some(c=>c.name==='redeem_claim'),false);assert.deepEqual(ui.errors,[]);}finally{ui.close();}
});
