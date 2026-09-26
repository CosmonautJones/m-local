// Development-only Windows/Mac relay. Application and matching logic stay in Jac.
import http from 'node:http';
import os from 'node:os';
import { pathToFileURL } from 'node:url';

export function createPhoneProxy({ upstreamHost = 'localhost', upstreamPort = 8000 } = {}) {
  const sockets = new Set();
  const allowed = (req) => {
    try {
      const pathname = decodeURIComponent(new URL(req.url, 'http://local').pathname);
      if (pathname.startsWith('/function/') || pathname.startsWith('/user/')) return true;
      if (!['GET', 'HEAD'].includes(req.method)) return false;
      return pathname === '/' || pathname === '/index.html' || pathname === '/favicon.ico' || pathname === '/@react-refresh'
        || ['/compiled/', '/node_modules/', '/@vite/', '/@fs/', '/assets/'].some(p => pathname.startsWith(p));
    } catch { return false; }
  };
  const options = (req) => ({
    hostname: upstreamHost, port: upstreamPort, path: req.url, method: req.method,
    headers: { ...req.headers, host: `${upstreamHost}:${upstreamPort}` },
  });
  const server = http.createServer((req, res) => {
    if (!allowed(req)) { res.writeHead(403); res.end('Not available through the phone preview.'); return; }
    const upstream = http.request(options(req), response => {
      res.writeHead(response.statusCode, response.headers);
      response.pipe(res);
    });
    upstream.setTimeout(15000, () => upstream.destroy(new Error('Upstream timeout')));
    upstream.on('error', () => {
      if (!res.headersSent) res.writeHead(502, { 'content-type': 'text/plain' });
      res.end('Start M-Local on this computer at http://localhost:8000, then reload.');
    });
    req.on('aborted', () => upstream.destroy());
    req.pipe(upstream);
  });
  server.on('connection', socket => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });
  server.on('upgrade', (req, socket, head) => {
    if (!allowed(req) || req.headers['sec-websocket-protocol'] !== 'vite-hmr') {
      socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'); return;
    }
    const upstream = http.request(options(req));
    upstream.setTimeout(15000, () => upstream.destroy());
    upstream.on('upgrade', (response, peer, upstreamHead) => {
      upstream.setTimeout(0);
      socket.write(`HTTP/1.1 ${response.statusCode} ${response.statusMessage}\r\n`);
      for (let i = 0; i < response.rawHeaders.length; i += 2) {
        socket.write(`${response.rawHeaders[i]}: ${response.rawHeaders[i + 1]}\r\n`);
      }
      socket.write('\r\n');
      if (head.length) peer.write(head);
      if (upstreamHead.length) socket.write(upstreamHead);
      socket.pipe(peer).pipe(socket);
      socket.on('close', () => peer.destroy());
      peer.on('error', () => socket.destroy());
      socket.on('error', () => peer.destroy());
    });
    upstream.on('response', () => { upstream.destroy(); socket.destroy(); });
    upstream.on('error', () => socket.destroy());
    socket.on('close', () => upstream.destroy());
    upstream.end();
  });
  server.stop = () => { for (const socket of sockets) socket.destroy(); server.close(); };
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = process.argv.slice(2);
  if (args.some(arg => arg !== '--lan' && !/^--port=\d+$/.test(arg))) {
    console.error('Usage: node scripts/phone-proxy.mjs [--lan] [--port=8080]');
    process.exit(2);
  }
  const port = Number(args.find(arg => arg.startsWith('--port='))?.split('=')[1] || 8080);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Use a port from 1024 to 65535.');
  const lan = args.includes('--lan');
  const server = createPhoneProxy();
  server.on('error', error => { console.error(error.message); process.exitCode = 1; });
  server.listen(port, lan ? '0.0.0.0' : '127.0.0.1', () => {
    console.log(`Phone preview relay: http://127.0.0.1:${port}/ -> localhost:8000`);
    if (lan) {
      console.log('Use fictional demo data on a trusted network. Stop with Ctrl+C.');
      for (const [name, addresses] of Object.entries(os.networkInterfaces())) {
        for (const address of addresses || []) {
          if (address.family === 'IPv4' && !address.internal) console.log(`${name}: http://${address.address}:${port}/`);
        }
      }
    } else console.log('Local only. Add --lan when ready to test from a phone on the same network.');
  });
  process.on('SIGINT', () => server.stop());
  process.on('SIGTERM', () => server.stop());
}
