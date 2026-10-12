export const PARTNERS_NAV_SNIPPET=`<style>
@media(max-width:760px){.mobile-nav{grid-template-columns:repeat(8,1fr)!important}.mobile-nav a{font-size:7.5px!important}.mobile-nav a .mi{font-size:15px!important}.mobile-nav a[data-partners-nav]{font-size:7.5px!important}.mobile-nav a[data-partners-nav] .mi{font-size:15px!important}}
.po-chooser{margin:8px 16px 14px;padding:14px;border:1px solid var(--line);border-radius:15px;background:#fbfcfa}
.po-chooser h3{margin:0 0 3px;font-size:15px}.po-chooser p{margin:0;color:var(--muted);font-size:10px;font-weight:700}
.po-sellers{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-top:12px}
.po-seller{border:1px solid var(--line);background:#fff;border-radius:12px;padding:11px;text-align:left;cursor:pointer;min-width:0}
.po-seller:hover{border-color:#9ab9a5}.po-seller.active{background:#173b28;color:#fff;border-color:#173b28}
.po-seller:disabled{opacity:.55;cursor:not-allowed;background:#f2f4f1}
.po-avatar{width:34px;height:34px;border-radius:9px;background:#edf5ef;color:var(--green);display:grid;place-items:center;font-size:11px;font-weight:950;margin-bottom:7px}
.po-seller.active .po-avatar{background:#2a5b40;color:#fff}.po-seller b{display:block;font-size:11px;overflow:hidden;text-overflow:ellipsis}.po-seller span{display:block;color:var(--muted);font-size:9px;margin-top:2px}.po-seller.active span{color:#c6d4ca}
.po-selected{display:none;margin:8px 16px 0;background:#173b28;color:#fff;border-radius:13px;padding:11px 13px;align-items:center;justify-content:space-between;gap:10px}
.po-selected.show{display:flex}.po-selected small{display:block;color:#c8d5cd;margin-top:2px;font-size:9px}.po-change{border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.08);color:#fff;border-radius:9px;padding:8px 10px;font-weight:850;cursor:pointer}
.partner-tabs.po-actions{background:transparent;padding:0;margin:12px 16px;display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.partner-tabs.po-actions button{background:#fff;border:1px solid var(--line);border-radius:13px;text-align:left;padding:12px;box-shadow:none;color:var(--text);min-height:76px}
.partner-tabs.po-actions button.active{border-color:#6da586;box-shadow:0 0 0 2px rgba(18,108,67,.08);color:var(--green)}
.partner-tabs.po-actions button b{display:block;font-size:12px}.partner-tabs.po-actions button span{display:block;color:var(--muted);font-size:9px;line-height:1.35;margin-top:4px;white-space:normal}
.po-locked{margin:8px 16px 14px;border:1px dashed #cbd6cd;border-radius:13px;padding:22px;text-align:center;color:var(--muted);font-size:11px;font-weight:800;background:#fafbfa}
.po-hidden{display:none!important}
@media(max-width:900px){.po-sellers{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:760px){.po-chooser{margin:8px 10px 12px;padding:12px}.po-sellers{grid-template-columns:1fr 1fr}.po-selected{margin:8px 10px 0}.partner-tabs.po-actions{margin:10px;grid-template-columns:1fr}.partner-tabs.po-actions button{min-width:0!important}.po-locked{margin:8px 10px 12px}}
</style><script data-partner-optimized>(()=>{

function addNav(){
 const desktop=document.querySelector('.side nav');
 if(desktop&&!desktop.querySelector('[data-partners-nav]')){
   const a=document.createElement('a');a.href='/partners';a.dataset.partnersNav='1';a.innerHTML='<span class="ni">⇄</span>Sherik sotuvchi';desktop.appendChild(a);
 }
 const mobile=document.querySelector('.mobile-nav');
 if(mobile&&!mobile.querySelector('[data-partners-nav]')){
   const a=document.createElement('a');a.href='/partners';a.dataset.partnersNav='1';a.innerHTML='<span class="mi">⇄</span>Sherik';mobile.appendChild(a);
 }
 const here=location.pathname;
 document.querySelectorAll('nav a').forEach(a=>{const p=new URL(a.href,location.href).pathname;a.classList.toggle('active',p==='/'?here==='/':here===p||here.startsWith(p+'/'))});
}

function optimizePartners(){
 if(location.pathname!=='/partners'||document.documentElement.dataset.partnerOptimized)return;
 const panel=document.querySelector('.partner-panel');if(!panel)return;
 document.documentElement.dataset.partnerOptimized='1';

 const sellers=[
  {name:'Palvannazar Direktor',key:'palvannazar',initials:'PD'},
  {name:'Rufat',key:'rufat',initials:'R'},
  {name:'Iqrom',key:'iqrom',initials:'I'},
  {name:'Asror',key:'asror',initials:'A'},
  {name:'Quvondiq',key:'quvondiq',initials:'Q'}
 ];
 const currentName=(document.querySelector('.userpill b')?.textContent||'').trim();
 const currentKey=(currentName.split(/\s+/)[0]||'').toLowerCase();
 const head=panel.querySelector('.partner-section-head');
 const chooser=document.createElement('div');chooser.className='po-chooser';
 chooser.innerHTML='<h3>Kimning o‘rniga ishlayapsiz?</h3><p>Avval sotuvchini tanlang. Keyingi barcha nasiya, yuk va sherik puli faqat shu sotuvchiga tegishli bo‘ladi.</p><div class="po-sellers"></div>';
 const sellerWrap=chooser.querySelector('.po-sellers');
 sellers.forEach(s=>{
   const b=document.createElement('button');b.type='button';b.className='po-seller';b.dataset.ownerKey=s.key;
   const self=currentKey===s.key;
   b.disabled=self;
   b.innerHTML='<div class="po-avatar">'+s.initials+'</div><b>'+s.name+'</b><span>'+(self?'Siz':'Tanlash')+'</span>';
   sellerWrap.appendChild(b);
 });
 if(head)head.after(chooser);else panel.prepend(chooser);

 const selected=document.createElement('div');selected.className='po-selected';
 selected.innerHTML='<div><b data-po-owner></b><small>Hozir shu sotuvchi uchun ishlayapsiz</small></div><button type="button" class="po-change">Almashtirish</button>';
 chooser.after(selected);

 const tabs=panel.querySelector('.partner-tabs');
 const actions=[...panel.querySelectorAll('.partner-action')];
 const help=panel.querySelector('.partner-help');
 const managerNote=!tabs?[...panel.children].find(x=>x.classList&&x.classList.contains('partner-note')):null;
 const summary=document.querySelector('.partner-summary');
 const allPanels=[...document.querySelectorAll('.content > .panel, .content .panel')];
 const secondary=allPanels.filter(x=>x!==panel&&x.querySelector('.partner-section-head'));
 const locked=document.createElement('div');locked.className='po-locked';locked.textContent='🔒 Avval yuqoridan sotuvchini tanlang';
 selected.after(locked);

 if(summary)summary.classList.add('po-hidden');
 if(tabs){tabs.classList.add('po-actions');tabs.classList.add('po-hidden')}
 actions.forEach(x=>x.classList.add('po-hidden'));
 if(help)help.classList.add('po-hidden');
 if(managerNote)managerNote.classList.add('po-hidden');
 secondary.forEach(x=>x.classList.add('po-hidden'));

 if(tabs){
   const bs=[...tabs.querySelectorAll('button')];
   if(bs[0])bs[0].innerHTML='<b>Nasiyalaridan pul oldim</b><span>Mijoz qarzini bersa</span>';
   if(bs[1])bs[1].innerHTML='<b>Yukidan sotdim</b><span>Uning yukidan savdo</span>';
   if(bs[2])bs[2].innerHTML='<b>Egasiga topshirdim</b><span>Qo‘lingizdagi pulni berish</span>';
 }
 const debtForm=panel.querySelector('form[action="/action/partner-payment"]');
 const saleForm=panel.querySelector('form[action="/action/partner-sale"]');
 const settleForm=panel.querySelector('form[action="/action/partner-settlement"]');
 if(debtForm){
   const note=debtForm.querySelector('.partner-note');if(note)note.innerHTML='<b>Nasiyalaridan pul oldim.</b> Mijoz bergan summa qarzidan darhol kamayadi va pul sizning qo‘lingizda, egasiniki deb turadi.';
   const firstLabel=debtForm.querySelector('.field');if(firstLabel&&firstLabel.firstChild)firstLabel.firstChild.nodeValue='Mijoz / nasiya';
   const submit=debtForm.querySelector('button[type="submit"],button:not([type])');if(submit)submit.textContent='Pul oldim';
 }
 if(saleForm){
   const note=saleForm.querySelector('.partner-note');if(note)note.innerHTML='<b>Yukidan sotdim.</b> Yuk qoldig‘i, savdo, foyda va nasiya yuk egasiga yoziladi. Kim sotgani tarixda qoladi.';
 }
 if(settleForm){
   const note=settleForm.querySelector('.partner-note');if(note)note.innerHTML='<b>Egasiga topshirdim.</b> Bu faqat sizning qo‘lingizdagi sherik pulini kamaytiradi. Mijoz qarzi ikkinchi marta o‘zgarmaydi.';
   const submit=settleForm.querySelector('button[type="submit"],button:not([type])');if(submit)submit.textContent='Egasiga topshirdim';
 }

 const debtSelect=debtForm?.querySelector('select[name="target"]');
 const loadSelect=saleForm?.querySelector('select[name="loadId"]');
 const customerSelect=saleForm?.querySelector('select[name="customerId"]');
 const settleSelect=settleForm?.querySelector('select[name="ownerId"]');

 function belongs(option,key){
   const t=(option.textContent||'').trim().toLowerCase();
   return t===key||t.startsWith(key+' ')||t.startsWith(key+' ·');
 }
 function filterSelect(select,key){
   if(!select)return;
   [...select.options].forEach((o,i)=>{if(i===0){o.hidden=false;return}o.hidden=!belongs(o,key)});
   if(select.selectedIndex>0&&select.selectedOptions[0]?.hidden)select.value='';
 }
 function filterTables(key){
   secondary.forEach(sec=>{
     const title=(sec.querySelector('h2')?.textContent||'').toLowerCase();
     const rows=[...sec.querySelectorAll('table tr')].slice(1);
     let visible=0;
     rows.forEach(r=>{
       if(r.querySelector('td[colspan]')){r.style.display='none';return}
       const cells=r.cells;if(!cells)return;
       let txt='';
       if(title.includes('sherik pullari'))txt=cells[2]?.textContent||'';
       else if(title.includes('tarixi'))txt=cells[2]?.textContent||'';
       else return;
       const ok=txt.trim().toLowerCase().startsWith(key);
       r.style.display=ok?'':'none';if(ok)visible++;
     });
     let empty=sec.querySelector('.po-empty-row');
     if(!visible){
       if(!empty){
         empty=document.createElement('tr');empty.className='po-empty-row';
         const td=document.createElement('td');td.colSpan=10;td.className='muted';td.textContent='Bu sotuvchi bo‘yicha hozircha ma’lumot yo‘q';empty.appendChild(td);
         sec.querySelector('table tbody,table')?.appendChild(empty);
       }
       empty.style.display='';
     }else if(empty)empty.style.display='none';
   });
 }
 function relabelHistory(){
   document.querySelectorAll('table td').forEach(td=>{
     const t=td.textContent.trim();
     if(t==='Nasiya qaytimi')td.textContent='Nasiyadan pul olindi';
     if(t==='Sherik savdo')td.textContent='Yukidan sotildi';
     if(t==='Pul topshirildi')td.textContent='Egasiga topshirildi';
   });
 }

 function apply(key){
   const s=sellers.find(x=>x.key===key);if(!s||key===currentKey)return;
   sessionStorage.setItem('optom_partner_owner',key);
   chooser.style.display='none';selected.classList.add('show');selected.querySelector('[data-po-owner]').textContent=s.name;
   locked.style.display='none';
   if(tabs)tabs.classList.remove('po-hidden');
   actions.forEach(x=>x.classList.remove('po-hidden'));
   if(help)help.classList.remove('po-hidden');
   if(managerNote)managerNote.classList.remove('po-hidden');
   secondary.forEach(x=>x.classList.remove('po-hidden'));
   filterSelect(debtSelect,key);filterSelect(loadSelect,key);filterSelect(customerSelect,key);filterSelect(settleSelect,key);filterTables(key);relabelHistory();
   sellerWrap.querySelectorAll('.po-seller').forEach(b=>b.classList.toggle('active',b.dataset.ownerKey===key));
   loadSelect?.dispatchEvent(new Event('change',{bubbles:true}));
 }
 function reset(){
   sessionStorage.removeItem('optom_partner_owner');
   chooser.style.display='';selected.classList.remove('show');locked.style.display='';
   if(tabs)tabs.classList.add('po-hidden');
   actions.forEach(x=>x.classList.add('po-hidden'));
   if(help)help.classList.add('po-hidden');
   if(managerNote)managerNote.classList.add('po-hidden');
   secondary.forEach(x=>x.classList.add('po-hidden'));
   [debtSelect,loadSelect,customerSelect,settleSelect].forEach(s=>{if(s)s.value=''});
 }
 sellerWrap.addEventListener('click',ev=>{const b=ev.target.closest('.po-seller');if(b&&!b.disabled)apply(b.dataset.ownerKey)});
 selected.querySelector('.po-change').addEventListener('click',reset);
 relabelHistory();
 const saved=sessionStorage.getItem('optom_partner_owner');
 if(saved&&saved!==currentKey&&sellers.some(x=>x.key===saved))apply(saved);
}

addNav();optimizePartners();
})()</script>`;
