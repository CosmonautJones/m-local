import test from 'node:test';
import assert from 'node:assert/strict';
import {app,held,until} from './harness.mjs';

test('saved QR scrolls within a viewport that reserves the navigation row', async () => {
 const ui=await app({verified:true,item:held()});
 try {
  ui.click('Show QR for Saved bowl');
  await until(()=>ui.document.querySelector('[data-testid="claim-qr"]'));
  const navigation=ui.document.querySelector('[data-testid="app-tabbar"]');
  const style=ui.window.getComputedStyle(navigation);
  assert.equal(style.position,'relative','navigation must occupy layout space instead of covering the saved QR');
  assert.equal(style.flexShrink,'0','navigation must retain its own row when offer content scrolls');
  assert.equal(navigation.previousElementSibling.style.minHeight,'0px','the offer scroll viewport must shrink above navigation');
  assert.deepEqual(ui.errors,[]);
 } finally {ui.close();}
});
