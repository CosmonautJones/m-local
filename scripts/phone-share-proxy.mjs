// Public app ingress: compiled assets and the app's exact RPCs only.
// Never place the development relay or the raw Jac server behind a tunnel.
import http from 'node:http';
import {isIP} from 'node:net';
import {pathToFileURL} from 'node:url';
import {createOnboardingLimit} from './onboarding-ingress.mjs';
import {createSerializedIngress,IngressError} from './serialized-ingress.mjs';
import {validateHomeFeed} from '../client/feed-validation.mjs';

const functions=new Set(['list_offers','get_offer','claim_offer','merchant_portal',
  'update_profile','save_offer','set_offer_status','resolve_claim','redeem_claim',
  'cancel_claim','offer_defaults','current_session','request_email_code','verify_email_code',
  'get_business_draft','import_business_website','upload_business_photo','import_business_photo','save_business_draft','get_business_profile',
  'get_account_profile','save_account_profile','merchant_insights','local_activity','list_places','nearby_places',
  'home_feed','taste_choices','save_taste','toggle_favorite','nearby_after']);

// Jac's compiled HTML bootstraps an inline script; React Native Web uses inline
// styles. Uploaded photos are local; website-picker previews may use HTTPS,
// data images and blob previews. No external script or network RPC is required.
const contentSecurityPolicy=["default-src 'self'","script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' data: https://fonts.gstatic.com","img-src 'self' data: blob: https:",
  "connect-src 'self'","media-src 'self' blob:","object-src 'none'","base-uri 'none'",
  "form-action 'self'","frame-ancestors 'none'"].join('; ');

const failureCodes=new Set(['ROUTE_DENIED','BODY_TOO_LARGE','BODY_DEADLINE','ONBOARDING_RATE_LIMITED',
  'QUEUE_FULL','QUEUE_DEADLINE','QUEUE_ABORTED','SERIALIZATION_CLOSED','UPSTREAM_DEADLINE',
  'UPSTREAM_FAILURE','UPSTREAM_5XX','READINESS_FAILED','DELIVERY_LIMIT','DELIVERY_DEADLINE']);

// A process-wide budget, rather than one large buffer per accepted socket.
// HTTP completion must not depend on a browser continuing to read its socket.
const maxResponseBytes=8*1024*1024,maxDeliveryBytes=16*1024*1024;

function createObserver(eventSink) {
  const failures=Object.fromEntries([...failureCodes].map(code=>[code,0]));
  return {
    fail(code,route,status) {
      if(!failureCodes.has(code))return;
      failures[code]=Math.min(Number.MAX_SAFE_INTEGER,failures[code]+1);
      // Only allowlisted RPC names, readiness, and fixed categories can reach
      // the sink. No query, body, identity, token, IP or raw exception is logged.
      const event={kind:'mlocal_ingress_failure',code,route,status,time:new Date().toISOString()};
      try {eventSink?.(Object.freeze(event));} catch { /* logging cannot crash ingress */ }
    },
    status:()=>({...failures}),
  };
}

function routeLabel(path) {
  if(path==='/healthz')return 'readiness';
  if(path.startsWith('/function/')&&functions.has(path.slice(10)))return path.slice(10);
  if(path==='/'||path==='/index.html'||path==='/favicon.ico'||path==='/static/client.js'||
      path==='/static/assets/manifest.webmanifest'||/^\/static\/assets\/[\w-]+\.js$/.test(path)||path.startsWith('/assets/')||path.startsWith('/static/assets/brand/')||path.startsWith('/static/photos/'))return 'asset';
  return 'blocked';
}

function responseHeaders(upstream={},secure=false) {
  const headers={...upstream};
  // Do not expose runtime versions, and do not accept weaker upstream policy.
  for(const name of ['server','x-powered-by','strict-transport-security'])delete headers[name];
  Object.assign(headers,{
    'content-security-policy':contentSecurityPolicy,
    'x-frame-options':'DENY','x-content-type-options':'nosniff',
    'referrer-policy':'strict-origin-when-cross-origin',
    'permissions-policy':'camera=(self), microphone=(), geolocation=()',
    'cache-control':'no-store',
  });
  if(secure)headers['strict-transport-security']='max-age=31536000';
  return headers;
}

export function createShareProxy({upstreamHost='localhost',upstreamPort=8200,
  trustCloudflare=true,trustFunnel=false,healthCheck=false,
  deploymentTopology=process.env.MLOCAL_DEPLOYMENT_TOPOLOGY||'',
  secureProductionIngress=false,maxQueuedRequests=32,queueWaitMs=10000,maxConnections=96,
  upstreamDeadlineMs,readinessDeadlineMs=5000,
  eventSink=process.env.MLOCAL_INGRESS_EVENT_LOG==='stderr' ? event=>console.error(JSON.stringify(event)) : undefined,
}={}) {
  if(!['','single-instance-serialized'].includes(deploymentTopology))throw new Error('Invalid deployment topology.');
  if(typeof secureProductionIngress!=='boolean')throw new Error('Invalid secure ingress policy.');
  if(!Number.isInteger(maxConnections)||maxConnections<1||maxConnections>256)throw new Error('Invalid ingress connection limit.');
  if(upstreamDeadlineMs!==undefined&&(!Number.isInteger(upstreamDeadlineMs)||upstreamDeadlineMs<1||upstreamDeadlineMs>80000))throw new Error('Invalid upstream deadline.');
  if(!Number.isInteger(readinessDeadlineMs)||readinessDeadlineMs<1||readinessDeadlineMs>5000)throw new Error('Invalid readiness deadline.');
  const lane=deploymentTopology==='single-instance-serialized'?createSerializedIngress({maxQueuedRequests,queueWaitMs}):null;
  const observer=createObserver(eventSink),limit=createOnboardingLimit();
  let deliveryBytes=0;

  function deliver(response,res,route,deadlineMs) {
    if(res.destroyed){response.resume();return;}
    let reserved=0,released=false,deliveryStopped=false;
    const release=()=>{
      if(released)return;
      released=true;clearTimeout(deadline);
      deliveryBytes-=reserved;reserved=0;
    };
    const stop=code=>{
      if(deliveryStopped)return;
      deliveryStopped=true;
      observer.fail(code,route,502);
      // Close only downstream delivery. Continue consuming the native response
      // to establish completion; a delivery problem never clears its lane.
      res.destroy();
    };
    const deadline=setTimeout(()=>stop('DELIVERY_DEADLINE'),deadlineMs);
    res.once('finish',release);res.once('close',release);
    res.writeHead(response.statusCode,responseHeaders(response.headers,secureProductionIngress));
    response.on('data',chunk=>{
      if(deliveryStopped||res.destroyed)return;
      if(reserved+chunk.length>maxResponseBytes||deliveryBytes+chunk.length>maxDeliveryBytes) {
        stop('DELIVERY_LIMIT');return;
      }
      reserved+=chunk.length;deliveryBytes+=chunk.length;
      // Deliberately consume upstream even if write returns false. The shared
      // byte budget bounds the outstanding output references until finish/close.
      res.write(chunk);
    });
    response.on('end',()=>{if(!deliveryStopped&&!res.destroyed)res.end();});
  }

  function upstreamRequest(options,{body,onResponse,signal,deadlineMs}) {
    return new Promise((resolve,reject)=>{
      let settled=false,timer,response;
      const finish=error=>{
        if(settled)return;
        settled=true;clearTimeout(timer);
        signal?.removeEventListener('abort',abort);
        error?reject(error):resolve();
      };
      const request=http.request({hostname:upstreamHost,port:upstreamPort,...options},reply=>{
        response=reply;
        reply.on('error',finish);
        reply.on('aborted',()=>finish(new IngressError('UPSTREAM_FAILURE')));
        reply.on('end',()=>finish());
        reply.on('close',()=>{if(!reply.complete)finish(new IngressError('UPSTREAM_FAILURE'));});
        onResponse(reply);
      });
      const abort=()=>{
        request.destroy(new IngressError('UPSTREAM_DEADLINE'));
        response?.destroy();
      };
      signal?.addEventListener('abort',abort,{once:true});
      request.on('error',finish);
      // Serialized deadlines belong to the lane and fail closed. Development
      // keeps its bounded forwarding behavior without acquiring a global lane.
      if(!lane)timer=setTimeout(abort,deadlineMs);
      request.end(body);
    });
  }

  function dispatch(task,{signal,deadlineMs}) {
    if(lane)return lane.run(task,{signal,timeoutMs:deadlineMs});
    if(signal?.aborted)return Promise.reject(new IngressError('QUEUE_ABORTED'));
    return task(undefined);
  }

  const proxy=http.createServer((req,res)=>{
    const path=req.url.split('?')[0],route=routeLabel(path);
    const read=['GET','HEAD'].includes(req.method);
    const allowed=read&&(path==='/'||path==='/index.html'||path==='/favicon.ico'||path==='/static/client.js'
      ||/^\/assets\/[\w-]+\.(js|css|png|svg|ico|webp|woff2?)$/.test(path)
      ||path==='/static/assets/manifest.webmanifest'
      ||/^\/static\/assets\/[\w-]+\.js$/.test(path)
      ||/^\/static\/assets\/brand\/[\w-]+\.(png|ttf|svg)$/.test(path)
      ||/^\/static\/photos\/[a-f0-9]{32}\.jpg$/.test(path))
      ||req.method==='POST'&&path.startsWith('/function/')&&functions.has(path.slice(10));
    for(const [name,value] of Object.entries(responseHeaders({},secureProductionIngress)))res.setHeader(name,value);
    const waiting=new AbortController();
    res.on('close',()=>waiting.abort());
    const fail=(code,status,message)=>{
      observer.fail(code,route,status);
      if(res.destroyed||res.writableEnded)return;
      if(res.headersSent){res.destroy();return;}
      res.writeHead(status,responseHeaders({'content-type':'text/plain',...(status===503?{'retry-after':'1'}:{})},secureProductionIngress));
      res.end(message);
    };

    if(healthCheck&&read&&path==='/healthz') {
      let finished=false;
      const finish=ready=>{
        if(finished)return;
        finished=true;clearTimeout(deadline);waiting.abort();
        if(!ready)observer.fail('READINESS_FAILED','readiness',503);
        if(!res.destroyed){res.writeHead(ready?200:503,responseHeaders({'content-type':'application/json'},secureProductionIngress));res.end(JSON.stringify({ready}));}
      };
      // Expiry cancels queued probes. An active probe still drains through its
      // full response; the lane's deadline latches closed if that never ends.
      const deadline=setTimeout(()=>finish(false),readinessDeadlineMs);
      res.on('close',()=>clearTimeout(deadline));
      (async()=>{
        let nativeBody='',nativeBytes=0,nativeStatus,nativeType;
        // Official Jac 0.37.23 registers this native route. A 200 app shell or
        // incomplete/misconfigured response is not evidence of readiness.
        await dispatch(signal=>upstreamRequest({path:'/healthz/ready',method:'GET',headers:{'accept-encoding':'identity'}},
          {signal,deadlineMs:readinessDeadlineMs,onResponse:response=>{
            nativeStatus=response.statusCode;nativeType=response.headers['content-type'];
            response.setEncoding('utf8');
            response.on('data',chunk=>{
              nativeBytes+=Buffer.byteLength(chunk,'utf8');
              if(nativeBytes>64*1024){finish(false);nativeBody='';}
              else if(!finished)nativeBody+=chunk;
            });
          }}),
          {signal:waiting.signal,deadlineMs:readinessDeadlineMs});
        if(finished)return;
        let runtimeReady=false;
        try {
          runtimeReady=nativeStatus===200&&typeof nativeType==='string'&&
            /^application\/json(?:;|$)/i.test(nativeType)&&JSON.parse(nativeBody)?.ready===true;
        }catch{ /* invalid native readiness is unready */ }
        if(!runtimeReady){finish(false);return;}
        let body='',status;
        await dispatch(signal=>upstreamRequest({path:'/function/home_feed',method:'POST',
          headers:{'content-type':'application/json','content-length':'2','accept-encoding':'identity'}},
          {body:'{}',signal,deadlineMs:readinessDeadlineMs,onResponse:response=>{
            status=response.statusCode;response.setEncoding('utf8');
            response.on('data',chunk=>{
              if(body.length+chunk.length>4*1024*1024){finish(false);body='';}
              else if(!finished)body+=chunk;
            });
          }}),{signal:waiting.signal,deadlineMs:readinessDeadlineMs});
        if(finished)return;
        try {
          const reply=JSON.parse(body);
          if(status!==200||reply?.ok!==true){finish(false);return;}
          validateHomeFeed(reply?.data?.result);finish(true);
        }catch{finish(false);}
      })().catch(error=>{observer.fail(failureCodes.has(error.code)?error.code:'UPSTREAM_FAILURE','readiness',503);finish(false);});
      return;
    }
    if(!allowed){fail('ROUTE_DENIED',403,'This endpoint is not available.');return;}
    const cloudflareIp=req.headers['cf-connecting-ip'],funnelIp=req.headers['x-forwarded-for'];
    const loopback=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
    const client=trustFunnel
      ?(loopback&&typeof funnelIp==='string'&&isIP(funnelIp)?funnelIp:req.socket.remoteAddress)
      :(trustCloudflare&&typeof cloudflareIp==='string'&&isIP(cloudflareIp)?cloudflareIp:req.socket.remoteAddress);
    const retry=limit(client,path);
    if(retry){
      observer.fail('ONBOARDING_RATE_LIMITED',route,429);
      res.writeHead(429,responseHeaders({'content-type':'application/json','retry-after':String(retry)},secureProductionIngress));
      res.end(JSON.stringify({ok:false,error:{code:'RATE_LIMITED',message:'Too many sign-in attempts. Please wait before retrying.'}}));return;
    }
    const forward=body=>{
      const headers={...req.headers,host:`${upstreamHost}:${upstreamPort}`};
      // Bounded bodies are fully received before joining the queue; never relay
      // a partial chunked mutation or an inconsistent incoming Content-Length.
      delete headers['transfer-encoding'];
      if(body)headers['content-length']=String(body.length);
      else {delete headers['content-length'];req.resume();}
      const deadlineMs=upstreamDeadlineMs??(path==='/function/import_business_website'?75000:30000);
      dispatch(signal=>upstreamRequest({path:req.url,method:req.method,headers},
        {body,signal,deadlineMs,onResponse:response=>{
          if(response.statusCode>=500)observer.fail('UPSTREAM_5XX',route,response.statusCode);
          deliver(response,res,route,deadlineMs);
        }}),{signal:waiting.signal,deadlineMs}).catch(error=>{
          const code=failureCodes.has(error.code)?error.code:'UPSTREAM_FAILURE';
          const status=['QUEUE_FULL','QUEUE_DEADLINE','SERIALIZATION_CLOSED'].includes(code)?503:502;
          fail(code,status,'M-Local is starting or unavailable. Ask the host to check the launcher, then reload.');
        });
    };
    if(req.method!=='POST'){forward();return;}
    const maxBody=path==='/function/upload_business_photo'?1400000:64*1024;
    let bytes=0,rejected=false;
    const chunks=[];
    const rejectBody=status=>{
      clearTimeout(deadline);rejected=true;chunks.length=0;
      fail(status===413?'BODY_TOO_LARGE':'BODY_DEADLINE',status,status===413?'Request is too large.':'Request took too long.');req.resume();
    };
    const deadline=setTimeout(()=>rejectBody(408),15000);
    if(Number(req.headers['content-length'])>maxBody){rejectBody(413);return;}
    req.on('data',chunk=>{
      if(rejected)return;
      bytes+=chunk.length;
      if(bytes>maxBody){rejectBody(413);return;}
      chunks.push(chunk);
    });
    req.on('end',()=>{clearTimeout(deadline);if(!rejected&&!res.writableEnded)forward(Buffer.concat(chunks));});
    req.on('aborted',()=>clearTimeout(deadline));
    req.on('error',()=>{clearTimeout(deadline);res.destroy();});
    res.on('close',()=>clearTimeout(deadline));
  });
  proxy.ingressStatus=()=>({failures:observer.status(),serialization:lane?.status()??{enabled:false},
    delivery:{bytes:deliveryBytes,maxBytes:maxDeliveryBytes,maxResponseBytes}});
  // Bound sockets and partially received requests as well as queued bodies.
  proxy.maxConnections=maxConnections;
  proxy.headersTimeout=10000;
  proxy.requestTimeout=15000;
  proxy.keepAliveTimeout=5000;
  proxy.maxRequestsPerSocket=100;
  proxy.on('close',()=>lane?.close());
  return proxy;
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href) {
  const proxy=createShareProxy();
  proxy.on('error',()=>{console.error('M-Local sharing gateway could not start.');process.exitCode=1;});
  proxy.listen(8280,'127.0.0.1',()=>console.log('M-Local sharing gateway ready on 127.0.0.1:8280.'));
  const stop=()=>{proxy.closeAllConnections();proxy.close();};
  process.on('SIGINT',stop);process.on('SIGTERM',stop);
}
