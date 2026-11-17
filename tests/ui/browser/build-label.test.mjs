import test from 'node:test';
import assert from 'node:assert/strict';
import {app, until} from './harness.mjs';

const stamp = {source_revision: '5865c31aa0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5', runtime_version: '0.37.23', project_version: '0.1.0'};

test('the welcome screen shows which build is live', async()=>{
 const ui = await app({role: 'guest', audience: '', item: {title: 'Welcome to M-Local'},
  intercept(name){ if(name === 'mlocal-build.json') return Response.json(stamp); }});
 try{
  await until(()=>ui.text().includes('M-Local v0.1.0 · 5865c31'));
  assert.equal(ui.document.querySelector('[data-testid="build-label"]').getAttribute('title'), 'Build ' + stamp.source_revision + ', Jac 0.37.23');
  assert.deepEqual(ui.errors, []);
 }finally{ui.close();}
});

test('without a deploy stamp the label stays hidden', async()=>{
 const ui = await app({role: 'guest', audience: '', item: {title: 'Welcome to M-Local'},
  intercept(name){ if(name === 'mlocal-build.json') return new Response('not found', {status: 404}); }});
 try{
  await until(()=>ui.text().includes('Welcome to M-Local'));
  assert.equal(ui.document.querySelector('[data-testid="build-label"]'), null);
 }finally{ui.close();}
});
