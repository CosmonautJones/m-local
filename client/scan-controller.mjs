// Browser resource/async orchestration only. Jac resolves and redeems the opaque credential.
export function isClaimPayload(value) {
  // 32 bytes -> 43 unpadded base64url chars; final two unused bits must be zero.
  return typeof value === 'string' && /^mlocal:v1:[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$/.test(value);
}

export function cameraError(error) {
  if (error?.name === 'NotAllowedError' || error?.name === 'PermissionDeniedError') return 'Camera permission was denied. Allow camera access in this browser’s site settings, then retry.';
  if (error?.name === 'NotFoundError' || error?.name === 'DevicesNotFoundError') return 'No camera was found. Connect a camera or use a phone with a camera over HTTPS.';
  if (error?.name === 'NotReadableError' || error?.name === 'TrackStartError') return 'The camera is unavailable. Close other apps using it, then retry.';
  return 'The camera could not start. Check browser camera permissions, close other camera apps, then retry.';
}

export function createScanController(deps, onChange = () => {}) {
  let state = {phase: 'idle', message: '', preview: null};
  let generation = 0, disposed = false, stream = null, controls = null, payload = '', latched = false;
  const current = (id) => !disposed && id === generation;
  const emit = (next) => { if (!disposed) {state = {...state, ...next}; onChange(state);} };
  const stopStream = (value) => { for (const track of value?.getTracks?.() ?? []) { try {track.stop();} catch {} } };
  const stopCamera = () => {
    try { controls?.stop(); } catch {}
    controls = null; stopStream(stream); stream = null;
  };
  const cancel = () => {
    generation++; latched = false; payload = ''; stopCamera();
    emit({phase: 'idle', message: '', preview: null});
  };
  async function startImage(file) {
    if(disposed||['requesting','scanning','decoding','resolving','redeeming'].includes(state.phase))return;
    cancel();const id=generation;
    if(!file||!['image/png','image/jpeg','image/webp','image/gif'].includes(file.type)||file.size<=0||file.size>10*1024*1024){
      emit({phase:'error',message:'Choose a PNG, JPEG, WebP or GIF QR image smaller than 10 MB.'});return;
    }
    emit({phase:'decoding',message:'Reading the QR image on this device.',preview:null});
    let scanned;
    try {
      const result=await deps.decodeImage(file);
      if(!current(id))return;
      scanned=result?.getText?.()||'';
    }catch{
      if(current(id))emit({phase:'error',preview:null,message:'No readable claim QR was found. Choose a clear screenshot showing the complete QR square, or retry the camera.'});
      return;
    }
    if(!isClaimPayload(scanned)){emit({phase:'error',preview:null,message:'This is not an M-Local claim QR. Ask the student to open their claimed offer and scan again.'});return;}
    payload=scanned;emit({phase:'resolving',message:'Checking the claim with the restaurant.',preview:null});
    try {
      const resolved=await deps.resolveClaim(scanned);
      if(!current(id))return;
      if(!resolved?.ok){payload='';emit({phase:'error',message:resolved?.message||'This claim cannot be redeemed. Ask the student to refresh their offer.',preview:null});return;}
      emit({phase:'preview',preview:resolved,message:'Check the saved terms and student ID before confirming.'});
    }catch{
      if(current(id)){payload='';emit({phase:'error',preview:null,message:'Could not check the claim. Check the connection, then scan again.'});}
    }
  }
  async function start(video) {
    if (disposed || ['requesting','scanning','decoding','resolving','redeeming'].includes(state.phase)) return;
    cancel(); const id = generation;
    if (!deps.secure) {emit({phase: 'error', message: 'Camera scanning needs HTTPS on a remote phone. Use the merchant laptop at localhost for the first test.'}); return;}
    if (!deps.requestStream) {emit({phase: 'error', message: 'This browser does not expose a camera. Try a current Safari, Chrome or Firefox browser with camera access.'}); return;}
    emit({phase: 'requesting', message: 'Allow camera access to scan the student’s QR.'});
    try {
      const acquired = await deps.requestStream();
      if (!current(id)) {stopStream(acquired); return;}
      stream = acquired; emit({phase: 'scanning', message: 'Point the camera at the student’s QR. Keep the whole square in view.'});
      const acquiredControls = await deps.decode(acquired, video, async (result) => {
        if (!result || !current(id) || latched) return;
        latched = true; stopCamera();
        const scanned = result.getText();
        if (!isClaimPayload(scanned)) {emit({phase: 'error', preview: null, message: 'This is not an M-Local claim QR. Ask the student to open their claimed offer and scan again.'}); return;}
        payload = scanned; emit({phase: 'resolving', message: 'Checking the claim with the restaurant…', preview: null});
        try {
          const resolved = await deps.resolveClaim(scanned);
          if (!current(id)) return;
          if (!resolved?.ok) {payload = ''; emit({phase: 'error', message: resolved?.message || 'This claim cannot be redeemed. Ask the student to refresh their offer.', preview: null}); return;}
          emit({phase: 'preview', preview: resolved, message: 'Check the saved terms and student ID before confirming.'});
        } catch {
          if (current(id)) {payload = ''; emit({phase: 'error', preview: null, message: 'Could not check the claim. Check the connection, then scan again.'});}
        }
      });
      // A scan or unmount can happen before ZXing returns its controls.
      if (!current(id) || latched) {try {acquiredControls?.stop();} catch {} stopStream(acquired);}
      else controls = acquiredControls;
    } catch (error) {
      if (current(id)) {stopCamera(); emit({phase: 'error', preview: null, message: cameraError(error)});}
    }
  }
  async function confirm() {
    if (disposed || state.phase !== 'preview' || !payload || !state.preview?.ok) return;
    const id = generation, value = payload;
    emit({phase: 'redeeming', message: 'Confirming redemption…'});
    try {
      const result = await deps.redeemClaim(value);
      if (!current(id)) return;
      if (result?.ok) {
        payload = ''; emit({phase: 'success', preview: null, message: result.message || 'Claim redeemed.'});
        // Refresh is secondary: never turn a confirmed redemption into a false failure.
        try {await deps.onRedeemed?.();} catch {}
      } else {
        payload = ''; emit({phase: 'error', preview: null, message: result?.message || 'Redemption was not accepted. Refresh the claim and scan again.'});
      }
    } catch {
      if (current(id)) emit({phase: 'preview', message: 'The connection failed. Check the connection and retry confirmation; the server prevents a second redemption.'});
    }
  }
  return {get state(){return state;}, start, startImage, confirm, cancel,
    dispose() {disposed = true; generation++; payload = ""; latched = true; stopCamera();}
  };
}
