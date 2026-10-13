import React, {useEffect, useRef, useState} from 'react';
import {QRCodeSVG} from 'qrcode.react';
import {createScanController, isClaimPayload} from './scan-controller.mjs';
import {uiFont, formButton, formSecondary} from './ui.js';

const box = {display:'flex',flexDirection:'column',gap:16,color:'var(--ml-ink)',fontFamily:uiFont};
const button = formButton;
const secondary = formSecondary;
const price = cents => '$'+(cents/100).toFixed(2);

// Browser-only React bridge: MobUI has no video capture primitive.
export function ClaimQr({payload, expiresTs}) {
  const [now,setNow] = useState(Date.now()/1000);
  useEffect(() => {const timer=setInterval(()=>setNow(Date.now()/1000),1000);return ()=>clearInterval(timer);},[]);
  const notice = {margin:0,padding:14,borderRadius:12,background:'var(--ml-warn-soft)',color:'var(--ml-warn)',fontFamily:uiFont,lineHeight:1.5};
  if (!isClaimPayload(payload)) return <p role="alert" style={notice}>This claim QR is unavailable. Refresh the offer to try again.</p>;
  if (!expiresTs || now >= expiresTs) return <p role="status" style={notice}>This hold has expired. Refresh the offer to check availability.</p>;
  const seconds = Math.max(0,Math.ceil(expiresTs-now));
  const remaining = `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
  return <div className="ml-qr-ticket" style={{background:'var(--ml-bg)',color:'var(--ml-ink)',fontFamily:uiFont,padding:16,borderRadius:20,alignSelf:'center',width:'100%',maxWidth:280,boxSizing:'border-box'}}>
    <QRCodeSVG data-testid="claim-qr" value={payload} bgColor="#FFFFFF" fgColor="#000000" size={240} level="M" marginSize={4} title="Show this M-Local claim QR to the restaurant" style={{display:'block',width:'100%',maxWidth:240,height:'auto',background:'#FFFFFF',colorScheme:'light',borderRadius:8}} />
    <div style={{display:'flex',alignItems:'baseline',justifyContent:'space-between',gap:8,paddingTop:14,borderTop:'1px solid var(--ml-border)',marginTop:12}}><span style={{fontSize:13,color:'var(--ml-muted)'}}>Hold expires in</span><strong style={{fontSize:24,fontVariantNumeric:'tabular-nums',letterSpacing:.5}}>{remaining}</strong></div>
  </div>;
}

export function ClaimScanner({resolveClaim, redeemClaim, onRedeemed}) {
  const video = useRef(null), controller = useRef(null), callbacks = useRef({resolveClaim,redeemClaim,onRedeemed});
  callbacks.current = {resolveClaim,redeemClaim,onRedeemed};
  const [state,setState] = useState({phase:'loading',message:'Loading QR scanner.',preview:null});
  const [loadAttempt,setLoadAttempt] = useState(0);
  useEffect(() => {
    let cancelled=false,instance=null;
    const hide = () => {if (document.hidden && instance && ['requesting','scanning','decoding','resolving'].includes(instance.state.phase)) instance.cancel();};
    const leave = () => instance?.cancel();
    setState({phase:'loading',message:'Loading QR scanner.',preview:null});
    async function initialize() {
      try {
        const {BrowserQRCodeReader} = await import('@zxing/browser');
        if (cancelled) return;
        const reader = new BrowserQRCodeReader();
        instance = createScanController({
          secure: window.isSecureContext,
          requestStream: navigator.mediaDevices?.getUserMedia ? () => navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:'environment'}}}) : null,
          decode: (stream,element,callback) => reader.decodeFromStream(stream,element,callback),
          decodeImage: async file => {
            const url=URL.createObjectURL(file);
            try{return await reader.decodeFromImageUrl(url);}
            finally{URL.revokeObjectURL(url);}
          },
          resolveClaim: value => callbacks.current.resolveClaim(value),
          redeemClaim: value => callbacks.current.redeemClaim(value),
          onRedeemed: () => callbacks.current.onRedeemed?.()
        },setState);
        controller.current=instance;
        document.addEventListener('visibilitychange',hide); window.addEventListener('pagehide',leave);
        setState(instance.state);
      } catch {
        if (!cancelled) setState({phase:'load-error',message:'The QR scanner could not load. Check your connection, then retry scanner loading.',preview:null});
      }
    }
    initialize();
    return () => {cancelled=true;document.removeEventListener('visibilitychange',hide);window.removeEventListener('pagehide',leave);instance?.dispose();if(controller.current===instance)controller.current=null;};
  },[loadAttempt]);
  const loading=state.phase==='loading', loadFailed=state.phase==='load-error';
  const active=['requesting','scanning','decoding','resolving'].includes(state.phase), confirming=state.phase==='redeeming';
  return <section aria-label="Scan a student claim" style={box}>
    <p style={{margin:0,lineHeight:1.5}}>Scan the student’s QR, review the saved offer, then confirm redemption.</p>
    <div className="ml-scan-window">
      <video ref={video} muted playsInline aria-label="QR camera preview" style={{width:'100%',maxHeight:320,background:'var(--ml-camera-bg)',display:active?'block':'none'}} />
      {!active&&<div style={{textAlign:'center',padding:54,color:'var(--ml-camera-ink)',lineHeight:1.5}}><strong style={{display:'block',fontSize:20,marginBottom:8}}>Scan a student’s QR</strong><span style={{fontSize:14,color:'var(--ml-camera-muted)'}}>Review the saved offer before confirming.</span></div>}
      <div className="ml-scan-reticle" aria-hidden="true"/>
    </div>
    {state.message && <p role={state.phase==='error'||loadFailed?'alert':'status'} aria-live="polite" style={{margin:0,lineHeight:1.5}}>{state.message}</p>}
    {state.preview && <div style={{...box,background:'var(--ml-bg)',padding:20,borderRadius:20,border:'1px solid var(--ml-border)'}}>
      <strong>{state.preview.title_snapshot}</strong>
      <strong style={{fontSize:26}}>{price(state.preview.price_cents)}</strong>
      <span>{state.preview.restaurant}</span>
      <span>For: {state.preview.eligibility || 'See restaurant conditions.'}</span>
      <span>{state.preview.terms || 'No additional terms.'}</span>
      <span>Hold expires {state.preview.expires_label}.</span>
      <small>Prices exclude tax unless the saved terms say otherwise. Check the stated ID requirement.</small>
      <button style={button} type="button" disabled={confirming} onClick={()=>controller.current?.confirm()}>{confirming?'Confirming…':'Confirm redemption'}</button>
    </div>}
    {!active && !state.preview && <button style={button} type="button" disabled={loading} onClick={()=>loadFailed?setLoadAttempt(attempt=>attempt+1):controller.current?.start(video.current)}>{loading?'Loading QR scanner':loadFailed?'Retry scanner loading':state.phase==='success'?'Scan next claim':state.phase==='error'?'Retry camera scan':'Start camera scan'}</button>}
    {!active&&!state.preview&&<label style={{...secondary,display:'flex',flexDirection:'column',gap:10,boxSizing:'border-box'}}>
      <span>Choose a QR image</span>
      <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" aria-label="Choose a QR image" disabled={loading||loadFailed} onChange={event=>{const file=event.target.files?.[0];event.target.value='';if(file)controller.current?.startImage(file);}} style={{maxWidth:'100%',font:'inherit',minHeight:44}}/>
    </label>}
    {(active || state.preview) && <button style={secondary} type="button" disabled={confirming} onClick={()=>controller.current?.cancel()}>Cancel scan</button>}
    <small style={{lineHeight:1.5,color:'var(--ml-muted)'}}>Allow camera access or choose a QR screenshot. Images are decoded on this device and are never uploaded; only the opaque claim credential is checked with the server. Redemption still needs your confirmation.</small>
  </section>;
}
