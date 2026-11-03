import test from 'node:test';
import assert from 'node:assert/strict';
import {app, until} from './harness.mjs';

test('privacy and terms open from the address, link to each other and return to the app', async()=>{
 const ui = await app({role: 'guest', audience: '', item: {title: 'Privacy Policy'},
  configureWindow(w){ w.history.replaceState(null, '', '/#privacy'); }});
 try{
  await until(()=>ui.text().includes('Privacy Policy') && ui.text().includes('Who we share it with'));
  assert.ok(ui.text().includes('not affiliated with or endorsed by the University of Michigan'));
  assert.ok(ui.text().includes('Last updated'));
  ui.window.location.hash = '#terms';
  ui.window.dispatchEvent(new ui.window.Event('hashchange'));
  await until(()=>ui.text().includes('Terms of Use') && ui.text().includes('How deals work'));
  ui.click('Back to M-Local');
  await until(()=>ui.text().includes('Welcome to M-Local'));
  assert.equal(ui.window.location.hash, '');
  const links = [...ui.document.querySelectorAll('a')].map(a=>a.getAttribute('href'));
  assert.ok(links.includes('/#terms') && links.includes('/#privacy'), 'the welcome screen links both pages');
  assert.deepEqual(ui.errors, []);
 }finally{ui.close();}
});

test('the sign-in form states the agreement next to the button and opens the pages in a new tab', async()=>{
 const {openSignIn} = await import('./harness.mjs');
 const ui = await app({role: 'guest'});
 try{
  await openSignIn(ui, 'student');
  await until(()=>ui.text().includes('By continuing you agree to the'));
  const terms = [...ui.document.querySelectorAll('a')].find(a=>a.textContent === 'Terms of Use');
  assert.equal(terms.getAttribute('target'), '_blank');
  assert.equal(terms.getAttribute('href'), '/#terms');
 }finally{ui.close();}
});
