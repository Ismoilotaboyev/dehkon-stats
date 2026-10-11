import {n,e,money,qty,dt,data,sellers,send} from './core.js';
import {layout,seller} from './ui.js';

const mark=x=>x.edited_at?`<span class="editmark">✎ ${e(x.edited_by||'')} · tahrirlangan</span>`:'';
const hist=(u,t,id)=>u.role==='manager'?` <a class="btn soft" href="/history?type=${t}&id=${id}">Tarix</a>`:'';
const media=x=>{let a=[];if(x.has_audio)a.push(`<audio controls preload="none" class="mobile-media-audio" src="/attachment/${x.id}/audio"></audio>`);if(x.has_image)a.push(`<a class="btn soft" target="_blank" href="/attachment/${x.id}/image">🖼 Rasm</a>`);return a.join('')};
const saleTypeScript=`var cr=this.value==='credit',cm=document.getElementById('creditModeField'),cf=document.getElementById('customerField'),cs=document.getElementById('customerSelect'),pf=document.getElementById('paidField'),ct=document.getElementById('creditMode');cm.style.display=cr?'block':'none';cf.style.display=cr?'block':'none';cs.required=cr;pf.style.display=cr&&ct.value==='partial'?'block':'none'`;
const creditModeScript=`document.getElementById('paidField').style.display=this.value==='partial'?'block':'none'`;

const css=`<style>
 .sc-mobile{display:none}
 .sc-panel>details>summary{padding:14px 16px;font-weight:800;color:#147447}
 @media(max-width:760px){
  .sc-desktop{display:none!important}.sc-mobile{display:grid;gap:10px;padding:10px}
  .sc-panel{background:transparent;border:0;box-shadow:none;overflow:visible}
  .sc-panel>details{background:#fff;border:1px solid var(--line);border-radius:14px;margin-bottom:10px;overflow:hidden}
  .sc-card{background:#fff;border:1px solid var(--line);border-radius:15px;padding:14px;box-shadow:none}
  .sc-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
  .sc-date{font-size:12px;color:var(--muted);font-weight:700}
  .sc-pill{border-radius:999px;padding:5px 9px;font-size:11px;font-weight:900;white-space:nowrap;background:#eaf4ed;color:#126c43}
  .sc-pill.debt{background:#fff2dd;color:#8a5200}.sc-pill.customer{background:#eef2ed;color:#56635a}
  .sc-name{display:block;font-size:18px;line-height:1.2;font-weight:900;letter-spacing:-.2px;margin-bottom:4px;color:var(--text)}
  .sc-sub{font-size:12px;color:var(--muted);font-weight:650;line-height:1.45}.sc-seller{font-size:11px;color:var(--muted);margin-top:3px}
  .sc-stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
  .sc-stats>div{background:#f5f7f4;border-radius:11px;padding:10px;min-width:0}.sc-stats span{display:block;font-size:10px;color:var(--muted);font-weight:800}.sc-stats b{display:block;margin-top:3px;font-size:15px;overflow-wrap:anywhere}
  .sc-debt{margin:-3px 0 11px;padding:9px 10px;border-radius:10px;background:#fff7e8;color:#8a5200;font-size:11px;font-weight:800;display:flex;justify-content:space-between;gap:8px}.sc-debt b{color:#7a4300}
  .sc-media{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:8px 0 11px}.mobile-media-audio{width:100%;height:38px}
  .sc-actions{display:grid;grid-template-columns:1fr auto;gap:8px}.sc-actions .btn{min-height:44px}.sc-actions .green{display:flex;align-items:center;justify-content:center}
 }
 </style>`;

export async function salesCustomersPage(res,url,u){
 const p=url.pathname;
 if(p!=='/sales'&&p!=='/customers')return false;
 const d=await data(u);

 if(p==='/sales'){
  const f=`<details><summary>+ Savdo</summary><form class="form" method="post" action="/action/sale" enctype="multipart/form-data"><div class="grid"><label class="field">Yuk<select name="loadId" required>${d.L.filter(x=>n(x.stock_kg)>0).map(x=>`<option value="${x.id}">${e(x.name)}${u.role==='manager'?' · '+e(x.seller_name):''}</option>`).join('')}</select></label><label class="field">KG<input name="kg" type="number" step="0.01" min="0.01" required></label><label class="field">Qop<input name="bags" type="number" value="0"></label><label class="field">Narx/kg<input name="price" type="number" min="0" required></label><label class="field">To‘lov turi<select name="saleType" onchange="${saleTypeScript}"><option value="cash">Naqd</option><option value="credit">Nasiya</option></select></label><label class="field" id="creditModeField" style="display:none">Nasiya turi<select id="creditMode" name="creditMode" onchange="${creditModeScript}"><option value="debt">To‘liq nasiya</option><option value="partial">Qisman to‘lov + nasiya</option></select></label><label class="field" id="customerField" style="display:none">Mijoz<select id="customerSelect" name="customerId"><option value="">Mijozni tanlang</option>${d.C.map(x=>`<option value="${x.id}">${e(x.name)}${u.role==='manager'?' · '+e(x.seller_name):''}</option>`).join('')}</select></label><label class="field" id="paidField" style="display:none">Hozir bergan puli<input name="paid" type="number" min="0" value="0"></label><label class="field">🖼 Rasm qo‘shish<input name="image" type="file" accept="image/*" capture="environment"><span class="muted">Ixtiyoriy</span></label><label class="field">🎙 Ovoz qo‘shish<input name="audio" type="file" accept="audio/*" capture="user"><span class="muted">Ixtiyoriy</span></label></div><button class="btn green" style="margin-top:10px">Saqlash</button></form></details>`;
  const rows=d.S.map(x=>`<tr><td>${dt(x.created_at)}${mark(x)}</td><td>${e(x.customer_name||'Naqd')}</td><td><a class="link" href="/load/${x.load_id}">${e(x.load_name)}</a></td><td>${qty(x.kg)}</td><td>${money(x.total)}</td><td>${money(x.paid_amount)}</td><td>${money(x.remaining_debt)}</td><td>${media(x)||'<span class="muted">—</span>'}</td><td><a class="btn soft" href="/edit/sale/${x.id}?returnTo=%2Fsales">Edit</a>${hist(u,'sale',x.id)}</td></tr>`).join('');
  const cards=d.S.map(x=>{const debt=n(x.remaining_debt)>0;return `<article class="sc-card"><div class="sc-top"><span class="sc-date">${dt(x.created_at)}</span><span class="sc-pill ${debt?'debt':''}">${debt?'Nasiya':'Naqd'}</span></div><div class="sc-name">${e(x.customer_name||'Naqd savdo')}</div><div class="sc-sub">${e(x.load_name)}</div>${u.role==='manager'?`<div class="sc-seller">${e(x.seller_name||'')}</div>`:''}<div class="sc-stats"><div><span>Miqdor</span><b>${qty(x.kg)} kg${n(x.bags)>0?' · '+qty(x.bags)+' qop':''}</b></div><div><span>Jami summa</span><b>${money(x.total)}</b></div></div>${debt?`<div class="sc-debt"><span>Qolgan nasiya</span><b>${money(x.remaining_debt)}</b></div>`:''}${(x.has_audio||x.has_image)?`<div class="sc-media">${media(x)}</div>`:''}<div class="sc-actions"><a class="btn green" href="/load/${x.load_id}">Yukni ochish</a><a class="btn soft" href="/edit/sale/${x.id}?returnTo=%2Fsales">Edit</a></div></article>`}).join('');
  send(res,layout(u,'Savdolar',`${css}<section class="panel sc-panel">${f}<div class="sc-desktop table"><table><tr><th>Sana</th><th>Mijoz</th><th>Yuk</th><th>KG</th><th>Summa</th><th>Savdoda olindi</th><th>Qolgan nasiya</th><th>Fayl</th><th>Amal</th></tr>${rows||'<tr><td colspan="9">Savdo yo‘q</td></tr>'}</table></div><div class="sc-mobile">${cards||'<div class="sc-card">Savdo yo‘q</div>'}</div></section>`));
  return true;
 }

 const ss=await sellers();
 const f=`<details><summary>+ Mijoz</summary><form class="form" method="post" action="/action/customer"><div class="grid">${seller(u,ss)}<label class="field">Ism<input name="name" required></label><label class="field">Telefon<input name="phone"></label><label class="field">Joy<input name="place"></label><label class="field">Eski qarz<input name="debt" type="number" min="0" value="0"></label></div><button class="btn green" style="margin-top:10px">Saqlash</button></form></details>`;
 const rows=d.C.map(x=>`<tr><td><a class="link" href="/debts/customer/${x.id}">${e(x.name)}</a>${mark(x)}</td>${u.role==='manager'?`<td>${e(x.seller_name)}</td>`:''}<td>${e(x.phone||'')}</td><td>${e(x.place||'')}</td><td>${money(x.debt)}</td><td><a class="btn soft" href="/edit/customer/${x.id}?returnTo=%2Fcustomers">Edit</a>${hist(u,'customer',x.id)}</td></tr>`).join('');
 const cards=d.C.map(x=>{const sales=d.S.filter(s=>+s.customer_id===+x.id),total=sales.reduce((a,s)=>a+n(s.total),0),debt=n(x.debt)>0;return `<article class="sc-card"><div class="sc-top"><span class="sc-date">${dt(x.created_at)}</span><span class="sc-pill ${debt?'debt':'customer'}">${debt?'Qarzi bor':'Mijoz'}</span></div><a class="sc-name" href="/debts/customer/${x.id}">${e(x.name)}</a><div class="sc-sub">${e(x.phone||'Telefon yo‘q')}${x.place?' · '+e(x.place):''}</div>${u.role==='manager'?`<div class="sc-seller">${e(x.seller_name)}</div>`:''}<div class="sc-stats"><div><span>Hozirgi qarz</span><b>${money(x.debt)}</b></div><div><span>Jami savdo</span><b>${money(total)}</b></div></div><div class="sc-actions"><a class="btn green" href="/debts/customer/${x.id}">Ko‘rish</a><a class="btn soft" href="/edit/customer/${x.id}?returnTo=%2Fcustomers">Edit</a></div></article>`}).join('');
 send(res,layout(u,'Mijozlar',`${css}<section class="panel sc-panel">${f}<div class="sc-desktop table"><table><tr><th>Mijoz</th>${u.role==='manager'?'<th>Savdogar</th>':''}<th>Telefon</th><th>Joy</th><th>Qarz</th><th>Amal</th></tr>${rows||'<tr><td colspan="6">Mijoz yo‘q</td></tr>'}</table></div><div class="sc-mobile">${cards||'<div class="sc-card">Mijoz yo‘q</div>'}</div></section>`));
 return true;
}
