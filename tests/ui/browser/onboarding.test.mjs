import {openSignIn} from './harness.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {app,rpc,until} from './harness.mjs';

test('student email has a fixed suffix and missing sender never shows a code-sent state',async()=>{
 const ui=await app({role:'guest',intercept(name){if(name==='request_email_code')return rpc({ok:false,message:'Email sign-in is not enabled yet.'});}});
 try{
  await openSignIn(ui);
  await until(()=>ui.document.querySelector('input[placeholder="uniqname"]'));
  assert.ok(ui.text().includes('@umich.edu'));
  assert.equal(ui.document.querySelector('input[placeholder="uniqname"]').getAttribute('aria-label'),'U-M uniqname');
  assert.equal(ui.document.querySelector('input[value="@umich.edu"]'),null);
  ui.click('Create an account');await until(()=>ui.document.querySelector('[placeholder="Your name"]'));
  ui.fill('Your name','Fixture');ui.fill('uniqname','fixture');ui.click('Send verification code');
  await until(()=>ui.text().includes('Email sign-in is not enabled yet.'));
  assert.equal(ui.document.querySelector('input[autocomplete="one-time-code"]'),null);
  assert.equal(ui.window.localStorage.getItem('jac_token'),null);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('code flow sends only the uniqname and enables code autofill without university password',async()=>{
 const ui=await app({role:'guest',intercept(name){
  if(name==='request_email_code')return rpc({ok:true,challenge:'opaque-fixture',email:'fixture@umich.edu',retry_after:60,message:'Check your inbox.'});
  if(name==='verify_email_code')return rpc({ok:false,message:'That code is invalid or expired.'});
 }});
 try{
  await openSignIn(ui);
  await until(()=>ui.document.querySelector('input[placeholder="uniqname"]'));
  ui.click('Create an account');await until(()=>ui.document.querySelector('[placeholder="Your name"]'));
  ui.fill('Your name','Fixture');ui.fill('uniqname','fixture');ui.click('Send verification code');
  await until(()=>ui.document.querySelector('input[autocomplete="one-time-code"]'));
  assert.equal(ui.document.querySelector('input[type="password"]'),null);
  assert.deepEqual(ui.calls.find(c=>c.name==='request_email_code').body,{value:'fixture',kind:'student',name:'Fixture'});
  ui.fill('123456','123456');ui.click('Verify and continue');
  await until(()=>ui.text().includes('That code is invalid or expired.'));
  assert.equal(ui.window.localStorage.getItem('jac_token'),null);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('business account path accepts work email and preserves manual entry fallback',async()=>{
 const ui=await app({role:'guest',audience:'business'});
 try{
  await openSignIn(ui,'business');
  await until(()=>ui.document.querySelector('input[placeholder="you@business.com"]'));
  assert.equal(ui.find('Current bowl'),undefined,'business visitors do not get the student feed');
  assert.equal(ui.find('Nearby')===undefined,true,'no app menu before sign-in');
  assert.equal(ui.document.querySelector('input[placeholder="uniqname"]'),null);
  assert.ok(ui.text().includes('Work email'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('first visit asks for a path and choosing deals removes business signup',async()=>{
 const ui=await app({role:'guest',audience:''});
 try{
  assert.ok(ui.find('Find local deals'));assert.ok(ui.find('List my business'));
  assert.equal(ui.document.querySelector('input'),null);
  ui.click('Find local deals');await until(()=>ui.document.querySelector('input[placeholder="uniqname"]'));
  assert.equal(ui.window.localStorage.getItem('mlocal_audience'),null);
  assert.equal(ui.find('List my business'),undefined);
  assert.equal(ui.find('Existing restaurant sign-in'),undefined);
  assert.equal(ui.document.querySelector('input[placeholder="you@business.com"]'),null);
  assert.equal(ui.find('Current bowl'),undefined,'deals need a signed-in account');
  assert.equal(ui.find('Business owner'),undefined);
  ui.click('Back');await until(()=>ui.find('Find local deals'));
  assert.equal(ui.find('Current bowl'),undefined,'deals need a signed-in account');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('business first visit sends a business code and leaves returning guests free to choose',async()=>{
 const ui=await app({role:'guest',audience:'',intercept(name){if(name==='request_email_code')return rpc({ok:false,message:'Fixture delivery disabled.'});}});
 let saved;
 try{
  ui.click('List my business');await until(()=>ui.document.querySelector('input[placeholder="you@business.com"]'));
  assert.equal(ui.find('Find local deals'),undefined);
  assert.equal(ui.document.querySelector('input[placeholder="uniqname"]'),null);
  ui.fill('Business Name','Owner');ui.fill('you@business.com','owner@example.test');ui.click('Send verification code');
  await until(()=>ui.text().includes('Fixture delivery disabled.'));
  assert.deepEqual(ui.calls.find(c=>c.name==='request_email_code').body,{value:'owner@example.test',kind:'business',name:'Owner'});
  saved=ui.window.localStorage.getItem('mlocal_audience');assert.equal(saved,null);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
 const returning=await app({role:'guest',audience:'business'});
 try{
  assert.ok(returning.find('Find local deals'));
  assert.ok(returning.find('List my business'));
  assert.equal(returning.document.querySelector('input'),null);
  assert.equal(returning.document.querySelector('input[placeholder="uniqname"]'),null);
 }finally{returning.close();}
});

test('verified student never receives a business creation prompt',async()=>{
 const ui=await app({role:'student',verified:true,audience:''});
 try{
  assert.equal(ui.find('Create a business profile'),undefined);
  assert.equal(ui.find('List my business'),undefined);
  assert.equal(ui.window.localStorage.getItem('mlocal_audience'),null);
 }finally{ui.close();}
});

test('restored business session ignores stale paths and returns to shared welcome on signout',async()=>{
 const ui=await app({role:'business',verified:true,audience:'student'});
 try{
  assert.ok(ui.text().includes('YOUR BUSINESS'));
  ui.click('Log out');await until(()=>ui.find('Find local deals'));
  assert.ok(ui.find('List my business'));
  ui.click('List my business');await until(()=>ui.document.querySelector('input[placeholder="you@business.com"]'));
  assert.equal(ui.document.querySelector('input[placeholder="uniqname"]'),null);
  assert.equal(ui.find('Find local deals'),undefined);
  assert.equal(ui.find('Current bowl'),undefined);
  ui.click('Back');await until(()=>ui.find('Find local deals'));
  assert.equal(ui.find('Sign in to claim'),undefined);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('business import fills an editable draft and requires confirmation before saving',async()=>{
 let submitted=false,approved=false,activated=false;
 const ui=await app({role:'business',verified:true,intercept(name,body){
  if(name==='get_business_draft')return rpc({ok:true,...(submitted?{name:'Reviewed Cafe',address:'123 Fixture St'}:{}),status:approved?'approved':submitted?'pending_review':'draft'});
  if(name==='import_business_website')return rpc({ok:true,name:'Imported Cafe',address:'123 Fixture St',website:body.website,menu_text:'Soup $8',sources:[body.website],menu_urls:[body.website+'/menu'],image_url:body.website+'/photo.jpg',image_urls:[body.website+'/photo.jpg'],message:'Review the imported details.'});
  if(name==='save_business_draft'){submitted=true;activated=approved;return rpc({...body,ok:true,status:approved?'active':'pending_review',message:approved?'Business profile saved.':'Submitted for review.'});}
  if(name==='current_session'&&activated)return rpc({authenticated:true,actor_id:'fixture-business',role:'merchant',restaurant_id:'owned-business',display_name:'Fixture owner',is_demo:false,email_verified:true});
 }});
 try{
  if(ui.find('Business profile'))ui.click('Business profile');await until(()=>ui.document.querySelector('input[placeholder="Business name"]'));
  await until(()=>!ui.document.querySelector('input[placeholder="Business name"]').disabled);
  ui.fill('https://your-business.com','https://example.com');ui.click('Import website details');
  await until(()=>ui.document.querySelector('input[placeholder="Business name"]').value==='Imported Cafe');
  const preview=ui.document.querySelector('img[alt="Selected business photo"]');
  assert.equal(preview?.getAttribute('src'),'https://example.com/photo.jpg');
  assert.equal(ui.window.getComputedStyle(preview).height,'190px');
  assert.equal(ui.window.getComputedStyle(preview).objectFit,'contain');
  assert.equal((preview.getAttribute('referrerpolicy')||preview.referrerPolicy),'no-referrer');
  assert.equal(ui.find('Review selected image'),undefined);
  assert.equal(ui.find('Found images'),undefined);
  assert.equal(ui.find('Submit for review').disabled,true);
  ui.fill('Business name','Reviewed Cafe');
  ui.document.querySelector('input[type="checkbox"]').click();ui.click('Submit for review');
  await until(()=>ui.find('Check approval'));
  assert.equal(ui.find('Insights'),undefined);assert.equal(ui.find('Offers'),undefined);
  approved=true;ui.click('Check approval');await until(()=>ui.find('Continue to offers'));
  ui.click('Continue to offers');
  await until(()=>ui.find('Insights'));
  ui.click('Offers');await until(()=>ui.find('New offer'));
  const request=ui.calls.find(c=>c.name==='save_business_draft');
  assert.equal(request.body.name,'Reviewed Cafe');assert.equal(request.body.confirmed,true);
  assert.equal('actor_id' in request.body,false);assert.equal('role' in request.body,false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
