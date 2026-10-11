import {e,qty,money,dt,data,sellers,send} from './core.js';
import {layout,seller} from './ui.js';

const mark=x=>x.edited_at?`<span class="editmark">✎ ${e(x.edited_by||'')} · tahrirlangan</span>`:'';

export async function loadsPage(res,url,u){
 if(url.pathname!=='/loads')return false;
 const d=await data(u),ss=await sellers();
 const desktopRows=d.L.map(x=>`<tr><td>${dt(x.created_at)}</td><td><a class="link" href="/load/${x.id}">${e(x.name)}</a>${mark(x)}</td>${u.role==='manager'?`<td>${e(x.seller_name)}</td>`:''}<td>${e(x.product)}</td><td>${x.profit_mode==='commission'?'Sotib beramiz':'O‘z yukimiz'}</td><td>${qty(x.arrived_kg)}</td><td>${qty(x.sold_kg)}</td><td><b>${qty(x.stock_kg)}</b></td><td>${x.profit_mode==='commission'?money(x.commission_per_kg)+'/kg':money(x.purchase_amount)}</td><td><a class="btn soft" href="/edit/load/${x.id}?returnTo=%2Floads">Edit</a></td></tr>`).join('');
 const mobileCards=d.L.map(x=>`<article class="load-card">
   <div class="load-card-top"><span class="load-date">${dt(x.created_at)}</span><span class="product-pill">${e(x.product)}</span></div>
   <a class="load-name" href="/load/${x.id}">${e(x.name)}</a>
   ${u.role==='manager'?`<div class="load-seller">${e(x.seller_name)}</div>`:''}
   <div class="load-mini-stats"><div><span>Sotilgan</span><b>${qty(x.sold_kg)} kg</b></div><div><span>Qoldiq</span><b>${qty(x.stock_kg)} kg</b></div></div>
   <div class="load-card-actions"><a class="btn green" href="/load/${x.id}">Ochish</a><a class="btn soft" href="/edit/load/${x.id}?returnTo=%2Floads">Edit</a></div>
 </article>`).join('');
 const f=`<details class="new-load"><summary>+ Yangi yuk</summary><form class="form" method="post" action="/action/load"><div class="grid">${seller(u,ss)}<label class="field">Yuk nomi<input name="name" required></label><label class="field">Mahsulot<select name="product"><option>Kartoshka</option><option>Piyoz</option></select></label><label class="field">Kelgan kg<input name="kg" type="number" step="0.01" required></label><label class="field">Kelgan qop <span class="muted">(ixtiyoriy)</span><input name="bags" type="number" min="0" step="1" placeholder="Kiritmasangiz ham bo‘ladi"><span class="muted">Bo‘sh qoldirilsa 0 qop deb saqlanadi.</span></label><label class="field">Foyda hisoblash usuli<select name="profitMode" id="profitMode" onchange="var o=this.value==='own';document.getElementById('buyField').style.display=o?'block':'none';document.getElementById('commissionField').style.display=o?'none':'block';document.getElementById('buyInput').required=o;document.getElementById('commissionInput').required=!o"><option value="own">1. O‘z yukimiz</option><option value="commission">2. Birovning yukini sotib beramiz</option></select></label><label class="field" id="buyField">Xarid summa<input id="buyInput" name="buy" type="number" min="0" required></label><label class="field" id="commissionField" style="display:none">1 kg uchun xizmat haqi<input id="commissionInput" name="commissionPerKg" type="number" min="0" value="100"><span class="muted">Kelishuvga qarab o‘zgartiriladi.</span></label></div><button class="btn green" style="margin-top:10px">Saqlash</button></form></details>`;
 const css=`<style>
 .new-load>summary{padding:15px 17px;font-weight:900;color:#126c43}
 .loads-mobile{display:none}
 @media(max-width:760px){
   .loads-desktop{display:none}.loads-mobile{display:grid;gap:10px;padding:10px}
   .loads-panel{background:transparent;border:0;box-shadow:none;overflow:visible}
   .loads-panel .new-load{background:#fff;border:1px solid var(--line);border-radius:14px;margin-bottom:10px;overflow:hidden}
   .load-card{background:#fff;border:1px solid var(--line);border-radius:15px;padding:14px;box-shadow:none}
   .load-card-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
   .load-date{font-size:12px;color:var(--muted);font-weight:700}.product-pill{background:#eaf4ed;color:#126c43;border-radius:999px;padding:5px 9px;font-size:11px;font-weight:900}
   .load-name{display:block;font-size:18px;line-height:1.2;font-weight:900;letter-spacing:-.2px;margin-bottom:4px}.load-seller{font-size:12px;color:var(--muted);margin-bottom:10px}
   .load-mini-stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}.load-mini-stats>div{background:#f5f7f4;border-radius:11px;padding:10px}.load-mini-stats span{display:block;font-size:10px;color:var(--muted);font-weight:800}.load-mini-stats b{display:block;margin-top:3px;font-size:15px}
   .load-card-actions{display:grid;grid-template-columns:1fr auto;gap:8px}.load-card-actions .btn{min-height:44px}
 }
 </style>`;
 send(res,layout(u,'Yuklar',`${css}<section class="panel loads-panel">${f}<div class="loads-desktop table"><table><tr><th>Sana</th><th>Yuk</th>${u.role==='manager'?'<th>Savdogar</th>':''}<th>Mahsulot</th><th>Hisob turi</th><th>Kelgan kg</th><th>Sotilgan kg</th><th>Qoldiq kg</th><th>Xarid / haq</th><th>Amal</th></tr>${desktopRows||'<tr><td colspan="10">Yuk yo‘q</td></tr>'}</table></div><div class="loads-mobile">${mobileCards||'<div class="card">Yuk yo‘q</div>'}</div></section>`));
 return true;
}
