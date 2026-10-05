import assert from 'node:assert/strict';
import http from 'node:http';
import {once} from 'node:events';
import test from 'node:test';
import {createShareProxy} from '../../scripts/phone-share-proxy.mjs';

async function fixture(t){
 const seen=[];
 const upstream=http.createServer((req,res)=>{seen.push(req.url);req.resume();res.end('{}');}).listen(0,'127.0.0.1');
 await once(upstream,'listening');
 const proxy=createShareProxy({upstreamHost:'127.0.0.1',upstreamPort:upstream.address().port}).listen(0,'127.0.0.1');
 await once(proxy,'listening');
 t.after(()=>{proxy.closeAllConnections();proxy.close();upstream.closeAllConnections();upstream.close();});
 return {origin:`http://127.0.0.1:${proxy.address().port}`,seen};
}

test('saved photos cross ingress with only exact random JPEG paths exposed',async t=>{
 const {origin,seen}=await fixture(t),photo='/static/photos/'+'a'.repeat(32)+'.jpg';
 assert.equal((await fetch(origin+photo)).status,200);
 assert.equal((await fetch(origin+photo,{method:'HEAD'})).status,200);
 const before=seen.length;
 for(const path of ['/static/photos/private.sqlite3','/static/photos/'+ 'a'.repeat(32)+'.png','/static/photos/short.jpg','/static/photos/%2e%2e/onboarding.sqlite3','/static/photos/sub/'+ 'a'.repeat(32)+'.jpg']){
  assert.equal((await fetch(origin+path)).status,403,path);
 }
 assert.equal((await fetch(origin+photo,{method:'POST',body:'{}'})).status,403);
 assert.equal(seen.length,before);
});

test('photo authoring RPCs cross ingress and ordinary form bounds remain small',async t=>{
 const {origin,seen}=await fixture(t);
 assert.equal((await fetch(origin+'/function/import_business_photo',{method:'POST',body:'{}'})).status,200);
 assert.equal((await fetch(origin+'/function/upload_business_photo',{method:'POST',body:JSON.stringify({payload:'x'.repeat(100000)})})).status,200);
 const before=seen.length;
 assert.equal((await fetch(origin+'/function/save_business_draft',{method:'POST',body:'x'.repeat(65537)})).status,413);
 assert.equal(seen.length,before);
});

test('oversized declared and chunked photos are rejected before forwarding',async t=>{
 const {origin,seen}=await fixture(t),url=origin+'/function/upload_business_photo';
 assert.equal((await fetch(url,{method:'POST',body:'x'.repeat(1400001)})).status,413);
 const status=await new Promise((resolve,reject)=>{
  const req=http.request(url,{method:'POST',headers:{'transfer-encoding':'chunked'}},res=>{res.resume();res.on('end',()=>resolve(res.statusCode));});
  req.on('error',reject);req.write('x'.repeat(700000));req.end('x'.repeat(700001));
 });
 assert.equal(status,413);assert.equal(seen.length,0);
});
