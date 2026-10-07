import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { gzipSync } from 'node:zlib';
import test from 'node:test';
import { createShareProxy } from '../../scripts/phone-share-proxy.mjs';

const emptyFeed={items:[],favorites:[],note:'',price_range:'',total_deals:0,signed_in:false,personalized:false,completed:false};
const guest={authenticated:false,actor_id:'',role:'guest',restaurant_id:'',display_name:'',is_demo:false,
  email_verified:false,business_account:false,catalog_activity:false};

async function serve(t, handler, options = {}) {
  const upstream = http.createServer(handler).listen(0, '127.0.0.1');
  await once(upstream, 'listening');
  const proxy = createShareProxy({ upstreamHost: '127.0.0.1', upstreamPort: upstream.address().port, ...options });
  proxy.listen(0, '127.0.0.1');
  await once(proxy, 'listening');
  t.after(() => {
    proxy.closeAllConnections(); proxy.close();
    upstream.closeAllConnections(); upstream.close();
  });
  return `http://127.0.0.1:${proxy.address().port}`;
}

test('public ingress refuses password sign-in and still forwards email verification', async t => {
  const forwarded=[];
  const origin=await serve(t,(req,res)=>{forwarded.push(req.url);res.end('{}');});
  assert.equal((await fetch(origin+'/user/login',{method:'POST',body:'{}'})).status,403);
  assert.equal((await fetch(origin+'/function/request_email_code',{method:'POST',body:'{}'})).status,200);
  assert.equal((await fetch(origin+'/function/verify_email_code',{method:'POST',body:'{}'})).status,200);
  assert.deepEqual(forwarded,['/function/request_email_code','/function/verify_email_code']);
});

test('host readiness reflects the backend and does not expose its diagnostics', async t => {
  let ready = false;
  const origin = await serve(t, (req, res) => {
    if(req.url === '/function/current_session') {
      assert.equal(req.method, 'POST');
      assert.equal(req.headers.authorization, undefined);
      res.writeHead(200, {'content-type':'application/json'});
      res.end(JSON.stringify({ok:true,data:{result:guest}}));
      return;
    }
    assert.equal(req.url, '/healthz/ready');
    res.writeHead(ready ? 200 : 503, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ready,status:ready?'ready':'not_ready',private:'backend diagnostics'}));
  }, { healthCheck: true });
  let response = await fetch(origin + '/healthz');
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { ready: false });
  ready = true;
  response = await fetch(origin + '/healthz');
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ready: true });
  assert.equal((await fetch(origin + '/ready')).status, 403);
  assert.equal((await fetch(origin + '/healthz/ready')).status, 403);
});

test('periodic readiness requires a canonical guest application RPC and redacts failures', async t => {
  let status=404, body={detail:'private missing endpoint diagnostics'};
  const origin=await serve(t,(req,res)=>{
    if(req.url==='/healthz/ready'){res.writeHead(200,{'content-type':'application/json'});res.end('{"ready":true}');return;}
    assert.equal(req.url,'/function/current_session');
    res.writeHead(status,{'content-type':'application/json'});res.end(JSON.stringify(body));
  },{healthCheck:true});
  for(const failure of [
    [404,{detail:'private missing endpoint diagnostics'}],
    [500,{ok:false,error:'private backend diagnostics'}],
    [200,{ok:false,data:{result:guest}}],
    [200,{ok:true,data:{result:null}}],
    [200,{ok:true,data:{result:{}}}],
    [200,{ok:true,data:{result:{...guest,authenticated:'false'}}}],
    [200,{ok:true,data:{result:{...guest,actor_id:'private actor'}}}],
    [200,{ok:true,data:{result:{...guest,role:'merchant'}}}],
    [200,{ok:true,data:{result:{...guest,extra:'private diagnostic'}}}]
  ]) {
    [status,body]=failure;
    const response=await fetch(origin+'/healthz');
    assert.equal(response.status,503,`unusable application response must be unhealthy: ${JSON.stringify(failure)}`);
    assert.deepEqual(await response.json(),{ready:false});
  }
  status=200;body={ok:true,data:{result:guest}};
  const response=await fetch(origin+'/healthz');
  assert.equal(response.status,200);
  assert.deepEqual(await response.json(),{ready:true});
});

test('compressed API responses retain their encoding and parse correctly on a phone', async t => {
  const origin = await serve(t, (req, res) => {
    res.writeHead(200, { 'content-type': 'application/json', 'content-encoding': 'gzip' });
    res.end(gzipSync('{"ok":true,"data":[{"title":"Lunch special"}]}'));
  });
  const response = await fetch(origin + '/function/list_offers', { method: 'POST', body: '{}' });
  assert.match(response.headers.get('content-type'), /application\/json/);
  assert.equal(response.headers.get('content-encoding'), 'gzip');
  assert.deepEqual(await response.json(), { ok: true, data: [{ title: 'Lunch special' }] });
});

test('readiness fails within its deadline when the application response never completes', {timeout:10000}, async t => {
  const origin=await serve(t,(req,res)=>{
    if(req.url==='/healthz/ready'){res.writeHead(200,{'content-type':'application/json'});res.end('{"ready":true}');return;}
    res.writeHead(200,{'content-type':'application/json'});
    res.write('{"ok":');
  },{healthCheck:true});
  const response=await fetch(origin+'/healthz');
  assert.equal(response.status,503);
  assert.deepEqual(await response.json(),{ready:false});
});

test('native readiness must be canonical JSON ready true before any application probe',async t=>{
  let nativeStatus=200,nativeBody='{}',nativeType='application/json',seen=[];
  const origin=await serve(t,(req,res)=>{
    seen.push(req.url);
    if(req.url==='/function/current_session') {
      res.writeHead(200,{'content-type':'application/json'});
      res.end(JSON.stringify({ok:true,data:{result:guest}}));return;
    }
    res.writeHead(nativeStatus,{'content-type':nativeType});res.end(nativeBody);
  },{healthCheck:true});
  for(const invalid of [
    [200,'{}','application/json'],
    [200,'{"ready":false}','application/json'],
    [200,'{"ready":"true"}','application/json'],
    [200,'{"ready":1}','application/json'],
    [200,'{"status":"ready"}','application/json'],
    [200,'{"ready":','application/json'],
    [200,'<html>App shell</html>','text/html'],
    [200,'{"ready":true}','text/html'],
    [503,'{"ready":true}','application/json'],
    [200,'x'.repeat(65537),'application/json'],
  ]) {
    [nativeStatus,nativeBody,nativeType]=invalid;seen=[];
    const response=await fetch(origin+'/healthz');
    assert.equal(response.status,503);
    assert.deepEqual(await response.json(),{ready:false});
    assert.deepEqual(seen,['/healthz/ready'],'unready native process must not reach the application probe');
  }
  nativeStatus=200;nativeBody='{"status":"ready","ready":true}';nativeType='application/json; charset=utf-8';seen=[];
  const response=await fetch(origin+'/healthz');
  assert.equal(response.status,200);assert.deepEqual(await response.json(),{ready:true});
  assert.deepEqual(seen,['/healthz/ready','/function/current_session']);
});

test('direct hosting cannot bypass signup limits by spoofing edge headers', async t => {
  const origin = await serve(t, (_req, res) => res.end('{}'), { trustCloudflare: false });
  for (let i = 0; i < 13; i++) {
    const response = await fetch(origin + '/function/request_email_code', {
      method: 'POST', body: '{}', headers: { 'cf-connecting-ip': `192.0.2.${i + 1}`, 'x-forwarded-for': `198.51.100.${i + 1}` },
    });
    assert.equal(response.status, i < 12 ? 200 : 429);
  }
});

test('trusted Render edge keeps different networks signup limits separate', async t => {
  const origin = await serve(t, (_req, res) => res.end('{}'), { trustCloudflare: true });
  for (let i = 0; i < 13; i++) {
    const response = await fetch(origin + '/function/request_email_code', {
      method: 'POST', body: '{}', headers: { 'cf-connecting-ip': '192.0.2.1' },
    });
    assert.equal(response.status, i < 12 ? 200 : 429);
  }
  assert.equal((await fetch(origin + '/function/request_email_code', {
    method: 'POST', body: '{}', headers: { 'cf-connecting-ip': '192.0.2.2' },
  })).status, 200);
});

test('Funnel uses its overwritten client IP and ignores spoofed Cloudflare headers', async t => {
  const origin = await serve(t, (_req, res) => res.end('{}'), { trustFunnel: true, trustCloudflare: false });
  for (let i = 0; i < 13; i++) {
    const response = await fetch(origin + '/function/request_email_code', {
      method: 'POST', body: '{}',
      headers: { 'x-forwarded-for': '192.0.2.1', 'cf-connecting-ip': `198.51.100.${i + 1}` },
    });
    assert.equal(response.status, i < 12 ? 200 : 429);
  }
  assert.equal((await fetch(origin + '/function/request_email_code', {
    method: 'POST', body: '{}', headers: { 'x-forwarded-for': '192.0.2.2' },
  })).status, 200, 'another network has its own request budget');
});
