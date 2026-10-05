import test from 'node:test';
import assert from 'node:assert/strict';
import {app,until,rpc} from './harness.mjs';

const storageKey='mlocal_offer_draft_fixture-merchant';
async function openNew(ui){ui.click('Offers');await until(()=>ui.find('New offer'));ui.click('New offer');await until(()=>ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));}
function fill(ui){ui.fill('Lunch bowl for $7','Recoverable fixture bowl');ui.fill('7.00','7.00');ui.fill('One per student. Dine-in only.','One per student.');}

test('refresh recovers a business draft and its committed but unacknowledged publish key',async()=>{
 const first=await app({role:'merchant',intercept(name){if(name==='save_offer')throw new Error('Response lost after commit');}});
 let saved,key;
 try{await openNew(first);fill(first);first.click('Publish offer');await until(()=>first.text().includes('Could not save the offer.'));
  saved=first.window.localStorage.getItem(storageKey);key=first.calls.find(c=>c.name==='save_offer').body.create_key;
  assert.equal(JSON.parse(saved).create_key,key);
 }finally{first.close();}
 const restored=await app({role:'merchant',configureWindow(w){w.localStorage.setItem(storageKey,saved);},intercept(name,body){
  if(name==='save_offer'){assert.equal(body.create_key,key);return rpc({ok:true,message:'Offer already published.',code:'original-offer'});}
 }});
 try{await openNew(restored);await until(()=>restored.text().includes('Recovered your draft'));
  assert.equal(restored.document.querySelector('[placeholder="Lunch bowl for $7"]').value,'Recoverable fixture bowl');
  restored.click('Publish offer');await until(()=>restored.text().includes('Offer already published.'));
  assert.equal(restored.window.localStorage.getItem(storageKey),null);assert.deepEqual(restored.errors,[]);
 }finally{restored.close();}
});

test('Cancel and sign-out remove local offer drafts',async()=>{
 const ui=await app({role:'merchant'});
 try{await openNew(ui);fill(ui);assert.ok(ui.window.localStorage.getItem(storageKey));ui.click('Cancel');
  await until(()=>ui.find('New offer'));assert.equal(ui.window.localStorage.getItem(storageKey),null);
  ui.click('New offer');await until(()=>ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));fill(ui);
  ui.click('Log out');await until(()=>ui.find('Find local deals'));assert.equal(ui.window.localStorage.getItem(storageKey),null);assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('a different business account cannot recover another account draft',async()=>{
 const ui=await app({role:'merchant',configureWindow(w){w.localStorage.setItem('mlocal_offer_draft_other-owner',JSON.stringify({draft:{title:'Other owner private draft'},create_key:'other-owner-private-key'}));}});
 try{await openNew(ui);assert.equal(ui.document.querySelector('[placeholder="Lunch bowl for $7"]').value,'');
  assert.equal(ui.text().includes('Other owner private draft'),false);assert.equal(ui.text().includes('Recovered your draft'),false);assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('storage failure keeps input and prevents an unrecoverable publish',async()=>{
 const ui=await app({role:'merchant',configureWindow(w){const set=w.Storage.prototype.setItem;w.Storage.prototype.setItem=function(key,value){if(key.startsWith('mlocal_offer_draft_'))throw new Error('Storage blocked');return set.call(this,key,value);};}});
 try{await openNew(ui);fill(ui);ui.click('Publish offer');await until(()=>ui.text().includes('Could not keep this draft on your device.'));
  assert.equal(ui.calls.some(c=>c.name==='save_offer'),false);assert.equal(ui.document.querySelector('[placeholder="Lunch bowl for $7"]').value,'Recoverable fixture bowl');
  assert.equal(ui.find('Publish offer').disabled,false);assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
