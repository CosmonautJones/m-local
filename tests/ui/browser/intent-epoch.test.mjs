import test from 'node:test';
import assert from 'node:assert/strict';
import {app,offer,home,rpc,until,setMaximumPrice} from './harness.mjs';

const student={authenticated:true,role:'student',actor_id:'fixture-student',restaurant_id:'',display_name:'Fixture student',is_demo:false,email_verified:true};
const tick=()=>new Promise(resolve=>setTimeout(resolve,40));
function verificationHeldAtFeed() {
 let verified=false,entered=false,held=true,release;
 const pending=new Promise(resolve=>release=resolve);
 return {
  entered:()=>entered,release,
  async intercept(name,body){
   if(name==='request_email_code')return rpc({ok:true,challenge:'fixture',email:'fixture@umich.edu',retry_after:60,message:''});
   if(name==='verify_email_code'){verified=true;return rpc({ok:true,token:'fresh-token',message:''});}
   if(name==='current_session'&&verified)return rpc(student);
   if(name==='home_feed'&&verified){
    if(held){held=false;entered=true;await pending;}
    return rpc(home([offer(),offer({id:'other-offer',title:'Other bowl'})],{signed_in:true}));
   }
   if(name==='get_offer'&&body.offer_id==='other-offer')return rpc(offer({id:'other-offer',title:'Other bowl'}));
  }
 };
}
async function verifySelected(ui) {
 ui.click('Find local deals');await until(()=>ui.find('Current bowl'));
 ui.click('Current bowl');await until(()=>ui.find('Sign in to claim'));
 ui.click('Sign in to claim');await until(()=>ui.document.querySelector('[placeholder="uniqname"]'));
 ui.fill('uniqname','fixture');ui.click('Send verification code');
 await until(()=>ui.document.querySelector('[autocomplete="one-time-code"]'));
 ui.fill('123456','123456');ui.click('Verify and continue');
}

for(const destination of ['welcome','business'])test(`an old verification feed cannot revive offer intent after logout to ${destination}`,async()=>{
 const fixture=verificationHeldAtFeed();
 const ui=await app({role:'guest',audience:'',intercept:fixture.intercept});
 try{
  await verifySelected(ui);await until(fixture.entered);
  const reads=ui.calls.filter(call=>call.name==='get_offer').length;
  ui.click('Log out');await until(()=>ui.find('Find local deals'));
  if(destination==='business'){
   ui.click('List my business');await until(()=>ui.document.querySelector('[placeholder="Business Name"]'));
  }
  fixture.release();await tick();
  assert.equal(ui.window.localStorage.getItem('mlocal_public_offer_intent'),null);
  assert.equal(ui.calls.filter(call=>call.name==='get_offer').length,reads);
  assert.equal(ui.document.querySelector('[data-testid="claim-qr"]'),null);
  if(destination==='welcome')assert.ok(ui.find('Find local deals'));
  else assert.ok(ui.document.querySelector('[placeholder="Business Name"]'));
  assert.deepEqual(ui.errors,[]);
 }finally{fixture.release();ui.close();}
});

test('a restored-session feed cannot restore the student audience after logout',async()=>{
 let entered=false,release;
 const pending=new Promise(resolve=>release=resolve);
 const ui=await app({verified:true,configureWindow(window){window.localStorage.setItem('mlocal_public_offer_intent','fixture-offer');},
  async intercept(name){if(name==='home_feed'){entered=true;await pending;return rpc(home([offer()],{signed_in:true}));}}
 });
 try{
  await until(()=>entered&&ui.find('Log out'));
  ui.click('Log out');await until(()=>ui.find('Find local deals'));
  release();await tick();
  assert.ok(ui.find('Find local deals'));
  assert.equal(ui.window.localStorage.getItem('mlocal_public_offer_intent'),null);
  assert.equal(ui.calls.some(call=>call.name==='get_offer'),false);
 }finally{release();ui.close();}
});

test('finishing verification respects a newer offer selection made during its feed refresh',async()=>{
 const fixture=verificationHeldAtFeed();
 const ui=await app({role:'guest',audience:'',intercept:fixture.intercept});
 try{
  await verifySelected(ui);await until(fixture.entered);
  await setMaximumPrice(ui,10);await until(()=>ui.find('Other bowl'));
  ui.click('Other bowl');await until(()=>ui.find('Claim this offer'));
  assert.equal(ui.window.localStorage.getItem('mlocal_public_offer_intent'),'other-offer');
  const reads=ui.calls.filter(call=>call.name==='get_offer').length;
  fixture.release();await tick();
  assert.equal(ui.window.localStorage.getItem('mlocal_public_offer_intent'),'other-offer');
  assert.equal(ui.calls.filter(call=>call.name==='get_offer').length,reads);
  assert.ok(ui.find('Other bowl'));
  assert.equal(ui.calls.some(call=>call.name==='claim_offer'),false);
 }finally{fixture.release();ui.close();}
});

test('initial session restoration respects an offer selected through a newer feed request',async()=>{
 let entered=false,held=true,release;
 const pending=new Promise(resolve=>release=resolve);
 const ui=await app({verified:true,configureWindow(window){window.localStorage.setItem('mlocal_public_offer_intent','fixture-offer');},
  async intercept(name,body){
   if(name==='home_feed'){
    if(held){held=false;entered=true;await pending;}
    return rpc(home([offer({id:'other-offer',title:'Other bowl'})],{signed_in:true}));
   }
   if(name==='get_offer'&&body.offer_id==='other-offer')return rpc(offer({id:'other-offer',title:'Other bowl'}));
  }
 });
 try{
  await until(()=>entered);
  await setMaximumPrice(ui,10);await until(()=>ui.find('Other bowl'));
  ui.click('Other bowl');await until(()=>ui.find('Claim this offer'));
  const reads=ui.calls.filter(call=>call.name==='get_offer').length;
  release();await tick();
  assert.equal(ui.window.localStorage.getItem('mlocal_public_offer_intent'),'other-offer');
  assert.equal(ui.calls.filter(call=>call.name==='get_offer').length,reads);
  assert.ok(ui.find('Other bowl'));
 }finally{release();ui.close();}
});
