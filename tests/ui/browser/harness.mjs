// Compiled UI checks with synthetic RPC responses. No real auth, DB or camera evidence.
import {createRequire} from 'node:module';
import {readFileSync,readdirSync} from 'node:fs';
import {resolve} from 'node:path';
const root=resolve(process.env.MLOCAL_UI_APP_ROOT || resolve(import.meta.dirname,'../../..'));
const runtimeRequire=createRequire(resolve(process.env.MLOCAL_UI_TEST_MODULES || `${root}/.jac/ui-test-runtime/node_modules`, '../package.json'));
const {JSDOM,VirtualConsole}=runtimeRequire('jsdom');
const clientRequire=createRequire(`${root}/.jac/client/package.json`);
const {transformSync}=clientRequire('esbuild');
const dist=resolve(root,'.jac/client/dist');
const bundle=readFileSync(resolve(dist,readdirSync(dist).find(n=>/^client\..*\.js$/.test(n))),'utf8');
const executable=transformSync(bundle,{format:'iife',target:'es2022'}).code;
export const qr='mlocal:v1:'+'A'.repeat(43);
export function offer(extra={}) {return {
 id:'fixture-offer',title:'Current bowl',description:'Fictional UI test meal',restaurant:'Fixture Kitchen',
 price:9,regular_price:12,address:'Fictional test address',neighborhood:'Test area',state:'active',remaining:4,quantity:5,
 eligibility:'Student ID',terms:'Current offer terms',menu_item:'',dietary:[],reasons:[],is_demo:false,time_label:'Until tonight',
 my_status:'',my_claim_id:'',my_qr_payload:'',my_title:'',my_price_cents:0,my_terms:'',my_eligibility:'',my_expires:'',my_expires_ts:0,entrance_note:'',note_date:'',image_url:'',access_context:{state:'none',notices:[]},
 start_input:'2026-09-26 17:00',end_input:'2026-09-26 23:00', ...extra
};}
export function held(extra={}) {return offer({my_claim_id:'fixture-claim',my_status:'claimed',my_qr_payload:qr,
 my_title:'Saved bowl',my_price_cents:300,my_terms:'Saved meal terms',my_eligibility:'Saved ID condition',
 my_expires:'8:00 PM',my_expires_ts:Date.now()/1000+1200,...extra});}
export function feedItem(o,extra={}) {return {offer:o,place:'fixture-kitchen',place_labels:[],categories:[],price_cents:Math.round((o.price||0)*100),
 regular_cents:Math.round((o.regular_price||0)*100),price_range:'',reasons:[],slot:'more',is_favorite:false,...extra};}
export function home(items,extra={}) {return {signed_in:false,personalized:false,completed:true,price_range:'',favorites:[],
 items:items.map(i=>i.offer?i:feedItem(i)),total_deals:items.length,note:'',...extra};}
const tastes=()=>({ok:true,message:'',signed_in:true,completed:true,categories:[],diets:[],price_range:'',favorites:[],
 all_categories:[{key:'pizza',label:'Pizza'}],all_diets:[{key:'vegetarian',label:'Vegetarian'}],all_price_ranges:[{key:'5to8',label:'$5 to $8'}]});
export async function until(fn,message='condition',timeout=3000) {
 const end=Date.now()+timeout;while(Date.now()<end){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw new Error(`Timed out: ${message}`);
}
export async function app({role='student',verified=false,audience='student',item=offer(),intercept,configureWindow}={}) {
 const errors=[],calls=[];let activeRole=role;
 const virtualConsole=new VirtualConsole();virtualConsole.on('jsdomError',e=>errors.push(e.message));
 // Jac build emits the real bundle; its HTTP server supplies the HTML shell at runtime.
 const dom=new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>',{url:'http://localhost:8123',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole});
 const w=dom.window;
 w.matchMedia=()=>({matches:false,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}});
 w.ResizeObserver=class{observe(){}unobserve(){}disconnect(){}};
 w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;w.Response=Response;w.Request=Request;w.Headers=Headers;
 if(configureWindow)configureWindow(w);
 if(audience)w.localStorage.setItem('mlocal_audience',audience);
 if(role!=='guest')w.localStorage.setItem('jac_token','synthetic-ui-token');
 const session=()=>({authenticated:activeRole!=='guest',role:activeRole,actor_id:`fixture-${activeRole}`,restaurant_id:activeRole==='merchant'?'fixture-restaurant':'',display_name:`Fixture ${activeRole}`,is_demo:!verified,email_verified:verified,business_account:verified&&['business','merchant'].includes(activeRole)});
 const portal=()=>({ok:true,name:'Fixture Kitchen',cuisine:'Test cuisine',blurb:'Fixture profile',address:'Test address',neighborhood:'Test area',entrance_note:'',note_date:'',image_url:item.image_url||'',offers:[item],claims:[],is_demo:true,message:''});
 w.fetch=async (url,options={})=>{
  const name=String(url).split('/').at(-1),body=options.body?JSON.parse(options.body):{};
  calls.push({name,body});
  const override=intercept?await intercept(name,body,{window:w,calls}):undefined;
  if(override!==undefined) return override;
  if(name==='login'){activeRole='student';return Response.json({ok:true,data:{token:'synthetic-ui-token',root_id:'fixture-student'}});}
  const visibleItem=w.localStorage.getItem('jac_token') ? item : Object.fromEntries(Object.entries(item).map(([key,value])=>[key,key.startsWith('my_') ? (typeof value==='number'?0:'') : value]));
  const results={current_session:session(),list_offers:[visibleItem],get_offer:visibleItem,merchant_portal:portal(),merchant_insights:{ok:false,message:"No recorded insights in this fixture."},
   home_feed:home([visibleItem],{signed_in:activeRole!=='guest'}),taste_choices:tastes(),save_taste:tastes(),toggle_favorite:tastes(),nearby_after:{ok:false,groups:[]},
   claim_offer:{ok:true,message:'Fixture claim accepted',claim_id:'fixture-claim',qr_payload:qr},
   cancel_claim:{ok:true,message:'Fixture cancellation accepted'},
   update_profile:portal(),save_offer:{ok:true,message:'Fixture offer saved',code:'fixture-offer'},
   get_business_draft:{ok:true,status:'draft',message:''},
   offer_defaults:['2026-09-26 17:00','2026-09-26 23:00'],set_offer_status:{ok:true,message:'Fixture status saved'}};
  if(!(name in results))throw new Error(`Unexpected fixture endpoint ${name}`);
  return rpc(results[name]);
 };
 w.addEventListener('error',e=>errors.push(e.message));
 w.eval(executable);
 const initialTitle=item.my_claim_id&&['claimed','redeemed'].includes(item.my_status)?item.my_title:item.title;
 try{await until(()=>[initialTitle,'Welcome to M-Local','Offers are on their way','Could not load offers.','Sign in to M-Local','List your business','YOUR BUSINESS','Profile and offers'].some(text=>w.document.body.textContent.includes(text)),'initial app render');}
 catch(error){dom.window.close();throw error;}
 return {window:w,document:w.document,calls,errors,text:()=>w.document.body.textContent,
  find(text){return [...w.document.querySelectorAll('*')].find(n=>n.textContent===text&&n.children.length===0);},
  click(text){const n=this.find(text);if(!n)throw new Error(`Missing control: ${text}`);n.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));},
  fill(placeholder,value){const n=w.document.querySelector(`[placeholder="${placeholder}"]`);if(!n)throw new Error(`Missing field: ${placeholder}`);const proto=n.tagName==='TEXTAREA'?w.HTMLTextAreaElement.prototype:w.HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(n,value);n.dispatchEvent(new w.Event('input',{bubbles:true}));},
  close(){dom.window.close();}
 };
}
export const rpc=value=>Response.json({ok:true,type:'response',data:{result:value,reports:[]},error:null});

// Apply filters through the visible dropdown, including React's native range event.
export async function setMaximumPrice(ui, value) {
 const trigger=ui.document.querySelector('.ml-filters button[aria-expanded]');
 if(trigger.getAttribute('aria-expanded')!=='true')trigger.click();
 await until(()=>ui.document.querySelector('[aria-label="Maximum price"]'));
 const slider=ui.document.querySelector('[aria-label="Maximum price"]');
 Object.getOwnPropertyDescriptor(ui.window.HTMLInputElement.prototype,'value').set.call(slider,String(value));
 slider.dispatchEvent(new ui.window.Event('input',{bubbles:true}));
 await until(()=>ui.document.querySelector('output').textContent===(value===20?'Any price':`$${value} or less`));
 ui.click('Show deals');
 await until(()=>trigger.getAttribute('aria-expanded')==='false');
}

// Auth tests enter via the same shared welcome screen as a signed-out visitor.
export async function openSignIn(ui, audience='student') {
 await until(()=>ui.find('Find local deals'));
 ui.click(audience==='business'?'List my business':'Find local deals');
 await until(()=>ui.document.querySelector('[placeholder="Your name"], [placeholder="Business Name"]'));
 ui.click('Sign in');
 await until(()=>!ui.document.querySelector('[placeholder="Your name"]'));
}
