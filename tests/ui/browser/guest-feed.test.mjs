import test from 'node:test';
import assert from 'node:assert/strict';
import {app,offer,held,home,rpc,until} from './harness.mjs';

const student={authenticated:true,role:'student',actor_id:'fixture-student',restaurant_id:'',display_name:'Fixture student',is_demo:false,email_verified:true};
function signupFlow(state,extra={}) {
 return (name,body)=>{
  if(name==='request_email_code')return rpc({ok:true,challenge:'fixture',email:'fixture@umich.edu',retry_after:60,message:'Check your inbox.'});
  if(name==='verify_email_code'){state.verified=true;return rpc({ok:true,token:'fresh-token',message:''});}
  if(name==='current_session'&&state.verified)return rpc(student);
  if(state.verified&&name==='get_offer'&&extra.getOffer)return rpc(extra.getOffer(body));
 };
}
async function verify(ui) {
 ui.fill('uniqname','fixture');ui.click('Send verification code');
 await until(()=>ui.document.querySelector('[autocomplete="one-time-code"]'));
 ui.fill('123456','123456');ui.click('Verify and continue');
}
async function browse(ui) {
 ui.click('Find local deals');await until(()=>ui.find('Current bowl'));
}

test('student visitors browse before sign-in and public responses never render private claim fields',async()=>{
 const ui=await app({role:'guest',audience:'',item:held(),intercept(name){
  if(name==='home_feed')return rpc(home([held()]));
  if(name==='get_offer')return rpc(held());
 }});
 try{
  await browse(ui);
  assert.ok(ui.calls.some(c=>c.name==='home_feed'));
  assert.equal(ui.document.querySelector('[placeholder="uniqname"]'),null);
  assert.ok(ui.find('Sign in'));
  ui.click('Current bowl');await until(()=>ui.find('Sign in to claim'));
  assert.equal(ui.document.querySelector('[data-testid="claim-qr"]'),null);
  assert.equal(ui.find('Cancel this hold'),undefined);
  assert.equal(ui.document.querySelector('[data-testid="app-tabbar"]'),null);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('verification returns to the public offer with fresh availability and never automatically claims',async()=>{
 const state={verified:false};
 const ui=await app({role:'guest',audience:'',intercept:signupFlow(state)});
 try{
  await browse(ui);ui.click('Current bowl');await until(()=>ui.find('Sign in to claim'));
  ui.click('Sign in to claim');await until(()=>ui.document.querySelector('[placeholder="uniqname"]'));
  assert.equal(ui.window.localStorage.getItem('mlocal_public_offer_intent'),'fixture-offer');
  assert.equal(ui.calls.some(c=>c.name==='claim_offer'),false);
  const before=ui.calls.filter(c=>c.name==='get_offer').length;
  await verify(ui);await until(()=>ui.find('Claim this offer'));
  assert.ok(ui.calls.filter(c=>c.name==='get_offer').length>before);
  assert.equal(ui.calls.some(c=>c.name==='claim_offer'),false);
  assert.equal(ui.window.localStorage.getItem('mlocal_public_offer_intent'),'fixture-offer');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

for(const [label,reply,message] of [
 ['removed',()=>null,'This offer is no longer available.'],
 ['sold out',()=>offer({state:'sold out',remaining:0}),'This offer is sold out right now.'],
 ['expired',()=>offer({state:'expired',remaining:0}),'This offer is expired right now.']
])test(`an offer ${label} during verification has clear recovery and no automatic claim`,async()=>{
 const state={verified:false};
 const ui=await app({role:'guest',audience:'',intercept:signupFlow(state,{getOffer:reply})});
 try{
  await browse(ui);ui.click('Current bowl');await until(()=>ui.find('Sign in to claim'));
  ui.click('Sign in to claim');await until(()=>ui.document.querySelector('[placeholder="uniqname"]'));
  await verify(ui);await until(()=>ui.text().includes(message));
  assert.equal(ui.find('Claim this offer'),undefined);
  assert.equal(ui.calls.some(c=>c.name==='claim_offer'),false);
  assert.ok(ui.find('Back to offers'));
 }finally{ui.close();}
});

test('reload resumes only a public offer ID and fetches current server state',async()=>{
 const ui=await app({role:'guest',audience:'',configureWindow(w){w.localStorage.setItem('mlocal_public_offer_intent','fixture-offer');}});
 try{
  await until(()=>ui.find('Sign in to claim'));
  assert.ok(ui.calls.some(c=>c.name==='get_offer'&&c.body.offer_id==='fixture-offer'));
  assert.equal(ui.window.localStorage.getItem('mlocal_public_offer_intent'),'fixture-offer');
  assert.equal(ui.window.localStorage.getItem('jac_token'),null);
  assert.equal(ui.document.querySelector('[data-testid="claim-qr"]'),null);
  ui.click('Back to offers');await until(()=>ui.find('Current bowl'));
  assert.equal(ui.window.localStorage.getItem('mlocal_public_offer_intent'),null);
 }finally{ui.close();}
});

test('a private credential or DTO in the public intent key is discarded on reload',async()=>{
 for(const value of ['mlocal:v1:'+'A'.repeat(43),JSON.stringify(held()),'../private','x'.repeat(129)]){
  const ui=await app({role:'guest',audience:'',configureWindow(w){w.localStorage.setItem('mlocal_public_offer_intent',value);}});
  try{
   assert.ok(ui.find('Find local deals'));
   assert.equal(ui.window.localStorage.getItem('mlocal_public_offer_intent'),null);
   assert.equal(ui.calls.some(c=>c.name==='get_offer'),false);
   assert.equal(ui.document.querySelector('[data-testid="claim-qr"]'),null);
  }finally{ui.close();}
 }
});

test('an authenticated reload restores the selected public offer without automatic claiming',async()=>{
 const ui=await app({verified:true,configureWindow(w){w.localStorage.setItem('mlocal_public_offer_intent','fixture-offer');}});
 try{
  await until(()=>ui.find('Claim this offer'));
  assert.ok(ui.calls.some(c=>c.name==='get_offer'&&c.body.offer_id==='fixture-offer'));
  assert.equal(ui.calls.some(c=>c.name==='claim_offer'),false);
  assert.equal(ui.window.localStorage.getItem('mlocal_public_offer_intent'),'fixture-offer');
 }finally{ui.close();}
});

test('guest favorites request sign-in and cancelling it restores the selected offer',async()=>{
 const ui=await app({role:'guest',audience:''});
 try{
  await browse(ui);
  ui.document.querySelector('[aria-label="Add Fixture Kitchen to favorites"]').click();
  await until(()=>ui.text().includes('Sign in to save your favorite places.'));
  assert.equal(ui.calls.some(c=>c.name==='toggle_favorite'),false);
  ui.click('Back');await until(()=>ui.find('Current bowl'));
  ui.click('Current bowl');await until(()=>ui.find('Sign in to claim'));
  ui.click('Sign in to claim');await until(()=>ui.document.querySelector('[placeholder="uniqname"]'));
  ui.click('Back');await until(()=>ui.find('Sign in to claim'));
 }finally{ui.close();}
});
