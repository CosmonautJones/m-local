import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import test from 'node:test';
import { createShareProxy } from '../../scripts/phone-share-proxy.mjs';

test('oversized declared and chunked RPC bodies never reach the app', async t => {
  let reached=0;
  const upstream=http.createServer((req,res)=>{reached++;req.resume();res.end('{}');}).listen(0,'127.0.0.1');
  await once(upstream,'listening');
  const proxy=createShareProxy({upstreamHost:'127.0.0.1',upstreamPort:upstream.address().port}).listen(0,'127.0.0.1');
  await once(proxy,'listening');
  t.after(()=>{proxy.closeAllConnections();proxy.close();upstream.closeAllConnections();upstream.close();});
  const url=`http://127.0.0.1:${proxy.address().port}/function/save_business_draft`;
  assert.equal((await fetch(url,{method:'POST',body:'x'.repeat(65*1024)})).status,413);
  const chunked=await new Promise((resolve,reject)=>{
    const request=http.request(url,{method:'POST',headers:{'transfer-encoding':'chunked'}},response=>{
      response.resume();response.on('end',()=>resolve(response.statusCode));
    });
    request.on('error',reject);
    request.write('x'.repeat(32*1024));request.write('x'.repeat(32*1024));request.end('x');
  });
  assert.equal(chunked,413);
  assert.equal(reached,0,'body rejection happens before forwarding any RPC');
  const valid=await fetch(url,{method:'POST',body:JSON.stringify({menu_text:'x'.repeat(4000)})});
  assert.equal(valid.status,200);assert.equal(reached,1);
});

test('phone link forwards app/auth traffic but never development files or admin APIs', async t => {
  const seen = [];
  const upstream = http.createServer((req, res) => {
    seen.push(req.url);
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ authorization: req.headers.authorization, path: req.url }));
  }).listen(0, '127.0.0.1');
  await once(upstream, 'listening');
  const proxy = createShareProxy({ upstreamHost: '127.0.0.1', upstreamPort: upstream.address().port });
  proxy.listen(0, '127.0.0.1');
  await once(proxy, 'listening');
  t.after(() => { proxy.closeAllConnections(); proxy.close(); upstream.closeAllConnections(); upstream.close(); });
  const origin = `http://127.0.0.1:${proxy.address().port}`;
  for (const path of ['/', '/static/client.js?hash=abc', '/assets/index-Ab12.js', '/assets/index-Ab12.css',
    '/static/assets/brand/logo-compact.png', '/static/assets/brand/logo-reversed.png', '/static/assets/brand/logo-master.png',
    '/static/assets/brand/app-icon.png', '/static/assets/brand/Figtree.ttf']) {
    assert.equal((await fetch(origin + path)).status, 200, path);
  }
  for (const path of ['/function/list_offers', '/function/current_session',
    '/function/request_email_code', '/function/verify_email_code', '/function/get_business_draft',
    '/function/import_business_website', '/function/save_business_draft', '/function/get_business_profile',
    '/function/get_account_profile', '/function/save_account_profile', '/function/merchant_insights',
    '/function/home_feed', '/function/taste_choices', '/function/save_taste', '/function/toggle_favorite', '/function/nearby_after']) {
    const response = await fetch(origin + path, { method: 'POST', body: '{}', headers: { authorization: 'Bearer test-only' } });
    assert.equal(response.status, 200, path);
    assert.equal((await response.json()).authorization, 'Bearer test-only');
  }
  const before = seen.length;
  for (const path of ['/graph/data', '/docs', '/openapi.json', '/.env', '/@fs/etc/passwd',
    '/node_modules/foo', '/compiled/main.js', '/assets/private.map', '/assets/%2e%2e/.env',
    '/function/internal_admin', '/user/login', '/user/register', '/user/delete',
    '/static/assets/brand/OFL.txt', '/static/assets/brand/README.md', '/static/assets/brand/%2e%2e/x.png',
    '/static/assets/other/logo.png', '/static/assets/brand/sub/logo.png', '/static/main.jac']) {
    assert.equal((await fetch(origin + path, { method: 'POST', body: '{}' })).status, 403, path);
    assert.equal((await fetch(origin + path)).status, 403, path);
  }
  assert.equal(seen.length, before, 'blocked traffic never reaches Jac');
});

test('four simultaneous testers share a network while excess signup requests stay bounded', async t => {
  let reached=0;
  const upstream=http.createServer((req,res)=>{reached++;res.end('{}');}).listen(0,'127.0.0.1');
  await once(upstream,'listening');
  const proxy=createShareProxy({upstreamHost:'127.0.0.1',upstreamPort:upstream.address().port}).listen(0,'127.0.0.1');
  await once(proxy,'listening');
  t.after(()=>{proxy.closeAllConnections();proxy.close();upstream.closeAllConnections();upstream.close();});
  const url=`http://127.0.0.1:${proxy.address().port}/function/request_email_code`;
  const firstGroup=await Promise.all(Array.from({length:4},(_,i)=>fetch(url,{
    method:'POST',body:JSON.stringify({value:`tester${i}@example.test`}),
  })));
  assert.deepEqual(firstGroup.map(response=>response.status),[200,200,200,200]);
  for(let i=4;i<12;i++)assert.equal((await fetch(url,{method:'POST',body:JSON.stringify({value:`different${i}@example.test`})})).status,200);
  const blocked=await fetch(url,{method:'POST',body:'{}'});
  assert.equal(blocked.status,429);assert.ok(Number(blocked.headers.get('retry-after'))>0);
  assert.equal(reached,12,'denied requests must not reach the mail sender');
});

test('offline app returns a recoverable 502 without filesystem details', async t => {
  const unused = http.createServer().listen(0, '127.0.0.1');
  await once(unused, 'listening');
  const port = unused.address().port;
  await new Promise(resolve => unused.close(resolve));
  const proxy = createShareProxy({ upstreamHost: '127.0.0.1', upstreamPort: port });
  proxy.listen(0, '127.0.0.1');
  await once(proxy, 'listening');
  t.after(() => { proxy.closeAllConnections(); proxy.close(); });
  const response = await fetch(`http://127.0.0.1:${proxy.address().port}/`);
  assert.equal(response.status, 502);
  assert.match(await response.text(), /starting|unavailable/i);
});
