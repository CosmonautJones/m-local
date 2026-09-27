import React, {useEffect, useRef, useState} from 'react';

const stack={display:'flex',flexDirection:'column',gap:12,minWidth:0,color:'#1d1a16',fontFamily:'system-ui, sans-serif'};
const input={width:'100%',minWidth:0,boxSizing:'border-box',minHeight:48,padding:'12px',fontSize:16,border:'1px solid #c9bfb2',borderRadius:10,background:'#fff',color:'#1d1a16'};
const button={...input,background:'#b83a0b',color:'#fff',fontWeight:700,cursor:'pointer',borderColor:'#b83a0b'};
const secondary={...button,background:'#fff',color:'#3a342c',borderColor:'#c9bfb2'};
const hint={fontSize:13,lineHeight:1.5,margin:0,color:'#6b6157'};
const label={...stack,gap:6,fontSize:14,fontWeight:600};
function Notice({children}) {return children ? <p role="status" aria-live="polite" style={{...hint,color:'#1f3a5f'}}>{children}</p>:null;}
function Input({title,...props}) {return <label style={label}>{title}<input style={input} {...props}/></label>;}

const audienceKey='mlocal_audience';
export function readAudience() {
 try {const value=localStorage.getItem(audienceKey);return ['student','business'].includes(value)?value:'';}catch{return '';}
}
export function rememberAudience(value) {
 if(!['student','business'].includes(value))return;
 try {localStorage.setItem(audienceKey,value);}catch{/* Browsing still works when storage is unavailable. */}
}
export function clearAudience() {
 try {localStorage.removeItem(audienceKey);}catch{/* Browsing still works when storage is unavailable. */}
}
export function audienceForSession(session) {
 if(!session?.authenticated)return '';
 return session.role==='student'?'student':['business','merchant'].includes(session.role)?'business':'';
}

export function AudienceWelcome({onChoose}) {
 const choice={...secondary,textAlign:'left',padding:'22px 20px',display:'flex',alignItems:'center',justifyContent:'space-between',gap:16,borderRadius:16};
 return <main style={{height:'100%',overflowY:'auto',background:'#f7f3ec',fontFamily:'system-ui, sans-serif',color:'#1d1a16'}}>
  <style>{'.mlocal-choice:focus-visible{outline:3px solid #1f3a5f;outline-offset:4px}.mlocal-choice:hover{filter:brightness(.97)}'}</style>
  <div style={{...stack,boxSizing:'border-box',minHeight:'100%',maxWidth:480,margin:'0 auto',padding:'36px 24px',justifyContent:'center',gap:28}}>
   <div style={{fontSize:12,fontWeight:750,letterSpacing:2,color:'#b83a0b'}}>M-LOCAL / ANN ARBOR</div>
   <header style={{...stack,gap:12}}>
    <h1 style={{fontSize:36,lineHeight:1.08,letterSpacing:-1.2,margin:0,fontWeight:800}}>Welcome to M-Local</h1>
    <p style={{...hint,fontSize:17}}>Good things are happening nearby.<br/>How will you join in?</p>
   </header>
   <div style={{...stack,gap:12}}>
    <button className="mlocal-choice" type="button" style={{...choice,background:'#b83a0b',borderColor:'#b83a0b',color:'#fff'}} onClick={()=>onChoose('student')}>
     <span style={{...stack,gap:8,color:'inherit'}}><span style={{fontSize:21,fontWeight:750}}>Find local deals</span><span style={{fontSize:14,lineHeight:1.5,fontWeight:400}}>Join with your U-M email.<br/>Discover offers from local favorites.</span></span><span aria-hidden="true" style={{fontSize:26}}>→</span>
    </button>
    <button className="mlocal-choice" type="button" style={choice} onClick={()=>onChoose('business')}>
     <span style={{...stack,gap:8,color:'inherit'}}><span style={{fontSize:21,fontWeight:750}}>List my business</span><span style={{fontSize:14,lineHeight:1.5,fontWeight:400}}>Create your business profile.<br/>Connect with the U-M community.</span></span><span aria-hidden="true" style={{fontSize:26}}>→</span>
    </button>
   </div>
   <p style={hint}>New here or coming back? Choose how you’d like to sign in.</p>
  </div>
 </main>;
}

export function EmailOnboarding({kind='student',requestCode,verifyCode,onVerified,legacySignIn,onLegacySession,onCancel,inputRef}) {
 const [name,setName]=useState(''),[value,setValue]=useState('');
 const [code,setCode]=useState(''),[challenge,setChallenge]=useState(null),[message,setMessage]=useState('');
 const [busy,setBusy]=useState(false),[cooldown,setCooldown]=useState(0),[demo,setDemo]=useState(false),[password,setPassword]=useState('');
 const mounted=useRef(true),inFlight=useRef(false),codeRef=useRef(null);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 useEffect(()=>{if(cooldown<=0)return;const timer=setTimeout(()=>setCooldown(v=>Math.max(0,v-1)),1000);return()=>clearTimeout(timer);},[cooldown]);
 useEffect(()=>{if(challenge)codeRef.current?.focus();else inputRef?.current?.focus();},[challenge,kind,demo]);
 async function run(action){if(inFlight.current)return;inFlight.current=true;setBusy(true);setMessage('');try{await action();}catch{if(mounted.current)setMessage('Could not connect. Your entries are kept; please try again.');}finally{inFlight.current=false;if(mounted.current)setBusy(false);}}
 async function send(){await run(async()=>{const reply=await requestCode(value,kind,name);if(!mounted.current)return;setMessage(reply.message);if(reply.ok){setChallenge(reply);setCode('');setCooldown(reply.retry_after||60);}});}
 async function verify(){await run(async()=>{const reply=await verifyCode(challenge.challenge,code);if(!mounted.current)return;if(!reply.ok){setMessage(reply.message);return;}await onVerified(reply.token);});}
 if(demo)return <form style={stack} onSubmit={e=>{e.preventDefault();run(async()=>{const session=await legacySignIn(value,password);if(mounted.current)await onLegacySession(session);});}}>
  <p style={hint}>Use the provisioned credentials shared by the demo host.</p>
  <Input title="Email" aria-label="Email" autoFocus placeholder="Email" type="email" autoComplete="username" value={value} onChange={e=>setValue(e.target.value)} required/>
  <Input title="Password" aria-label="Password" placeholder="Password" type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required/>
  <button style={button} disabled={busy}>{busy?'Signing in...':'Sign in'}</button>
  <button style={secondary} type="button" disabled={busy} onClick={()=>{setDemo(false);setValue('');setPassword('');setMessage('');}}>Back to email verification</button><Notice>{message}</Notice>
 </form>;
 return <form style={stack} onSubmit={e=>{e.preventDefault();challenge?verify():send();}}>
  {!challenge ? <>
   <Input title="Your name" placeholder="Your name" autoComplete="name" maxLength={80} value={name} onChange={e=>setName(e.target.value)} required disabled={busy}/>
   {kind==='student' ? <label style={label}>U-M email
    <div style={{display:'flex',border:'1px solid #c9bfb2',borderRadius:10,overflow:'hidden',minWidth:0}}>
     <input ref={inputRef} autoFocus aria-label="U-M uniqname" aria-describedby="umich-email-help" style={{...input,border:0,borderRadius:0,flex:1}} placeholder="uniqname" autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false} pattern="[A-Za-z][A-Za-z0-9]{1,31}" maxLength={32} value={value} onChange={e=>setValue(e.target.value)} required disabled={busy}/>
     <span style={{padding:'13px 10px',background:'#eee9e2',color:'#6b6157',fontWeight:500,whiteSpace:'nowrap'}}>@umich.edu</span>
    </div>
    <span id="umich-email-help" style={hint}>Enter your uniqname. We’ll email a code to verify your U-M inbox. No university password needed.</span>
   </label> : <Input title="Work email" placeholder="you@business.com" type="email" autoComplete="email" maxLength={254} value={value} onChange={e=>setValue(e.target.value)} required disabled={busy}/>}
   {kind==='business'&&<p style={hint}>Verify your work email, then start your business profile from your website or enter it yourself.</p>}
   <button style={button} disabled={busy}>{busy?'Sending...':'Send verification code'}</button>
   <p style={hint}>New here? Verifying your email creates your account. Returning? It signs you back in.</p>
  </> : <>
   <strong>Check your email</strong><p style={hint}>Enter the code sent to <strong>{challenge.email}</strong>. It expires in 10 minutes.</p>
   <label style={label}>Verification code<input ref={codeRef} style={{...input,letterSpacing:6,fontSize:24}} aria-label="Verification code" placeholder="123456" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,''))} required disabled={busy}/></label>
   <button style={button} disabled={busy}>{busy?'Verifying...':'Verify and continue'}</button>
   <button style={secondary} type="button" disabled={busy||cooldown>0} onClick={send}>{cooldown>0?`Resend code in ${cooldown}s`:'Resend code'}</button>
   <button style={secondary} type="button" disabled={busy} onClick={()=>{setChallenge(null);setCode('');setMessage('');}}>Change email</button>
  </>}
  <Notice>{message}</Notice>
  {!challenge&&<button style={{...secondary,fontSize:13}} type="button" disabled={busy} onClick={()=>{setDemo(true);setValue('');setMessage('');}}>{kind==='student'?'Demo sign-in':'Existing restaurant sign-in'}</button>}
  <button style={secondary} type="button" disabled={busy} onClick={onCancel}>Keep browsing</button>
 </form>;
}

const empty={name:'',cuisine:'',description:'',address:'',website:'',menu_text:'',menu_url:'',image_url:'',status:'draft',image_urls:[],menu_urls:[],sources:[]};
export function BusinessOnboarding({getDraft,importWebsite,saveDraft}) {
 const [draft,setDraft]=useState(empty),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[confirmed,setConfirmed]=useState(false),[ready,setReady]=useState(false);
 const mounted=useRef(true),inFlight=useRef(false),edited=useRef(false);
 useEffect(()=>{mounted.current=true;getDraft().then(reply=>{if(!mounted.current||edited.current)return;if(reply.ok)setDraft({...empty,...reply});else setMessage(reply.message);}).catch(()=>{if(mounted.current)setMessage('Could not load your saved profile. Retry before making changes.');}).finally(()=>{if(mounted.current)setReady(true);});return()=>{mounted.current=false;};},[]);
 const field=(key,value)=>{edited.current=true;setDraft(d=>({...d,[key]:value,status:'draft'}));setConfirmed(false);};
 async function run(action){if(inFlight.current)return;inFlight.current=true;setBusy(true);setMessage('');try{const reply=await action();if(!mounted.current)return;if(reply.ok){setDraft({...empty,...reply});setConfirmed(false);}setMessage(reply.message);}catch{if(mounted.current)setMessage('Could not connect. Your entries are kept; please retry.');}finally{inFlight.current=false;if(mounted.current)setBusy(false);}}
 const imported=()=>run(()=>importWebsite(draft.website));
 return <section aria-label="Create your business profile" style={{...stack,paddingTop:16,borderTop:'1px solid #e7dfd3'}}>
  <h3 style={{margin:0,fontSize:20}}>Bring your business to M-Local</h3>
  <p style={hint}>Start with your website. We’ll find details, menu links and image options for you to review. You can also fill this in yourself.</p>
  <form style={stack} onSubmit={e=>{e.preventDefault();imported();}}>
   <Input title="Business website" placeholder="https://your-business.com" type="url" value={draft.website} onChange={e=>field('website',e.target.value)} disabled={busy||!ready} required/>
   <button style={secondary} disabled={busy||!ready}>{busy?'Working...':'Import website details'}</button>
  </form>
  <Notice>{message}</Notice>
  {draft.sources.length>0&&<div style={hint}>Sources: {draft.sources.map((url,i)=><React.Fragment key={url}>{i>0?' · ':''}<a href={url} target="_blank" rel="noopener noreferrer">{i===0?'Website':'Menu page'}</a></React.Fragment>)}</div>}
  <form style={stack} onSubmit={e=>{e.preventDefault();run(()=>saveDraft(draft.name,draft.cuisine,draft.description,draft.address,draft.website,draft.menu_text,draft.menu_url,draft.image_url,confirmed));}}>
   <Input title="Business name" placeholder="Business name" maxLength={160} value={draft.name} onChange={e=>field('name',e.target.value)} required disabled={busy||!ready}/>
   <Input title="Cuisine" placeholder="Cuisine" maxLength={120} value={draft.cuisine} onChange={e=>field('cuisine',e.target.value)} disabled={busy||!ready}/>
   <Input title="Street address" placeholder="Street address" maxLength={500} value={draft.address} onChange={e=>field('address',e.target.value)} required disabled={busy||!ready}/>
   <label style={label}>About your business<textarea style={{...input,minHeight:90,resize:'vertical'}} placeholder="About your business" maxLength={1000} value={draft.description} onChange={e=>field('description',e.target.value)} disabled={busy||!ready}/></label>
   <label style={label}>Menu notes to review<textarea style={{...input,minHeight:120,resize:'vertical'}} placeholder="Menu items and prices" maxLength={4000} value={draft.menu_text} onChange={e=>field('menu_text',e.target.value)} disabled={busy||!ready}/></label>
   <p style={hint}>Check item names and prices against your current menu. These notes do not create offers.</p>
   {draft.menu_urls.length>0&&<label style={label}>Found menu links<select style={input} value={draft.menu_url} onChange={e=>field('menu_url',e.target.value)} disabled={busy}><option value="">Choose a menu link</option>{draft.menu_urls.map(url=><option key={url} value={url}>{url}</option>)}</select></label>}
   <Input title="Menu link" placeholder="https://your-business.com/menu" type="url" maxLength={2048} value={draft.menu_url} onChange={e=>field('menu_url',e.target.value)} disabled={busy||!ready}/>
   {draft.image_urls.length>0&&<label style={label}>Found images<select style={input} value={draft.image_url} onChange={e=>field('image_url',e.target.value)} disabled={busy}><option value="">Choose an image</option>{draft.image_urls.map(url=><option key={url} value={url}>{url}</option>)}</select></label>}
   <Input title="Image link" placeholder="https://your-business.com/photo.jpg" type="url" maxLength={2048} value={draft.image_url} onChange={e=>field('image_url',e.target.value)} disabled={busy||!ready}/>
   {draft.image_url&&/^https:\/\//.test(draft.image_url)&&<a href={draft.image_url} target="_blank" rel="noopener noreferrer" style={hint}>Review selected image</a>}
   <label style={{...hint,display:'flex',gap:10,alignItems:'flex-start',minHeight:44}}><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)} disabled={busy||!ready} style={{width:20,height:20,flexShrink:0}}/>I can represent this business and have permission to use the details and selected image.</label>
   <button style={button} disabled={busy||!ready||!confirmed}>{busy?'Saving...':'Save business for review'}</button>
   <p style={hint}>{draft.status==='pending_review'?'Saved for review. ':''}The team must confirm business ownership before publishing or enabling offer management.</p>
  </form>
 </section>;
}
