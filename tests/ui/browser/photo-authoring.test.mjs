import test from 'node:test';
import assert from 'node:assert/strict';
import {app,offer,rpc,until} from './harness.mjs';
const local='/static/photos/'+'a'.repeat(32)+'.jpg', other='/static/photos/'+'b'.repeat(32)+'.jpg';
const remote='https://example.test/bowl.jpg';

test('business website choices show photos, select a canonical copy and save it',async()=>{
 const ui=await app({role:'business',verified:true,intercept(name,body){
  if(name==='get_business_draft')return rpc({ok:true,name:'Cafe',address:'123 Test',image_urls:[remote,'https://example.test/cafe.png']});
  if(name==='import_business_photo')return rpc({ok:true,url:local});
  if(name==='save_business_draft')return rpc({ok:false,message:'Saved fixture submitted.'});
 }});
 try{
  await until(()=>ui.document.querySelector('.ml-photo-choice'));
  assert.equal(ui.document.querySelectorAll('.ml-photo-choice img').length,2);
  assert.equal(ui.document.querySelector('select option[value="'+remote+'"]'),null);
  ui.document.querySelector('.ml-photo-choice').click();
  await until(()=>ui.document.querySelector('.ml-photo-preview img')?.getAttribute('src')===local);
  assert.equal(ui.document.querySelector('.ml-photo-choice').getAttribute('aria-pressed'),'true');
  ui.document.querySelector('input[type=checkbox]').click();ui.click('Submit for review');
  await until(()=>ui.text().includes('Saved fixture submitted.'));
  assert.equal(ui.calls.find(c=>c.name==='save_business_draft').body.image_url,local);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('failed website image selection keeps the existing photo and removal is explicit',async()=>{
 const ui=await app({role:'business',verified:true,intercept(name){
  if(name==='get_business_draft')return rpc({ok:true,name:'Cafe',address:'123 Test',image_url:local,image_urls:[remote]});
  if(name==='import_business_photo')return rpc({ok:false,message:'Website photo unavailable.'});
 }});
 try{
  await until(()=>ui.document.querySelector('.ml-photo-choice'));
  ui.document.querySelector('.ml-photo-choice').click();await until(()=>ui.text().includes('Website photo unavailable.'));
  assert.equal(ui.document.querySelector('.ml-photo-preview img').getAttribute('src'),local);
  ui.click('Remove photo');await until(()=>!ui.document.querySelector('.ml-photo-preview'));
  assert.equal(ui.document.querySelector('input[type=file]').getAttribute('accept'),'image/*');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('offer editing reuses website thumbnails and sends its own photo to save',async()=>{
 const ui=await app({role:'merchant',item:offer({offer_image_url:local}),intercept(name){
  if(name==='import_business_website')return rpc({ok:true,image_urls:[remote],image_url:remote});
  if(name==='import_business_photo')return rpc({ok:true,url:other});
 }});
 try{
  await until(()=>ui.find('New offer'));ui.click('Edit');await until(()=>ui.document.querySelector('[aria-label="Offer photo"]'));
  assert.equal(ui.document.querySelector('.ml-photo-preview img').getAttribute('src'),local);
  const section=ui.document.querySelector('[aria-label="Offer photo"]');
  section.querySelector('details').open=true;
  ui.fill('https://your-business.com','https://example.test');ui.click('Find website photos');
  await until(()=>ui.document.querySelector('.ml-photo-choice img'));
  ui.document.querySelector('.ml-photo-choice').click();await until(()=>ui.document.querySelector('.ml-photo-preview img').getAttribute('src')===other);
  ui.click('Save changes');await until(()=>ui.calls.some(c=>c.name==='save_offer'));
  assert.equal(ui.calls.find(c=>c.name==='save_offer').body.image_url,other);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('failed offer images retain readable offer content',async()=>{
 const ui=await app({item:offer({offer_image_url:local,image_url:remote})});
 try{
  const image=ui.document.querySelector('img[alt="Current bowl"]');assert.ok(image);
  image.dispatchEvent(new ui.window.Event('error'));await until(()=>ui.text().includes('Photo unavailable'));
  assert.ok(ui.find('Current bowl'));assert.ok(ui.find('$9.00'));
  assert.equal(ui.document.querySelector('img[src="'+remote+'"]'),null,'business image is not misrepresented as the dish');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
