export const LOAD_ARCHIVE_SNIPPET=`<script>(()=>{
 const m=location.pathname.match(/^\/load\/(\d+)$/);if(!m)return;
 const id=Number(m[1]);
 const lang=localStorage.getItem('optom_hisob_lang')||'uz_lat';
 const T={
  uz_lat:{finish:'Yukni tugatish',archived:'Arxivlangan',confirm:'Yukni tugatilsinmi? Tugatilgach yangi savdo va xarajat qo‘shib bo‘lmaydi. Barcha eski ma’lumotlar saqlanadi.',err:'Bu yuk arxivlangan. Yangi operatsiya qo‘shib bo‘lmaydi.'},
  uz_cyr:{finish:'Юкни тугатиш',archived:'Архивланган',confirm:'Юкни тугатилсинми? Тугатилгач янги савдо ва харажат қўшиб бўлмайди. Барча эски маълумотлар сақланади.',err:'Бу юк архивланган. Янги операция қўшиб бўлмайди.'},
  ru:{finish:'Завершить груз',archived:'В архиве',confirm:'Завершить груз? После завершения нельзя будет добавлять новые продажи и расходы. Вся история сохранится.',err:'Этот груз в архиве. Новые операции добавлять нельзя.'}
 }[lang]||null;
 const txt=T||{finish:'Yukni tugatish',archived:'Arxivlangan',confirm:'Yukni tugatilsinmi?',err:'Bu yuk arxivlangan.'};
 const fmt=v=>{try{return new Intl.DateTimeFormat(lang==='ru'?'ru-RU':'uz-UZ',{timeZone:'Asia/Tashkent',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(v))}catch{return ''}};
 const infoDetails=document.querySelector('section.panel > details');if(!infoDetails)return;
 const summary=infoDetails.querySelector(':scope > summary');if(!summary)return;
 summary.style.display='flex';summary.style.alignItems='center';summary.style.justifyContent='space-between';summary.style.gap='10px';
 const right=document.createElement('span');right.setAttribute('data-load-finish-control','1');right.style.cssText='display:flex;align-items:center;gap:7px;margin-left:auto;flex-shrink:0';summary.appendChild(right);
 const makeButton=()=>{
  right.innerHTML='';
  const btn=document.createElement('button');btn.type='button';btn.textContent=txt.finish;btn.style.cssText='border:1px solid #efd0aa;background:#fff1e2;color:#854b00;border-radius:10px;min-height:38px;padding:0 11px;font-weight:900;font:inherit;font-size:12px;cursor:pointer;white-space:nowrap';
  btn.addEventListener('click',ev=>{ev.preventDefault();ev.stopPropagation();if(!confirm(txt.confirm))return;const f=document.createElement('form');f.method='post';f.action='/action/finish-load';f.style.display='none';const i=document.createElement('input');i.name='id';i.value=String(id);f.appendChild(i);document.body.appendChild(f);f.submit()});right.appendChild(btn);
 };
 const makeArchived=s=>{
  right.innerHTML='';
  const badge=document.createElement('span');badge.textContent=txt.archived+(s?.archived_at?' · '+fmt(s.archived_at):'');badge.style.cssText='background:#eef0ee;color:#687068;border-radius:999px;padding:6px 9px;font-size:11px;font-weight:900;white-space:nowrap';right.appendChild(badge);
  const nested=[...infoDetails.querySelectorAll('details')].filter(x=>x!==infoDetails);nested.forEach(x=>x.style.display='none');
  const infoPanel=infoDetails.closest('section.panel'),salePanel=infoPanel?.nextElementSibling;if(salePanel?.matches?.('section.panel'))salePanel.style.display='none';
 };
 makeButton();
 fetch('/api/load/'+id+'/status',{credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(s=>{if(s?.archived)makeArchived(s)}).catch(()=>{});
 if(new URLSearchParams(location.search).get('error')==='archived')alert(txt.err);
})();</script>`;
