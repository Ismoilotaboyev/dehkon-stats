import {e,money,dt,data,sellers,send} from './core.js';
import {layout,seller} from './ui.js';

const mark=x=>x.edited_at?`<span class="editmark">✎ ${e(x.edited_by||'')} · tahrirlangan</span>`:'';
const hist=(u,t,id)=>u.role==='manager'?` <a class="btn soft" href="/history?type=${t}&id=${id}">Tarix</a>`:'';

const css=`<style>
 .expense-mobile{display:none}
 .expense-panel>details>summary{padding:14px 16px;font-weight:800;color:#147447}
 @media(max-width:760px){
  .expense-desktop{display:none!important}.expense-mobile{display:grid;gap:10px;padding:10px}
  .expense-panel{background:transparent;border:0;box-shadow:none;overflow:visible}
  .expense-panel>details{background:#fff;border:1px solid var(--line);border-radius:14px;margin-bottom:10px;overflow:hidden}
  .expense-card{background:#fff;border:1px solid var(--line);border-radius:15px;padding:14px;box-shadow:none}
  .expense-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
  .expense-date{font-size:12px;color:var(--muted);font-weight:700}
  .expense-pill{background:#fff2dd;color:#8a5200;border-radius:999px;padding:5px 9px;font-size:11px;font-weight:900;white-space:nowrap}
  .expense-name{display:block;font-size:18px;line-height:1.2;font-weight:900;letter-spacing:-.2px;margin-bottom:4px;color:var(--text)}
  .expense-sub{font-size:12px;color:var(--muted);font-weight:650;line-height:1.45}.expense-seller{font-size:11px;color:var(--muted);margin-top:3px}
  .expense-stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
  .expense-stats>div{background:#f5f7f4;border-radius:11px;padding:10px;min-width:0}.expense-stats span{display:block;font-size:10px;color:var(--muted);font-weight:800}.expense-stats b{display:block;margin-top:3px;font-size:15px;overflow-wrap:anywhere}
  .expense-note{margin:-3px 0 11px;padding:9px 10px;border-radius:10px;background:#f5f7f4;color:#56635a;font-size:11px;font-weight:700;line-height:1.4}
  .expense-actions{display:grid;grid-template-columns:1fr auto;gap:8px}.expense-actions .btn{min-height:44px}.expense-actions .green{display:flex;align-items:center;justify-content:center}
 }
 </style>`;

export async function expensesPage(res,url,u){
 if(url.pathname!=='/expenses')return false;
 const d=await data(u),ss=await sellers();
 const f=`<details><summary>+ Xarajat</summary><form class="form" method="post" action="/action/expense"><div class="grid">${seller(u,ss)}<label class="field">Nomi<input name="name" required></label><label class="field">Yuk<select name="loadId"><option value="">Umumiy</option>${d.L.map(x=>`<option value="${x.id}">${e(x.name)}${u.role==='manager'?' · '+e(x.seller_name):''}</option>`).join('')}</select></label><label class="field">Summa<input name="amount" type="number" min="0" required></label><label class="field">Izoh<input name="note"></label></div><button class="btn green" style="margin-top:10px">Saqlash</button></form></details>`;
 const rows=d.E.map(x=>`<tr><td>${dt(x.created_at)}${mark(x)}</td><td>${e(x.name)}</td>${u.role==='manager'?`<td>${e(x.seller_name)}</td>`:''}<td>${x.load_id?`<a class="link" href="/load/${x.load_id}">${e(x.load_name)}</a>`:'Umumiy'}</td><td>${money(x.amount)}</td><td>${e(x.note||'')}</td><td><a class="btn soft" href="/edit/expense/${x.id}?returnTo=%2Fexpenses">Edit</a>${hist(u,'expense',x.id)}</td></tr>`).join('');
 const cards=d.E.map(x=>`<article class="expense-card"><div class="expense-top"><span class="expense-date">${dt(x.created_at)}</span><span class="expense-pill">Xarajat</span></div><div class="expense-name">${e(x.name)}</div><div class="expense-sub">${x.load_id?e(x.load_name):'Umumiy xarajat'}</div>${u.role==='manager'?`<div class="expense-seller">${e(x.seller_name)}</div>`:''}<div class="expense-stats"><div><span>Summa</span><b>${money(x.amount)}</b></div><div><span>Yuk</span><b>${x.load_id?e(x.load_name):'Umumiy'}</b></div></div>${x.note?`<div class="expense-note">${e(x.note)}</div>`:''}<div class="expense-actions">${x.load_id?`<a class="btn green" href="/load/${x.load_id}">Yukni ochish</a>`:'<span></span>'}<a class="btn soft" href="/edit/expense/${x.id}?returnTo=%2Fexpenses">Tahrirlash</a></div></article>`).join('');
 send(res,layout(u,'Xarajatlar',`${css}<section class="panel expense-panel">${f}<div class="expense-desktop table"><table><tr><th>Sana</th><th>Nomi</th>${u.role==='manager'?'<th>Savdogar</th>':''}<th>Yuk</th><th>Summa</th><th>Izoh</th><th>Amal</th></tr>${rows||'<tr><td colspan="7">Xarajat yo‘q</td></tr>'}</table></div><div class="expense-mobile">${cards||'<div class="expense-card">Xarajat yo‘q</div>'}</div></section>`));
 return true;
}
