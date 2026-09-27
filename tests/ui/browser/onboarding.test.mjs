import test from 'node:test';
import assert from 'node:assert/strict';
import {app,rpc,until} from './harness.mjs';

test('student email has a fixed suffix and missing sender never shows a code-sent state',async()=>{
 const ui=await app({role:'guest',intercept(name){if(name==='request_email_code')return rpc({ok:false,message:'Email sign-in is not enabled yet.'});}});
 try{
  ui.click('Open sign in');await until(()=>ui.document.querySelector('input[placeholder="uniqname"]'));
  assert.ok(ui.text().includes('@umich.edu'));
  assert.equal(ui.document.querySelector('input[placeholder="uniqname"]').getAttribute('aria-label'),'U-M uniqname');
  assert.equal(ui.document.querySelector('input[value="@umich.edu"]'),null);
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
  ui.click('Open sign in');await until(()=>ui.document.querySelector('input[placeholder="uniqname"]'));
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
  ui.click('Open sign in');
  await until(()=>ui.document.querySelector('input[placeholder="you@business.com"]'));
  assert.equal(ui.document.querySelector('input[placeholder="uniqname"]'),null);
  assert.ok(ui.text().includes('work email'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('first visit asks for a path and choosing deals removes business signup',async()=>{
 const ui=await app({role:'guest',audience:''});
 try{
  assert.ok(ui.find('Find local deals'));assert.ok(ui.find('List my business'));
  assert.equal(ui.document.querySelector('input'),null);
  ui.click('Find local deals');await until(()=>ui.document.querySelector('input[placeholder="uniqname"]'));
  assert.equal(ui.window.localStorage.getItem('mlocal_audience'),'student');
  assert.equal(ui.find('List my business'),undefined);
  assert.equal(ui.find('Existing restaurant sign-in'),undefined);
  assert.equal(ui.document.querySelector('input[placeholder="you@business.com"]'),null);
  ui.click('Keep browsing');await until(()=>ui.find('Open sign in'));ui.click('Open sign in');
  await until(()=>ui.document.querySelector('input[placeholder="uniqname"]'));
  assert.equal(ui.find('Business owner'),undefined);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('business first visit sends a business code and remembers only that login path',async()=>{
 const ui=await app({role:'guest',audience:'',intercept(name){if(name==='request_email_code')return rpc({ok:false,message:'Fixture delivery disabled.'});}});
 let saved;
 try{
  ui.click('List my business');await until(()=>ui.document.querySelector('input[placeholder="you@business.com"]'));
  assert.equal(ui.find('Find local deals'),undefined);
  assert.equal(ui.document.querySelector('input[placeholder="uniqname"]'),null);
  ui.fill('Your name','Owner');ui.fill('you@business.com','owner@example.test');ui.click('Send verification code');
  await until(()=>ui.text().includes('Fixture delivery disabled.'));
  assert.deepEqual(ui.calls.find(c=>c.name==='request_email_code').body,{value:'owner@example.test',kind:'business',name:'Owner'});
  saved=ui.window.localStorage.getItem('mlocal_audience');assert.equal(saved,'business');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
 const returning=await app({role:'guest',audience:saved});
 try{
  assert.equal(returning.find('Find local deals'),undefined);
  returning.click('Open sign in');await until(()=>returning.document.querySelector('input[placeholder="you@business.com"]'));
  assert.equal(returning.document.querySelector('input[placeholder="uniqname"]'),null);
 }finally{returning.close();}
});

test('verified student never receives a business creation prompt',async()=>{
 const ui=await app({role:'student',verified:true,audience:''});
 try{
  assert.equal(ui.find('Create a business profile'),undefined);
  assert.equal(ui.find('List my business'),undefined);
  assert.equal(ui.window.localStorage.getItem('mlocal_audience'),'student');
 }finally{ui.close();}
});

test('business signout returns to the neutral account-choice screen',async()=>{
 const ui=await app({role:'business',verified:true,audience:'student'});
 try{
  assert.equal(ui.window.localStorage.getItem('mlocal_audience'),'business');
  ui.click('Sign out');await until(()=>ui.find('Find local deals'));
  assert.equal(ui.window.localStorage.getItem('mlocal_audience'),null);
  assert.ok(ui.find('List my business'));
  assert.equal(ui.find('Open sign in'),undefined);
  ui.click('Find local deals');await until(()=>ui.document.querySelector('input[placeholder="uniqname"]'));
  assert.equal(ui.document.querySelector('input[placeholder="you@business.com"]'),null);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('student signout returns to the neutral account-choice screen',async()=>{
 const ui=await app({role:'student',verified:true,audience:'business'});
 try{
  assert.equal(ui.window.localStorage.getItem('mlocal_audience'),'student');
  ui.click('Sign out');await until(()=>ui.find('Find local deals'));
  assert.equal(ui.window.localStorage.getItem('mlocal_audience'),null);
  assert.ok(ui.find('List my business'));
  assert.equal(ui.find('Open sign in'),undefined);
  ui.click('List my business');await until(()=>ui.document.querySelector('input[placeholder="you@business.com"]'));
  assert.equal(ui.document.querySelector('input[placeholder="uniqname"]'),null);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('business import fills an editable draft and requires confirmation before saving',async()=>{
 const ui=await app({role:'business',verified:true,intercept(name,body){
  if(name==='get_business_draft')return rpc({ok:true});
  if(name==='import_business_website')return rpc({ok:true,name:'Imported Cafe',address:'123 Fixture St',website:body.website,menu_text:'Soup $8',sources:[body.website],menu_urls:[body.website+'/menu'],image_urls:[body.website+'/photo.jpg'],message:'Review the imported details.'});
  if(name==='save_business_draft')return rpc({...body,ok:true,status:'pending_review',message:'Business profile saved for review.'});
 }});
 try{
  if(ui.find('Create a business profile'))ui.click('Create a business profile');await until(()=>ui.document.querySelector('input[placeholder="Business name"]'));
  await until(()=>!ui.document.querySelector('input[placeholder="Business name"]').disabled);
  ui.fill('https://your-business.com','https://example.com');ui.click('Import website details');
  await until(()=>ui.document.querySelector('input[placeholder="Business name"]').value==='Imported Cafe');
  assert.equal(ui.find('Save business for review').disabled,true);
  ui.fill('Business name','Reviewed Cafe');
  ui.document.querySelector('input[type="checkbox"]').click();ui.click('Save business for review');
  await until(()=>ui.text().includes('Business profile saved for review.'));
  const request=ui.calls.find(c=>c.name==='save_business_draft');
  assert.equal(request.body.name,'Reviewed Cafe');assert.equal(request.body.confirmed,true);
  assert.equal('actor_id' in request.body,false);assert.equal('role' in request.body,false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
