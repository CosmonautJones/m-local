import test from 'node:test';
import assert from 'node:assert/strict';
import {app, home, offer, rpc, until} from './harness.mjs';

test('the feed asks for one page and shows more deals on request', async()=>{
 const deals=n=>Array.from({length:n},(_,i)=>offer({id:'deal-'+i,title:'Deal number '+i}));
 const ui=await app({verified:true,item:offer({id:'deal-0',title:'Deal number 0'}),intercept(name,body){
  if(name==='home_feed')return rpc(home(deals(Math.min(body.limit||100,100)),{matching_deals:100}));
 }});
 try{
  await until(()=>ui.text().includes('Deal number 39'));
  const first=ui.calls.filter(c=>c.name==='home_feed').at(-1);
  assert.equal(first.body.limit,40);
  assert.ok(!ui.text().includes('Deal number 40'));
  assert.ok(ui.text().includes('Showing 40 deals of 100.'));
  ui.click('Show more deals (60 more)');
  await until(()=>ui.text().includes('Deal number 79'));
  assert.equal(ui.calls.filter(c=>c.name==='home_feed').at(-1).body.limit,80);
  ui.click('Show more deals (20 more)');
  await until(()=>ui.text().includes('Deal number 99'));
  assert.equal(ui.find('Show more deals (0 more)'),undefined);
  assert.ok(ui.text().includes('Showing 100 deals.'));
  assert.deepEqual(ui.errors,[]);
 }finally{ui.close();}
});
