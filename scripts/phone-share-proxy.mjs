// Public app ingress: compiled assets and the app's exact RPCs only.
// Never place the development relay or the raw Jac server behind a tunnel.
import http from 'node:http';
import {isIP} from 'node:net';
import { pathToFileURL } from 'node:url';
import {createOnboardingLimit} from './onboarding-ingress.mjs';
import {validateHomeFeed} from '../client/feed-validation.mjs';

const functions = new Set(['list_offers', 'get_offer', 'claim_offer', 'merchant_portal',
  'update_profile', 'save_offer', 'set_offer_status', 'resolve_claim', 'redeem_claim',
  'cancel_claim', 'offer_defaults', 'current_session', 'request_email_code', 'verify_email_code',
  'get_business_draft', 'import_business_website', 'upload_business_photo', 'import_business_photo', 'save_business_draft', 'get_business_profile',
  'get_account_profile', 'save_account_profile', 'merchant_insights', 'local_activity', 'list_places', 'nearby_places',
  'home_feed', 'taste_choices', 'save_taste', 'toggle_favorite', 'nearby_after']);

export function createShareProxy({ upstreamHost = 'localhost', upstreamPort = 8200,
  trustCloudflare = true, trustFunnel = false, healthCheck = false } = {}) {
  const limit=createOnboardingLimit();
  return http.createServer((req, res) => {
    const path = req.url.split('?')[0];
    const read = ['GET', 'HEAD'].includes(req.method);
    const allowed = read && (path === '/' || path === '/index.html' || path === '/favicon.ico' || path === '/static/client.js'
      || /^\/assets\/[\w-]+\.(js|css|png|svg|ico|webp|woff2?)$/.test(path)
      || /^\/static\/assets\/brand\/[\w-]+\.(png|ttf)$/.test(path)
      || /^\/static\/photos\/[a-f0-9]{32}\.jpg$/.test(path))
      || req.method === 'POST' && functions.has(path.replace(/^\/function\//, '')) && path.startsWith('/function/');
    res.setHeader('x-content-type-options', 'nosniff');
    res.setHeader('referrer-policy', 'no-referrer');
    res.setHeader('permissions-policy', 'camera=(self), microphone=(), geolocation=()');
    res.setHeader('cache-control', 'no-store');
    if (healthCheck && read && path === '/healthz') {
      let active;
      let finished=false;
      const finish = ready => {
        if (finished || res.destroyed) return;
        finished=true;
        clearTimeout(deadline);
        res.writeHead(ready ? 200 : 503, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ ready }));
      };
      // Runtime readiness alone misses missing RPCs and an unavailable catalog.
      // Use one deadline for both anonymous probes and expose no diagnostics.
      const deadline=setTimeout(()=>{finish(false);active?.destroy();},5000);
      res.on('close',()=>{clearTimeout(deadline);active?.destroy();});
      const checkFeed=()=>{
        if(finished)return;
        if(!functions.has('home_feed')){finish(false);return;}
        active=http.request({hostname:upstreamHost,port:upstreamPort,path:'/function/home_feed',method:'POST',
          headers:{'content-type':'application/json','content-length':'2','accept-encoding':'identity'}},response=>{
          if(response.statusCode!==200){response.resume();finish(false);return;}
          let body='';
          response.setEncoding('utf8');
          response.on('data',chunk=>{
            body+=chunk;
            if(body.length>4*1024*1024){finish(false);response.destroy();}
          });
          response.on('error',()=>finish(false));
          response.on('end',()=>{
            try{
              const reply=JSON.parse(body),feed=reply?.data?.result;
              if(reply?.ok!==true){finish(false);return;}
              validateHomeFeed(feed);
              finish(true);
            }catch{finish(false);}
          });
        });
        active.on('error',()=>finish(false));
        active.end('{}');
      };
      active = http.get({ hostname: upstreamHost, port: upstreamPort, path: '/ready' }, response => {
        response.on('error',()=>finish(false));
        response.on('end',()=>{if(response.statusCode===200)checkFeed();else finish(false);});
        response.resume();
      });
      active.on('error', () => finish(false));
      return;
    }
    if (!allowed) { res.writeHead(403); res.end('This endpoint is not available.'); return; }
    // The phone launcher uses a loopback cloudflared connection. Hosted callers
    // must explicitly opt into an edge that overwrites CF-Connecting-IP (Render).
    // A direct listener must not trust caller-supplied forwarding headers.
    const cloudflareIp=req.headers['cf-connecting-ip'];
    const funnelIp=req.headers['x-forwarded-for'];
    const loopback=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
    // Funnel's HTTP proxy replaces X-Forwarded-For. It does not sanitize CF IP.
    // Trust one valid address only from the local daemon, never a forwarded list.
    const client=trustFunnel
      ? (loopback&&typeof funnelIp==='string'&&isIP(funnelIp)?funnelIp:req.socket.remoteAddress)
      : (trustCloudflare&&typeof cloudflareIp==='string'&&isIP(cloudflareIp)?cloudflareIp:req.socket.remoteAddress);
    const retry=limit(client,path);
    if(retry){res.writeHead(429,{'content-type':'application/json','retry-after':String(retry)});res.end(JSON.stringify({ok:false,error:{code:'RATE_LIMITED',message:'Too many sign-in attempts. Please wait before retrying.'}}));return;}
    const forward = body => {
    const upstream = http.request({ hostname: upstreamHost, port: upstreamPort,
      path: req.url, method: req.method,
      headers: { ...req.headers, host: `${upstreamHost}:${upstreamPort}` },
    }, response => {
      // Keep credentials and dynamic responses out of intermediary caches.
      res.writeHead(response.statusCode, { ...response.headers, 'cache-control': 'no-store' });
      response.pipe(res);
    });
    upstream.setTimeout(path==='/function/import_business_website'?75000:30000, () => upstream.destroy(new Error('timeout')));
    upstream.on('error', () => {
      if (!res.headersSent) res.writeHead(502, { 'content-type': 'text/plain' });
      res.end('M-Local is starting or unavailable. Ask the host to check the launcher, then reload.');
    });
    req.on('aborted', () => upstream.destroy());
    res.on('close', () => { if (!res.writableEnded) upstream.destroy(); });
    if(body)upstream.end(body);else req.pipe(upstream);
    };
    if(req.method!=='POST'){forward();return;}
    // Resized photo payloads get a separate bound; profile forms stay at 64 KiB.
    // Buffer bounded RPC bodies
    // so a chunked oversized request cannot partly execute at the upstream.
    const maxBody=path==='/function/upload_business_photo'?1400000:64*1024;
    let bytes=0, rejected=false;
    const chunks=[];
    const rejectBody=status=>{
      clearTimeout(deadline);
      rejected=true;chunks.length=0;
      if(!res.headersSent){res.writeHead(status,{'content-type':'text/plain'});res.end(status===413?'Request is too large.':'Request took too long.');}
      req.resume();
    };
    const deadline=setTimeout(()=>rejectBody(408),15000);
    if(Number(req.headers['content-length'])>maxBody){rejectBody(413);return;}
    req.on('data',chunk=>{
      if(rejected)return;
      bytes+=chunk.length;
      if(bytes>maxBody){rejected=true;chunks.length=0;rejectBody(413);return;}
      chunks.push(chunk);
    });
    req.on('end',()=>{
      clearTimeout(deadline);
      if(!rejected&&!res.writableEnded)forward(Buffer.concat(chunks));
    });
    req.on('aborted',()=>clearTimeout(deadline));
    req.on('error',()=>{clearTimeout(deadline);res.destroy();});
    res.on('close',()=>clearTimeout(deadline));
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const proxy = createShareProxy();
  proxy.on('error', error => { console.error(error.message); process.exitCode = 1; });
  proxy.listen(8280, '127.0.0.1', () => console.log('M-Local sharing gateway ready on 127.0.0.1:8280.'));
  const stop = () => { proxy.closeAllConnections(); proxy.close(); };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
}
