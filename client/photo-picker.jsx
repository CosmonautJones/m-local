import React, {useEffect, useRef, useState} from 'react';

export function PhotoPicker({label, value='', candidates=[], onChange, uploadPhoto, importPhoto, importWebsite, onBusyChange=()=>{}, disabled=false}) {
  const [busy,setBusy]=useState(false), [error,setError]=useState(''), [failed,setFailed]=useState(false);
  const [website,setWebsite]=useState(''), [imported,setImported]=useState([]);
  const [link,setLink]=useState(''), [selectedSource,setSelectedSource]=useState('');
  const mounted=useRef(true), inFlight=useRef(false);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>setFailed(false),[value]);
  async function upload(event) {
    const file=event.target.files?.[0];event.target.value='';
    if(!file || inFlight.current || disabled)return;
    if(!['image/jpeg','image/png','image/webp','image/heic','image/heif'].includes(file.type) || file.size>20*1024*1024){setError('Choose a JPG, PNG or WebP photo under 20 MB. For HEIC, export a JPG if your browser cannot open it.');return;}
    inFlight.current=true;setBusy(true);setError('');onBusyChange(true);
    let url;
    try {
      url=URL.createObjectURL(file);
      const image=new Image();image.src=url;await image.decode();
      if(image.naturalWidth*image.naturalHeight>60000000)throw new Error('This photo is too large. Choose a smaller photo.');
      const scale=Math.min(1,1600/Math.max(image.naturalWidth,image.naturalHeight));
      const canvas=document.createElement('canvas');canvas.width=Math.round(image.naturalWidth*scale);canvas.height=Math.round(image.naturalHeight*scale);
      const context=canvas.getContext('2d');if(!context)throw new Error('Your browser could not prepare this photo.');
      context.fillStyle='#ffffff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(image,0,0,canvas.width,canvas.height);
      let payload=canvas.toDataURL('image/jpeg',.82);
      if(payload.length>1398128)payload=canvas.toDataURL('image/jpeg',.62);
      if(payload.length>1398128)throw new Error('This photo is too large after resizing. Choose a smaller photo.');
      const result=await uploadPhoto(payload);
      if(!mounted.current)return;
      if(!result?.ok || !result.url)throw new Error(result?.message || 'Photo could not be uploaded. Your current photo is kept.');
      setSelectedSource('');onChange(result.url);
    } catch(e) {if(mounted.current)setError(e?.message?.includes('source image')?'This photo could not be opened. Try a JPG, PNG or WebP.':e?.message || 'Could not upload. Your current photo is kept; try again.');}
    finally{if(url)URL.revokeObjectURL(url);inFlight.current=false;if(mounted.current){setBusy(false);onBusyChange(false);}}
  }
  async function findPhotos() {
    if(inFlight.current || disabled || !website.trim())return;
    inFlight.current=true;setBusy(true);setError('');onBusyChange(true);
    try {
      const result=await importWebsite(website.trim());
      if(!mounted.current)return;
      if(!result?.ok)throw new Error(result?.message || 'Could not read this website. You can still upload a photo.');
      const photos=result.image_urls || [];setImported(photos);
      if(!photos.length)setError('No photos found on that website. Upload one from your phone instead.');
    } catch(e) {if(mounted.current)setError(e?.message || 'Could not read this website. Your selected photo is kept.');}
    finally{inFlight.current=false;if(mounted.current){setBusy(false);onBusyChange(false);}}
  }
  async function choosePhoto(url) {
    if(inFlight.current || disabled || !url)return;
    inFlight.current=true;setBusy(true);setError('');onBusyChange(true);
    try {
      const result=await importPhoto(url);
      if(!mounted.current)return;
      if(!result?.ok || !result.url)throw new Error(result?.message || 'This photo could not be imported. Your selected photo is kept.');
      setSelectedSource(url);onChange(result.url);
    }catch(e){if(mounted.current)setError(e?.message || 'Could not import this photo. Upload one instead.');}
    finally{inFlight.current=false;if(mounted.current){setBusy(false);onBusyChange(false);}}
  }
  const locked=disabled||busy;
  const choices=[...new Set([...candidates,...imported])].filter(x=>typeof x==='string'&&x);
  return <section className="ml-photo-picker" aria-label={label}>
    <style>{`.ml-photo-picker{display:flex;flex-direction:column;gap:12px;min-width:0}.ml-photo-picker h4{margin:0;font-size:16px}.ml-photo-preview{margin:0;border-radius:14px;overflow:hidden;background:var(--ml-sunken);border:1px solid var(--ml-border)}.ml-photo-preview img{display:block;width:100%;height:190px;object-fit:contain}.ml-photo-preview figcaption{padding:9px 12px;font-size:12px;color:var(--ml-muted)}.ml-photo-actions{display:flex;gap:10px;flex-wrap:wrap}.ml-photo-actions button,.ml-photo-upload{box-sizing:border-box;border:1px solid var(--ml-border);background:var(--ml-surface);color:var(--ml-ink);font:600 14px Figtree,system-ui;padding:11px 15px;border-radius:10px;min-height:44px;cursor:pointer}.ml-photo-upload{position:relative;overflow:hidden;display:inline-flex;align-items:center;border-color:var(--ml-accent);color:var(--ml-accent)}.ml-photo-upload input{position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer}.ml-photo-upload:focus-within,.ml-photo-picker button:focus-visible,.ml-photo-picker input:focus-visible{outline:3px solid var(--ml-focus);outline-offset:3px}.ml-photo-picker [disabled]{opacity:.55;cursor:default}.ml-photo-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:10px}.ml-photo-choice{position:relative;padding:0;border:2px solid var(--ml-border);border-radius:12px;overflow:hidden;background:var(--ml-surface);color:var(--ml-ink);cursor:pointer;min-width:0}.ml-photo-choice[aria-pressed=true]{border-color:var(--ml-accent);box-shadow:0 0 0 1px var(--ml-accent)}.ml-photo-choice img{display:block;width:100%;height:90px;object-fit:contain;background:var(--ml-sunken)}.ml-photo-choice span{display:block;padding:7px;font:600 12px Figtree,system-ui}.ml-photo-hint{font-size:13px;line-height:1.5;color:var(--ml-muted);margin:0}.ml-photo-picker details{font-size:13px;color:var(--ml-muted)}.ml-photo-link{display:block;width:100%;box-sizing:border-box;margin-top:10px;padding:12px;border:1px solid var(--ml-border);border-radius:10px;background:var(--ml-surface);color:var(--ml-ink)}`}</style>
    <h4>{label}</h4>
    {value && !failed && <figure className="ml-photo-preview"><img src={value} alt={'Selected '+label.toLowerCase()} referrerPolicy="no-referrer" onError={()=>setFailed(true)}/><figcaption>Selected photo · appears publicly when saved</figcaption></figure>}
    {failed && <p className="ml-photo-hint" role="status">This photo could not load. Choose another photo or remove it.</p>}
    <div className="ml-photo-actions">
      <label className="ml-photo-upload">{busy?'Uploading…':value?'Replace photo':'Upload photo'}<input type="file" accept="image/*" aria-label={'Upload '+label.toLowerCase()} disabled={locked} onChange={upload}/></label>
      {value && <button type="button" disabled={locked} onClick={()=>{onChange('');setSelectedSource('');setError('');}}>Remove photo</button>}
    </div>
    <p className="ml-photo-hint">Choose a photo from your phone. JPG, PNG or WebP; up to 20 MB. Photos are resized for faster loading.</p>
    {choices.length>0 && <><p className="ml-photo-hint">Or choose a photo found on your website</p><div className="ml-photo-grid" role="group" aria-label="Website photos">{choices.map((url,i)=><WebsitePhoto key={url} url={url} index={i} selected={url===value||url===selectedSource} disabled={locked} choose={choosePhoto}/>)}</div></>}
    {importWebsite && <details><summary>Find photos on your website</summary><label>Business website<input className="ml-photo-link" aria-label={'Website for '+label.toLowerCase()} type="url" maxLength={2048} placeholder="https://your-business.com" value={website} disabled={locked} onChange={e=>setWebsite(e.target.value)}/></label><div className="ml-photo-actions" style={{marginTop:10}}><button type="button" disabled={locked || !website.trim()} onClick={findPhotos}>{busy?'Finding photos…':'Find website photos'}</button></div></details>}
    <details><summary>Add a photo from another website</summary><label>Public photo link<input className="ml-photo-link" aria-label={label+' link'} type="url" maxLength={2048} placeholder="https://your-business.com/photo.jpg" value={link} disabled={locked} onChange={e=>setLink(e.target.value)}/></label><div className="ml-photo-actions" style={{marginTop:10}}><button type="button" disabled={locked||!link.trim()} onClick={()=>choosePhoto(link.trim())}>Use website photo</button></div></details>
    {error && <p className="ml-photo-hint" role="alert">{error}</p>}
  </section>;
}

function WebsitePhoto({url,index,selected,disabled,choose}) {
  const [failed,setFailed]=useState(false);
  if(failed)return <div className="ml-photo-hint">Website photo {index+1} unavailable</div>;
  return <button className="ml-photo-choice" type="button" aria-label={'Choose website photo '+(index+1)} aria-pressed={selected} disabled={disabled} onClick={()=>choose(url)}><img src={url} alt={'Website photo '+(index+1)} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={()=>setFailed(true)}/><span>{selected?'✓ Selected':'Photo '+(index+1)}</span></button>;
}
