import test from 'node:test';
import assert from 'node:assert/strict';
import {app,offer,until} from './harness.mjs';

const logo = 'https://example.com/logo.png';
const food = 'https://example.com/bowl.jpg';

function following(node, other) {
  return Boolean(node.compareDocumentPosition(other) & node.ownerDocument.defaultView.Node.DOCUMENT_POSITION_FOLLOWING);
}

test('deal and detail use the offer photo separately from business identity, and no photo draws nothing', async () => {
  const shown = await app({item: offer({image_url: logo,offer_image_url: food})});
  try {
    const deal = shown.document.querySelector('img[alt="Current bowl"]');
    assert.equal(deal?.getAttribute('src'), food);
    assert.equal(deal.style.height, '184px');
    assert.equal(deal.style.width, '100%');
    assert.equal(deal.style.objectFit, 'cover');
    assert.equal(deal.getAttribute('referrerpolicy') || deal.referrerPolicy, 'no-referrer');
    assert.ok(following(deal, shown.find('Fixture Kitchen')));
    shown.click('Current bowl');
    await until(() => shown.text().includes('Claim this offer'));
    const detail = shown.document.querySelector('img[alt="Current bowl"]');
    assert.equal(detail.style.height, '220px');
    assert.ok(following(detail, shown.find('Current bowl')));
    assert.deepEqual(shown.errors, []);
  } finally { shown.close(); }

  const blank = await app({item: offer({image_url: ''})});
  try {
    assert.equal(blank.document.querySelector('img[alt="Current bowl"]'), null);
    blank.click('Current bowl');
    await until(() => blank.text().includes('Claim this offer'));
    assert.equal(blank.document.querySelector('img[alt="Current bowl"]'), null);
    assert.deepEqual(blank.errors, []);
  } finally { blank.close(); }
});

test('merchant profile shows the logo beside the restaurant name', async () => {
  const ui = await app({role: 'merchant', item: offer({image_url: logo})});
  try {
    ui.click('Offers');
    await until(() => ui.text().includes('Restaurant profile'));
    const mark = ui.document.querySelector('img[alt="Fixture Kitchen"]');
    assert.equal(mark?.getAttribute('src'), logo);
    assert.equal(mark.style.width, '64px');
    assert.equal(mark.style.height, '64px');
    assert.ok(following(mark, ui.find('Fixture Kitchen')));
    assert.deepEqual(ui.errors, []);
  } finally { ui.close(); }
});

test('offer screen renders current, stale, and missing access context', async () => {
  const current = await app({item: offer({
    access_context: {state: 'current', notices: [{id: 'n1', state: 'current', entrance_instruction: 'Use the alley door.', summary: 'Alley summary'}]},
  })});
  try {
    current.click('Current bowl');
    await until(() => current.text().includes('Current access'));
    assert.ok(current.text().includes('Use the alley door.'));
    assert.deepEqual(current.errors, []);
  } finally { current.close(); }

  const stale = await app({item: offer({access_context: {state: 'needs_recheck', notices: []}})});
  try {
    stale.click('Current bowl');
    await until(() => stale.text().includes('Access needs a recheck'));
    assert.ok(stale.text().includes('The last access note for this place is stale. Confirm the entrance with the restaurant.'));
    assert.deepEqual(stale.errors, []);
  } finally { stale.close(); }

  const none = await app({item: offer({access_context: {state: 'none', notices: []}})});
  try {
    none.click('Current bowl');
    await until(() => none.text().includes('No reviewed access information for this place.'));
    assert.equal(none.text().includes('Current access'), false);
    assert.equal(none.text().includes('Access needs a recheck'), false);
    assert.deepEqual(none.errors, []);
  } finally { none.close(); }
});
