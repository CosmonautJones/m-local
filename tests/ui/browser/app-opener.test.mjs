import test from 'node:test';
import assert from 'node:assert/strict';
import {app, until} from './harness.mjs';

const opener = ui => ui.document.querySelector('[data-testid="app-opener"]');

test('opener plays over the app on first open and removes itself when finished', async () => {
  const ui = await app({role:'student'});
  try {
    assert.ok(opener(ui), 'opener is shown on first open');
    assert.ok(opener(ui).querySelector('img[src="/static/assets/brand/m-mark-maize.png"]'));
    assert.ok(opener(ui).querySelector('img[src="/static/assets/brand/local-word-white.png"]'));
    await until(() => !opener(ui), 'opener finishes', 9000);
    assert.deepEqual(ui.errors, []);
  } finally {ui.close();}
});

test('tapping the opener skips it', async () => {
  const ui = await app({role:'student'});
  try {
    opener(ui).dispatchEvent(new ui.window.MouseEvent('click', {bubbles:true}));
    await until(() => !opener(ui), 'opener skipped', 1500);
  } finally {ui.close();}
});

test('Escape skips the opener', async () => {
  const ui = await app({role:'student'});
  try {
    ui.window.dispatchEvent(new ui.window.KeyboardEvent('keydown', {key:'Escape'}));
    await until(() => !opener(ui), 'opener skipped by Escape', 1500);
  } finally {ui.close();}
});

test('opener replays on every page load, including refreshes in the same tab', async () => {
  const ui = await app({role:'student', configureWindow(w) {w.sessionStorage.setItem('mlocal_opener_seen', '1');}});
  try {
    assert.ok(opener(ui), 'a refresh plays the opener again');
  } finally {ui.close();}
});

test('opener is skipped for reduced motion', async () => {
  const ui = await app({role:'student', configureWindow(w) {
    w.matchMedia = q => ({matches:q.includes('reduce'), addListener(){}, removeListener(){}, addEventListener(){}, removeEventListener(){}});
  }});
  try {
    assert.equal(opener(ui), null);
  } finally {ui.close();}
});
