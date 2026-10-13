import React, {useEffect, useState} from 'react';

export function OfferImage({url, width, height, alt, fit='cover'}) {
  const [failed,setFailed]=useState(false);
  useEffect(()=>setFailed(false),[url]);
  if(!url)return null;
  const stretch=width==='100%';
  if(failed)return <div role="status" style={{width:stretch?'100%':width,minHeight:44,display:'grid',placeItems:'center',color:'var(--ml-muted)',background:'var(--ml-sunken)',borderRadius:10,fontSize:12}}>Photo unavailable</div>;
  return <img src={url} alt={alt||'Offer photo'} width={stretch?undefined:width} height={height} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={()=>setFailed(true)} style={{width:stretch?'100%':width,height,objectFit:fit,display:'block',borderRadius:12}}/>;
}
