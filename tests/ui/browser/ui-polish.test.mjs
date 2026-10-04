import test from 'node:test';
import assert from 'node:assert/strict';
import {app,rpc,until} from './harness.mjs';

test('business setup keeps optional photo and menu fields out of the required path',async()=>{
 const ui=await app({role:'business',verified:true,intercept(name){
  if(name==='get_business_draft')return rpc({ok:true,name:'Fixture Cafe',address:'123 Fixture Street'});
  if(name==='save_business_draft')return rpc({ok:false,message:'Fixture save retained.'});
 }});
 try{
  await until(()=>ui.document.querySelector('[placeholder="Business name"]')?.value==='Fixture Cafe');
  const extras=ui.document.querySelector('details');
  assert.ok(extras,'optional details have an explicit disclosure');
  assert.equal(extras.open,false);
  assert.equal(extras.querySelector('summary').textContent,'Photo and menu (optional)');
  assert.equal(extras.querySelectorAll('[required]').length,0);
  assert.equal(ui.document.querySelector('[placeholder="Business name"]').closest('details'),null);
  assert.equal(ui.document.querySelector('[placeholder="Street address"]').closest('details'),null);
  extras.open=true;
  ui.fill('https://your-business.com/photo.jpg','https://example.test/photo.jpg');
  ui.fill('Menu items and prices','Soup $8');
  extras.open=false;
  ui.document.querySelector('input[type="checkbox"]').click();
  ui.click('Save business profile');await until(()=>ui.text().includes('Fixture save retained.'));
  const request=ui.calls.find(call=>call.name==='save_business_draft');
  assert.equal(request.body.image_url,'https://example.test/photo.jpg');
  assert.equal(request.body.menu_text,'Soup $8');
  ui.fill('https://your-business.com/photo.jpg','invalid link');
  ui.document.querySelector('[placeholder="https://your-business.com/photo.jpg"]').dispatchEvent(new ui.window.Event('invalid'));
  assert.equal(ui.document.querySelector('details').open,true,'invalid optional fields reopen so the browser can focus them');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('offer dietary choices use checkboxes and save the existing dietary contract',async()=>{
 const ui=await app({role:'merchant'});
 try{
  ui.click('Manage');await until(()=>ui.find('New offer'));
  ui.click('New offer');await until(()=>ui.document.querySelector('[placeholder="Lunch bowl for $7"]'));
  const extras=ui.document.querySelector('details');
  assert.ok(extras);
  assert.equal(extras.open,false);
  extras.open=true;
  const vegan=ui.document.querySelector('input[aria-label="Vegan"]');
  assert.ok(vegan);vegan.click();await until(()=>vegan.checked);
  assert.equal(ui.document.querySelector('[placeholder="vegetarian, vegan, gluten-free, halal"]'),null);
  ui.fill('Lunch bowl for $7','Vegan lunch');ui.fill('7.00','7');
  ui.fill('One per student. Dine-in only.','One per student.');
  ui.click('Publish offer');await until(()=>ui.calls.some(call=>call.name==='save_offer'));
  assert.equal(ui.calls.find(call=>call.name==='save_offer').body.dietary,'vegan');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
