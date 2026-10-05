import test from 'node:test';
import assert from 'node:assert/strict';
import {app,until} from './harness.mjs';

test('signed-out visits ignore an old path and keep both account choices available',async()=>{
 for(const audience of ['student','business']){
  const ui=await app({role:'guest',audience});
  try{
   assert.ok(ui.find('Find local deals'));
   assert.ok(ui.find('List my business'));
   assert.equal(ui.text().includes('New here or coming back?'),false);
   assert.equal(ui.text().includes('remember it on this browser'),false);
   assert.equal(ui.calls.some(c=>c.name==='home_feed'),false);
   ui.click('Find local deals');await until(()=>ui.document.querySelector('[placeholder="uniqname"]'));
   ui.click('Back');await until(()=>ui.find('List my business'));
   ui.click('List my business');await until(()=>ui.document.querySelector('[type="email"]'));
   assert.equal(ui.document.querySelector('[placeholder="uniqname"]'),null);
   assert.equal(ui.window.localStorage.getItem('jac_token'),null);
   assert.deepEqual(ui.errors,[]);
  }finally{ui.close();}
 }
});

test('valid sessions stay signed in, then logout returns every role to the shared welcome screen',async()=>{
 for(const role of ['student','business','merchant']){
  const ui=await app({role,verified:true,audience:role==='student'?'business':'student'});
  try{
   assert.equal(ui.find('Find local deals'),undefined);
   assert.ok(ui.find('Log out'));
   assert.equal(ui.window.localStorage.getItem('jac_token'),'synthetic-ui-token');
   ui.click('Log out');await until(()=>ui.find('Find local deals'));
   assert.ok(ui.find('List my business'));
   assert.equal(ui.document.querySelector('[data-testid="app-tabbar"]'),null);
   assert.equal(ui.window.localStorage.getItem('jac_token'),null);
   assert.deepEqual(ui.errors,[]);
  }finally{ui.close();}
 }
});

test('business bottom navigation uses the requested main labels without subtitles',async()=>{
 const ui=await app({role:'merchant',verified:true});
 try{
  const buttons=[...ui.document.querySelectorAll('[data-testid="app-tabbar"] button')];
  assert.deepEqual(buttons.map(button=>[...button.children].filter(child=>child.tagName!=='svg').map(child=>child.textContent)),[
   ['Offers'],['Scan QR'],['Insights'],['Account']
  ]);
 }finally{ui.close();}
});
