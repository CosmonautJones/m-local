import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';

// Exercise the actual QR React bridge and controller, with controllable scanner
// import/camera boundaries. This does not claim physical-camera or network proof.
const root=resolve(process.env.MLOCAL_UI_APP_ROOT || resolve(import.meta.dirname,'../../..'));
const clientRequire=createRequire(`${root}/.jac/client/package.json`);
const runtimeRequire=createRequire(resolve(process.env.MLOCAL_UI_TEST_MODULES || `${root}/.jac/ui-test-runtime/node_modules`,'../package.json'));
const {build}=clientRequire('esbuild');
const {JSDOM}=runtimeRequire('jsdom');
const qrSource=resolve(root,'client/qr.jsx');
const result=await build({
  stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {ClaimQr,ClaimScanner} from ${JSON.stringify(qrSource)};
    const root=createRoot(document.getElementById('root'));
    window.mountQr=props=>root.render(React.createElement(ClaimQr,props));
    window.mountScanner=props=>root.render(React.createElement(ClaimScanner,props));
    window.unmountQr=()=>root.unmount();`,resolveDir:root,loader:'jsx'},
  bundle:true,write:false,format:'iife',platform:'browser',nodePaths:[resolve(root,'.jac/client/node_modules')],
  define:{'process.env.NODE_ENV':'"production"'},
  plugins:[{name:'scanner-boundaries',setup(builder){
    builder.onLoad({filter:/[/\\]client[/\\]qr\.jsx$/},args=>({
      contents:readFileSync(args.path,'utf8').replace(/import\((['"])@zxing\/browser\1\)/g,'window.loadScannerLibrary()'),loader:'jsx',resolveDir:resolve(root,'client')
    }));
    builder.onResolve({filter:/^@zxing\/browser$/},()=>({path:'scanner-module',namespace:'fixture'}));
    builder.onLoad({filter:/^scanner-module$/,namespace:'fixture'},()=>({contents:'window.scannerImports++;export const BrowserQRCodeReader=window.Reader;'}));
    // These inert style constants belong to generated Jac UI code. Scanner
    // lifecycle assertions use actual qr.jsx elements and no simulated sizing.
    builder.onResolve({filter:/^\.\/ui\.js$/},()=>({path:'ui-style',namespace:'fixture'}));
    builder.onLoad({filter:/^ui-style$/,namespace:'fixture'},()=>({contents:"export const uiFont='system-ui';export const formButton={};export const formSecondary={};"}));
  }}]
});
const executable=result.outputFiles[0].text;
const payload='mlocal:v1:'+'A'.repeat(43);
const preview={ok:true,claim_id:'fixture-claim',title_snapshot:'Saved bowl',price_cents:700,restaurant:'Fixture Kitchen',terms:'Dine in',eligibility:'Student ID',expires_label:'8 PM',expires_ts:Date.now()/1000+900};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
async function until(predicate,label){const end=Date.now()+3000;while(Date.now()<end){if(predicate())return;await new Promise(r=>setTimeout(r,5));}assert.fail(`Timed out: ${label}`);}
function fixture({load,requestStream,decodeStream,decodeImage}={}){
  const dom=new JSDOM('<!doctype html><div id="root"></div>',{url:'https://fixture.invalid',runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window,counts={readers:0,streams:0,reads:0,writes:0,revoked:0,refreshes:0};
  w.scannerImports=0;w.scannerLoadCalls=0;Object.defineProperty(w,'isSecureContext',{value:true});
  Object.defineProperty(w.navigator,'mediaDevices',{value:{getUserMedia:async()=>{counts.streams++;return requestStream?requestStream():{getTracks:()=>[]};}}});
  w.URL.createObjectURL=()=> 'blob:fixture-qr';w.URL.revokeObjectURL=()=>counts.revoked++;
  w.Reader=class{
    constructor(){counts.readers++;}
    decodeFromStream(...args){return decodeStream?decodeStream(...args):Promise.resolve({stop(){}});}
    decodeFromImageUrl(url){return decodeImage?decodeImage(url):Promise.resolve({getText:()=>payload});}
  };
  w.loadScannerLibrary=()=>{w.scannerImports++;w.scannerLoadCalls++;return load?load({BrowserQRCodeReader:w.Reader}):Promise.resolve({BrowserQRCodeReader:w.Reader});};
  w.eval(executable);
  const props={resolveClaim:async value=>{assert.equal(value,payload);counts.reads++;return preview;},redeemClaim:async value=>{assert.equal(value,payload);counts.writes++;return {ok:true,message:'Claim redeemed.'};},onRedeemed:()=>counts.refreshes++};
  let unmounted=false;
  return {window:w,document:w.document,counts,props,text:()=>w.document.body.textContent,
    mount:()=>w.mountScanner(props),
    click(label){const button=[...w.document.querySelectorAll('button')].find(node=>node.textContent===label);assert.ok(button,`Missing button: ${label}`);button.click();},
    unmount(){if(!unmounted){w.unmountQr();unmounted=true;}},
    close(){this.unmount();w.close();}
  };
}

test('the real scanner dependency is absent from the initial QR bundle and available as a dynamic chunk',async()=>{
  const bundled=await build({entryPoints:[qrSource],outdir:resolve(root,'.jac/scanner-test-bundle'),
    bundle:true,splitting:true,write:false,metafile:true,format:'esm',platform:'browser',
    nodePaths:[resolve(root,'.jac/client/node_modules')],
    plugins:[{name:'generated-ui-styles',setup(builder){
      builder.onResolve({filter:/^\.\/ui\.js$/},()=>({path:'ui-style',namespace:'fixture'}));
      builder.onLoad({filter:/^ui-style$/,namespace:'fixture'},()=>({contents:"export const uiFont='system-ui';export const formButton={};export const formSecondary={};"}));
    }}]
  });
  const outputs=bundled.metafile.outputs,entry=Object.keys(outputs).find(key=>outputs[key].entryPoint===qrSource||outputs[key].entryPoint?.endsWith('client/qr.jsx'));
  assert.ok(entry,'actual QR component entry exists');
  const initial=new Set();
  function visit(key){assert.ok(outputs[key],`Missing bundled output ${key}`);if(initial.has(key))return;initial.add(key);for(const dependency of outputs[key].imports)if(dependency.kind!=='dynamic-import'&&!dependency.external)visit(dependency.path);}
  visit(entry);
  for(const key of initial)assert.equal(Object.keys(outputs[key].inputs).some(input=>/[@/]zxing[/\\]/.test(input)),false,'initial QR static imports contain no scanner implementation');
  const scannerOutputs=Object.keys(outputs).filter(key=>Object.keys(outputs[key].inputs).some(input=>/[@/]zxing[/\\]/.test(input)));
  assert.ok(scannerOutputs.length>0,'the pinned scanner implementation remains in the build');
  assert.ok([...initial].some(key=>outputs[key].imports.some(dependency=>dependency.kind==='dynamic-import')),'scanner module is loaded through a dynamic import');
});

test('rendering a student claim QR does not load the scanner library or request a camera',async()=>{
  const f=fixture();try{
    f.window.mountQr({payload,expiresTs:Date.now()/1000+900});
    await until(()=>f.document.querySelector('[data-testid="claim-qr"]'),'student QR');
    assert.equal(f.window.scannerImports,0,'student module import and render must leave scanner code unloaded');
    assert.equal(f.counts.readers,0);assert.equal(f.counts.streams,0);
  }finally{f.close();}
});

test('merchant scanner loading is visible and cannot request a camera before its import completes',async()=>{
  const pending=deferred(),f=fixture({load:()=>pending.promise});try{
    f.mount();await until(()=>f.document.querySelector('section')&&(f.window.scannerLoadCalls===1||f.counts.readers===1),'merchant scanner initialization');
    assert.match(f.text(),/Loading.*scanner/i);assert.equal(f.counts.readers,0);assert.equal(f.counts.streams,0);
    const start=[...f.document.querySelectorAll('button')].find(node=>/Loading.*scanner/i.test(node.textContent));
    assert.ok(start);assert.equal(start.disabled,true);assert.equal(f.document.querySelector('input[type=file]').disabled,true);
    pending.resolve({BrowserQRCodeReader:f.window.Reader});
    await until(()=>f.text().includes('Start camera scan'),'loaded scanner');
    assert.equal(f.counts.readers,1);assert.equal(f.counts.streams,0);
  }finally{f.close();}
});

test('an import resolving after scanner unmount creates no reader or camera resources',async()=>{
  const pending=deferred(),f=fixture({load:()=>pending.promise});try{
    f.mount();await until(()=>f.document.querySelector('section')&&(f.window.scannerLoadCalls===1||f.counts.readers===1),'pending scanner initialization');f.unmount();
    pending.resolve({BrowserQRCodeReader:f.window.Reader});await new Promise(r=>setTimeout(r,20));
    assert.equal(f.counts.readers,0);assert.equal(f.counts.streams,0);assert.equal(f.document.querySelector('video'),null);
  }finally{f.close();}
});

test('failed scanner loading explains recovery and an explicit retry can initialize the scanner',async()=>{
  let attempts=0;const retry=deferred(),f=fixture({load:()=>++attempts===1?Promise.reject(new Error('private transport detail')):retry.promise});try{
    f.mount();await until(()=>f.document.querySelector('[role=alert]'),'scanner import error');
    assert.match(f.text(),/scanner.*load|load.*scanner/i);assert.match(f.text(),/connection.*retry|retry.*connection/i);
    assert.doesNotMatch(f.text(),/private transport detail/);assert.equal(f.counts.streams,0);
    f.click('Retry scanner loading');await until(()=>attempts===2,'second scanner import');
    retry.resolve({BrowserQRCodeReader:f.window.Reader});await until(()=>f.text().includes('Start camera scan'),'retry succeeds');
    assert.equal(f.counts.readers,1);f.click('Start camera scan');await until(()=>f.counts.streams===1,'camera start');
  }finally{f.close();}
});

test('scanner image fallback still checks saved terms and waits for explicit redemption confirmation',async()=>{
  const f=fixture();try{
    f.mount();await until(()=>f.counts.readers===1&&f.text().includes('Start camera scan'),'loaded scanner');
    const input=f.document.querySelector('input[type=file]');
    Object.defineProperty(input,'files',{value:[new f.window.File(['fixture'],'claim.png',{type:'image/png'})]});
    input.dispatchEvent(new f.window.Event('change',{bubbles:true}));
    await until(()=>f.text().includes('Confirm redemption'),'saved claim preview');
    assert.match(f.text(),/Saved bowl/);assert.match(f.text(),/Dine in/);assert.equal(f.counts.streams,0);
    assert.equal(f.counts.reads,1);assert.equal(f.counts.writes,0);assert.equal(f.counts.revoked,1);
    f.click('Confirm redemption');await until(()=>f.text().includes('Claim redeemed.'),'confirmed redemption');
    assert.equal(f.counts.writes,1);assert.equal(f.counts.refreshes,1);
  }finally{f.close();}
});

test('a camera stream acquired after account unmount has every track stopped',async()=>{
  const pending=deferred();let stops=0;const f=fixture({requestStream:()=>pending.promise});try{
    f.mount();await until(()=>f.counts.readers===1&&f.text().includes('Start camera scan'),'loaded scanner');f.click('Start camera scan');
    await until(()=>f.counts.streams===1,'camera requested');f.unmount();
    pending.resolve({getTracks:()=>[{stop:()=>stops++},{stop:()=>stops++}]});
    await until(()=>stops===2,'late tracks stopped');assert.equal(f.counts.reads,0);assert.equal(f.counts.writes,0);
  }finally{f.close();}
});

test('decoder controls arriving after scanner unmount are stopped along with existing camera tracks',async()=>{
  const pending=deferred();let tracks=0,controls=0,decodes=0;
  const f=fixture({requestStream:()=>({getTracks:()=>[{stop:()=>tracks++}]}),decodeStream:()=>{decodes++;return pending.promise;}});try{
    f.mount();await until(()=>f.counts.readers===1&&f.text().includes('Start camera scan'),'loaded scanner');f.click('Start camera scan');
    await until(()=>decodes===1,'decoder requested');f.unmount();
    assert.ok(tracks>=1);pending.resolve({stop:()=>controls++});
    await until(()=>controls===1,'late controls stopped');assert.equal(f.counts.reads,0);assert.equal(f.counts.writes,0);
  }finally{f.close();}
});
