import assert from 'node:assert/strict';
import http from 'node:http';
import {once} from 'node:events';
import test from 'node:test';
import {createShareProxy} from '../../scripts/phone-share-proxy.mjs';

const feed={items:[],favorites:[],note:'',price_range:'',total_deals:0,signed_in:false,personalized:false,completed:false};
const guest={authenticated:false,actor_id:'',role:'guest',restaurant_id:'',display_name:'',is_demo:false,
  email_verified:false,business_account:false,catalog_activity:false};
const reply=(res,value,status=200)=>{res.writeHead(status,{'content-type':'application/json'});res.end(JSON.stringify(value));};
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));

async function serve(t,handler,options={}) {
  const upstream=http.createServer(handler).listen(0,'127.0.0.1');await once(upstream,'listening');
  const proxy=createShareProxy({upstreamHost:'127.0.0.1',upstreamPort:upstream.address().port,
    deploymentTopology:'single-instance-serialized',healthCheck:true,startupCatalogCheck:true,...options});
  proxy.listen(0,'127.0.0.1');await once(proxy,'listening');
  t.after(()=>{proxy.closeAllConnections();proxy.close();upstream.closeAllConnections();upstream.close();});
  return {origin:`http://127.0.0.1:${proxy.address().port}`,proxy};
}

test('cold catalog gates RPC admission once, then bounded readiness uses the guest application RPC',async t=>{
  const seen=[];let finish;
  const {origin}=await serve(t,(req,res)=>{
    seen.push(req.url);
    if(req.url==='/healthz/ready'){reply(res,{ready:true});return;}
    if(req.url==='/function/home_feed'){finish=()=>reply(res,{ok:true,data:{result:feed}});return;}
    if(req.url==='/function/current_session'){assert.equal(req.headers.authorization,undefined);reply(res,{ok:true,data:{result:guest}});return;}
    reply(res,{ok:true});
  },{readinessDeadlineMs:80});
  for(let i=0;i<100&&!finish;i++)await pause(5);
  assert.equal(typeof finish,'function','startup must run the full catalog');
  const before=await fetch(origin+'/function/claim_offer',{method:'POST',body:'{}'});
  assert.equal(before.status,503,'no graph request may be admitted before catalog acceptance');
  assert.equal(seen.includes('/function/claim_offer'),false,'pending admission must have no upstream side effect');
  const began=performance.now(),pending=await fetch(origin+'/healthz');
  assert.equal(pending.status,503);assert.ok(performance.now()-began<1000);
  finish();await pause(30);
  for(const ready of await Promise.all([fetch(origin+'/healthz'),fetch(origin+'/healthz')])) {
    assert.equal(ready.status,200);
    assert.deepEqual(await ready.json(),{ready:true});
  }
  assert.equal(seen.filter(path=>path==='/function/home_feed').length,1,'periodic health must not repeat catalog traversal');
  assert.equal(seen.filter(path=>path==='/function/current_session').length,2);
});

test('uncertain startup completion keeps admission closed and never retries the catalog',async t=>{
  let catalogs=0;
  const {origin,proxy}=await serve(t,(req,res)=>{
    if(req.url==='/healthz/ready'){reply(res,{ready:true});return;}
    catalogs++;res.writeHead(200,{'content-type':'application/json'});res.write('{"ok":');
  },{upstreamDeadlineMs:80});
  await pause(130);
  assert.equal(proxy.ingressStatus().serialization.closed,true);
  assert.equal(proxy.ingressStatus().startupCatalog,'failed');
  for(let i=0;i<2;i++)assert.equal((await fetch(origin+'/healthz')).status,503);
  assert.equal((await fetch(origin+'/function/claim_offer',{method:'POST',body:'{}'})).status,503);
  assert.equal(catalogs,1);
});

test('closing the gateway during catalog acceptance cannot reopen its lane or admission',async t=>{
  let finish;
  const {proxy}=await serve(t,(req,res)=>{
    if(req.url==='/healthz/ready'){reply(res,{ready:true});return;}
    finish=()=>reply(res,{ok:true,data:{result:feed}});
  });
  for(let i=0;i<100&&!finish;i++)await pause(5);
  assert.equal(typeof finish,'function');
  const closed=once(proxy,'close');proxy.close();await closed;
  finish();await pause(30);
  assert.equal(proxy.ingressStatus().serialization.closed,true);
  assert.equal(proxy.ingressStatus().startupCatalog,'failed');
});

test('failed full startup catalog preserves all original feed-shape refusals and never admits RPCs',async t=>{
  for(const [status,body] of [
    [404,{detail:'private missing catalog'}],[500,{ok:false,error:'private storage diagnostic'}],
    [200,{ok:false,data:{result:feed}}],
    ...[null,{items:{},favorites:[]},{items:[],favorites:[]},
      {...feed,items:[null]},{...feed,favorites:[null]}].map(result=>[200,{ok:true,data:{result}}])]) {
    const seen=[];
    const {origin}=await serve(t,(req,res)=>{seen.push(req.url);req.url==='/healthz/ready'?reply(res,{ready:true}):reply(res,body,status);});
    await pause(30);
    assert.equal((await fetch(origin+'/healthz')).status,503);
    assert.equal((await fetch(origin+'/function/claim_offer',{method:'POST',body:'{}'})).status,503);
    assert.equal(seen.includes('/function/claim_offer'),false,'failed catalog must have no upstream claim side effect');
  }
});

test('an application storage failure makes periodic readiness unhealthy without repeating a startup catalog',async t=>{
  let sessionStatus=200,feeds=0;
  const {origin}=await serve(t,(req,res)=>{
    if(req.url==='/healthz/ready'){reply(res,{ready:true});return;}
    if(req.url==='/function/home_feed'){feeds++;reply(res,{ok:true,data:{result:feed}});return;}
    assert.equal(req.url,'/function/current_session');
    reply(res,sessionStatus===200?{ok:true,data:{result:guest}}:{ok:false,error:'private storage diagnostic'},sessionStatus);
  });
  await pause(30);assert.equal((await fetch(origin+'/healthz')).status,200);
  sessionStatus=500;
  const failed=await fetch(origin+'/healthz');assert.equal(failed.status,503);
  assert.deepEqual(await failed.json(),{ready:false});assert.equal(feeds,1);
});
