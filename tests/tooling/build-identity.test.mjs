import assert from 'node:assert/strict';
import http from 'node:http';
import {once} from 'node:events';
import test from 'node:test';
import {createShareProxy} from '../../scripts/phone-share-proxy.mjs';

const identity={schema:1,status:'known',build_id:'a'.repeat(64),source_sha:'b'.repeat(40),source_tree:'c'.repeat(40),
  artifact_sha256:'d'.repeat(64),dependency_archive_sha256:'e'.repeat(64),
  serving_mode:'source-at-fixed-canonical-entry',verification:'launch-snapshot'};

async function serve(t,buildIdentity,options={},handler) {
  let forwarded=0;
  const upstream=http.createServer((req,res)=>{forwarded++;if(handler){handler(req,res);return;}res.setHeader('x-mlocal-build','spoofed');res.end('app');});
  upstream.listen(0,'127.0.0.1');await once(upstream,'listening');
  const proxy=createShareProxy({upstreamHost:'127.0.0.1',upstreamPort:upstream.address().port,
    buildIdentity,secureProductionIngress:true,...options});
  proxy.listen(0,'127.0.0.1');await once(proxy,'listening');
  t.after(()=>{proxy.closeAllConnections();proxy.close();upstream.closeAllConnections();upstream.close();});
  return {origin:`http://127.0.0.1:${proxy.address().port}`,forwarded:()=>forwarded};
}

test('build routes return one frozen packaged snapshot without upstream RPC',async t=>{
  const input={...identity};
  const {origin,forwarded}=await serve(t,input);
  input.build_id='f'.repeat(64);
  const response=await fetch(origin+'/version.json?ignored=SECRET',{headers:{'x-mlocal-build':'spoofed',cookie:'SECRET'}});
  assert.equal(response.status,200);
  assert.deepEqual(await response.json(),identity);
  assert.equal(response.headers.get('cache-control'),'no-store');
  assert.equal(response.headers.get('x-content-type-options'),'nosniff');
  assert.equal(response.headers.get('x-mlocal-build'),identity.build_id);
  assert.equal(response.headers.get('server'),null);
  const page=await fetch(origin+'/build');
  assert.equal(page.status,200);
  const html=await page.text();
  assert.match(html,/M-Local build/);
  assert.ok(html.includes(identity.source_sha)&&html.includes(identity.build_id));
  assert.ok(!html.includes('SECRET'));
  for(const route of ['/version.json','/build']) {
    const head=await fetch(origin+route,{method:'HEAD'});
    assert.equal(head.status,200);assert.equal(await head.text(),'');
    assert.equal((await fetch(origin+route,{method:'POST',body:'{}'})).status,403);
  }
  assert.equal(forwarded(),0);
  const app=await fetch(origin+'/');
  assert.equal(app.headers.get('x-mlocal-build'),identity.build_id,'upstream header cannot label this gateway');
});

test('missing build metadata is unknown and never uses an environment SHA',async t=>{
  const previous=process.env.GITHUB_SHA;process.env.GITHUB_SHA='f'.repeat(40);
  t.after(()=>{if(previous===undefined)delete process.env.GITHUB_SHA;else process.env.GITHUB_SHA=previous;});
  const {origin,forwarded}=await serve(t);
  const response=await fetch(origin+'/version.json');assert.equal(response.status,200);
  const value=await response.json();assert.equal(value.status,'unknown');
  for(const key of ['build_id','source_sha','source_tree','artifact_sha256','dependency_archive_sha256'])assert.equal(value[key],null);
  assert.equal(forwarded(),0);
});

test('malformed or sensitive metadata refuses with a fixed diagnostic',()=>{
  for(const value of ['{SECRET',JSON.stringify({...identity,source_sha:'/private/SECRET'}),
    {...identity,configuration:{password:'SECRET'}},{...identity,verification:'runtime-git'}]) {
    assert.throws(()=>createShareProxy({buildIdentity:value}),error=>{
      assert.equal(error.message,'Invalid M-Local build identity.');return true;
    });
  }
});


test('different package launches change identity without changing helper code',async t=>{
  const next={...identity,build_id:'f'.repeat(64),source_sha:'f'.repeat(40)};
  const a=await serve(t,identity),b=await serve(t,next);
  assert.deepEqual(await(await fetch(a.origin+'/version.json')).json(),identity);
  assert.deepEqual(await(await fetch(b.origin+'/version.json')).json(),next);
});

test('known and unknown build pages leave readiness gates unchanged',async t=>{
  const guest={authenticated:false,actor_id:'',role:'guest',restaurant_id:'',display_name:'',is_demo:false,
    email_verified:false,business_account:false,merchant_paused:false,catalog_activity:false};
  for(const snapshot of [identity,undefined]) {
    let ready=false;
    const server=await serve(t,snapshot,{healthCheck:true},(req,res)=>{
      res.writeHead(200,{'content-type':'application/json'});
      if(req.url==='/healthz/ready')res.end(JSON.stringify({ready}));
      else res.end(JSON.stringify({ok:true,data:{result:guest}}));
    });
    assert.equal((await fetch(server.origin+'/version.json')).status,200);
    assert.equal((await fetch(server.origin+'/build')).status,200);
    assert.equal(server.forwarded(),0);
    assert.deepEqual(await(await fetch(server.origin+'/healthz')).json(),{ready:false});
    ready=true;
    const health=await fetch(server.origin+'/healthz');
    assert.equal(health.status,200);assert.deepEqual(await health.json(),{ready:true});
  }
});
