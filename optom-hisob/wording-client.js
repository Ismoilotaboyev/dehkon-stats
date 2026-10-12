export const WORDING_SNIPPET=`<script>(()=>{
const KEY='optom_hisob_lang';
const MAP={
 uz_lat:{'Edit':'Tahrirlash','edit':'tahrirlash','Mijozni Edit':'Mijozni tahrirlash','Mijozni edit':'Mijozni tahrirlash'},
 uz_cyr:{'Edit':'Таҳрирлаш','edit':'таҳрирлаш','Едит':'Таҳрирлаш','едит':'таҳрирлаш','Мижозни Едит':'Мижозни таҳрирлаш','Мижозни едит':'Мижозни таҳрирлаш'},
 ru:{'Edit':'Редактировать','edit':'редактировать','Mijozni Edit':'Редактировать клиента','Mijozni edit':'Редактировать клиента'}
};
function legacyDates(){document.querySelectorAll('.legacy-desktop tr[data-list-item] td:first-child,.legacy-card-top span:first-child').forEach(el=>{if(el.textContent.trim()==='null'||el.textContent.trim()==='')el.textContent='Sana yo‘q'})}
function run(){const lang=localStorage.getItem(KEY)||'uz_lat',m=MAP[lang]||MAP.uz_lat;const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;while(n=w.nextNode()){const p=n.parentElement;if(!p||['SCRIPT','STYLE','NOSCRIPT','TEXTAREA'].includes(p.tagName)||p.closest('.lang-switch'))continue;const t=n.nodeValue.trim();if(m[t])n.nodeValue=n.nodeValue.replace(t,m[t]);}document.querySelectorAll('[data-label],[title],[aria-label],[placeholder]').forEach(el=>{for(const a of ['data-label','title','aria-label','placeholder']){const v=el.getAttribute(a);if(v&&m[v])el.setAttribute(a,m[v]);}});legacyDates()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(run,0));else setTimeout(run,0);window.addEventListener('pageshow',()=>setTimeout(run,0));
})();</script>`;
