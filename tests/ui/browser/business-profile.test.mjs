import assert from 'node:assert/strict';
import test from 'node:test';
import {app, home, offer, rpc, until} from './harness.mjs';

const profile = (extra={}) => ({ok:true,message:'',slug:'fixture-kitchen',name:'Fixture Kitchen',
 cuisine:'Seasonal bowls',blurb:'A neighborhood kitchen with a changing seasonal menu.',
 address:'123 Example Street, Ann Arbor',neighborhood:'Downtown',entrance_note:'Use the side entrance.',
 note_date:'2026-09-27',is_demo:false,offers:[offer()],...extra});

test('the business profile shows its saved photo and falls back when it cannot load',async()=>{
 const image_url='https://images.example.test/kitchen.png';
 const ui=await app({verified:true,intercept(name){if(name==='get_business_profile')return rpc(profile({image_url}));}});
 try{
  ui.click('Fixture Kitchen');await until(()=>ui.find('A neighborhood kitchen with a changing seasonal menu.'));
  const image=ui.document.querySelector('.ml-business-hero img');
  assert.ok(image,'saved business photo is visible on its profile');
  assert.equal(image.src,image_url);assert.equal(image.alt,'Fixture Kitchen business photo');
  assert.equal(image.getAttribute('referrerpolicy'),'no-referrer');
  image.dispatchEvent(new ui.window.Event('error'));
  await until(()=>!ui.document.querySelector('.ml-business-hero img'));
  assert.equal(ui.document.querySelector('.ml-business-monogram').textContent,'FK');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('business names open profiles while offer titles retain their existing detail flow',async()=>{
 const ui=await app({verified:true,intercept(name){if(name==='get_business_profile')return rpc(profile());}});
 try{
  ui.click('Fixture Kitchen');await until(()=>ui.find('A neighborhood kitchen with a changing seasonal menu.'));
  assert.deepEqual(ui.calls.find(c=>c.name==='get_business_profile').body,{slug:'fixture-kitchen',offer_id:''});
  assert.match(ui.text(),/123 Example Street/);assert.match(ui.text(),/Unverified restaurant note/);
  assert.ok(ui.document.querySelector('a[href^="https://www.google.com/maps/search/"]'));
  assert.equal(ui.calls.some(c=>c.name==='claim_offer'),false);
  ui.click('Current bowl');await until(()=>ui.find('Claim this offer'));
  assert.ok(ui.calls.some(c=>c.name==='get_offer'));
  ui.click('Back to offers');await until(()=>ui.find('Refresh offers'));
  ui.click('Current bowl');await until(()=>ui.find('Claim this offer'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('opening a profile from an offer returns to that offer without losing its claim state',async()=>{
 const ui=await app({verified:true,intercept(name){if(name==='get_business_profile')return rpc(profile());}});
 try{
  ui.click('Current bowl');await until(()=>ui.find('View business profile'));
  ui.click('View business profile');await until(()=>ui.find('A neighborhood kitchen with a changing seasonal menu.'));
  assert.deepEqual(ui.calls.find(c=>c.name==='get_business_profile').body,{slug:'',offer_id:'fixture-offer'});
  ui.click('Back to offer');await until(()=>ui.find('Claim this offer'));
  assert.equal(ui.calls.some(c=>c.name==='claim_offer'),false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('profile load failure offers retry and an empty business has a useful offers state',async()=>{
 let attempts=0;
 const ui=await app({verified:true,intercept(name){if(name==='get_business_profile'){
  if(++attempts===1)throw new Error('offline');return rpc(profile({offers:[],entrance_note:'',address:''}));
 }}});
 try{
  ui.click('Fixture Kitchen');await until(()=>ui.find('Retry business profile'));
  ui.click('Retry business profile');await until(()=>ui.find('No offers right now'));
  assert.equal(ui.document.querySelector('a[href^="https://www.google.com/maps/search/"]'),null);
  assert.equal(attempts,2);assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('a favorite without a current offer opens its business and never removes the favorite',async()=>{
 const ui=await app({verified:true,intercept(name){
  if(name==='home_feed')return rpc(home([offer()],{signed_in:true,show_samples:false,favorites:[{slug:'quiet-kitchen',name:'Quiet Kitchen',cuisine:'Cafe',labels:[],best_offer_id:'',best_price_cents:0,best_offer_title:'',is_demo:false}]}));
  if(name==='get_business_profile')return rpc(profile({slug:'quiet-kitchen',name:'Quiet Kitchen',offers:[]}));
 }});
 try{
  ui.click('Quiet Kitchen');await until(()=>ui.find('No offers right now'));
  assert.equal(ui.calls.some(c=>c.name==='toggle_favorite'),false);
  assert.equal(ui.calls.find(c=>c.name==='get_business_profile').body.slug,'quiet-kitchen');
  ui.click('Back to offers');await until(()=>ui.find('Remove favorite'));
  ui.click('Remove favorite');await until(()=>ui.calls.some(c=>c.name==='toggle_favorite'));
  assert.equal(ui.calls.find(c=>c.name==='toggle_favorite').body.slug,'quiet-kitchen');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('logout cancels a pending business view and guest visits never request a profile',async()=>{
 let release;
 const pending=new Promise(resolve=>{release=resolve;});
 const ui=await app({verified:true,intercept(name){if(name==='get_business_profile')return pending;}});
 try{
  ui.click('Fixture Kitchen');await until(()=>ui.calls.some(c=>c.name==='get_business_profile'));
  ui.click('Account');await until(()=>ui.find('Log out of M-Local'));
  ui.click('Log out of M-Local');await until(()=>ui.find('Find local deals'));
  release(rpc(profile()));await new Promise(resolve=>setTimeout(resolve,60));
  assert.equal(ui.text().includes('A neighborhood kitchen'),false);
  assert.deepEqual(ui.errors,[]);
 }finally{release(rpc(profile()));ui.close();}
 const guest=await app({role:'guest'});
 try{assert.equal(guest.calls.some(c=>c.name==='get_business_profile'),false);}finally{guest.close();}
});

test('merchants can preview their public business page without exposing management controls',async()=>{
 const ui=await app({role:'merchant',verified:true,intercept(name){if(name==='get_business_profile')return rpc(profile());}});
 try{
  ui.click('Manage');await until(()=>ui.find('View business page'));
  ui.click('View business page');await until(()=>ui.find('A neighborhood kitchen with a changing seasonal menu.'));
  assert.deepEqual(ui.calls.find(c=>c.name==='get_business_profile').body,{slug:'',offer_id:''});
  assert.equal(ui.find('Save profile'),undefined);assert.equal(ui.find('Claim this offer'),undefined);
  ui.click('Back to Manage');await until(()=>ui.find('Edit business details'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
