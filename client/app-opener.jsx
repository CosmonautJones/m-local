import React, {useEffect, useState} from 'react';

// App opener ported from the Claude Design "Mmm Local Intro" (navy theme).
// Choreography is authored on a 1080x1920 stage and keyed to T, seconds since start.
// Plays on every page load. Timing state lives at module level so UiFoundation
// remounts between app screens continue the same run instead of restarting or cutting it.

const CUES = {Drop:0, Yum:1.4, Local:3.4, Hold:4.8};
const TOTAL = 6.2;
const EXIT_MS = 320;
const W = 1080, H = 1920;
const INK = '#FFFFFF', SQUARE = '#FEC809', BG = '#02305C';
const MARK = '/static/assets/brand/m-mark-maize.png';
const WORD = '/static/assets/brand/local-word-white.png';

const S = 2;
const MT = 836;
const BASE = MT + 118 * S;
const X_ALONE = 540 - 146 * S / 2;
const X_YUM = 70;
const X_FINAL = 90;
const FONT = 300;
const GLYPHS = ['m', 'm', '.', '.'];

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const Easing = {
  easeInCubic: t => t * t * t,
  easeOutCubic: t => (--t) * t * t + 1,
  easeOutBack: t => {const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);},
};
function animate(from, to, start, end, ease) {
  return t => t <= start ? from : t >= end ? to : from + (to - from) * ease((t - start) / (end - start));
}
const MOTION = {
  enter: (from, to, start, end) => animate(from, to, start, end, Easing.easeOutCubic),
  pop: (from, to, start, end) => animate(from, to, start, end, Easing.easeOutBack),
  drop: (from, to, start, end) => animate(from, to, start, end, Easing.easeInCubic),
};
// 0..1 bump (up and back) across [a,b]
const hop = (T, a, b) => (T <= a || T >= b) ? 0 : Math.sin(Math.PI * (T - a) / (b - a));

function Piece({T}) {
  const C = CUES;
  const mx = T < C.Yum + 1 ? MOTION.enter(X_ALONE, X_YUM, C.Yum - 0.1, C.Yum + 0.35)(T)
                           : MOTION.enter(X_YUM, X_FINAL, C.Local + 0.05, C.Local + 0.6)(T);

  const mScale = MOTION.pop(0.35, 1, C.Drop + 0.15, C.Drop + 0.75)(T);
  const mOp = MOTION.enter(0, 1, C.Drop + 0.15, C.Drop + 0.45)(T);
  const land = C.Drop + 0.95;
  const mSquash = 1 - 0.07 * hop(T, land, land + 0.28) - 0.03 * hop(T, C.Local + 0.75, C.Local + 1.0);
  const mStretch = 1 + 0.04 * hop(T, land, land + 0.28);

  const sqFall = MOTION.drop(-760, 0, C.Drop + 0.55, land)(T);
  const sqY = sqFall - 46 * hop(T, land, land + 0.34) - 14 * hop(T, land + 0.34, land + 0.5)
            - 70 * hop(T, C.Local + 0.7, C.Local + 1.15);
  const sqRot = MOTION.enter(-120, 0, C.Drop + 0.55, land)(T) + MOTION.enter(0, 90, C.Local + 0.7, C.Local + 1.15)(T);
  const sqSquash = 1 - 0.25 * hop(T, land - 0.02, land + 0.12);

  const yumA = C.Yum + 1.0, yumB = C.Yum + 1.95;
  const env = clamp(Math.min((T - yumA) / 0.2, (yumB - T) / 0.25), 0, 1);
  const letters = GLYPHS.map((g, i) => {
    const t0 = C.Yum + 0.15 + i * (i < 2 ? 0.28 : 0.22) + (i >= 2 ? 0.12 : 0);
    const s = MOTION.pop(0, 1, t0, t0 + 0.38)(T);
    const y = MOTION.enter(70, 0, t0, t0 + 0.38)(T);
    const phase = (T - yumA) * Math.PI * 2 * 2.1 - i * 0.7;
    const bob = -Math.max(0, Math.sin(phase)) * 26 * env;
    const chew = 1 + 0.08 * Math.sin(phase + Math.PI / 2) * env;
    const e0 = C.Local + i * 0.05;
    const gone = MOTION.drop(1, 0, e0, e0 + 0.32)(T);
    return <span key={i} style={{
      display:'inline-block', transformOrigin:'50% 100%',
      marginLeft: i === 2 ? 6 : (i === 3 ? -14 : 0),
      opacity: clamp(s * 3, 0, 1) * gone,
      transform: `translateY(${y + bob}px) scale(${s * (2 - chew)}, ${s * chew * gone})`,
    }}>{g}</span>;
  });

  const lA = C.Local + 0.2;
  const wipe = MOTION.enter(100, 0, lA, lA + 0.55)(T);
  const lY = MOTION.pop(36, 0, lA, lA + 0.6)(T);
  const lOp = MOTION.enter(0, 1, lA, lA + 0.25)(T);

  const push = MOTION.enter(1, 1.035, C.Local + 0.8, C.Hold + 1.4)(T);
  const out = MOTION.drop(1, 0, C.Hold + 1.05, C.Hold + 1.4)(T);

  return <div style={{position:'absolute', inset:0, opacity:out, transform:`scale(${push})`, transformOrigin:'540px 960px'}}>
    <div style={{position:'absolute', left:mx, top:MT, width:150 * S, height:124 * S}}>
      <img src={MARK} alt="" draggable="false" style={{
        position:'absolute', left:0, top:0, width:'100%', height:'100%', opacity:mOp,
        transformOrigin:`50% ${118 * S}px`, transform:`scale(${mScale * mStretch}, ${mScale * mSquash})`,
      }}/>
      <div style={{
        position:'absolute', left:139 * S, top:-26 * S, width:36 * S, height:36 * S,
        borderRadius:6 * S, background:SQUARE, transformOrigin:'50% 50%',
        transform:`translateY(${sqY + 36 * S * (1 - sqSquash) / 2}px) rotate(${sqRot}deg) scale(${2 - sqSquash}, ${sqSquash})`,
      }}/>
    </div>
    <div style={{
      position:'absolute', left:mx + 316, top:BASE - FONT * 0.95, height:FONT * 1.2,
      fontFamily:'Figtree, system-ui, sans-serif', fontWeight:800, fontSize:FONT, lineHeight:1.2, letterSpacing:'-0.03em',
      color:INK, whiteSpace:'nowrap',
    }}>{letters}</div>
    <img src={WORD} alt="" draggable="false" style={{
      position:'absolute', left:mx + 170 * S, top:MT, width:280 * S, height:124 * S,
      opacity:lOp, clipPath:`inset(-10% ${wipe}% -10% 0)`, transform:`translateY(${lY}px)`,
    }}/>
  </div>;
}

const run = {startedAt:null, done:false};

function shouldPlay() {
  try {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false;
  } catch (error) {console.warn('M-Local opener: reduced-motion check failed', error);}
  return true;
}

function stageScale() {
  return Math.min(window.innerWidth / W, window.innerHeight / H) || 0.2;
}

export function AppOpener() {
  const [, setFrame] = useState(0);
  const [leaving, setLeaving] = useState(false);
  const [removed, setRemoved] = useState(false);
  const [scale, setScale] = useState(stageScale);
  if (run.startedAt === null && !run.done) {
    if (shouldPlay()) run.startedAt = performance.now();
    else run.done = true;
  }

  useEffect(() => {
    if (run.done) return undefined;
    let raf = 0, exitTimer = 0;
    const finish = () => {
      if (run.done) return;
      run.done = true;
      setLeaving(true);
      exitTimer = setTimeout(() => setRemoved(true), EXIT_MS);
    };
    const tick = () => {
      if ((performance.now() - run.startedAt) / 1000 >= TOTAL) {finish(); return;}
      setFrame(f => f + 1);
      raf = requestAnimationFrame(tick);
    };
    const onKey = e => {if (e.key === 'Escape') finish();};
    const onResize = () => setScale(stageScale());
    run.skip = finish;
    raf = requestAnimationFrame(tick);
    window.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(exitTimer);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
    };
  }, []);

  if (removed || (run.done && !leaving)) return null;
  const T = Math.min(TOTAL, (performance.now() - run.startedAt) / 1000);
  return <div data-testid="app-opener" aria-hidden="true" onClick={() => run.skip && run.skip()} style={{
    position:'fixed', inset:0, zIndex:2147483000, background:BG, overflow:'hidden', cursor:'pointer',
    opacity:leaving ? 0 : 1, transition:`opacity ${EXIT_MS}ms ease`, pointerEvents:leaving ? 'none' : 'auto',
  }}>
    <div style={{position:'absolute', left:'50%', top:'50%', width:W, height:H,
      transform:`translate(-50%, -50%) scale(${scale})`, transformOrigin:'50% 50%'}}>
      <Piece T={T}/>
    </div>
  </div>;
}
