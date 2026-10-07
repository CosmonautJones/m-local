import assert from 'node:assert/strict';
import http from 'node:http';
import {once} from 'node:events';
import test from 'node:test';
import {createShareProxy} from '../../scripts/phone-share-proxy.mjs';

const emptyFeed={items:[],favorites:[],note:'',price_range:'',total_deals:0,signed_in:false,personalized:false,completed:false};
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));

async function serve(t,handler,options={}) {
  const upstream=http.createServer(handler).listen(0,'127.0.0.1');
  await once(upstream,'listening');
  const proxy=createShareProxy({upstreamHost:'127.0.0.1',upstreamPort:upstream.address().port,trustCloudflare:false,...options}).listen(0,'127.0.0.1');
  await once(proxy,'listening');
  t.after(()=>{proxy.closeAllConnections();proxy.close();upstream.closeAllConnections();upstream.close();});
  return {origin:`http://127.0.0.1:${proxy.address().port}`,proxy};
}

test('ingress security policy overrides upstream headers on success and refusal',async t=>{
  const {origin}=await serve(t,(_req,res)=>{
    res.writeHead(200,{'content-security-policy':"default-src *",'x-content-type-options':'unsafe',
      'referrer-policy':'unsafe-url','permissions-policy':'camera=*','strict-transport-security':'max-age=1',
      'server':'private backend version','x-powered-by':'private runtime','cache-control':'public'});
    res.end('ok');
  });
  for(const path of ['/','/openapi.json']) {
    const response=await fetch(origin+path);
    assert.equal(response.headers.get('x-content-type-options'),'nosniff');
    assert.equal(response.headers.get('referrer-policy'),'strict-origin-when-cross-origin');
    assert.equal(response.headers.get('permissions-policy'),'camera=(self), microphone=(), geolocation=()');
    assert.equal(response.headers.get('cache-control'),'no-store');
    assert.match(response.headers.get('content-security-policy'),/frame-ancestors 'none'/);
    assert.match(response.headers.get('content-security-policy'),/object-src 'none'/);
    assert.equal(response.headers.get('server'),null);
    assert.equal(response.headers.get('x-powered-by'),null);
    assert.equal(response.headers.get('strict-transport-security'),null,'HTTP and dev do not set HSTS');
  }
});

test('HSTS requires explicit verified secure production ingress',async t=>{
  const {origin}=await serve(t,(_req,res)=>res.end('ok'),{secureProductionIngress:true});
  assert.equal((await fetch(origin)).headers.get('strict-transport-security'),'max-age=31536000');
});

test('serialization holds every upstream request until its entire response ends',async t=>{
  const seen=[];
  let finishFirst;
  const {origin}=await serve(t,(req,res)=>{
    seen.push(req.url);
    if(seen.length===1){res.writeHead(200);res.write('first');finishFirst=()=>res.end(' completed');}
    else res.end('second');
  },{deploymentTopology:'single-instance-serialized'});
  const first=await fetch(origin+'/static/client.js');
  const secondPromise=fetch(origin+'/function/claim_offer',{method:'POST',body:'{}'});
  await pause(40);
  assert.deepEqual(seen,['/static/client.js'],'response headers must not release the gate');
  finishFirst();
  assert.equal(await first.text(),'first completed');
  assert.equal(await (await secondPromise).text(),'second');
  assert.deepEqual(seen,['/static/client.js','/function/claim_offer']);
});

test('readiness metadata and guest application probes use the same serialized gate',async t=>{
  const seen=[];
  let finishFirst;
  const {origin}=await serve(t,(req,res)=>{
    seen.push(req.url);
    if(req.url==='/function/claim_offer'){res.writeHead(200);res.write('{}');finishFirst=()=>res.end();}
    else if(req.url==='/healthz/ready'){res.writeHead(200,{'content-type':'application/json'});res.end('{"ready":true}');}
    else {res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({ok:true,data:{result:{
      authenticated:false,actor_id:'',role:'guest',restaurant_id:'',display_name:'',is_demo:false,
      email_verified:false,business_account:false,catalog_activity:false}}}));}
  },{deploymentTopology:'single-instance-serialized',healthCheck:true});
  const first=await fetch(origin+'/function/claim_offer',{method:'POST',body:'{}'});
  const ready=fetch(origin+'/healthz');
  await pause(40);
  assert.deepEqual(seen,['/function/claim_offer']);
  finishFirst();await first.text();
  const response=await ready;
  assert.equal(response.status,200);
  assert.deepEqual(await response.json(),{ready:true});
  assert.deepEqual(seen,['/function/claim_offer','/healthz/ready','/function/current_session']);
});

test('queue saturation and waiting deadline never forward rejected work',async t=>{
  const seen=[];
  let finish;
  const {origin}=await serve(t,(req,res)=>{
    seen.push(req.url);res.writeHead(200);res.write('busy');finish=()=>res.end();
  },{deploymentTopology:'single-instance-serialized',maxQueuedRequests:1,queueWaitMs:100});
  const active=await fetch(origin+'/');
  const queued=fetch(origin+'/function/get_offer',{method:'POST',body:'{}'});
  await pause(15);
  const full=await fetch(origin+'/function/current_session',{method:'POST',body:'{}'});
  assert.equal(full.status,503);assert.equal(full.headers.get('retry-after'),'1');
  assert.equal((await queued).status,503);
  assert.deepEqual(seen,['/']);
  finish();await active.text();
});

test('active deadline fails closed including readiness until coordinated restart',async t=>{
  let reached=0;
  const events=[];
  const {origin,proxy}=await serve(t,(_req,res)=>{reached++;res.writeHead(200);res.write('unfinished');},
    {deploymentTopology:'single-instance-serialized',upstreamDeadlineMs:80,healthCheck:true,eventSink:event=>events.push(event)});
  const response=await fetch(origin+'/');
  await assert.rejects(response.text());
  assert.equal((await fetch(origin+'/function/claim_offer',{method:'POST',body:'{}'})).status,503);
  assert.equal((await fetch(origin+'/healthz')).status,503);
  assert.equal(reached,1,'uncertain upstream completion may not overlap later requests');
  assert.equal(proxy.ingressStatus().serialization.closed,true);
  assert.ok(events.some(event=>event.code==='UPSTREAM_DEADLINE'));
});

test('client abort drains an active response before permitting the next request',async t=>{
  const seen=[];
  let finish;
  const {origin}=await serve(t,(req,res)=>{
    seen.push(req.url);
    if(seen.length===1){res.writeHead(200);res.write('working');finish=()=>res.end();}
    else res.end('next');
  },{deploymentTopology:'single-instance-serialized'});
  const request=http.get(origin);
  const [response]=await once(request,'response');
  response.destroy();request.destroy();
  const next=fetch(origin+'/function/current_session',{method:'POST',body:'{}'});
  await pause(40);assert.deepEqual(seen,['/']);
  finish();assert.equal(await (await next).text(),'next');
});

test('development keeps parallel forwarding without topology opt-in',async t=>{
  let active=0,max=0;
  const {origin}=await serve(t,(_req,res)=>{active++;max=Math.max(max,active);setTimeout(()=>{active--;res.end('ok');},30);});
  await Promise.all([fetch(origin),fetch(origin)]);
  assert.equal(max,2);
});

test('paused asset recipients cannot close serialization or block later RPCs',async t=>{
  for(const size of [1,2,16].map(mib=>mib*1024*1024)) {
    await t.test(`${size/1024/1024} MiB asset`,async t=>{
      const {origin,proxy}=await serve(t,(req,res)=>{
        if(req.url==='/static/client.js') {
          res.writeHead(200,{'content-length':String(size)});res.end(Buffer.alloc(size,97));
        } else res.end('{}');
      },{deploymentTopology:'single-instance-serialized',upstreamDeadlineMs:200});
      const request=http.get(origin+'/static/client.js');
      request.on('error',()=>{});
      const [response]=await once(request,'response');
      response.on('error',()=>{});response.pause();
      t.after(()=>{response.destroy();request.destroy();});
      await pause(300);
      assert.equal(proxy.ingressStatus().serialization.closed,false,'downstream backpressure is not uncertain native completion');
      assert.equal((await fetch(origin+'/function/current_session',{method:'POST',body:'{}'})).status,200);
    });
  }
});

test('incomplete mutation response still closes the lane when its recipient pauses',async t=>{
  let reached=0;
  const {origin,proxy}=await serve(t,(_req,res)=>{
    reached++;res.writeHead(200);res.write('accepted but unfinished');
  },{deploymentTopology:'single-instance-serialized',upstreamDeadlineMs:100});
  const request=http.request(origin+'/function/claim_offer',{method:'POST'});
  request.on('error',()=>{});request.end('{}');
  const [response]=await once(request,'response');
  response.on('error',()=>{});response.pause();
  t.after(()=>{response.destroy();request.destroy();});
  await pause(150);
  assert.equal(proxy.ingressStatus().serialization.closed,true);
  assert.equal((await fetch(origin+'/function/current_session',{method:'POST',body:'{}'})).status,503);
  assert.equal(reached,1);
});

test('paused deliveries share one fixed memory budget across client connections',async t=>{
  const events=[];
  const size=7*1024*1024;
  const {origin,proxy}=await serve(t,(_req,res)=>{
    res.writeHead(200,{'content-length':String(size)});res.end(Buffer.alloc(size,97));
  },{deploymentTopology:'single-instance-serialized',upstreamDeadlineMs:1000,eventSink:event=>events.push(event)});
  // Hold downstream finish deterministically. Kernel socket-buffer sizes can
  // otherwise deliver a complete body before an application pauses its reader.
  // The native response and serialized completion path remain unchanged.
  const pendingEnds=[];
  proxy.on('request',(req,res)=>{
    if(req.url!=='/static/client.js')return;
    const end=res.end;
    res.end=function(...args){pendingEnds.push(()=>end.apply(res,args));return res;};
  });
  t.after(()=>{for(const finish of pendingEnds)finish();});
  for(let i=0;i<4;i++) {
    const request=http.get(origin+'/static/client.js');
    request.on('error',()=>{});
    const [response]=await once(request,'response');
    response.on('error',()=>{});response.pause();
    t.after(()=>{response.destroy();request.destroy();});
    for(let attempt=0;attempt<100&&proxy.ingressStatus().serialization.active;attempt++) {
      assert.ok(proxy.ingressStatus().delivery.bytes<=16*1024*1024);
      await pause(5);
    }
    assert.equal(proxy.ingressStatus().serialization.active,false);
    assert.equal(proxy.ingressStatus().serialization.closed,false);
  }
  assert.ok(events.some(event=>event.code==='DELIVERY_LIMIT'),'combined output is bounded across sockets');
  assert.ok(proxy.ingressStatus().delivery.bytes<=proxy.ingressStatus().delivery.maxBytes);
});

test('aborting a queued request removes it without native execution or closing the lane',async t=>{
  const seen=[];
  let finish;
  const {origin,proxy}=await serve(t,(req,res)=>{
    seen.push(req.url);
    if(seen.length===1){res.writeHead(200);res.write('busy');finish=()=>res.end();}
    else res.end('ok');
  },{deploymentTopology:'single-instance-serialized',maxQueuedRequests:1});
  const active=await fetch(origin);
  const cancelled=http.request(origin+'/function/get_offer',{method:'POST'});
  cancelled.on('error',()=>{});cancelled.end('{}');
  for(let i=0;i<20&&proxy.ingressStatus().serialization.queued===0;i++)await pause(5);
  assert.equal(proxy.ingressStatus().serialization.queued,1);
  cancelled.destroy();
  for(let i=0;i<20&&proxy.ingressStatus().serialization.queued!==0;i++)await pause(5);
  assert.equal(proxy.ingressStatus().serialization.queued,0);
  assert.equal(proxy.ingressStatus().serialization.closed,false);
  finish();await active.text();
  assert.equal((await fetch(origin+'/function/current_session',{method:'POST',body:'{}'})).status,200);
  assert.deepEqual(seen,['/','/function/current_session']);
});

test('incomplete upstream socket failure closes the lane rather than replaying a write',async t=>{
  let reached=0;
  const {origin,proxy}=await serve(t,(_req,res)=>{
    reached++;res.writeHead(200,{'content-length':'1000'});res.write('partial');setImmediate(()=>res.destroy());
  },{deploymentTopology:'single-instance-serialized',healthCheck:true});
  await assert.rejects(async()=>{const response=await fetch(origin);await response.text();});
  for(let i=0;i<20&&!proxy.ingressStatus().serialization.closed;i++)await pause(5);
  assert.equal(proxy.ingressStatus().serialization.closed,true);
  assert.equal((await fetch(origin+'/function/claim_offer',{method:'POST',body:'{}'})).status,503);
  assert.equal((await fetch(origin+'/healthz')).status,503);
  assert.equal(reached,1);
});

test('a complete upstream error records a redacted event and releases serialization',async t=>{
  const events=[];
  let reached=0;
  const {origin,proxy}=await serve(t,(_req,res)=>{reached++;res.writeHead(reached===1?500:200);res.end('{}');},
    {deploymentTopology:'single-instance-serialized',eventSink:event=>{events.push(event);throw new Error('sink unavailable');}});
  assert.equal((await fetch(origin)).status,500);
  assert.equal((await fetch(origin)).status,200);
  assert.equal(proxy.ingressStatus().serialization.closed,false);
  assert.equal(events[0].code,'UPSTREAM_5XX');
});

test('serialized chunked body rejection occurs before queueing or forwarding',async t=>{
  let reached=0;
  const {origin,proxy}=await serve(t,(_req,res)=>{reached++;res.end('{}');},
    {deploymentTopology:'single-instance-serialized'});
  const status=await new Promise((resolve,reject)=>{
    const request=http.request(origin+'/function/save_business_draft',{method:'POST',headers:{'transfer-encoding':'chunked'}},response=>{
      response.resume();response.on('end',()=>resolve(response.statusCode));
    });
    request.on('error',reject);request.write('x'.repeat(32768));request.end('x'.repeat(32769));
  });
  assert.equal(status,413);assert.equal(reached,0);
  assert.equal(proxy.ingressStatus().serialization.queued,0);
  assert.equal(proxy.ingressStatus().failures.BODY_TOO_LARGE,1);
});

test('failure events and counters omit request bodies, credentials, IPs and query values',async t=>{
  const events=[];
  const {origin,proxy}=await serve(t,(_req,res)=>res.end('{}'),{eventSink:event=>events.push(event)});
  const headers={authorization:'Bearer SECRET_TOKEN',cookie:'SECRET_COOKIE','cf-connecting-ip':'192.0.2.99'};
  await fetch(origin+'/user/register?email=SECRET_EMAIL',{method:'POST',headers,body:'SECRET_BODY'});
  await fetch(origin+'/function/save_business_draft?token=SECRET_QUERY',{method:'POST',headers,body:'x'.repeat(65537)});
  for(let i=0;i<13;i++)await fetch(origin+'/function/request_email_code',{method:'POST',headers,body:'{}'});
  const text=JSON.stringify({events,status:proxy.ingressStatus()});
  assert.doesNotMatch(text,/SECRET|192\.0\.2\.99|authorization|cookie/i);
  assert.ok(events.some(event=>event.code==='ROUTE_DENIED'));
  assert.ok(events.some(event=>event.code==='BODY_TOO_LARGE'));
  assert.ok(events.some(event=>event.code==='ONBOARDING_RATE_LIMITED'));
  assert.equal(proxy.ingressStatus().failures.ROUTE_DENIED,1);
});

test('invalid selected topology is rejected instead of silently parallel serving',()=>{
  assert.throws(()=>createShareProxy({deploymentTopology:'single-instance-threaded'}),/topology/i);
});

test('install metadata exposes only the exact public manifest and authored brand icons',async t=>{
  const reached=[];
  const {origin}=await serve(t,(req,res)=>{reached.push(req.url);res.end('public asset');});
  for(const path of ['/static/assets/manifest.webmanifest','/static/assets/brand/app-icon.svg',
                    '/static/assets/brand/app-icon-192.png','/static/assets/brand/app-icon-512.png']) {
    const response=await fetch(origin+path);
    assert.equal(response.status,200,path);
    assert.equal(await response.text(),'public asset');
  }
  const head=await fetch(origin+'/static/assets/manifest.webmanifest',{method:'HEAD'});
  assert.equal(head.status,200);
  const before=reached.length;
  for(const path of ['/static/assets/package.json','/static/assets/manifest.private.webmanifest',
                    '/static/assets/.env','/static/assets/%2e%2e/.env']) {
    assert.equal((await fetch(origin+path)).status,403,path);
  }
  assert.equal((await fetch(origin+'/static/assets/manifest.webmanifest',{method:'POST'})).status,403);
  assert.equal(reached.length,before,'private/static alternatives never reach native');
});

test('emitted lazy JavaScript chunks are readable assets without exposing private paths',async t=>{
  const reached=[],events=[];
  const {origin}=await serve(t,(req,res)=>{
    reached.push([req.method,req.url]);
    res.writeHead(req.url.endsWith('failed.js')?500:200,{'content-type':'text/javascript'});
    res.end('export const loaded=true;');
  },{eventSink:event=>events.push(event)});
  const path='/static/assets/index-DD9CTm96.js';
  const response=await fetch(origin+path);
  assert.equal(response.status,200);
  assert.match(response.headers.get('content-type'),/javascript/);
  assert.equal(await response.text(),'export const loaded=true;');
  assert.equal((await fetch(origin+path,{method:'HEAD'})).status,200);
  assert.equal((await fetch(origin+'/static/assets/failed.js')).status,500);
  assert.equal(events.at(-1).route,'asset');
  const before=reached.length;
  for(const blocked of ['/static/assets/private/key.pem','/static/assets/.env',
    '/static/assets/private/chunk.js','/static/assets/index-DD9CTm96.js.map',
    '/static/assets/%2e%2e/private/key.js','/static/assets/index.js%2fprivate']) {
    assert.equal((await fetch(origin+blocked)).status,403,blocked);
  }
  assert.equal((await fetch(origin+path,{method:'POST'})).status,403);
  assert.equal(reached.length,before,'private paths and asset writes never reach native');
});
