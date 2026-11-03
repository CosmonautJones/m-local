/** Read an emailed business review token from the URL fragment, then remove it from the address bar. */
export function takeReviewToken(){
 try{
  const match=/^#approve=([A-Za-z0-9_-]{100,120})$/.exec(window.location.hash||'');
  if(!match)return '';
  window.history.replaceState(null,'',window.location.pathname+window.location.search);
  return match[1];
 }catch{return '';}
}
