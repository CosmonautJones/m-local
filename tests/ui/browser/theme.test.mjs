import test from 'node:test';
import assert from 'node:assert/strict';
import {app,held,rpc,until} from './harness.mjs';

function deviceTheme(window,dark=false){
  const listeners=new Set();
  const query={matches:dark,addEventListener:(_,callback)=>listeners.add(callback),removeEventListener:(_,callback)=>listeners.delete(callback)};
  window.matchMedia=()=>query;
  return value=>{query.matches=value;listeners.forEach(callback=>callback({matches:value}));};
}
async function choose(ui,value){
  const control=ui.document.querySelector('[data-testid="theme-toggle"]');
  assert.ok(control,'the theme control is available');
  assert.equal(control.textContent,'','only an icon is visible');
  assert.equal(control.getAttribute('aria-label'),`Switch to ${value} mode`);
  assert.ok(control.querySelector('svg[aria-hidden="true"]'));
  control.dispatchEvent(new ui.window.MouseEvent('click',{bubbles:true}));
  await until(()=>ui.document.documentElement.dataset.theme===value);
}

test('welcome appearance follows system, persists selection, and keeps one logo without loading offers',async()=>{
  let changeDevice;
  const ui=await app({role:'guest',configureWindow(window){changeDevice=deviceTheme(window,true);}});
  try{
    await until(()=>ui.document.documentElement.dataset.theme==='dark');
    const logo=ui.document.querySelector('[role="img"][aria-label="M Local"]');
    assert.ok(logo);
    await choose(ui,'light');
    await until(()=>ui.document.documentElement.dataset.theme==='light');
    assert.equal(ui.window.localStorage.getItem('mlocal_theme'),'light');
    assert.equal(ui.document.querySelector('[role="img"][aria-label="M Local"]'),logo,'theme switching keeps the same logo element');
    changeDevice(false);changeDevice(true);
    assert.equal(ui.document.documentElement.dataset.theme,'light');
    await choose(ui,'dark');
    await until(()=>ui.document.documentElement.dataset.theme==='dark');
    changeDevice(false);
    assert.equal(ui.document.documentElement.dataset.theme,'dark','an explicit choice overrides the device');
    assert.equal(ui.calls.some(call=>call.name==='home_feed'),false);
    assert.deepEqual(ui.errors,[]);
  }finally{ui.close();}
});

test('saved dark appearance restores and remains selected through account navigation and logout',async()=>{
  const ui=await app({verified:true,configureWindow(window){window.localStorage.setItem('mlocal_theme','dark');},intercept(name){
    if(name==='get_account_profile')return rpc({ok:true,message:'',display_name:'Fixture student',email:'fixture@umich.edu',role:'student',email_verified:true,is_demo:false});
  }});
  try{
    await until(()=>ui.document.documentElement.dataset.theme==='dark');
    ui.click('Account');
    await until(()=>ui.document.querySelector('[data-testid="theme-toggle"]'));
    assert.equal(ui.document.querySelector('[data-testid="theme-toggle"]').getAttribute('aria-label'),'Switch to light mode');
    await choose(ui,'light');
    await until(()=>ui.document.documentElement.dataset.theme==='light');
    assert.equal(ui.window.localStorage.getItem('jac_token'),'synthetic-ui-token');
    ui.click('Log out');await until(()=>ui.find('Find local deals'));
    assert.equal(ui.document.querySelector('[data-testid="theme-toggle"]').getAttribute('aria-label'),'Switch to dark mode');
    assert.equal(ui.window.localStorage.getItem('mlocal_theme'),'light');
    assert.equal(ui.window.localStorage.getItem('jac_token'),null);
    assert.deepEqual(ui.errors,[]);
  }finally{ui.close();}
});

test('blocked theme storage does not prevent switching or entering either sign-in path',async()=>{
  const ui=await app({role:'guest',configureWindow(window){
    const prototype=window.Storage.prototype,getItem=prototype.getItem,setItem=prototype.setItem;
    prototype.getItem=function(key){if(key==='mlocal_theme')throw new Error('Blocked');return getItem.call(this,key);};
    prototype.setItem=function(key,value){if(key==='mlocal_theme')throw new Error('Blocked');return setItem.call(this,key,value);};
  }});
  try{
    await choose(ui,'dark');await until(()=>ui.document.documentElement.dataset.theme==='dark');
    ui.click('List my business');await until(()=>ui.document.querySelector('[type="email"]'));
    assert.equal(ui.document.documentElement.dataset.theme,'dark');
    ui.click('Back');await until(()=>ui.find('Find local deals'));
    assert.equal(ui.document.querySelector('[data-testid="theme-toggle"]').getAttribute('aria-label'),'Switch to light mode');
    ui.click('Find local deals');await until(()=>ui.find('Sign in'));
    ui.click('Sign in');await until(()=>ui.document.querySelector('[placeholder="uniqname"]'));
    assert.deepEqual(ui.errors,[]);
  }finally{ui.close();}
});

test('dark mode keeps claim QR modules black with a white quiet zone',async()=>{
  const ui=await app({item:held(),configureWindow(window){window.localStorage.setItem('mlocal_theme','dark');}});
  try{
    ui.click('Saved bowl');await until(()=>ui.document.querySelector('[data-testid="claim-qr"]'));
    const qr=ui.document.querySelector('[data-testid="claim-qr"]');
    assert.equal(ui.document.documentElement.dataset.theme,'dark');
    assert.equal(qr.style.background,'rgb(255, 255, 255)');
    assert.ok(qr.querySelector('[fill="#FFFFFF"]'));
    assert.ok(qr.querySelector('[fill="#000000"]'));
    assert.deepEqual(ui.errors,[]);
  }finally{ui.close();}
});
