/** Pure, shared rules for the live dashboard and aggregate-only recap. */
export const PERIODS = [7, 30, 90, 365];
export const METRIC_KEYS = ['claims', 'redemptions', 'unique_customers', 'returning_customers', 'value_cents', 'savings_cents', 'savings_known', 'cohort_redeemed', 'cancelled', 'expired', 'pending', 'unknown_outcomes'];

function metricSet(value) {
  if (!value || typeof value !== 'object') throw new Error('The metrics response is incomplete.');
  return Object.fromEntries(METRIC_KEYS.map(key => {
    if (!Number.isSafeInteger(value[key]) || value[key] < 0) throw new Error('The metrics response contains an invalid total.');
    return [key, value[key]];
  }));
}
function text(value, limit = 200) { return typeof value === 'string' ? value.slice(0, limit) : ''; }
function date(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value + 'T12:00:00Z')) || new Date(value + 'T12:00:00Z').toISOString().slice(0, 10) !== value) throw new Error('The metrics response contains an invalid date.');
  return value;
}
function offers(value) {
  if (!Array.isArray(value)) throw new Error('The offer summary is incomplete.');
  return value.map(offer => {
    if (!Number.isSafeInteger(offer.redemptions) || offer.redemptions < 0 || !Number.isSafeInteger(offer.value_cents) || offer.value_cents < 0) throw new Error('The offer summary contains an invalid total.');
    // No offer IDs, account identifiers, locations, or unknown fields cross this boundary.
    return {title: text(offer.title) || 'Untitled offer', redemptions: offer.redemptions, value_cents: offer.value_cents};
  }).sort((a, b) => b.redemptions - a.redemptions || a.title.localeCompare(b.title));
}

export const SALES_KEYS = ['morning', 'lunch', 'dinner', 'late'];
const whole = value => Number.isSafeInteger(value) && value >= 0;
function cell(value) {
  if (!value || !whole(value.redemptions) || !whole(value.value_cents)) throw new Error('The sales summary contains an invalid total.');
  const discount = value.discount_cents === undefined ? 0 : value.discount_cents, known = value.discount_known === undefined ? 0 : value.discount_known;
  if (!whole(discount) || !whole(known) || known > value.redemptions || (known === 0 && discount !== 0)) throw new Error('The sales summary contains an invalid discount.');
  return {redemptions: value.redemptions, value_cents: value.value_cents, discount_cents: discount, discount_known: known};
}
export function salesSummary(value, frames) {
  if (value === undefined || value === null) return null;
  if (typeof value !== 'object' || !Array.isArray(value.blocks) || !Array.isArray(value.days) || !Array.isArray(value.offers)) throw new Error('The sales summary is incomplete.');
  if (value.blocks.length !== SALES_KEYS.length || value.blocks.some((block, index) => !block || block.key !== SALES_KEYS[index])) throw new Error('The sales summary is out of order.');
  if (value.days.length !== frames.length - 1) throw new Error('The sales summary does not cover the selected period.');
  const days = value.days.map((day, index) => {
    if (!day || day.date !== frames[index + 1].date) throw new Error('The sales summary dates do not match the timeline.');
    const parts = Object.fromEntries(SALES_KEYS.map(key => [key, cell(day[key])]));
    const total = cell(day.total);
    if (SALES_KEYS.reduce((sum, key) => sum + parts[key].redemptions, 0) !== total.redemptions || SALES_KEYS.reduce((sum, key) => sum + parts[key].value_cents, 0) !== total.value_cents
      || SALES_KEYS.reduce((sum, key) => sum + parts[key].discount_cents, 0) !== total.discount_cents || SALES_KEYS.reduce((sum, key) => sum + parts[key].discount_known, 0) !== total.discount_known) throw new Error('The sales summary does not add up.');
    return {date: day.date, total, ...parts};
  });
  const offers = value.offers.slice(0, 50).map(offer => {
    if (!offer || !whole(offer.claims) || !whole(offer.redemptions) || !whole(offer.value_cents) || !Array.isArray(offer.blocks)) throw new Error('The sales summary contains an invalid offer.');
    const blocks = SALES_KEYS.map(key => {
      const found = offer.blocks.find(block => block && block.key === key);
      if (!found || !whole(found.claims) || !whole(found.redemptions) || !whole(found.value_cents)) throw new Error('The sales summary contains an invalid offer.');
      return {key, label: text(found.label, 40), claims: found.claims, redemptions: found.redemptions, value_cents: found.value_cents};
    });
    return {title: text(offer.title) || 'Untitled offer', schedule: text(offer.schedule, 80), claims: offer.claims, redemptions: offer.redemptions, value_cents: offer.value_cents, busiest: text(offer.busiest, 40), blocks};
  });
  return {blocks: value.blocks.map(block => ({key: block.key, label: text(block.label, 40), hours: text(block.hours, 40)})), days, offers};
}
export function salesChart(sales, key, cutoff, ceiling = 0) {
  const shown = Math.max(0, Math.min(sales.days.length, Math.trunc(Number(cutoff)) || 0));
  const values = sales.days.map(day => day[key].value_cents);
  const full = sales.days.map(day => day[key].value_cents + day[key].discount_cents);
  const maximum = Math.max(1, ceiling, ...full.slice(0, shown));
  const step = sales.days.length > 1 ? 696 / sales.days.length : 696;
  const bars = values.map((value, index) => {
    const day = sales.days[index][key], live = index < shown;
    const height = live && value ? Math.max(2, Math.round(value / maximum * 120)) : 0;
    const extra = live && day.discount_cents ? Math.max(2, Math.round(day.discount_cents / maximum * 120)) : 0;
    const slot = Math.round((12 + step * index) * 10) / 10;
    return {day: index + 1, date: sales.days[index].date, value, redemptions: day.redemptions, discount: day.discount_cents, known: day.discount_known,
      regular: value + day.discount_cents, live, x: Math.round((12 + step * index + step * 0.15) * 10) / 10, width: Math.round(step * 0.7 * 10) / 10,
      y: 132 - height, height, extra, top: 132 - height - extra, slot, slot_width: Math.round(step * 10) / 10,
      center: Math.round((12 + step * (index + 0.5)) / 720 * 1000) / 10};
  });
  const past = sales.days.slice(0, shown);
  const best = past.reduce((top, day) => day[key].value_cents > (top ? top[key].value_cents : 0) ? day : top, null);
  const sum = field => past.reduce((total, day) => total + day[key][field], 0);
  return {key, maximum, bars, shown,
    value_cents: sum('value_cents'), redemptions: sum('redemptions'),
    discount_cents: sum('discount_cents'), discount_known: sum('discount_known'), regular_cents: sum('value_cents') + sum('discount_cents'),
    best_date: best ? best.date : '', best_value_cents: best ? best[key].value_cents : 0};
}
export function salesPeak(sales, cutoff) {
  const shown = Math.max(0, Math.min(sales.days.length, Math.trunc(Number(cutoff)) || 0));
  return Math.max(1, ...sales.days.slice(0, shown).flatMap(day => SALES_KEYS.map(key => day[key].value_cents + day[key].discount_cents)));
}

export function normalizeInsights(reply, expectedPeriod) {
  if (!reply || reply.ok !== true) throw new Error(text(reply?.message) || 'Your business insights could not be loaded.');
  if (!PERIODS.includes(reply.period_days) || (expectedPeriod && reply.period_days !== expectedPeriod)) throw new Error('The metrics response is for a different period.');
  if (!Array.isArray(reply.frames) || reply.frames.length !== reply.period_days + 1) throw new Error('The metrics timeline is incomplete.');
  const frames = reply.frames.map((frame, index) => {
    if (frame.day !== index) throw new Error('The metrics timeline is out of order.');
    return {day: index, date: date(frame.date), daily: metricSet(frame.daily), totals: metricSet(frame.totals), offers: offers(frame.offers)};
  });
  for (let i = 1; i < frames.length; i++) {
    if (Date.parse(frames[i].date) - Date.parse(frames[i - 1].date) !== 86400000) throw new Error('The metrics timeline has a missing date.');
  }
  if (METRIC_KEYS.some(key => frames[0].totals[key] !== 0 || frames[0].daily[key] !== 0) || frames[0].offers.length) throw new Error('The metrics timeline needs a zero baseline.');
  if (!Number.isFinite(reply.as_of) || reply.as_of < 0 || !Number.isFinite(new Date(reply.as_of * 1000).getTime())) throw new Error('The metrics response has no collection time.');
  const start = date(reply.start_date), end = date(reply.end_date);
  if (frames[1].date !== start || frames.at(-1).date !== end) throw new Error('The metrics dates do not match the selected period.');
  return {
    business_name: text(reply.business_name) || 'Your business', is_demo: reply.is_demo === true,
    period_days: reply.period_days, timezone: 'America/Detroit', start_date: start, end_date: end,
    as_of: reply.as_of, coverage_start_date: reply.coverage_start_date ? date(reply.coverage_start_date) : '',
    warnings: Array.isArray(reply.warnings) ? reply.warnings.filter(item => typeof item === 'string').map(item => text(item, 400)).slice(0, 12) : [],
    frames,
    sales: salesSummary(reply.sales, frames),
  };
}

export const money = cents => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: cents % 100 ? 2 : 0}).format(cents / 100);
export const count = value => new Intl.NumberFormat('en-US').format(value);
export function displayDate(value, year = false) { return new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric', ...(year ? {year: 'numeric'} : {}), timeZone: 'UTC'}).format(new Date(value + 'T12:00:00Z')); }
export function resolvedRate(metrics) {
  const denominator = metrics.cohort_redeemed + metrics.cancelled + metrics.expired;
  return {denominator, percent: denominator ? Math.round(metrics.cohort_redeemed / denominator * 100) : null};
}
export function selectCutoff(data, cutoff) {
  const index = Math.max(0, Math.min(data.frames.length - 1, Number.isFinite(cutoff) ? Math.floor(cutoff) : 0));
  const frame = data.frames[index], history = data.frames.slice(0, index + 1);
  const active = history.filter(item => item.daily.redemptions > 0);
  const busiest = active.reduce((best, item) => !best || item.daily.redemptions > best.daily.redemptions ? item : best, null);
  return {index, frame, history, rate: resolvedRate(frame.totals), first: active[0] || null, busiest, top: frame.offers[0] || null};
}
export function chartSeries(data, cutoff, mode = 'cumulative') {
  const {history} = selectCutoff(data, cutoff);
  const values = history.map(frame => mode === 'daily' ? frame.daily.redemptions : frame.totals.redemptions);
  const maximum = Math.max(1, ...values);
  return {maximum, points: values.map((value, day) => ({day, value, x: 12 + day / data.period_days * 696, y: 154 - value / maximum * 132}))};
}

/** A later request, range change, replay action or unmount invalidates old responses. */
export function createRequestGate() {
  let sequence = 0;
  return {begin: () => ++sequence, invalidate: () => { sequence++; }, accepts: token => token === sequence};
}

/** Re-select every field even when passed a previously normalized response. */
export function recapPayload(data) {
  // Keep the exporter safe even if a future caller passes a raw API response.
  data = normalizeInsights({...data, ok: true});
  return {
    business_name: text(data.business_name), is_demo: data.is_demo === true,
    period_days: data.period_days, timezone: 'America/Detroit',
    start_date: date(data.start_date), end_date: date(data.end_date),
    as_of: Number.isFinite(data.as_of) ? data.as_of : 0,
    coverage_start_date: data.coverage_start_date ? date(data.coverage_start_date) : '',
    // Warning prose is shown in the private view; the shared file uses a generic coverage note.
    has_coverage_warnings: Array.isArray(data.warnings) && data.warnings.length > 0,
    frames: data.frames.map(frame => ({day: frame.day, date: date(frame.date), daily: metricSet(frame.daily), totals: metricSet(frame.totals), offers: offers(frame.offers)})),
  };
}
export function escapeHtml(value) { return String(value).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char])); }
export function safeJson(value) { return JSON.stringify(value).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029'); }

// This function is embedded verbatim in exported HTML. Only the allowlisted JSON is provided.
function mountRecap() {
  const data = JSON.parse(document.getElementById('recap-data').textContent);
  const byId = id => document.getElementById(id);
  const fmt = n => new Intl.NumberFormat('en-US').format(n);
  const cash = n => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: n % 100 ? 2 : 0}).format(n / 100);
  const dateFmt = value => new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'}).format(new Date(value + 'T12:00:00Z'));
  let cutoff = data.period_days, timer = null;
  function stop() { clearInterval(timer); timer = null; byId('play').textContent = 'Play period'; }
  function render() {
    const frame = data.frames[cutoff], m = frame.totals;
    byId('date').textContent = cutoff ? 'Through ' + dateFmt(frame.date) : 'Before the period begins';
    byId('seek').value = cutoff;
    byId('progress').textContent = 'Day ' + cutoff + ' of ' + data.period_days;
    for (const key of ['claims', 'redemptions', 'returning_customers']) byId(key).textContent = fmt(m[key]);
    byId('value_cents').textContent = cash(m.value_cents);
    const denominator = m.cohort_redeemed + m.cancelled + m.expired;
    byId('outcomes').textContent = (denominator ? Math.round(m.cohort_redeemed / denominator * 100) + '% of resolved claims redeemed. ' : 'No resolved claims yet. ') + fmt(m.cohort_redeemed) + ' redeemed · ' + fmt(m.cancelled) + ' cancelled · ' + fmt(m.expired) + ' expired';
    const history = data.frames.slice(0, cutoff + 1), maximum = Math.max(1, ...history.map(f => f.totals.redemptions));
    byId('line').setAttribute('points', history.map((f, index) => (12 + index / data.period_days * 696) + ',' + (154 - f.totals.redemptions / maximum * 132)).join(' '));
    byId('chart').setAttribute('aria-label', 'Cumulative redemptions through this date: ' + m.redemptions);
    byId('maximum').textContent = 'Chart scale: 0 to ' + fmt(maximum) + ' redemptions';
    const list = byId('offers'); list.replaceChildren();
    for (const offer of frame.offers.slice(0, 5)) { const li = document.createElement('li'); const label = document.createElement('span'); label.textContent = offer.title; const total = document.createElement('strong'); total.textContent = fmt(offer.redemptions) + ' · ' + cash(offer.value_cents); li.append(label, total); list.append(li); }
    if (!frame.offers.length) { const li = document.createElement('li'); li.textContent = 'Redeemed offers will appear here.'; list.append(li); }
    const busiest = history.reduce((best, f) => f.daily.redemptions > (best?.daily.redemptions || 0) ? f : best, null);
    byId('story').textContent = busiest ? dateFmt(busiest.date) + ' was the busiest day so far, with ' + fmt(busiest.daily.redemptions) + ' redemptions.' : 'The first recorded redemption will begin this story.';
  }
  byId('seek').addEventListener('input', event => { stop(); cutoff = Number(event.target.value); render(); });
  byId('reset').addEventListener('click', () => { stop(); cutoff = 0; render(); });
  byId('latest').addEventListener('click', () => { stop(); cutoff = data.period_days; render(); });
  byId('play').addEventListener('click', () => { if (timer) { stop(); return; } if (cutoff >= data.period_days) cutoff = 0; render(); byId('play').textContent = 'Pause replay'; timer = setInterval(() => { cutoff = Math.min(data.period_days, cutoff + 1); render(); if (cutoff >= data.period_days) stop(); }, 150); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  render();
}

export function buildRecapHtml(input, showProvenance = true) {
  const data = recapPayload(input), name = escapeHtml(data.business_name), period = data.period_days === 365 ? 'Your year in review' : `Your ${data.period_days} days in review`;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>${name} · M-Local recap</title><style>
  :root{color-scheme:light;--bg:#F9F6F0;--surface:#FFFFFF;--ink:#0B1F38;--muted:#5F6B7A;--border:#DDD5C7;--accent:#02305C;--on-accent:#FFFFFF;--mark:#FEC809;--focus:#2365A0}
  @media(prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#091624;--surface:#12243A;--ink:#F9F6F0;--muted:#B0C0D1;--border:#34485F;--accent:#FEC809;--on-accent:#0B1F38;--mark:#FEC809;--focus:#FEC809}}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 Figtree,system-ui,sans-serif}main{max-width:980px;margin:auto;padding:36px 24px}.eyebrow{font-size:12px;font-weight:800;letter-spacing:.13em;text-transform:uppercase;color:var(--accent)}h1{font-size:clamp(34px,6vw,62px);font-weight:850;line-height:1.08;letter-spacing:-.03em;margin:12px 0}h2{font-size:20px;margin:0 0 14px}.note{color:var(--muted);font-size:13px}.hero{border-bottom:1px solid var(--border);padding-bottom:24px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin:30px 0}.metric strong{display:block;font-size:clamp(28px,4vw,40px);font-variant-numeric:tabular-nums}.metric span{font-size:13px;color:var(--muted)}.timeline{position:relative;background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:24px}.timeline:after{content:'';position:absolute;top:-7px;right:24px;width:14px;height:14px;background:var(--mark);border-radius:3px}svg{display:block;width:100%;height:auto;overflow:visible}button{min-height:48px;padding:10px 16px;background:var(--surface);border:1px solid var(--border);border-radius:12px;color:var(--ink);font:700 14px Figtree,system-ui,sans-serif;cursor:pointer}button:first-child{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}button:focus-visible,input:focus-visible{outline:3px solid var(--focus);outline-offset:3px}.controls{display:flex;gap:8px;flex-wrap:wrap}input{width:100%;accent-color:var(--accent);margin:18px 0;min-height:30px}.meta{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:13px}.story{font-size:25px;font-weight:750;line-height:1.4;margin:28px 0}ul{padding:0;list-style:none}li{display:flex;justify-content:space-between;gap:20px;border-bottom:1px solid var(--border);padding:13px 0;overflow-wrap:anywhere}li span{min-width:0}li strong{white-space:nowrap}footer{margin-top:30px;border-top:1px solid var(--border);padding-top:16px}@media(max-width:550px){main{padding:24px 16px}.metrics{grid-template-columns:repeat(2,1fr)}.timeline{padding:16px}li{flex-direction:column;gap:2px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
  </style></head><body><main><header class="hero"><div class="eyebrow">M-Local · Business recap${data.is_demo && showProvenance ? ' · Demo business' : ''}</div><h1>${period}</h1><p>${name}</p><p class="note">${escapeHtml(displayDate(data.start_date, true))} to ${escapeHtml(displayDate(data.end_date, true))} · America/Detroit</p></header><section class="metrics" aria-label="Recorded business metrics">${[['claims', 'Claims'], ['redemptions', 'Redemptions'], ['returning_customers', 'Returning accounts'], ['value_cents', 'Redeemed offer value']].map(([id, label]) => `<div class="metric"><strong id="${id}">0</strong><span>${label}</span></div>`).join('')}</section><section class="timeline" aria-label="Period replay"><div class="meta"><strong id="date"></strong><span id="progress"></span></div><svg id="chart" role="img" viewBox="0 0 720 174"><line x1="12" x2="708" y1="154" y2="154" stroke="var(--border)"/><polyline id="line" fill="none" stroke="var(--accent)" stroke-width="3" stroke-linejoin="round"/></svg><p class="note" id="maximum"></p><label class="note" for="seek">Replay date</label><input id="seek" type="range" min="0" max="${data.period_days}" step="1"><div class="controls"><button id="play">Play period</button><button id="reset">Reset</button><button id="latest">Period totals</button></div></section><p class="story" id="story"></p><section><h2>Claim outcomes</h2><p id="outcomes"></p><p class="note">Outcomes follow claims created in this period. Redemption rate excludes pending and unknown outcomes. Redemptions and value include offers claimed earlier and redeemed in this period.</p></section><section><h2>Most-redeemed offers</h2><ul id="offers"></ul></section><footer class="note"><p>This recap contains aggregate business activity only. Returning accounts redeemed here on another earlier local date. Redeemed offer value uses the price recorded at claim time; it is not payment revenue.</p><p>Snapshot collected ${escapeHtml(new Date(data.as_of * 1000).toISOString())}.${data.has_coverage_warnings ? ' Some historical records have incomplete evidence; this recap includes only supported metrics.' : ''} Views, nearby selections, and verified visits are not collected in this recap.</p></footer></main><script id="recap-data" type="application/json">${safeJson(data)}</script><script>(${mountRecap.toString()})();</script></body></html>`;
}
