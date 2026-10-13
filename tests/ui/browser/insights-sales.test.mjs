import test from 'node:test';
import assert from 'node:assert/strict';
import {app,rpc,until} from './harness.mjs';
import {METRIC_KEYS,SALES_KEYS} from '../../../client/insights-support.mjs';

const zero=()=>Object.fromEntries(METRIC_KEYS.map(key=>[key,0]));
const names={morning:'Morning',lunch:'Lunch',dinner:'Dinner',late:'Late night'};
const hours={morning:'6 AM to 11 AM',lunch:'11 AM to 4 PM',dinner:'4 PM to 9 PM',late:'9 PM to 6 AM'};
function insights(days,withSales=true,busy=true) {
 const end=Date.UTC(2026,8,27),date=day=>new Date(end-(days-day)*86400000).toISOString().slice(0,10);
 const daily=day=>busy&&day?{redemptions:3,value_cents:1500}:{redemptions:0,value_cents:0};
 const frames=Array.from({length:days+1},(_,day)=>({day,date:date(day),daily:{...zero(),claims:day&&busy?3:0,redemptions:daily(day).redemptions,value_cents:daily(day).value_cents},
  totals:{...zero(),claims:busy?day*3:0,redemptions:busy?day*3:0,cohort_redeemed:busy?day*3:0,value_cents:busy?day*1500:0},offers:day&&busy?[{title:'Lunch bowl',redemptions:day*3,value_cents:day*1500}]:[]}));
 const cell=(redemptions,value_cents,discount_cents=0,discount_known=0)=>({redemptions,value_cents,discount_cents,discount_known});
 const sales={blocks:SALES_KEYS.map(key=>({key,label:names[key],hours:hours[key]})),
  days:frames.slice(1).map(frame=>busy?{date:frame.date,morning:cell(0,0),lunch:cell(2,1000,600,2),dinner:cell(0,0),late:cell(1,500),total:cell(3,1500,600,2)}:{date:frame.date,morning:cell(0,0),lunch:cell(0,0),dinner:cell(0,0),late:cell(0,0),total:cell(0,0)}),
  offers:busy?[{title:'Lunch bowl',schedule:'Sep 27, 11 AM to 2 PM',claims:days*2,redemptions:days*2,value_cents:days*1000,busiest:'Lunch',blocks:SALES_KEYS.map(key=>({key,label:names[key],claims:key==='lunch'?days*2:0,redemptions:key==='lunch'?days*2:0,value_cents:key==='lunch'?days*1000:0}))},
   {title:'Late slice',schedule:'',claims:days,redemptions:days,value_cents:days*500,busiest:'Late night',blocks:SALES_KEYS.map(key=>({key,label:names[key],claims:key==='late'?days:0,redemptions:key==='late'?days:0,value_cents:key==='late'?days*500:0}))}]:[]};
 return {ok:true,business_name:`Fixture ${days} days`,is_demo:true,period_days:days,timezone:'America/Detroit',start_date:date(1),end_date:date(days),as_of:end/1000,coverage_start_date:date(1),warnings:[],frames,...(withSales?{sales}:{})};
}
const merchant=async make=>{const ui=await app({role:'merchant',verified:true,intercept(name,body){if(name==='merchant_insights')return rpc(make(body.days));}});ui.click('Insights');return ui;};
const region=ui=>ui.document.querySelector('section[aria-label="Sales through your offers"]');
const chart=(ui,part)=>region(ui).querySelector(`.bi-sales-chart[data-part="${part}"]`);
const bars=(ui,part)=>chart(ui,part).querySelectorAll('svg rect.bi-bar-paid').length;
const yellow=(ui,part)=>chart(ui,part).querySelectorAll('svg rect.bi-bar-discount').length;
const spot=(ui,part,day)=>chart(ui,part).querySelector(`svg rect.bi-bar-hit[data-day="${day}"]`);
const tip=(ui,part)=>chart(ui,part).querySelector('.bi-sales-tip');
const over=(ui,node,type)=>node.dispatchEvent(new ui.window.MouseEvent(type,{bubbles:true}));
function setRange(ui,day){const range=ui.document.querySelector('#bi-replay-date');Object.getOwnPropertyDescriptor(ui.window.HTMLInputElement.prototype,'value').set.call(range,String(day));range.dispatchEvent(new ui.window.Event('input',{bubbles:true}));}

test('a restaurant sees overall sales, then morning, lunch, dinner and late night',async()=>{
 const ui=await merchant(days=>insights(days));
 try{
  await until(()=>region(ui),'sales charts');
  assert.deepEqual([...region(ui).querySelectorAll('.bi-sales-chart')].map(node=>node.dataset.part),['total','morning','lunch','dinner','late']);
  assert.deepEqual([...region(ui).querySelectorAll('.bi-sales-chart h3')].map(node=>node.textContent),['All day','Morning','Lunch','Dinner','Late night']);
  assert.ok(chart(ui,'total').textContent.includes('$450'));assert.ok(chart(ui,'total').textContent.includes('90 redeemed'));
  assert.ok(chart(ui,'lunch').textContent.includes('$300'));assert.ok(chart(ui,'lunch').textContent.includes('11 AM to 4 PM'));
  assert.ok(chart(ui,'late').textContent.includes('$150'));assert.ok(chart(ui,'morning').textContent.includes('$0'));
  assert.ok(chart(ui,'morning').textContent.includes('No redemptions recorded here yet.'));
  assert.equal(bars(ui,'total'),30);assert.equal(bars(ui,'lunch'),30);assert.equal(bars(ui,'late'),30);assert.equal(bars(ui,'morning'),0);assert.equal(bars(ui,'dinner'),0);
  assert.ok(chart(ui,'total').textContent.includes('Top of chart: $21'));
  assert.ok(chart(ui,'lunch').textContent.includes('Top of chart: $16'));assert.ok(chart(ui,'late').textContent.includes('Top of chart: $16'),'time-of-day charts share a scale');
  assert.equal(chart(ui,'total').querySelector('svg').getAttribute('aria-label'),'All day sales through your offers: $450 from 90 redemptions');
  const text=region(ui).textContent;
  assert.ok(text.includes('What each offer did, and when'));assert.ok(text.includes('Current schedule: Sep 27, 11 AM to 2 PM'));
  assert.ok(text.includes('Lunch: 60 claimed, 60 redeemed'));assert.ok(text.includes('Busiest: Late night'));
  setRange(ui,10);await until(()=>bars(ui,'total')===10,'charts follow the replay date');
  assert.ok(chart(ui,'total').textContent.includes('$150'));assert.ok(chart(ui,'total').textContent.includes('30 redeemed'));
  assert.equal(bars(ui,'lunch'),10);
  ui.click('7 days');await until(()=>ui.find('Fixture 7 days'));await until(()=>bars(ui,'total')===7);
  assert.ok(chart(ui,'total').textContent.includes('$105'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});

test('sales charts have an honest empty state and are skipped for an older server reply',async()=>{
 const empty=await merchant(days=>insights(days,true,false));
 try{
  await until(()=>region(empty));
  assert.equal(region(empty).querySelectorAll('.bi-sales-chart').length,5);
  assert.equal(region(empty).querySelectorAll('svg rect.bi-bar-paid, svg rect.bi-bar-discount').length,0);
  assert.ok(region(empty).querySelector('[aria-label="Total subsidized through discounts"]').textContent.includes('No redemption in this period has a recorded regular price'));
  assert.ok(chart(empty,'total').textContent.includes('$0'));assert.ok(chart(empty,'total').textContent.includes('No redemptions recorded here yet.'));
  assert.equal(region(empty).textContent.includes('What each offer did'),false);
  assert.deepEqual(empty.errors,[]);
 }finally{empty.close();}
 const older=await merchant(days=>insights(days,false));
 try{
  await until(()=>older.text().includes('Most-redeemed offers'));
  assert.equal(region(older),null);
  assert.deepEqual(older.errors,[]);
 }finally{older.close();}
});

test('pointing at a day shows its date, money and redemptions, and yellow shows the lost potential',async()=>{
 const ui=await merchant(days=>insights(days));
 try{
  await until(()=>region(ui),'sales charts');
  assert.equal(tip(ui,'total'),null,'nothing pops up until a day is chosen');
  assert.equal(yellow(ui,'total'),30);assert.equal(yellow(ui,'lunch'),30);assert.equal(yellow(ui,'late'),0,'no yellow without a known regular price');assert.equal(yellow(ui,'morning'),0);
  assert.equal(chart(ui,'total').querySelectorAll('svg rect.bi-bar-hit').length,30);
  const day=spot(ui,'total',30);
  assert.equal(day.getAttribute('aria-label'),'Sep 27, 2026: $15 in redemptions, 3 redemptions');
  over(ui,day,'mouseover');await until(()=>tip(ui,'total'),'pop-up for the last day');
  assert.deepEqual([...tip(ui,'total').children].map(node=>node.textContent),['Sep 27, 2026','$15 in redemptions','3 redemptions']);
  assert.equal(chart(ui,'total').querySelector('.bi-bar-paid').getAttribute('fill'),'var(--ml-good)');
  assert.equal(tip(ui,'lunch'),null,'only the chart being pointed at shows a pop-up');
  over(ui,spot(ui,'total',1),'mouseover');await until(()=>tip(ui,'total').textContent.includes('Aug 29, 2026'));
  over(ui,chart(ui,'total').querySelector('.bi-sales-plot'),'mouseout');await until(()=>tip(ui,'total')===null,'pop-up goes away');
  spot(ui,'late',5).dispatchEvent(new ui.window.MouseEvent('click',{bubbles:true}));await until(()=>tip(ui,'late'),'tapping works on a phone');
  assert.deepEqual([...tip(ui,'late').children].map(node=>node.textContent),['Sep 2, 2026','$5 in redemptions','1 redemption']);
  over(ui,spot(ui,'morning',3),'mouseover');await until(()=>tip(ui,'morning'));
  assert.deepEqual([...tip(ui,'morning').children].map(node=>node.textContent),['Aug 31, 2026','$0 in redemptions','0 redemptions']);
  const key=region(ui).querySelector('.bi-sales-key').textContent;
  assert.ok(key.includes('Paid with your offers'));assert.ok(key.includes('Lost potential: what regular prices would have added'));
  assert.equal(chart(ui,'total').textContent.includes('$630 at regular prices'),false);
  assert.ok(chart(ui,'lunch').textContent.includes('$480 at regular prices'));
  const cost=region(ui).querySelector('[aria-label="Total subsidized through discounts"]');
  assert.equal(cost.querySelector('strong').textContent,'$180');
  assert.ok(cost.textContent.includes('$180 in recorded discounts across 60 redemptions with a known regular price.'));
  assert.ok(cost.textContent.includes('Some redemptions have no recorded regular price.'));
  assert.equal(cost.textContent.includes('would have brought in $630'),false);
  setRange(ui,10);await until(()=>bars(ui,'total')===10);
  assert.equal(yellow(ui,'total'),10);assert.equal(chart(ui,'total').querySelectorAll('svg rect.bi-bar-hit').length,10,'days beyond the replay date cannot be chosen');
  assert.equal(cost.querySelector('strong').textContent,'$60');
  assert.equal(ui.document.querySelector('button button'),null);
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
