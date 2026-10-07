import test from 'node:test';
import assert from 'node:assert/strict';
import {app,openSignIn} from './harness.mjs';

test('email sign-in controls declare at least44px keyboard and touch targets',async()=>{
 const ui=await app({role:'guest',audience:''});
 try{
  await openSignIn(ui);
  const controls=[...ui.document.querySelectorAll('.ml-auth button,.ml-auth select')];
  assert.ok(controls.length>=3);
  for(const control of controls){
   assert.ok(parseFloat(ui.window.getComputedStyle(control).minHeight)>=44,control.textContent.trim()+' target is too short');
  }
 }finally{ui.close();}
});
