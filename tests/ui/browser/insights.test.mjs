import test from 'node:test';
import assert from 'node:assert/strict';
import {app,rpc,until} from './harness.mjs';
import {METRIC_KEYS} from '../../../client/insights-support.mjs';
const zero=()=>Object.fromEntries(METRIC_KEYS.map(key=>[key,0]));
function fixture(days,name=`Fixture ${days} days`){
 const end=Date.UTC(2026,8,27),date=day=>new Date(end-(days-day)*86400000).toISOString().slice(0,10);
 const frames=Array.from({length:days+1},(_,day)=>({day,date:date(day),daily:{...zero(),claims:day?2:0,redemptions:day?1:0},totals:{...zero(),claims:day*2,redemptions:day,cohort_redeemed:day,expired:day,value_cents:day*600,unique_customers:Math.min(day,2),returning_customers:day>2?1:0},offers:day?[{title:'Current lunch',redemptions:day,value_cents:day*600}]:[]}));
 return {ok:true,business_name:name,is_demo:true,period_days:days,timezone:'America/Detroit',start_date:date(1),end_date:date(days),as_of:end/1000,coverage_start_date:date(1),warnings:['Historical sample'],frames};
}
const metric=(ui,title)=>[...ui.document.querySelectorAll('.bi-metric')].find(n=>n.querySelector('h3').textContent===title).querySelector('strong').textContent;
function setRange(ui,day){const range=ui.document.querySelector('#bi-replay-date');Object.getOwnPropertyDescriptor(ui.window.HTMLInputElement.prototype,'value').set.call(range,String(day));range.dispatchEvent(new ui.window.Event('input',{bubbles:true}));}
const tick=ms=>new Promise(resolve=>setTimeout(resolve,ms));

test('local activity stays separate from own merchant insights and hides fixture labels', async()=>{
 const ui=await app({role:'merchant',verified:true,intercept(name,body){
  if(name==='current_session')return rpc({authenticated:true,role:'merchant',actor_id:'fixture-merchant',restaurant_id:'fixture-restaurant',display_name:'Owner',email_verified:true,catalog_activity:true});
  if(name==='merchant_insights')return rpc({...fixture(body.days,'Own Kitchen'),is_demo:false});
  if(name==='local_activity')return rpc({...fixture(body.days,'Local Cafe'),warnings:[]});
 }});
 try {
  ui.click('Insights');
  await until(()=>ui.document.body.textContent.includes('Own Kitchen'));
  ui.click('Explore local activity');
  await until(()=>ui.document.body.textContent.includes('Local Cafe'));
  assert.equal(ui.document.querySelector('.bi-badge'),null);
  assert.equal(ui.document.body.textContent.includes('Own Kitchen'),false);
  ui.click('Your business');
  await until(()=>ui.document.body.textContent.includes('Own Kitchen'));
  assert.equal(ui.document.body.textContent.includes('Local Cafe'),false);
 } finally {ui.close();}
});

test('native Insights range, playback, freeze, stale-response isolation and recap export',async()=>{
 let holdNext=false,release,requestedPeriod,blob,downloadName,background;
 const ui=await app({role:'merchant',verified:true,configureWindow(w){
  w.URL.createObjectURL=value=>{blob=value;return 'blob:fixture';};w.URL.revokeObjectURL=()=>{};
  w.HTMLAnchorElement.prototype.click=function(){downloadName=this.download;};
  const original=w.setInterval.bind(w);w.setInterval=(callback,ms)=>{if(ms===120000){background=callback;return 987654;}return original(callback,ms);};
 },intercept(name,body){if(name==='merchant_insights'){
  if(holdNext){holdNext=false;requestedPeriod=body.days;return new Promise(resolve=>{release=resolve;});}
  return rpc(fixture(body.days));
 }}});
 try{
  ui.click('Insights');
  await until(()=>ui.find('Fixture 30 days'),'initial recording');
  assert.equal(metric(ui,'Redemptions'),'30');assert.equal(ui.document.querySelector('.bi-progress').textContent,'Day 30 / 30');
  ui.click('7 days');await until(()=>ui.find('Fixture 7 days'),'7 day recording');
  assert.equal(metric(ui,'Claims'),'14');assert.equal(ui.calls.filter(c=>c.name==='merchant_insights').at(-1).body.days,7);
  ui.click('Reset');await until(()=>metric(ui,'Redemptions')==='0');assert.equal(ui.document.querySelector('.bi-offers'),null);
  setRange(ui,3);await until(()=>metric(ui,'Redemptions')==='3');ui.click('Daily');await until(()=>ui.document.querySelectorAll('.bi-chart rect').length===3);
  ui.click('Play');await until(()=>Number(ui.document.querySelector('#bi-replay-date').value)>3);ui.click('Pause replay');
  const paused=ui.document.querySelector('#bi-replay-date').value;await tick(220);assert.equal(ui.document.querySelector('#bi-replay-date').value,paused);
  const speed=ui.document.querySelector('#bi-replay-speed');speed.value='3';speed.dispatchEvent(new ui.window.Event('change',{bubbles:true}));
  ui.click('Play');await until(()=>ui.document.querySelector('#bi-replay-date').value==='7');assert.ok(ui.find('Replay this period'));
  const calls=ui.calls.filter(c=>c.name==='merchant_insights').length;background();await tick(20);assert.equal(ui.calls.filter(c=>c.name==='merchant_insights').length,calls,'replay freezes auto updates');
  holdNext=true;ui.click('Return to latest');await until(()=>release);assert.equal(requestedPeriod,7);
  ui.click('Reset');release(rpc(fixture(7,'STALE REPLAY REPLY')));release=null;await tick(40);
  assert.equal(metric(ui,'Redemptions'),'0');assert.equal(ui.find('STALE REPLAY REPLY'),undefined);
  ui.click('Return to latest');await until(()=>metric(ui,'Redemptions')==='7');
  holdNext=true;ui.click('90 days');await until(()=>release);assert.equal(requestedPeriod,90);const finishOld=release;release=null;
  ui.click('7 days');await until(()=>ui.find('Fixture 7 days'));finishOld(rpc(fixture(90,'STALE RANGE REPLY')));await tick(40);
  assert.equal(ui.find('STALE RANGE REPLY'),undefined);assert.equal(metric(ui,'Redemptions'),'7');
  setRange(ui,2);await until(()=>metric(ui,'Redemptions')==='2');ui.click('Download recap');await until(()=>blob);
  const html=await new Promise((resolve,reject)=>{const reader=new ui.window.FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsText(blob);});
  assert.equal(downloadName,'M-Local-7-day-recap-2026-09-27.html');assert.match(html,/"day":7/);assert.match(html,/Fixture 7 days/);assert.doesNotMatch(html,/synthetic-ui-token|fixture-merchant/);
  holdNext=true;ui.click('Return to latest');await until(()=>release);ui.click('Account');await until(()=>!ui.document.querySelector('.bi'));release(rpc(fixture(7,'STALE UNMOUNT REPLY')));release=null;await tick(40);
  assert.equal(ui.document.querySelector('.bi'),null);assert.equal(ui.find('STALE UNMOUNT REPLY'),undefined);assert.deepEqual(ui.errors,[]);
 }finally{release?.(rpc(fixture(requestedPeriod)));ui.close();}
});
test('native Insights preserves malformed-response errors, retry, and previous data on refresh failure',async()=>{
 let request=0;
 const ui=await app({role:'merchant',verified:true,intercept(name,body){if(name==='merchant_insights'){
  request++;
  if(request===1)return rpc(fixture(7));
  if(request===3)return rpc({ok:false,message:'Refresh unavailable'});
  return rpc(fixture(body.days));
 }}});
 try{
  ui.click('Insights');
  await until(()=>ui.text().includes('The metrics response is for a different period.'));
  assert.equal(ui.document.querySelector('.bi-metrics'),null);
  ui.click('Refresh');await until(()=>ui.find('Fixture 30 days'));assert.equal(metric(ui,'Redemptions'),'30');
  ui.click('Refresh');await until(()=>ui.text().includes('Refresh unavailable'));
  assert.equal(metric(ui,'Redemptions'),'30');assert.ok(ui.text().includes('The last loaded recording is still shown.'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
