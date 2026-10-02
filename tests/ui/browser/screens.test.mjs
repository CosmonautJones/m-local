import {openSignIn} from './harness.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {app,home,offer,feedItem,rpc,until} from './harness.mjs';

const heart=(ui,word)=>ui.document.querySelector(`[aria-label="${word} Fixture Kitchen ${word==='Add'?'to':'from'} favorites"]`);
const has=(ui,text)=>ui.find(text)!==undefined;

test('guest gets the sign-in screen and never sees or loads deals',async()=>{
 const ui=await app({role:'guest'});
 try{
  await openSignIn(ui);
  await until(()=>ui.document.querySelector('input[placeholder="uniqname"]'));
  assert.ok(ui.text().includes('Sign in to M-Local'));
  assert.equal(has(ui,'Current bowl'),false);assert.equal(has(ui,'Your favorites'),false);
  assert.equal(has(ui,'Nearby'),false);assert.equal(has(ui,'Account'),false);assert.equal(has(ui,'Log out'),false);
  assert.equal(heart(ui,'Add'),null);
  assert.equal(has(ui,'Keep browsing'),false);
  assert.equal(ui.calls.some(c=>['home_feed','list_offers','get_offer'].includes(c.name)),false,'no deals are requested before sign-in');
  ui.click('Back');await until(()=>has(ui,'Find local deals'));
  assert.equal(has(ui,'Current bowl'),false);
  assert.equal(ui.calls.some(c=>['home_feed','list_offers','get_offer'].includes(c.name)),false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('student heart adds the place to the favorites strip and can remove it',async()=>{
 let kept=false;
 const place={slug:'fixture-kitchen',name:'Fixture Kitchen',cuisine:'Test cuisine',neighborhood:'Test area',labels:[],live_offers:1,best_offer_id:'fixture-offer',best_offer_title:'Current bowl',best_price_cents:900,is_demo:false};
 const ui=await app({verified:true,intercept(name){
  if(name==='toggle_favorite'){kept=!kept;return undefined;}
  if(name==='home_feed')return rpc(home([feedItem(offer(),{is_favorite:kept})],{signed_in:true,favorites:kept?[place]:[]}));
 }});
 try{
  assert.ok(has(ui,'Your favorites'));assert.ok(has(ui,'Tap the heart on a place to keep it here.'));
  heart(ui,'Add').dispatchEvent(new ui.window.MouseEvent('click',{bubbles:true}));
  await until(()=>heart(ui,'Remove'),'heart turns on');
  assert.deepEqual(ui.calls.find(c=>c.name==='toggle_favorite').body,{slug:'fixture-kitchen',offer_id:''});
  assert.equal(has(ui,'Tap the heart on a place to keep it here.'),false);
  assert.equal(ui.calls.some(c=>c.name==='get_offer'),false,'the heart must not open the offer under it');
  assert.equal(ui.document.querySelector('button button'),null,'no button nested inside a button');
  heart(ui,'Remove').dispatchEvent(new ui.window.MouseEvent('click',{bubbles:true}));
  await until(()=>heart(ui,'Add'),'heart turns off');
  assert.ok(has(ui,'Tap the heart on a place to keep it here.'));
  assert.equal(ui.calls.filter(c=>c.name==='toggle_favorite').length,2);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('student menu is Offers and Account, and log out hides the deals',async()=>{
 const ui=await app({verified:true});
 try{
  assert.ok(has(ui,'Offers'));assert.ok(has(ui,'Account'));
  assert.equal(has(ui,'Manage'),false);assert.equal(has(ui,'Redeem'),false);
  assert.ok(has(ui,'Log out'));
  ui.click('Account');await until(()=>ui.text().includes('YOUR ACCOUNT'));
  assert.ok(has(ui,'Log out'));assert.ok(has(ui,'Edit my tastes'));
  ui.click('Log out');await until(()=>ui.find('Find local deals'));
  assert.equal(ui.window.localStorage.getItem('jac_token'),null);
  assert.equal(has(ui,'Nearby'),false);assert.equal(has(ui,'Log out'),false);assert.equal(has(ui,'Current bowl'),false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('restaurant lands on Insights with business navigation and can log out',async()=>{
 const ui=await app({role:'merchant',verified:true,audience:'business'});
 try{
  await until(()=>ui.calls.some(c=>c.name==='merchant_insights'),'private insights load on landing');
  assert.ok(has(ui,'Insights'));
  assert.equal(ui.calls.some(c=>c.name==='home_feed'),false,'business landing does not fetch the student feed');
  assert.equal(ui.document.querySelector('[data-testid="app-tabbar"] [role=button]').textContent,'Insights');
  ui.click('Manage');await until(()=>has(ui,'New offer'));
  assert.ok(has(ui,'Manage'));assert.ok(has(ui,'Redeem'));assert.ok(has(ui,'Account'));
  assert.equal(has(ui,'Nearby'),false);assert.equal(has(ui,'Your favorites'),false);
  ui.click('Redeem');await until(()=>ui.text().includes('Scan a claim'));
  assert.ok(has(ui,'Log out'));
  ui.click('Log out');await until(()=>ui.find('Find local deals'));
  assert.equal(ui.window.localStorage.getItem('jac_token'),null);
  assert.equal(has(ui,'Manage'),false);assert.equal(has(ui,'Current bowl'),false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('business without a restaurant sees only its own account and can log out',async()=>{
 const ui=await app({role:'business',verified:true,audience:'business'});
 try{
  assert.ok(ui.text().includes('YOUR BUSINESS'));assert.ok(ui.document.querySelector('[placeholder="Business name"]'));assert.equal(has(ui,'Business profile'),false);assert.ok(has(ui,'Log out'));
  assert.equal(has(ui,'Current bowl'),false);assert.equal(has(ui,'Nearby'),false);assert.equal(has(ui,'Manage'),false);
  ui.click('Log out');await until(()=>ui.find('Find local deals'));
  assert.equal(has(ui,'Business profile'),false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('sample listings stay hidden unless the server turns demo mode on',async()=>{
 const sample=feedItem(offer({id:'sample-offer',title:'Sample bowl',restaurant:'Sample Place (Demo)',is_demo:true}),{place:'sample-place'});
 const feed=on=>rpc(home([feedItem(offer()),sample],{show_samples:on}));
 const hidden=await app({intercept(name){if(name==='home_feed')return feed(false);}});
 try{assert.ok(has(hidden,'Current bowl'));assert.equal(has(hidden,'Sample bowl'),false);assert.deepEqual(hidden.errors,[]);}finally{hidden.close();}
 const shown=await app({intercept(name){if(name==='home_feed')return feed(true);}});
 try{await until(()=>has(shown,'Sample bowl'));assert.ok(has(shown,'Current bowl'));assert.deepEqual(shown.errors,[]);}finally{shown.close();}
});

test('sign in, log out and sign in again requests and accepts a second code',async()=>{
 let signedIn=false,requests=0;
 const ui=await app({role:'guest',intercept(name){
  if(name==='request_email_code')return rpc({ok:true,challenge:`challenge-${++requests}`,email:'fixture@umich.edu',retry_after:60,message:'Check your inbox.'});
  if(name==='verify_email_code'){signedIn=true;return rpc({ok:true,message:'',token:'synthetic-ui-token'});}
  if(name==='current_session')return rpc({authenticated:signedIn,actor_id:signedIn?'fixture-student':'',role:signedIn?'student':'guest',restaurant_id:'',display_name:'Fixture student',email_verified:signedIn,is_demo:false});
  if(name==='home_feed')return rpc(home([offer()],{signed_in:signedIn}));
 }});
 const signIn=async round=>{
  await openSignIn(ui);
  await until(()=>ui.document.querySelector('input[placeholder="uniqname"]'),`sign-in form, round ${round}`);
  ui.fill('uniqname','fixture');ui.click('Send verification code');
  await until(()=>ui.document.querySelector('input[autocomplete="one-time-code"]'),`code field, round ${round}`);
  ui.fill('123456','123456');ui.click('Verify and continue');
  await until(()=>has(ui,'Current bowl'),`deals after sign-in, round ${round}`);
 };
 try{
  await signIn(1);
  ui.click('Log out');signedIn=false;
  await signIn(2);
  assert.equal(requests,2);
  assert.deepEqual(ui.calls.filter(c=>c.name==='verify_email_code').map(c=>c.body.challenge),['challenge-1','challenge-2']);
  assert.ok(has(ui,'Log out'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
