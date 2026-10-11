import {e,qty,money,dt,data,sellers,send} from './core.js';
import {layout,seller} from './ui.js';

const mark=x=>x.edited_at?`<span class="editmark">✎ ${e(x.edited_by||'')} · tahrirlangan</span>`:'';

export async function loadsPage(res,url,u){
 if(url.pathname!=='/loads')return false;
 const d=await data(u),ss=await sellers();
 const desktopRows=d.L.map(x=>`<tr><td>${dt(x.created_at)}</td><td><a class="link" href="/load/${x.id}">${e(x.name)}</a>${mark(x)}</td>${u.role==='manager'?`<td>${e(x.seller_name)}</td>`:''}<td>${e(x.product)}</td><td>${x.profit_mode==='commission'?'Sotib beramiz':'O‘z yukimiz'}</td><td>${qty(x.arrived_kg)}</td><td>${qty(x.sold_kg)}</td><td><b>${qty(x.stock_kg)}</b></td><td>${x.profit_mode==='commission'?money(x.commission_per_kg)+'/kg':money(x.purchase_amount)}</td><td><a class="btn soft" href="/edit/load/${x.id}?returnTo=%2Floads">Edit</a></td></tr>`).join('');
 const mobileRows=d.L.map(x=>`<tr>
   <td>${dt(x.created_at)}</td>
   <td><span class="product-text">${e(x.product)}</span></td>
   <td class="load-title-cell"><a href="/load/${x.id}">${e(x.name)}</a>${u.role==='manager'?`<small>${e(x.seller_name)}</small>`:''}</td>
   <td class="num">${qty(x.sold_kg)}</td>
   <td class="num stock">${qty(x.stock_kg)}</td>
   <td class="action-cell"><a class="edit-link" href="/edit/load/${x.id}?returnTo=%2Floads">Edit</a></td>
 </tr>`).join('');
 const f=`<details class="new-load"><summary>+ Yangi yuk</summary><form class="form" method="post" action="/action/load"><div class="grid">${seller(u,ss)}<label class="field">Yuk nomi<input name="name" required></label><label class="field">Mahsulot<select name="product"><option>Kartoshka</option><option>Piyoz</option></select></label><label class="field">Kelgan kg<input name="kg" type="number" step="0.01" required></label><label class="field">Kelgan qop<input name="bags" type="number" value="0"></label><label class="field">Foyda hisoblash usuli<select name="profitMode" id="profitMode" onchange="var o=this.value==='own';document.getElementById('buyField').style.display=o?'block':'none';document.getElementById('commissionField').style.display=o?'none':'block';document.getElementById('buyInput').required=o;document.getElementById('commissionInput').required=!o"><option value="own">1. O‘z yukimiz</option><option value="commission">2. Birovning yukini sotib beramiz</option></select></label><label class="field" id="buyField">Xarid summa<input id="buyInput" name="buy" type="number" min="0" required></label><label class="field" id="commissionField" style="display:none">1 kg uchun xizmat haqi<input id="commissionInput" name="commissionPerKg" type="number" min="0" value="100"><span class="muted">Kelishuvga qarab o‘zgartiriladi.</span></label></div><button class="btn green" style="margin-top:10px">Saqlash</button></form></details>`;
 const css=`<style>
 .new-load>summary{padding:15px 17px;font-weight:900;color:#126c43}
 .loads-mobile{display:none}
 @media(max-width:760px){
   .loads-desktop{display:none}.loads-mobile{display:block}
   .loads-panel{background:#fff;border:1px solid var(--line);box-shadow:none;overflow:hidden}
   .loads-panel .new-load{border-bottom:1px solid var(--line)}
   .mobile-sheet-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;background:#fff}
   .mobile-sheet{width:100%;min-width:650px;border-collapse:separate;border-spacing:0;font-size:11px}
   .mobile-sheet th{position:sticky;top:0;z-index:2;background:#eef2ed;color:#5f6d64;font-size:10px;font-weight:900;padding:9px 10px;border-bottom:1px solid #dce4da;white-space:nowrap;text-transform:none}
   .mobile-sheet td{padding:10px;border-bottom:1px solid #e8ede7;white-space:nowrap;background:#fff;vertical-align:middle}
   .mobile-sheet tr:last-child td{border-bottom:0}
   .mobile-sheet tbody tr:active td{background:#f6f8f5}
   .mobile-sheet .load-title-cell{min-width:150px;white-space:normal}
   .mobile-sheet .load-title-cell a{display:block;color:#126c43;font-size:12px;font-weight:900;line-height:1.2}
   .mobile-sheet .load-title-cell small{display:block;margin-top:3px;color:var(--muted);font-size:9px;font-weight:700}
   .mobile-sheet .product-text{font-weight:800}
   .mobile-sheet .num{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}
   .mobile-sheet .stock{font-weight:900;color:#172019}
   .mobile-sheet .action-cell{text-align:center;padding:6px 8px}
   .mobile-sheet .edit-link{display:inline-flex;align-items:center;justify-content:center;min-height:32px;padding:6px 10px;border-radius:8px;background:#eef2ed;color:#26372d;font-size:10px;font-weight:900}
   .sheet-hint{padding:7px 10px;background:#fafbf9;border-bottom:1px solid var(--line);color:var(--muted);font-size:9px;font-weight:700}
 }
 </style>`;
 const mobile=`<div class="loads-mobile"><div class="sheet-hint">Jadvalni chap-o‘ngga surish mumkin</div><div class="mobile-sheet-wrap"><table class="mobile-sheet"><thead><tr><th>Sana</th><th>Mahsulot</th><th>Yuk</th><th>Sotilgan kg</th><th>Qoldiq kg</th><th>Edit</th></tr></thead><tbody>${mobileRows||'<tr><td colspan="6">Yuk yo‘q</td></tr>'}</tbody></table></div></div>`;
 send(res,layout(u,'Yuklar',`${css}<section class="panel loads-panel">${f}<div class="loads-desktop table"><table><tr><th>Sana</th><th>Yuk</th>${u.role==='manager'?'<th>Savdogar</th>':''}<th>Mahsulot</th><th>Hisob turi</th><th>Kelgan kg</th><th>Sotilgan kg</th><th>Qoldiq kg</th><th>Xarid / haq</th><th>Amal</th></tr>${desktopRows||'<tr><td colspan="10">Yuk yo‘q</td></tr>'}</table></div>${mobile}</section>`));
 return true;
}
