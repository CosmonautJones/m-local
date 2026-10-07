import test from 'node:test';
import assert from 'node:assert/strict';
import {app,held,offer,rpc,until} from './harness.mjs';

function claimClock(){
 let w,visible=true,online=true,next=1;const timers=new Map();
 return {
  configureWindow(window){w=window;
   Object.defineProperty(w.document,'visibilityState',{configurable:true,get:()=>visible?'visible':'hidden'});
   Object.defineProperty(w.navigator,'onLine',{configurable:true,get:()=>online});
   w.setInterval=(fn,delay)=>{const id=next++;timers.set(id,{fn,delay});return id;};
   w.clearInterval=id=>timers.delete(id);
  },
  tick(){for(const t of [...timers.values()])if(t.delay===3000)t.fn();},
  visible(value){visible=value;w.document.dispatchEvent(new w.Event('visibilitychange'));},
  online(value){online=value;w.dispatchEvent(new w.Event(value?'online':'offline'));},
  count(){return [...timers.values()].filter(t=>t.delay===3000).length;}
 };
}

for(const status of ['redeemed','expired'])test(`a visible held claim refreshes and announces ${status} without retaining a live QR`,async()=>{
 const clock=claimClock();let changed=false;
 const ui=await app({item:held(),configureWindow:clock.configureWindow,intercept(name){if(name==='get_offer'&&changed)return rpc(held({my_status:status,my_qr_payload:'',my_expires_ts:Date.now()/1000-1}));}});
 try{
  ui.click('Saved bowl');await until(()=>ui.document.querySelector('[data-testid="claim-qr"]'));
  assert.equal(clock.count(),1,'held claims must refresh within three seconds');
  changed=true;clock.tick();await until(()=>ui.text().includes(status==='redeemed'?'Your saved claim was redeemed.':'Your hold has expired.'));
  assert.equal(ui.document.querySelector('[data-testid="claim-qr"]'),null);
  assert.ok(ui.document.querySelector('[role="status"],[role="alert"]'));
  assert.equal(clock.count(),0,'terminal claim status stops polling');
  assert.equal(ui.calls.some(c=>c.name==='claim_offer'||c.name==='redeem_claim'),false);
 }finally{ui.close();}
});

test('claim refresh coalesces requests skips hidden or offline pages and removes listeners on exit',async()=>{
 const clock=claimClock();let release;
 const pending=new Promise(resolve=>release=resolve);
 const ui=await app({item:held(),configureWindow:clock.configureWindow,intercept:async(name,body,{calls})=>{
  if(name==='get_offer'&&calls.filter(c=>c.name==='get_offer').length===2){await pending;return rpc(held());}
 }});
 try{
  ui.click('Saved bowl');await until(()=>ui.document.querySelector('[data-testid="claim-qr"]'));
  const reads=()=>ui.calls.filter(c=>c.name==='get_offer').length;
  clock.visible(false);clock.tick();await new Promise(r=>setTimeout(r,30));assert.equal(reads(),1);
  clock.online(false);clock.visible(true);clock.tick();await new Promise(r=>setTimeout(r,30));assert.equal(reads(),1);
  clock.online(true);await until(()=>reads()===2);
  clock.tick();clock.visible(true);clock.online(true);await new Promise(r=>setTimeout(r,30));assert.equal(reads(),2);
  release();await new Promise(r=>setTimeout(r,30));ui.click('Back to offers');await until(()=>ui.find('Refresh offers'));
  assert.equal(clock.count(),0);clock.tick();clock.visible(true);clock.online(true);await new Promise(r=>setTimeout(r,30));assert.equal(reads(),2);
 }finally{release();ui.close();}
});

test('sign-out ignores a claim polling response from the old account',async()=>{
 const clock=claimClock();let release;
 const pending=new Promise(resolve=>release=resolve);
 const ui=await app({item:held(),configureWindow:clock.configureWindow,intercept:async(name,body,{calls})=>{
  if(name==='get_offer'&&calls.filter(c=>c.name==='get_offer').length===2){await pending;return rpc(held({my_status:'redeemed'}));}
 }});
 try{
  ui.click('Saved bowl');await until(()=>ui.document.querySelector('[data-testid="claim-qr"]'));
  clock.tick();await until(()=>ui.calls.filter(c=>c.name==='get_offer').length===2);
  ui.click('Log out');await until(()=>ui.find('Find local deals'));
  release();await new Promise(r=>setTimeout(r,30));
  assert.equal(ui.text().includes('Saved meal terms'),false);
  assert.equal(ui.text().includes('Your saved claim was redeemed.'),false);
  assert.equal(ui.document.querySelector('[data-testid="claim-qr"]'),null);
  assert.equal(clock.count(),0);
 }finally{release();ui.close();}
});
