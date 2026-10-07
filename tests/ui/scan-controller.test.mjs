import test from 'node:test';
import assert from 'node:assert/strict';
import { createScanController, isClaimPayload } from '../../client/scan-controller.mjs';

const payload = 'mlocal:v1:' + 'A'.repeat(43);
const preview = {ok: true, claim_id: 'claim-1', title_snapshot: 'Saved bowl', price_cents: 700, terms: 'Dine in', eligibility: 'Student ID', expires_ts: Date.now()/1000+900};
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise,resolve,reject}; };
function setup(overrides={}) {
  let callback, stops=0, controlStops=0, reads=0, writes=0;
  const stream = {getTracks: () => [{stop: () => stops++}]};
  const deps = {
    secure: true, requestStream: async () => stream,
    decode: async (_stream,_video,cb) => {callback=cb;return {stop:()=>controlStops++};},
    resolveClaim: async () => {reads++;return preview;},
    redeemClaim: async () => {writes++;return {ok:true,message:'Redeemed.'};},
    ...overrides
  };
  const controller = createScanController(deps);
  return {controller, stream, detect: (text=payload) => callback({getText:()=>text}), get counts(){return {stops,controlStops,reads,writes};}};
}

test('strict canonical QR grammar rejects URLs, padding, wrong version and noncanonical final bits', () => {
  assert.equal(isClaimPayload(payload),true);
  for(const value of ['https://example.com',payload+'=',payload.replace('v1','v2'),' '+payload,payload.slice(0,-1)+'B']) assert.equal(isClaimPayload(value),false);
});
test('repeated detections resolve once and never redeem before explicit confirmation', async () => {
  const hold=deferred(); let reads=0; const f=setup({resolveClaim:()=>{reads++;return hold.promise;}});
  await f.controller.start({}); const first=f.detect(); await f.detect();
  assert.equal(f.controller.state.phase,'resolving'); assert.equal(reads,1); assert.equal(f.counts.writes,0); assert.ok(f.counts.stops>0);
  hold.resolve(preview); await first;
  assert.equal(f.controller.state.phase,'preview'); assert.equal(f.counts.writes,0);
  await Promise.all([f.controller.confirm(),f.controller.confirm()]); assert.equal(f.counts.writes,1);
});
test('camera denial is actionable and starting again recovers', async () => {
  let failed=true; const f=setup({requestStream:async()=>{if(failed)throw {name:'NotAllowedError'};return {getTracks:()=>[]};}});
  await f.controller.start({}); assert.match(f.controller.state.message,/permission|allow/i); assert.equal(f.controller.state.phase,'error');
  failed=false; await f.controller.start({}); assert.equal(f.controller.state.phase,'scanning');
});
test('insecure context and missing camera API never request a stream', async () => {
  const f=setup({secure:false,requestStream:()=>{throw Error('must not run');}}); await f.controller.start({}); assert.match(f.controller.state.message,/HTTPS|localhost/);
  const absent=setup({requestStream:null}); await absent.controller.start({}); assert.match(absent.controller.state.message,/camera|browser/i);
});
test('cancel and unmount stop tracks and ignore late stream and resolve results', async () => {
  const pending=deferred(); const f=setup({requestStream:()=>pending.promise}); const start=f.controller.start({}); f.controller.cancel(); pending.resolve(f.stream); await start; assert.equal(f.counts.stops,1); assert.equal(f.controller.state.phase,'idle');
  const read=deferred(); const g=setup({resolveClaim:()=>read.promise}); await g.controller.start({}); const detection=g.detect(); g.controller.dispose(); read.resolve(preview); await detection; assert.notEqual(g.controller.state.phase,'preview'); assert.ok(g.counts.stops>0);
});
test('cancelled preview cannot mutate and malformed scans never call the server', async () => {
  const f=setup(); await f.controller.start({}); await f.detect('https://example.com'); assert.equal(f.counts.reads,0); assert.equal(f.counts.writes,0);
  await f.controller.start({}); await f.detect(); f.controller.cancel(); await f.controller.confirm(); assert.equal(f.counts.writes,0);
});
test('resolve and redeem network failures release busy state for retry', async () => {
  let failRead=true, failWrite=true;
  const f=setup({resolveClaim:async()=>{if(failRead)throw Error('offline');return preview;},redeemClaim:async()=>{if(failWrite)throw Error('offline');return {ok:true,message:'Redeemed.'};}});
  await f.controller.start({}); await f.detect(); assert.equal(f.controller.state.phase,'error');
  failRead=false; await f.controller.start({}); await f.detect(); await f.controller.confirm(); assert.equal(f.controller.state.phase,'preview'); assert.match(f.controller.state.message,/connection|retry/i);
  failWrite=false; await f.controller.confirm(); assert.equal(f.controller.state.phase,'success');
});
test('controls arriving after detection or cancellation are stopped', async () => {
  const pending=deferred(); const f=setup({decode:async(_s,_v,cb)=>{await cb({getText:()=>payload});return pending.promise;}});
  const start=f.controller.start({}); await Promise.resolve(); await Promise.resolve(); f.controller.cancel(); let stopped=0; pending.resolve({stop:()=>stopped++}); await start; assert.equal(stopped,1);
});

test('a local QR image resolves to preview and needs explicit confirmation without a camera', async () => {
  const file={type:'image/png',size:200};let decodes=0;
  const f=setup({secure:false,requestStream:null,decodeImage:async value=>{assert.equal(value,file);decodes++;return {getText:()=>payload};}});
  assert.equal(typeof f.controller.startImage,'function','image fallback is available');
  await f.controller.startImage(file);
  assert.equal(decodes,1);assert.equal(f.controller.state.phase,'preview');
  assert.equal(f.counts.reads,1);assert.equal(f.counts.writes,0);
  await f.controller.confirm();assert.equal(f.counts.writes,1);
});

test('unsafe oversized and nonclaim QR images never reach admission or redemption endpoints', async () => {
  let decodes=0;const f=setup({decodeImage:async()=>{decodes++;return {getText:()=> 'https://example.test'};}});
  assert.equal(typeof f.controller.startImage,'function','image fallback is available');
  for(const file of [{type:'image/svg+xml',size:100},{type:'image/png',size:10*1024*1024+1}])await f.controller.startImage(file);
  assert.equal(decodes,0);assert.equal(f.counts.reads,0);
  await f.controller.startImage({type:'image/png',size:200});
  assert.equal(f.controller.state.phase,'error');assert.equal(f.counts.reads,0);assert.equal(f.counts.writes,0);
});

test('cancelled image decoding and overlapping image requests cannot replace the next preview', async () => {
  const pending=deferred();let decodes=0;const f=setup({decodeImage:()=>{decodes++;return pending.promise;}});
  assert.equal(typeof f.controller.startImage,'function','image fallback is available');
  const first=f.controller.startImage({type:'image/png',size:200});
  await f.controller.startImage({type:'image/jpeg',size:200});assert.equal(decodes,1);
  f.controller.cancel();pending.resolve({getText:()=>payload});await first;
  assert.equal(f.controller.state.phase,'idle');assert.equal(f.counts.reads,0);assert.equal(f.counts.writes,0);
});
