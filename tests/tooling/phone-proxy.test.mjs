import assert from 'node:assert/strict';
import http from 'node:http';
import test from 'node:test';
import { createPhoneProxy } from '../../scripts/phone-proxy.mjs';

const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));

test('phone relay forwards application POST bodies and refuses admin routes', async () => {
  const requests = [];
  const upstream = http.createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    requests.push(req.url);
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ method: req.method, body, url: req.url }));
  });
  const upstreamPort = await listen(upstream);
  const proxy = createPhoneProxy({ upstreamHost: '127.0.0.1', upstreamPort });
  const port = await listen(proxy);
  try {
    const response = await fetch(`http://127.0.0.1:${port}/function/list_offers`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{"max_price":"5"}',
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { method: 'POST', body: '{"max_price":"5"}', url: '/function/list_offers' });
    for (const path of ['/admin/', '/%61dmin/', '/graph', '/introspect', '/openapi.json']) {
      assert.equal((await fetch(`http://127.0.0.1:${port}${path}`)).status, 403);
    }
    assert.equal(requests.length, 1);
    const entry = await fetch(`http://127.0.0.1:${port}/index.html?html-proxy&index=0.js`);
    assert.equal(entry.status, 200, 'Vite must be able to load the app entry module');
  } finally { proxy.stop(); upstream.closeAllConnections(); upstream.close(); }
});

test('phone relay reports a stopped app as an actionable 502', async () => {
  const temporary = http.createServer();
  const unavailablePort = await listen(temporary);
  await new Promise(resolve => temporary.close(resolve));
  const proxy = createPhoneProxy({ upstreamHost: '127.0.0.1', upstreamPort: unavailablePort });
  const port = await listen(proxy);
  try {
    const response = await fetch(`http://127.0.0.1:${port}/`);
    assert.equal(response.status, 502);
    assert.match(await response.text(), /Start M-Local/);
  } finally { proxy.stop(); }
});
