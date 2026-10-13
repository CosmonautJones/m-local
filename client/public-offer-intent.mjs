// Persist only a public catalog identifier. Server reads always recheck availability.
const key='mlocal_public_offer_intent';
const valid=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value);
export function readPublicOfferIntent(storage) {
 try{
  const store=storage||globalThis.localStorage,value=store.getItem(key);
  if(valid(value))return value;
  store.removeItem(key);
 }catch{/* Browsing and sign-in remain usable when storage is unavailable. */}
 return '';
}
export function rememberPublicOfferIntent(value,storage) {
 try{const store=storage||globalThis.localStorage;if(valid(value))store.setItem(key,value);else store.removeItem(key);}catch{}
}
export function clearPublicOfferIntent(storage) {
 try{(storage||globalThis.localStorage).removeItem(key);}catch{}
}
