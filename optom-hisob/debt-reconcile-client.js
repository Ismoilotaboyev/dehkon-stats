export const DEBT_RECONCILE_SNIPPET=`<script>(()=>{
const parseMoney=t=>{const s=String(t||'').replace(/[^0-9-]/g,'');return Number(s)||0};
const fmt=v=>new Intl.NumberFormat('uz-UZ').format(Math.max(0,Math.round(v)))+' so‘m';
function profile(){
 const hero=document.querySelector('.debt-hero');if(!hero)return;
 const k=[...hero.querySelectorAll('.debt-kpi')];
 const box=label=>k.find(x=>(x.querySelector('span')?.textContent||'').trim()===label);
 const cur=box('Hozirgi qarzi'),tot=box('Jami nasiya olgan'),rep=box('Jami qaytargan');if(!cur||!tot||!rep)return;
 const current=parseMoney(cur.querySelector('b')?.textContent),total=parseMoney(tot.querySelector('b')?.textContent),shown=parseMoney(rep.querySelector('b')?.textContent),correct=Math.max(0,total-current);
 if(shown!==correct){
  rep.querySelector('b').textContent=fmt(correct);
  const excess=Math.max(0,shown-correct);
  if(excess>0){const chips=hero.querySelector('.debt-chips');if(chips&&!chips.querySelector('.debt-reconcile-warning')){const s=document.createElement('span');s.className='debt-chip debt-reconcile-warning';s.innerHTML='Hisob tekshiruvi: <strong>'+fmt(excess)+'</strong> ortiqcha qaytim yozuvi';chips.appendChild(s)}}
 }
}
function listing(){
 document.querySelectorAll('.debt-card-mobile').forEach(card=>{
  const stats=card.querySelectorAll('.debt-mini-stats>div'),meta=card.querySelector('.debt-meta');if(stats.length<2||!meta)return;
  const current=parseMoney(stats[0].querySelector('b')?.textContent),total=parseMoney(meta.querySelector('span b')?.textContent),correct=Math.max(0,total-current),b=stats[1].querySelector('b');if(b)b.textContent=fmt(correct)
 });
 document.querySelectorAll('.debts-desktop tbody tr').forEach(tr=>{const td=tr.querySelectorAll('td');if(td.length<6)return;const current=parseMoney(td[2]?.textContent),total=parseMoney(td[4]?.textContent),correct=Math.max(0,total-current);if(td[5])td[5].textContent=fmt(correct)})
}
function run(){profile();listing()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(run,0));else setTimeout(run,0);
window.addEventListener('pageshow',()=>setTimeout(run,0));
})();</script>`;