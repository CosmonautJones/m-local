import test from 'node:test';
import assert from 'node:assert/strict';
import {app} from './harness.mjs';

test('the running app identifies M-Local with public metadata and install links',async()=>{
 const ui=await app();
 try{
  assert.equal(ui.document.title,'M-Local');
  assert.match(ui.document.querySelector('meta[name="description"]')?.content||'',/Ann Arbor/);
  assert.equal(ui.document.querySelector('link[rel="icon"]')?.getAttribute('href'),'/static/assets/brand/app-icon.svg');
  assert.equal(ui.document.querySelector('link[rel="manifest"]')?.getAttribute('href'),'/static/assets/manifest.webmanifest');
  assert.equal(ui.document.querySelector('meta[name="theme-color"]')?.content,'#02305C');
  assert.equal(ui.window.navigator.serviceWorker,undefined,'app metadata does not introduce private-response caching');
 }finally{ui.close();}
});
