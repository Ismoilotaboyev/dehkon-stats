import {n,e,money,data,send} from './core.js';
import {layout} from './ui.js';

const DAY=86400000;
const daysBetween=(a,b=new Date())=>Math.max(0,Math.ceil((new Date(b)-new Date(a))/DAY));
const salePayInfo=(s,pays)=>{
 const arr=pays.filter(p=>+p.sale_id===+s.id).sort((a,b)=>new Date(a.created_at)-new Date(b.created_at));
 let sum=0,closedAt=null,debt=n(s.debt_amount);
 for(const p of arr){sum+=n(p.amount);if(!closedAt&&debt>0&&sum>=debt)closedAt=p.created_at}
 return {repaid:sum,remaining:Math.max(0,debt-sum),closedAt,closeDays:closedAt?daysBetween(s.created_at,closedAt):null};
};
const customerStats=(c,sales,pays)=>{
 const C=sales.filter(x=>+x.customer_id===+c.id&&n(x.debt_amount)>0);
 const P=pays.filter(x=>+x.customer_id===+c.id);
 const infos=C.map(x=>({...x,...salePayInfo(x,P)}));
 const oldPaid=P.filter(x=>!x.sale_id).reduce((a,x)=>a+n(x.amount),0);
 const openingRemaining=Math.max(0,n(c.opening_debt)-oldPaid);
 const closed=infos.filter(x=>x.closeDays!==null);
 const avgDays=closed.length?Math.round(closed.reduce((a,x)=>a+x.closeDays,0)/closed.length):null;
 return {
  credits:infos,
  totalCredit:n(c.opening_debt)+C.reduce((a,x)=>a+n(x.debt_amount),0),
  repaid:oldPaid+infos.reduce((a,x)=>a+n(x.repaid),0),
  currentDebt:openingRemaining+infos.reduce((a,x)=>a+n(x.remaining),0),
  openCount:infos.filter(x=>x.remaining>0).length,
  avgDays
 };
};

export async function debtsPage(res,url,u){
 if(url.pathname!=='/debts')return false;
 const d=await data(u);
 const customers=d.C.filter(c=>n(c.opening_debt)>0||d.S.some(s=>+s.customer_id===+c.id&&n(s.debt_amount)>0));
 const stats=customers.map(c=>({c,st:customerStats(c,d.S,d.P)})).sort((a,b)=>b.st.currentDebt-a.st.currentDebt);
 const closedAll=stats.flatMap(x=>x.st.credits.filter(s=>s.closeDays!==null));
 const avgAll=closedAll.length?Math.round(closedAll.reduce((a,x)=>a+x.closeDays,0)/closedAll.length):null;
 const totalDebt=stats.reduce((a,x)=>a+x.st.currentDebt,0);
 const openSales=stats.reduce((a,x)=>a+x.st.openCount,0);

 const desktopRows=stats.map(({c,st})=>`<tr>
  <td><a class="link" href="/debts/customer/${c.id}"><b>${e(c.name)}</b></a><div class="muted">${e(c.phone||'')} ${c.place?'· '+e(c.place):''}</div></td>
  ${u.role==='manager'?`<td>${e(c.seller_name)}</td>`:''}
  <td><b>${money(st.currentDebt)}</b></td><td>${st.credits.length}</td><td>${money(st.totalCredit)}</td><td>${money(st.repaid)}</td><td>${st.openCount}</td><td>${st.avgDays===null?'—':st.avgDays+' kun'}</td><td><a class="btn green" href="/debts/customer/${c.id}">Ko‘rish</a></td>
 </tr>`).join('');

 const mobileCards=stats.map(({c,st})=>`<article class="debt-card-mobile">
  <div class="debt-card-top"><span class="debt-open-label">Ochiq: ${st.openCount}</span><span class="debt-pill">Nasiya</span></div>
  <a class="debt-name" href="/debts/customer/${c.id}">${e(c.name)}</a>
  ${u.role==='manager'?`<div class="debt-seller">${e(c.seller_name)}</div>`:''}
  <div class="debt-contact">${e(c.phone||'Telefon yo‘q')}${c.place?' · '+e(c.place):''}</div>
  <div class="debt-mini-stats">
   <div><span>Hozirgi qarz</span><b>${money(st.currentDebt)}</b></div>
   <div><span>Qaytargan</span><b>${money(st.repaid)}</b></div>
  </div>
  <div class="debt-meta"><span>Jami nasiya: <b>${money(st.totalCredit)}</b></span><span>O‘rtacha: <b>${st.avgDays===null?'—':st.avgDays+' kun'}</b></span></div>
  <div class="debt-card-actions"><a class="btn green" href="/debts/customer/${c.id}">Ko‘rish</a></div>
 </article>`).join('');

 const css=`<style>
 .debts-mobile{display:none}
 @media(max-width:760px){
  .debts-summary{grid-template-columns:1fr 1fr!important;gap:8px!important;margin-bottom:10px}
  .debts-summary .card{min-width:0;padding:12px;border-radius:13px}
  .debts-summary .card span{font-size:10px}.debts-summary .card b{font-size:16px;line-height:1.2}
  .debts-desktop{display:none}.debts-mobile{display:grid;gap:10px;padding:10px}
  .debts-panel{background:transparent;border:0;box-shadow:none;overflow:visible}
  .debts-panel>.ph{background:#fff;border:1px solid var(--line);border-radius:14px;padding:13px 14px;margin-bottom:10px}
  .debts-panel>.ph h2{font-size:15px;margin:0}.debts-panel>.ph .muted{font-size:10px;margin-top:3px;line-height:1.35}
  .debt-card-mobile{background:#fff;border:1px solid var(--line);border-radius:15px;padding:14px;box-shadow:none}
  .debt-card-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
  .debt-open-label{font-size:12px;color:var(--muted);font-weight:800}.debt-pill{background:#fff4df;color:#8a6200;border-radius:999px;padding:5px 9px;font-size:11px;font-weight:900}
  .debt-name{display:block;font-size:18px;line-height:1.2;font-weight:900;letter-spacing:-.2px;margin-bottom:4px}
  .debt-seller{font-size:12px;color:var(--muted);font-weight:700;margin-bottom:3px}.debt-contact{font-size:12px;color:var(--muted);line-height:1.35}
  .debt-mini-stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0 9px}.debt-mini-stats>div{background:#f5f7f4;border-radius:11px;padding:10px;min-width:0}.debt-mini-stats span{display:block;font-size:10px;color:var(--muted);font-weight:800}.debt-mini-stats b{display:block;margin-top:3px;font-size:14px;overflow-wrap:anywhere}
  .debt-meta{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:10px;font-weight:700;margin-bottom:11px}.debt-meta b{color:var(--text)}
  .debt-card-actions{display:grid}.debt-card-actions .btn{min-height:44px;width:100%}
 }
 </style>`;

 const summary=`<div class="cards debts-summary"><div class="card"><span>Jami qolgan nasiya</span><b>${money(totalDebt)}</b></div><div class="card"><span>Nasiya mijozlar</span><b>${stats.length}</b></div><div class="card"><span>Ochiq nasiya savdolar</span><b>${openSales}</b></div><div class="card"><span>O‘rtacha yopish</span><b>${avgAll===null?'—':avgAll+' kun'}</b></div></div>`;
 const body=`${css}${summary}<section class="panel debts-panel"><div class="ph"><div><h2>Mijozlar bo‘yicha nasiya</h2><div class="muted">Mijoz ustiga bosing — barcha savdosi, olgan mahsuloti, qarzi, qaytimlari va statistikasi ochiladi.</div></div></div><div class="debts-desktop table"><table><tr><th>Mijoz</th>${u.role==='manager'?'<th>Savdogar</th>':''}<th>Hozirgi qarz</th><th>Nasiya savdo</th><th>Jami nasiya</th><th>Qaytargan</th><th>Ochiq</th><th>O‘rtacha</th><th></th></tr>${desktopRows||'<tr><td colspan="9">Nasiya mijoz yo‘q</td></tr>'}</table></div><div class="debts-mobile">${mobileCards||'<div class="card">Nasiya mijoz yo‘q</div>'}</div></section>`;
 send(res,layout(u,'Nasiyalar',body));
 return true;
}
