import {openSignIn} from './harness.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {app,home,offer,rpc,until} from './harness.mjs';

test('returning email sign-in needs no name and can switch to business signup',async()=>{
 const ui=await app({role:'guest',intercept(name){if(name==='request_email_code')return rpc({ok:false,message:'Fixture delivery disabled.'});}});
 try{
  await openSignIn(ui);
  await until(()=>ui.document.querySelector('[placeholder="uniqname"]'));
  assert.equal(ui.document.querySelector('[placeholder="Your name"]'),null,'returning users should not have to invent a name again');
  ui.fill('uniqname','fixture');ui.click('Send verification code');await until(()=>ui.text().includes('Fixture delivery disabled.'));
  assert.equal(ui.calls.find(c=>c.name==='request_email_code').body.name,'');
  ui.click('Create an account');await until(()=>ui.document.querySelector('[placeholder="Your name"]'));
  assert.equal(ui.document.querySelector('[placeholder="Your name"]').required,true);
  const accountType=ui.document.querySelector('select[aria-label="Account type"]');
  accountType.value='business';accountType.dispatchEvent(new ui.window.Event('change',{bubbles:true}));
  await until(()=>ui.document.querySelector('[placeholder="you@business.com"]'));
  assert.equal(ui.document.querySelector('[placeholder="uniqname"]'),null);
  assert.equal(accountType.value,'business');
  assert.equal(ui.document.querySelector('[type="password"]'),null);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('account edit persists on reopen, refreshes session name, and cannot edit email or role',async()=>{
 let displayName='Fixture student';
 const profile=()=>({ok:true,message:'',display_name:displayName,email:'fixture@umich.edu',role:'student',email_verified:true,is_demo:false});
 const ui=await app({verified:true,intercept(name,body){
  if(name==='get_account_profile')return rpc(profile());
  if(name==='save_account_profile'){displayName=body.display_name;return rpc({...profile(),message:'Account profile saved.'});}
  if(name==='current_session')return rpc({authenticated:true,actor_id:'fixture-student',role:'student',restaurant_id:'',display_name:displayName,email_verified:true,is_demo:false});
 }});
 try{
  ui.click('Account');await until(()=>ui.document.querySelector('[placeholder="Display name"]'));
  await until(()=>!ui.document.querySelector('[placeholder="Display name"]').disabled);
  assert.ok(ui.text().includes('fixture@umich.edu'));assert.ok(ui.text().includes('Email verified'));
  assert.equal(ui.document.querySelector('input[type="email"]'),null);
  assert.equal(ui.document.querySelector('select[aria-label="Account type"]'),null);
  ui.fill('Display name','Updated fixture');ui.click('Save account');await until(()=>ui.text().includes('Account profile saved.'));
  await until(()=>ui.find('Updated fixture'));
  assert.deepEqual(ui.calls.find(c=>c.name==='save_account_profile').body,{display_name:'Updated fixture'});
  assert.equal(ui.find('Close account'),undefined);
  ui.click('Hide account details');await until(()=>!ui.document.querySelector('[placeholder="Display name"]'));
  ui.click('Account');await until(()=>ui.document.querySelector('[placeholder="Display name"]')?.value==='Updated fixture');
  ui.fill('Display name','Not saved');ui.click('Cancel changes');
  await until(()=>ui.document.querySelector('[placeholder="Display name"]')?.value==='Updated fixture');
  assert.equal(ui.calls.filter(c=>c.name==='save_account_profile').length,1);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('account rejection preserves input and allows a successful retry',async()=>{
 let attempts=0;
 const profile={ok:true,message:'',display_name:'Fixture student',email:'fixture@umich.edu',role:'student',email_verified:true,is_demo:false};
 const ui=await app({verified:true,intercept(name,body){
  if(name==='get_account_profile')return rpc(profile);
  if(name==='save_account_profile')return rpc(++attempts===1?{...profile,ok:false,message:'Fixture save rejected.'}:{...profile,display_name:body.display_name,message:'Account profile saved.'});
 }});
 try{
  ui.click('Account');await until(()=>ui.document.querySelector('[placeholder="Display name"]')?.value==='Fixture student');
  ui.fill('Display name','Kept name');ui.click('Save account');await until(()=>ui.text().includes('Fixture save rejected.'));
  assert.equal(ui.document.querySelector('[placeholder="Display name"]').value,'Kept name');
  assert.equal(ui.find('Save account').disabled,false);
  ui.click('Save account');await until(()=>ui.text().includes('Account profile saved.'));
  assert.equal(attempts,2);assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('pending business reopens its saved submission and clearly waits for approval',async()=>{
 const draft={ok:true,name:'Saved fixture cafe',address:'123 Fixture Street',status:'pending_review',message:''};
 const ui=await app({role:'business',verified:true,intercept(name){if(name==='get_business_draft')return rpc(draft);}});
 try{
  await until(()=>ui.document.querySelector('[placeholder="Business name"]')?.value==='Saved fixture cafe');
  assert.ok(ui.text().includes('Your business is awaiting approval'));
  assert.ok(ui.find('Check approval'));
  assert.equal(ui.find('New offer'),undefined);assert.equal(ui.find('Offers'),undefined);
  assert.equal(ui.find('Business profile'),undefined);
  assert.equal(ui.find('Close business profile'),undefined);
  assert.ok(ui.document.querySelector('[placeholder="Business name"]'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

const businessSession=role=>({authenticated:true,actor_id:'fixture-business',role,restaurant_id:role==='merchant'?'owned-business':'',display_name:'Fixture owner',email_verified:true,is_demo:false,business_account:true});
async function completeBusiness(ui){
 await until(()=>ui.document.querySelector('[placeholder="Business name"]')&&!ui.document.querySelector('[placeholder="Business name"]').disabled);
 ui.fill('Business name','Self-service cafe');ui.fill('Street address','123 Fixture Street');ui.document.querySelector('input[type="checkbox"]').click();
 const submit=ui.find('Submit for review');
 submit.click();
}

test('submission stays pending and check approval opens management only after server approval',async()=>{
 let submitted=false,approved=false;
 const fields={name:'Self-service cafe',address:'123 Fixture Street'};
 const ui=await app({role:'business',verified:true,intercept(name,body){
  if(name==='get_business_draft')return rpc({ok:true,...fields,status:approved?'approved':submitted?'pending_review':'draft'});
  if(name==='save_business_draft'){submitted=true;return rpc({...body,ok:true,status:approved?'active':'pending_review',message:approved?'Business profile saved.':'Submitted for review.'});}
  if(name==='current_session')return rpc(businessSession(approved?'merchant':'business'));
 }});
 try{
  await completeBusiness(ui);await until(()=>ui.find('Check approval'));
  assert.equal(ui.find('Offers'),undefined);assert.equal(ui.find('New offer'),undefined);
  ui.click('Check approval');await until(()=>ui.calls.filter(c=>c.name==='get_business_draft').length===2);
  await until(()=>ui.find('Check approval')&&!ui.find('Check approval').disabled);
  assert.equal(ui.find('Offers'),undefined);
  approved=true;ui.click('Check approval');await until(()=>ui.find('Continue to offers'));
  assert.equal(ui.find('Offers'),undefined);
  ui.click('Continue to offers');await until(()=>ui.find('New offer'));
  assert.equal(ui.calls.filter(c=>c.name==='save_business_draft').length,2);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('verified merchant edits use one business form and distinguish routine saves from identity review',async()=>{
 const saved={ok:true,name:'Fixture Kitchen',address:'Test address',description:'Saved description',status:'active',approved_name:'Fixture Kitchen',approved_address:'Test address'};
 const ui=await app({role:'merchant',verified:true,intercept(name,body){
  if(name==='get_business_draft')return rpc(saved);
  if(name==='save_business_draft')return rpc({...saved,...body,status:'pending_review',message:'Submitted for review.'});
 }});
 try{
  ui.click('Offers');await until(()=>ui.find('Edit business details'));ui.click('Edit business details');
  await until(()=>ui.document.querySelector('[placeholder="Business name"]')?.value==='Fixture Kitchen');
  assert.equal(ui.document.querySelector('[placeholder="Restaurant name"]'),null);
  ui.fill('About your business','Routine description edit');
  assert.ok(ui.find('Save business profile'),'routine edits keep the normal save action');
  ui.fill('Business name','Changed business identity');
  assert.ok(ui.find('Submit for review'),'identity edit makes review explicit');
  ui.document.querySelector('input[type="checkbox"]').click();ui.click('Submit for review');
  await until(()=>ui.find('Check approval'));
  assert.ok(ui.find('Offers'),'pending identity changes preserve offer management');
  assert.ok(ui.text().includes('Later name or address changes need review'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('saving an active business profile refreshes server authority and opens offer management',async()=>{
 let activated=false;
 const ui=await app({role:'business',verified:true,intercept(name,body){
  if(name==='get_business_draft')return rpc({ok:true});
  if(name==='save_business_draft'){activated=true;return rpc({...body,ok:true,status:'active',message:'Business profile saved.'});}
  if(name==='current_session')return rpc(businessSession(activated?'merchant':'business'));
 }});
 try{
  await completeBusiness(ui);await until(()=>ui.find('Offers'),'activated business gets its navigation');
  assert.ok(ui.find('New offer'),'business setup opens offer management immediately');
  assert.ok(ui.find('Offers'));assert.ok(ui.find('Restaurant profile'));
  assert.equal(ui.document.querySelector('[placeholder="Business name"]'),null);
  const request=ui.calls.find(c=>c.name==='save_business_draft');
  assert.equal(request.body.name,'Self-service cafe');assert.equal('role' in request.body,false);assert.equal('actor_id' in request.body,false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('saved active profile survives a session refresh failure and retries without saving twice',async()=>{
 let activated=false,refreshes=0;
 const ui=await app({role:'business',verified:true,intercept(name,body){
  if(name==='get_business_draft')return rpc({ok:true});
  if(name==='save_business_draft'){activated=true;return rpc({...body,ok:true,status:'active',message:'Business profile saved.'});}
  if(name==='current_session'){
   if(activated&&refreshes++===0)throw new Error('Fixture refresh failure');
   return rpc(businessSession(activated?'merchant':'business'));
  }
 }});
 try{
  await completeBusiness(ui);await until(()=>ui.find('Open offer management'),'saved profile has an access refresh retry');
  assert.ok(ui.text().includes('Your business profile was saved'));
  assert.equal(ui.find('New offer'),undefined);
  assert.equal(ui.document.querySelector('[placeholder="Business name"]').value,'Self-service cafe');
  ui.click('Open offer management');await until(()=>ui.find('Insights'));
  ui.click('Offers');await until(()=>ui.find('New offer'));
  assert.equal(ui.calls.filter(c=>c.name==='save_business_draft').length,1);
  assert.equal(refreshes,2);assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('failed business save retains entries and does not enable offer management',async()=>{
 const ui=await app({role:'business',verified:true,intercept(name){
  if(name==='get_business_draft')return rpc({ok:true});
  if(name==='save_business_draft')return rpc({ok:false,message:'Fixture activation failed.',status:'draft'});
 }});
 try{
  await completeBusiness(ui);await until(()=>ui.text().includes('Fixture activation failed.'));
  assert.equal(ui.document.querySelector('[placeholder="Business name"]').value,'Self-service cafe');
  assert.equal(ui.find('Offers'),undefined);assert.equal(ui.find('Open offer management'),undefined);
  assert.equal(ui.calls.filter(c=>c.name==='current_session').length,1,'failure must not request or invent merchant access');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('active save response alone cannot invent merchant authority before session confirmation',async()=>{
 const ui=await app({role:'business',verified:true,intercept(name,body){
  if(name==='get_business_draft')return rpc({ok:true});
  if(name==='save_business_draft')return rpc({...body,ok:true,status:'active',message:'Business profile saved.'});
 }});
 try{
  await completeBusiness(ui);await until(()=>ui.find('Open offer management'));
  assert.equal(ui.find('Offers'),undefined);assert.equal(ui.find('New offer'),undefined);
  assert.equal(ui.calls.some(c=>c.name==='merchant_portal'),false);
  assert.ok(ui.text().includes('Your business profile was saved'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('offer validation blocks invalid prices and confirmed publication appears in the refreshed list',async()=>{
 let posted=null;
 const ui=await app({role:'merchant',intercept(name,body){
  if(name==='save_offer'){posted=offer({id:'new-post',title:body.title,price:Number(body.price)});return rpc({ok:true,message:'Offer published.',code:'new-post'});}
  if(name==='merchant_portal'&&posted)return rpc({ok:true,name:'Fixture Kitchen',cuisine:'Test cuisine',blurb:'Fixture profile',address:'Test address',neighborhood:'Test area',entrance_note:'',note_date:'',offers:[posted],claims:[],is_demo:true,message:''});
  if(name==='home_feed'&&posted)return rpc(home([posted]));
 }});
 try{ui.click("Offers");await until(()=>ui.text().includes("New offer"));
  ui.click('Offers');await until(()=>ui.find('New offer'));ui.click('New offer');
  await until(()=>ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));
  assert.ok(ui.text().includes('Starts (Eastern) *'));
  assert.ok(ui.text().includes('Ends (Eastern) *'));
  assert.ok(ui.text().includes('Times are Ann Arbor local time (Eastern), even when you are traveling.'));
  ui.fill('Lunch bowl for $7','Posted fixture lunch');ui.fill('7.00','7.123');
  ui.click('Publish offer');await until(()=>ui.text().includes('at most two decimal places'));
  assert.equal(ui.calls.some(c=>c.name==='save_offer'),false);
  ui.fill('7.00','7.25');ui.fill('One per student. Dine-in only.','One per student.');ui.click('Publish offer');await until(()=>ui.find('Posted fixture lunch'));
  assert.equal(ui.document.querySelector('[placeholder="Lunch bowl for $7"]'),null);
  assert.equal(ui.calls.filter(c=>c.name==='save_offer').length,1);
  ui.click('Offers');await until(()=>ui.find('Posted fixture lunch'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('rejected offer publication preserves every entered value and remains editable',async()=>{
 const ui=await app({role:'merchant',intercept(name){if(name==='save_offer')return rpc({ok:false,message:'Fixture publication rejected.',code:''});}});
 try{ui.click("Offers");await until(()=>ui.text().includes("New offer"));
  ui.click('Offers');await until(()=>ui.find('New offer'));ui.click('New offer');await until(()=>ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));
  ui.fill('Lunch bowl for $7','Keep this lunch');ui.fill('7.00','6.50');ui.fill('One per student. Dine-in only.','Keep these terms');ui.click('Publish offer');
  await until(()=>ui.text().includes('Fixture publication rejected.'));
  assert.equal(ui.document.querySelector('[placeholder="Lunch bowl for $7"]').value,'Keep this lunch');
  assert.equal(ui.document.querySelector('[placeholder="7.00"]').value,'6.50');
  assert.equal(ui.document.querySelector('[placeholder="One per student. Dine-in only."]').value,'Keep these terms');
  assert.equal(ui.find('Publish offer').disabled,false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('business load failure blocks overwriting a saved application until retry succeeds',async()=>{
 let reads=0;
 const ui=await app({role:'business',verified:true,intercept(name){if(name==='get_business_draft')return rpc(++reads===1?{ok:false,message:'Fixture load failed.'}:{ok:true,name:'Retained cafe',address:'123 Fixture Street',status:'pending_review'});}});
 try{
  await until(()=>ui.text().includes('Fixture load failed.'));
  assert.equal(ui.document.querySelector('[placeholder="Business name"]').disabled,true);
  ui.click('Retry business profile');await until(()=>ui.document.querySelector('[placeholder="Business name"]')?.value==='Retained cafe');
  assert.equal(ui.document.querySelector('[placeholder="Business name"]').disabled,false);
  assert.equal(ui.calls.some(c=>c.name==='save_business_draft'),false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('merchant profile cancellation restores saved details without sending a write',async()=>{
 const ui=await app({role:'merchant'});
 try{ui.click("Offers");await until(()=>ui.text().includes("New offer"));
  ui.click('Offers');await until(()=>ui.find('Edit business details'));
  assert.equal(ui.document.querySelector('[placeholder="Restaurant name"]'),null,'the default Manage screen focuses on offers');
  ui.click('Edit business details');await until(()=>ui.document.querySelector('[placeholder="Restaurant name"]')?.value==='Fixture Kitchen');
  ui.fill('Restaurant name','Unsaved name');ui.click('Cancel profile changes');
  await until(()=>ui.find('Edit business details'));
  ui.click('Edit business details');
  await until(()=>ui.document.querySelector('[placeholder="Restaurant name"]')?.value==='Fixture Kitchen');
  assert.equal(ui.calls.some(c=>c.name==='update_profile'),false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('a configured merchant with a student inbox keeps routine editing without business signup',async()=>{
 const ui=await app({role:'merchant',verified:true,intercept(name){
  if(name==='current_session')return rpc({authenticated:true,actor_id:'fixture-student-merchant',role:'merchant',restaurant_id:'fixture-restaurant',display_name:'Fixture operator',email_verified:true,is_demo:false,business_account:false});
 }});
 try{
  ui.click('Offers');await until(()=>ui.find('New offer'));
  ui.click('Edit business details');await until(()=>ui.document.querySelector('[placeholder="Restaurant name"]'));
  assert.equal(ui.document.querySelector('[placeholder="Restaurant name"]').readOnly,true);
  assert.equal(ui.document.querySelector('[placeholder="Street address"]').readOnly,true);
  assert.equal(ui.document.querySelector('[placeholder="Noodles"]').readOnly,false);
  assert.equal(ui.calls.some(c=>c.name==='get_business_draft'),false);
  ui.fill('Noodles','Updated fixture cuisine');ui.click('Save profile');
  await until(()=>ui.calls.some(c=>c.name==='update_profile'));
  assert.equal(ui.calls.find(c=>c.name==='update_profile').body.cuisine,'Updated fixture cuisine');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('editing an offer keeps absent regular price optional and uses save changes',async()=>{
 const ui=await app({role:'merchant',item:offer({regular_price:0,state:'paused'})});
 try{ui.click("Offers");await until(()=>ui.text().includes("New offer"));
  ui.click('Offers');await until(()=>ui.find('Edit'));ui.click('Edit');await until(()=>ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));
  assert.equal(ui.document.querySelector('[placeholder="11.50"]').value,'');
  assert.equal(ui.find('Publish offer'),undefined);
  ui.fill('Lunch bowl for $7','Updated paused lunch');ui.click('Save changes');await until(()=>ui.text().includes('Fixture offer saved'));
  assert.equal(ui.calls.find(c=>c.name==='save_offer').body.offer_id,'fixture-offer');
  assert.equal(ui.calls.find(c=>c.name==='save_offer').body.regular_price,'');
  assert.equal(ui.calls.some(c=>c.name==='set_offer_status'),false);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('unsaved offer details survive moving between Redeem and Manage',async()=>{
 const ui=await app({role:'merchant'});
 try{ui.click("Offers");await until(()=>ui.text().includes("New offer"));
  ui.click('Offers');await until(()=>ui.find('New offer'));ui.click('New offer');await until(()=>ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));
  ui.fill('Lunch bowl for $7','Retain this draft');ui.fill('7.00','6.75');ui.fill('One per student. Dine-in only.','Keep draft terms');
  assert.equal(ui.find('Nearby')===undefined,true,'restaurants do not get the student feed');
  ui.click('Scan QR');await until(()=>!ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));
  ui.click('Offers');await until(()=>ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));
  assert.equal(ui.document.querySelector('[placeholder="Lunch bowl for $7"]').value,'Retain this draft');
  assert.equal(ui.document.querySelector('[placeholder="7.00"]').value,'6.75');
  assert.equal(ui.document.querySelector('[placeholder="One per student. Dine-in only."]').value,'Keep draft terms');
  assert.equal(ui.calls.some(c=>c.name==='save_offer'),false);assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('pending publication blocks navigation and repeat submission until confirmed',async()=>{
 let release;const pending=new Promise(resolve=>{release=resolve;});
 const ui=await app({role:'merchant',intercept:async(name)=>{if(name==='save_offer'){await pending;return rpc({ok:true,message:'Deferred publication complete.',code:'new-post'});}}});
 try{ui.click("Offers");await until(()=>ui.text().includes("New offer"));
  ui.click('Offers');await until(()=>ui.find('New offer'));ui.click('New offer');await until(()=>ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));
  ui.fill('Lunch bowl for $7','Publish only once');ui.fill('7.00','6.75');ui.fill('One per student. Dine-in only.','One per student.');ui.click('Publish offer');
  await until(()=>ui.calls.some(c=>c.name==='save_offer'));
  ui.click('Scan QR');ui.click('Saving...');
  assert.ok(ui.document.querySelector('[placeholder="Lunch bowl for $7"]'),'keep the composer mounted while the write is pending');
  assert.equal(ui.calls.filter(c=>c.name==='save_offer').length,1);
  release();await until(()=>ui.text().includes('Deferred publication complete.'));
  assert.equal(ui.document.querySelector('[placeholder="Lunch bowl for $7"]'),null);
  assert.equal(ui.calls.filter(c=>c.name==='save_offer').length,1);assert.deepEqual(ui.errors,[]);
 }finally{release();ui.close();}
});

test('merchant profile fields prevent newer edits being overwritten by a pending save',async()=>{
 let release;const pending=new Promise(resolve=>{release=resolve;});
 const ui=await app({role:'merchant',intercept:async(name)=>{if(name==='update_profile')await pending;}});
 try{ui.click("Offers");await until(()=>ui.text().includes("New offer"));
  ui.click('Offers');await until(()=>ui.find('Edit business details'));
  ui.click('Edit business details');await until(()=>ui.document.querySelector('[placeholder="Restaurant name"]'));
  assert.equal(ui.document.querySelector('[placeholder="Restaurant name"]').readOnly,true);
  assert.equal(ui.document.querySelector('[placeholder="Street address"]').readOnly,true);
  ui.fill('Noodles','Submitted cuisine');ui.click('Save profile');await until(()=>ui.calls.some(c=>c.name==='update_profile'));
  const inputs=[...ui.document.querySelectorAll('[placeholder="Restaurant name"],[placeholder="Noodles"],[placeholder="Short description"],[placeholder="Street address"],[placeholder="Kerrytown"],[placeholder="Use the side door while sidewalk work continues"],[placeholder="2026-09-26"]')];
  assert.equal(inputs.length,7);assert.ok(inputs.every(input=>input.readOnly),'the submitted profile must stay unchanged until its response arrives');
  release();await until(()=>ui.find('Edit business details'));
  assert.deepEqual(ui.errors,[]);
 }finally{release();ui.close();}
});
