import {useEffect,useState} from 'react';

let cached=null;

/** Read the source stamp written at deploy time (scripts/jachammer-stage.py). */
function loadBuild(){
 if(!cached){
  cached=fetch('/static/assets/mlocal-build.json',{cache:'no-store'})
   .then(r=>r.ok?r.json():null)
   .then(b=>b&&typeof b.project_version==='string'&&/^[0-9a-f]{7,40}$/.test(b.source_revision||'')?b:null)
   .catch(()=>null);
 }
 return cached;
}

/** "M-Local v0.1.0 · 5865c31" so anyone can tell which build is live. Renders nothing in local development. */
export function BuildLabel({style}){
 const [build,setBuild]=useState(null);
 useEffect(()=>{let live=true;loadBuild().then(b=>{if(live)setBuild(b);});return ()=>{live=false;};},[]);
 if(!build)return null;
 const text='M-Local v'+build.project_version+' · '+build.source_revision.slice(0,7);
 return <span data-testid="build-label" title={'Build '+build.source_revision+', Jac '+(build.runtime_version||'')} style={{fontSize:12,color:'var(--ml-muted)',fontVariantNumeric:'tabular-nums',...(style||{})}}>{text}</span>;
}
