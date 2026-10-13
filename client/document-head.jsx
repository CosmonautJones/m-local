import {useLayoutEffect} from 'react';

export function DocumentHead() {
 useLayoutEffect(()=>{
  document.title='M-Local';
  for(const [name,content] of [['description','Browse local restaurant offers in Ann Arbor. Sign in with your U-M email to claim a time-limited deal.'],['theme-color','#02305C'],['application-name','M-Local'],['apple-mobile-web-app-title','M-Local']]){
   let element=document.head.querySelector(`meta[name="${name}"]`);
   if(!element){element=document.createElement('meta');element.name=name;document.head.append(element);}
   element.content=content;
  }
  for(const [rel,href] of [['icon','/static/assets/brand/app-icon.svg'],['apple-touch-icon','/static/assets/brand/app-icon-180.png'],['manifest','/static/assets/manifest.webmanifest']]){
   let element=document.head.querySelector(`link[rel="${rel}"]`);
   if(!element){element=document.createElement('link');element.rel=rel;document.head.append(element);}
   element.href=href;
  }
 },[]);
 return null;
}
