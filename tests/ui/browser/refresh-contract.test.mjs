import {openSignIn} from './harness.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {app, until, setMaximumPrice} from './harness.mjs';

test('signed-out authentication hides app data and never requests merchant authority', async()=>{
 for(const audience of ['student','business']){
  const ui=await app({role:'guest',audience});
  try{
  await openSignIn(ui,audience);
   assert.equal(ui.find('Keep browsing'),undefined);
   assert.equal(ui.find('Current bowl'),undefined);
   assert.equal(ui.document.querySelector('[data-testid=app-tabbar]'),null);
   assert.equal(ui.calls.some(c=>['merchant_portal','merchant_insights'].includes(c.name)),false);
   assert.equal(ui.calls.some(c=>c.name==='home_feed'),audience==='student');
   ui.click('Back');await until(()=>ui.find(audience==='student'?'Current bowl':'Find local deals'));
   assert.equal(!!ui.find('Current bowl'),audience==='student');
   assert.deepEqual(ui.errors,[]);
  }finally{ui.close();}
 }
});

test('maximum price stays consistent when opening and refreshing an offer',async()=>{
 const ui=await app({verified:true});
 try{
  await setMaximumPrice(ui,8);
  await until(()=>ui.calls.some(c=>c.name==='home_feed'&&c.body.price_range==='0-8'));
  ui.click('Current bowl');await until(()=>ui.find('Refresh offer and claim'));
  assert.equal(ui.calls.filter(c=>c.name==='get_offer').at(-1).body.max_price,'8');
  ui.click('Refresh offer and claim');
  await until(()=>ui.calls.filter(c=>c.name==='get_offer').length===2);
  assert.equal(ui.calls.filter(c=>c.name==='get_offer').at(-1).body.max_price,'8');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('closing the filters discards draft edits and keeps focus on the trigger',async()=>{
 const ui=await app({verified:true});
 try{
  await setMaximumPrice(ui,8);
  const trigger=ui.document.querySelector('.ml-filters button[aria-expanded]');
  trigger.click();await until(()=>ui.document.querySelector('input[type="range"]'));
  const slider=ui.document.querySelector('input[type="range"]');
  Object.getOwnPropertyDescriptor(ui.window.HTMLInputElement.prototype,'value').set.call(slider,'4');
  slider.dispatchEvent(new ui.window.Event('input',{bubbles:true}));
  await until(()=>ui.document.querySelector('output').textContent==='$4 or less');
  slider.dispatchEvent(new ui.window.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  await until(()=>trigger.getAttribute('aria-expanded')==='false');
  assert.equal(ui.document.activeElement,trigger);
  trigger.click();await until(()=>ui.document.querySelector('input[type="range"]'));
  assert.equal(ui.document.querySelector('input[type="range"]').value,'8');
  assert.equal(ui.calls.filter(c=>c.name==='home_feed').at(-1).body.price_range,'0-8');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('filter dropdown applies an actual maximum price, time and diet, then clears them',async()=>{
 const ui=await app({verified:true});
 try{
  const trigger=()=>ui.document.querySelector('.ml-filters button[aria-expanded]');
  assert.ok(trigger(),'the filter dropdown replaces the old chip rows');
  assert.equal(ui.document.querySelector('[aria-label="Maximum price"]'),null,'collapsed by default');
  trigger().click();
  await until(()=>ui.document.querySelector('[aria-label="Maximum price"]'));
  assert.equal(ui.document.querySelector('[aria-label="Minimum price"]'),null,'v2 uses a maximum-price slider');
  const slider=ui.document.querySelector('[aria-label="Maximum price"]');
  Object.getOwnPropertyDescriptor(ui.window.HTMLInputElement.prototype,'value').set.call(slider,'8');
  slider.dispatchEvent(new ui.window.Event('input',{bubbles:true}));
  const option=text=>[...ui.document.querySelectorAll('.ml-filter-option')].find(n=>n.textContent===text).querySelector('input');
  option('Right now').click();
  await until(()=>option('Right now').checked);
  option('Vegan').click();
  await until(()=>option('Vegan').checked);
  ui.click('Show deals');
  await until(()=>ui.calls.some(c=>c.name==='home_feed'&&c.body.price_range==='0-8'));
  assert.deepEqual(ui.calls.filter(c=>c.name==='home_feed').at(-1).body,{price_range:'0-8',window:'now',diets:'vegan'});
  assert.equal(ui.document.querySelector('[aria-label="Maximum price"]'),null);
  trigger().click();await until(()=>ui.find('Clear all'));ui.click('Clear all');
  await until(()=>ui.calls.filter(c=>c.name==='home_feed').at(-1).body.price_range==='');
  assert.deepEqual(ui.calls.filter(c=>c.name==='home_feed').at(-1).body,{price_range:'',window:'any',diets:''});
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('feed header keeps refresh and logout, drops the duplicate brand line, and counts one deal correctly',async()=>{
 const ui=await app({verified:true});
 try{
  await until(()=>ui.find('Current bowl'));
  await until(()=>ui.text().includes('Showing 1 deal.'));
  assert.equal(ui.text().includes('1 deals'),false);
  assert.equal(ui.text().includes('M-LOCAL · ANN ARBOR'),false);
  assert.ok(ui.find('Refresh offers'));
  assert.ok(ui.find('Log out'));
  assert.ok(ui.document.querySelector('[data-testid="app-masthead"]').contains(ui.find('Log out')),'logout is beside the logo');
  assert.ok(ui.document.querySelector('.ml-feed-toolbar').contains(ui.find('Refresh offers')),'refresh is beside compact filters');
  const tab=ui.find('Offers')?.closest('[role=button]');
  assert.ok(tab,'the Offers tab is rendered');
  assert.equal(ui.window.getComputedStyle(tab).borderTopLeftRadius,'0px','selected tab indicator is a straight bar, not an arc');
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
