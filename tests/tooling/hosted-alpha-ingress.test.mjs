import assert from 'node:assert/strict';
import http from 'node:http';
import {once} from 'node:events';
import test from 'node:test';
import {createShareProxy} from '../../scripts/phone-share-proxy.mjs';

test('hosted source assets and token-protected operations pass the restricted gateway',async t=>{
 const seen=[];
 const upstream=http.createServer((req,res)=>{seen.push(req.url);req.resume();res.end('{}');}).listen(0,'127.0.0.1');
 await once(upstream,'listening');
 const proxy=createShareProxy({upstreamHost:'127.0.0.1',upstreamPort:upstream.address().port,
  deploymentTopology:'single-instance-serialized'}).listen(0,'127.0.0.1');
 await once(proxy,'listening');
 t.after(()=>{proxy.closeAllConnections();proxy.close();upstream.closeAllConnections();upstream.close();});
 const origin=`http://127.0.0.1:${proxy.address().port}`;
 for(const path of ['/client.CIzQzR1J.js','/static/assets/mlocal-build.json']){
  assert.equal((await fetch(origin+path)).status,200,path);
  assert.equal((await fetch(origin+path,{method:'HEAD'})).status,200,path);
 }
 for(const name of ['review_link_details','approve_from_review_link','download_backup']){
  assert.equal((await fetch(origin+'/function/'+name,{method:'POST',body:'{}'})).status,200,name);
 }
 const before=seen.length;
 for(const path of ['/user/register','/user/login','/docs','/graph/data','/assets/private.json',
  '/client.js','/client../secret.js','/function/approve_business']){
  for(const method of ['GET','POST'])assert.equal((await fetch(origin+path,{method})).status,403,path);
 }
 assert.equal((await fetch(origin+'/function/download_backup')).status,403);
 assert.equal(seen.length,before,'native and arbitrary operator routes never reach the app');
});
