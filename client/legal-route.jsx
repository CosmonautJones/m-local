import {useEffect,useState} from 'react';

const current=()=>{const hash=(window.location.hash||'').toLowerCase();return hash==='#privacy'?'privacy':hash==='#terms'?'terms':'';};

/** '' | 'privacy' | 'terms', following the URL fragment. */
export function useLegalRoute(){
 const [page,setPage]=useState(current);
 useEffect(()=>{const update=()=>setPage(current());window.addEventListener('hashchange',update);return ()=>window.removeEventListener('hashchange',update);},[]);
 return page;
}

/** Leave a legal page and return to the app without reloading it. */
export function leaveLegal(){
 try{window.history.replaceState(null,'',window.location.pathname+window.location.search);}catch{/* ignore */}
 window.dispatchEvent(new Event('hashchange'));
}
