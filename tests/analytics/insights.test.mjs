import test from 'node:test';
import assert from 'node:assert/strict';
import {METRIC_KEYS, SALES_KEYS, salesSummary, salesChart, salesPeak, normalizeInsights, selectCutoff, chartSeries, resolvedRate, createRequestGate, recapPayload, buildRecapHtml} from '../../client/insights-support.mjs';

export function fixture() {
  const zero = () => Object.fromEntries(METRIC_KEYS.map(key => [key, 0]));
  const frames = [];
  for (let day = 0; day <= 7; day++) {
    const totals = {...zero(), claims: day * 2, redemptions: day, unique_customers: Math.min(day, 2), returning_customers: day > 2 ? 1 : 0, value_cents: day * 600, savings_cents: day * 200, savings_known: day, cohort_redeemed: day, expired: day, actor_id: 'SECRET-METRIC-ACCOUNT'};
    const daily = {...zero(), claims: day ? 2 : 0, redemptions: day ? 1 : 0};
    frames.push({day, date: `2026-09-${String(day + 20).padStart(2,'0')}`, totals, daily, offers: day ? [{id:'SECRET-OFFER-ID',title: day > 3 ? 'Later offer title' : 'Earlier offer title', redemptions: day, value_cents:day * 600, customer_email:'SECRET-OFFER-EMAIL'}] : [], actor_id:'SECRET-FRAME-ACCOUNT'});
  }
  return {ok:true, business_name:'Fixture café', is_demo:true, period_days:7, timezone:'America/Detroit',start_date:'2026-09-21',end_date:'2026-09-27',as_of:1790553600,coverage_start_date:'2026-09-21',warnings:[],frames,totals:frames.at(-1).totals, offers:frames.at(-1).offers, actor_id:'SECRET-ROOT-ACCOUNT',qr_token:'SECRET-QR-TOKEN', emails:['SECRET-EMAIL']};
}

test('historical cutoff controls every metric, offer, story and chart scale', () => {
  const data = normalizeInsights(fixture(), 7), zero = selectCutoff(data, 0), earlier = selectCutoff(data, 2);
  assert.equal(zero.frame.totals.claims, 0);
  assert.equal(zero.top, null);
  assert.equal(zero.busiest, null);
  assert.equal(earlier.frame.totals.redemptions, 2);
  assert.equal(earlier.top.title, 'Earlier offer title');
  assert.equal(earlier.history.length, 3);
  assert.equal(earlier.busiest.date, '2026-09-21');
  assert.equal(chartSeries(data, 2).maximum, 2);
  assert.equal(chartSeries(data, 2, 'daily').maximum, 1);
  assert.equal(selectCutoff(data, 999).index, 7);
  assert.equal(selectCutoff(data, -4).index, 0);
});

test('resolved claim rate excludes pending, unknown, and carried-over redemptions', () => {
  assert.deepEqual(resolvedRate({cohort_redeemed:3,cancelled:1,expired:2,pending:20,unknown_outcomes:30,redemptions:50}),{denominator:6,percent:50});
  assert.deepEqual(resolvedRate({cohort_redeemed:0,cancelled:0,expired:0,pending:3}),{denominator:0,percent:null});
});

test('normalization rejects malformed metrics, wrong range and missing chronology', () => {
  assert.throws(() => normalizeInsights(fixture(), 30), /different period/);
  const wrong = fixture(); wrong.frames[4].totals.redemptions = -1;
  assert.throws(() => normalizeInsights(wrong), /invalid total/);
  const gap = fixture(); gap.frames[4].date = gap.frames[3].date;
  assert.throws(() => normalizeInsights(gap), /missing date/);
  const baseline = fixture(); baseline.frames[0].totals.claims = 1;
  assert.throws(() => normalizeInsights(baseline), /zero baseline/);
  const impossible = fixture(); impossible.frames[4].date = '2026-02-31';
  assert.throws(() => normalizeInsights(impossible), /invalid date/);
  const invalidExport = fixture(); invalidExport.period_days = '<script>unsafe</script>';
  assert.throws(() => buildRecapHtml(invalidExport), /different period/);
  const invalidDay = fixture(); invalidDay.frames[2].day = {secret: 'PRIVATE'};
  assert.throws(() => buildRecapHtml(invalidDay), /out of order/);
  assert.throws(() => normalizeInsights({ok:false,message:'Access denied.'}), /Access denied/);
});

test('recap omits pending and unknown history rows', () => {
  const html = buildRecapHtml(normalizeInsights(fixture()));
  assert.match(html, /Claim outcomes/);
  assert.doesNotMatch(html, />\\d+ pending/);
  assert.doesNotMatch(html, />\\d+ unknown/);
});

test('presentation can hide the visible provenance label without losing metadata', () => {
  const clean = normalizeInsights({...fixture(), is_demo: true});
  assert.match(buildRecapHtml(clean), /Demo business/);
  assert.doesNotMatch(buildRecapHtml(clean, false), /Demo business/);
  assert.equal(recapPayload(clean).is_demo, true);
});

test('normalization and export exclude unknown fields at every level', () => {
  const raw = fixture();
  raw.warnings = ['SECRET-PRIVATE-WARNING'];
  const clean = normalizeInsights(raw), exported = recapPayload({...clean,actor_id:'SECRET-REINTRODUCED'});
  const serialized = JSON.stringify(exported), html = buildRecapHtml({...clean, qr_token:'SECRET-REINTRODUCED-QR'});
  assert.equal(exported.has_coverage_warnings, true);
  assert.doesNotMatch(serialized, /SECRET|actor_id|qr_token|customer_email/);
  assert.doesNotMatch(html, /SECRET|actor_id|qr_token|customer_email/);
  assert.equal(exported.frames[1].offers[0].title, 'Earlier offer title');
  assert.equal(Object.keys(exported.frames[1].offers[0]).length, 3);
});

test('hostile source strings remain text in the standalone recap', () => {
  const raw = fixture();
  raw.business_name = '</title><img src=x onerror="window.PWNED=1">';
  raw.frames[7].offers[0].title = '</script><script>window.PWNED=2</script>';
  const html = buildRecapHtml(normalizeInsights(raw));
  assert.doesNotMatch(html, /<img src=x|<script>window.PWNED/);
  assert.match(html, /&lt;\/title&gt;/);
  assert.match(html, /\\u003c\/script>/);
  assert.doesNotMatch(html, /(?:src|href)=["']https?:/);
});

test('out-of-order responses, replay, range switches and unmount invalidate old requests', () => {
  const gate = createRequestGate(), old = gate.begin(), current = gate.begin();
  assert.equal(gate.accepts(old), false);
  assert.equal(gate.accepts(current), true);
  gate.invalidate();
  assert.equal(gate.accepts(current), false);
  const refreshed = gate.begin();
  assert.equal(gate.accepts(refreshed), true);
  gate.invalidate();
  assert.equal(gate.accepts(refreshed), false);
});

const names = {morning:'Morning', lunch:'Lunch', dinner:'Dinner', late:'Late night'};
export function sales(source = fixture()) {
  const none = () => ({redemptions: 0, value_cents: 0, discount_cents: 0, discount_known: 0});
  const days = source.frames.slice(1).map((frame, index) => {
    const lunch = {redemptions: index % 2 ? 2 : 1, value_cents: index % 2 ? 1000 : 500, discount_cents: index % 2 ? 600 : 300, discount_known: index % 2 ? 2 : 1};
    const late = index === 3 ? {redemptions: 1, value_cents: 300, discount_cents: 0, discount_known: 0} : none();
    return {date: frame.date, morning: none(), lunch, dinner: none(), late,
      total: {redemptions: lunch.redemptions + late.redemptions, value_cents: lunch.value_cents + late.value_cents, discount_cents: lunch.discount_cents, discount_known: lunch.discount_known}, actor_id: 'SECRET-PERSON'};
  });
  return {blocks: SALES_KEYS.map(key => ({key, label: names[key], hours: 'Fixture hours'})), days,
    offers: [{id: 'SECRET-OFFER-ID', title: 'Lunch bowl', schedule: 'Sep 27, 11 AM to 2 PM', claims: 12, redemptions: 10, value_cents: 5000, busiest: 'Lunch', customer_email: 'secret@example.test',
      blocks: SALES_KEYS.map(key => ({key, label: names[key], claims: key === 'lunch' ? 12 : 0, redemptions: key === 'lunch' ? 10 : 0, value_cents: key === 'lunch' ? 5000 : 0}))}]};
}

test('sales pass through with only known fields, and are optional', () => {
  assert.equal(normalizeInsights(fixture(), 7).sales, null);
  const data = normalizeInsights({...fixture(), sales: sales()}, 7);
  assert.deepEqual(data.sales.blocks.map(block => block.key), SALES_KEYS);
  assert.equal(data.sales.days.length, 7);
  assert.deepEqual(Object.keys(data.sales.days[0]).sort(), ['date','dinner','late','lunch','morning','total']);
  assert.deepEqual(Object.keys(data.sales.offers[0]).sort(), ['blocks','busiest','claims','redemptions','schedule','title','value_cents']);
  assert.equal(JSON.stringify(data.sales).includes('SECRET'), false);
  assert.equal(JSON.stringify(data.sales).includes('secret@'), false);
});

test('sales reject malformed, misdated and non-adding summaries', () => {
  const frames = normalizeInsights(fixture(), 7).frames;
  const broken = [
    summary => { summary.blocks.reverse(); },
    summary => { summary.days.pop(); },
    summary => { summary.days[0].date = '2020-01-01'; },
    summary => { summary.days[1].lunch.value_cents = -1; },
    summary => { summary.days[2].total.value_cents += 1; },
    summary => { summary.days[2].total.redemptions += 1; },
    summary => { summary.days[3].late.redemptions = 1.5; },
    summary => { summary.days[1].lunch.discount_cents = -5; },
    summary => { summary.days[1].total.discount_cents += 1; },
    summary => { summary.days[0].lunch.discount_known = 9; summary.days[0].total.discount_known = 9; },
    summary => { summary.days[3].late.discount_cents = 50; summary.days[3].total.discount_cents += 50; },
    summary => { summary.offers[0].redemptions = '3'; },
    summary => { summary.offers[0].blocks = summary.offers[0].blocks.slice(1); },
    summary => { delete summary.offers; },
  ];
  for (const damage of broken) {
    const summary = sales();
    damage(summary);
    assert.throws(() => salesSummary(summary, frames));
  }
  assert.equal(salesSummary(undefined, frames), null);
});

test('sales charts total, scale and hide days beyond the replay date', () => {
  const data = normalizeInsights({...fixture(), sales: sales()}, 7);
  const all = salesChart(data.sales, 'total', 7), lunch = salesChart(data.sales, 'lunch', 7, salesPeak(data.sales, 7)), late = salesChart(data.sales, 'late', 7, salesPeak(data.sales, 7));
  assert.equal(all.value_cents, 5300);
  assert.equal(all.redemptions, 11);
  assert.equal(lunch.value_cents + late.value_cents, all.value_cents);
  assert.equal(all.maximum, 1900, 'the scale leaves room for the regular price');
  assert.equal(lunch.maximum, 1600);
  assert.equal(late.maximum, 1600, 'time-of-day charts share one scale');
  assert.equal(all.discount_cents, 3000);
  assert.equal(all.discount_known, 10);
  assert.equal(all.regular_cents, 8300);
  assert.equal(lunch.discount_cents + late.discount_cents, all.discount_cents);
  const second = all.bars[1];
  assert.deepEqual([second.value, second.redemptions, second.discount, second.known, second.regular, second.date], [1000, 2, 600, 2, 1600, data.sales.days[1].date]);
  assert.ok(all.bars.every(bar => bar.top === bar.y - bar.extra && bar.top >= 12 && bar.slot >= 12 && bar.slot + bar.slot_width <= 708.1 && bar.center > 0 && bar.center < 100));
  assert.equal(late.bars[3].extra, 0, 'no yellow bar without a known regular price');
  assert.ok(lunch.bars[1].extra > 0 && lunch.bars[1].height > lunch.bars[1].extra);
  assert.equal(all.bars.length, 7);
  assert.equal(all.best_date, data.sales.days[3].date);
  assert.ok(all.bars.every(bar => bar.x >= 12 && bar.x + bar.width <= 708 && bar.y >= 12 && bar.y + bar.height === 132));
  const older = sales();
  for (const day of older.days) for (const key of ['total', ...SALES_KEYS]) { delete day[key].discount_cents; delete day[key].discount_known; }
  const plain = salesChart(normalizeInsights({...fixture(), sales: older}, 7).sales, 'total', 7);
  assert.equal(plain.discount_cents, 0);
  assert.equal(plain.maximum, 1300);
  assert.ok(plain.bars.every(bar => bar.extra === 0));
  assert.equal(late.bars.filter(bar => bar.height > 0).length, 1);
  const early = salesChart(data.sales, 'total', 2);
  assert.equal(early.value_cents, 1500);
  assert.equal(early.bars.filter(bar => bar.height > 0).length, 2);
  assert.equal(early.bars.filter(bar => bar.live).length, 2);
  assert.equal(early.discount_cents, 900);
  assert.equal(salesChart(data.sales, 'total', 0).value_cents, 0);
  assert.equal(salesChart(data.sales, 'total', 0).best_date, '');
  assert.equal(salesChart(data.sales, 'total', 999).value_cents, 5300);
  assert.equal(salesChart(data.sales, 'morning', 7).maximum, 1);
});
