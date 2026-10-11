import {n,e,money,qty,dt,data,send} from './core.js';
import {layout} from './ui.js';

const DAY=86400000;
const TZ='Asia/Tashkent';
const partMap=v=>Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hourCycle:'h23'}).formatToParts(new Date(v)).filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
const dayKey=v=>{const p=partMap(v);return `${p.year}-${p.month}-${p.day}`};
const localHour=v=>Number(partMap(v).hour||0);
const startOfToday=()=>{const p=partMap(new Date());return new Date(`${p.year}-${p.month}-${p.day}T00:00:00+05:00`)};
const rangeStart=(range,today)=>{
 if(range==='today')return today;
 if(range==='7d')return new Date(today.getTime()-6*DAY);
 if(range==='30d')return new Date(today.getTime()-29*DAY);
 if(range==='month'){const p=partMap(today);return new Date(`${p.year}-${p.month}-01T00:00:00+05:00`)}
 return null;
};
const sum=(arr,fn)=>arr.reduce((a,x)=>a+n(fn(x)),0);
const inRange=(x,start,field='created_at')=>!start||new Date(x[field])>=start;
const pct=(v,total)=>total>0?Math.round((v/total)*100):0;
const capPct=v=>Math.max(0,Math.min(100,v));
const shortMoney=v=>{
 const x=n(v),a=Math.abs(x);
 if(a>=1e9)return `${(x/1e9).toFixed(a>=10e9?0:1)} mlrd`;
 if(a>=1e6)return `${(x/1e6).toFixed(a>=10e6?0:1)} mln`;
 if(a>=1e3)return `${(x/1e3).toFixed(a>=10e3?0:1)} ming`;
 return new Intl.NumberFormat('uz-UZ').format(x);
};

function profitFor(sales,expenses,loadById){
 const gross=sales.reduce((a,s)=>{
  const L=loadById.get(+s.load_id);
  if(!L)return a;
  if(L.profit_mode==='commission')return a+n(s.kg)*n(L.commission_per_kg);
  const cost=n(L.purchase_amount)/Math.max(n(L.arrived_kg),1);
  return a+n(s.total)-n(s.kg)*cost;
 },0);
 return gross-sum(expenses,x=>x.amount);
}

function chartData(range,today,sales,pays,expenses,loadById){
 if(range==='today'){
  const labels=['00–04','04–08','08–12','12–16','16–20','20–24'];
  const values=labels.map((_,i)=>{
   const lo=i*4,hi=lo+4;
   const S=sales.filter(x=>{const h=localHour(x.created_at);return h>=lo&&h<hi});
   const P=pays.filter(x=>{const h=localHour(x.created_at);return h>=lo&&h<hi});
   const E=expenses.filter(x=>{const h=localHour(x.created_at);return h>=lo&&h<hi});
   return {sales:sum(S,x=>x.total),paid:sum(S,x=>x.paid_amount)+sum(P,x=>x.amount),profit:profitFor(S,E,loadById)};
  });
  return {labels,values};
 }
 let start;
 if(range==='7d')start=new Date(today.getTime()-6*DAY);
 else if(range==='30d')start=new Date(today.getTime()-29*DAY);
 else if(range==='month')start=rangeStart('month',today);
 else start=new Date(today.getTime()-13*DAY);
 const days=[];
 for(let t=start.getTime();t<=today.getTime()+1000;t+=DAY)days.push(new Date(t));
 if(days.length>31)days.splice(0,days.length-31);
 const labels=days.map(d=>{const p=partMap(d);return `${p.day}.${p.month}`});
 const values=days.map(d=>{
  const k=dayKey(d);
  const S=sales.filter(x=>dayKey(x.created_at)===k);
  const P=pays.filter(x=>dayKey(x.created_at)===k);
  const E=expenses.filter(x=>dayKey(x.created_at)===k);
  return {sales:sum(S,x=>x.total),paid:sum(S,x=>x.paid_amount)+sum(P,x=>x.amount),profit:profitFor(S,E,loadById)};
 });
 return {labels,values};
}

function linePoints(values,maxV){
 const h=178,top=18,w=1000;
 if(values.length===1)return `0,${top+h-(Math.max(0,values[0])/maxV)*h} 1000,${top+h-(Math.max(0,values[0])/maxV)*h}`;
 return values.map((v,i)=>{
  const x=(i/(values.length-1))*w;
  const y=top+h-(Math.max(0,n(v))/maxV)*h;
  return `${x.toFixed(1)},${y.toFixed(1)}`;
 }).join(' ');
}

function dashboardCss(){
 return `<style>
 .dash{--dg:#0d7a43;--dg2:#075f34;--dsoft:#eaf6ee;--dline:#dfe9e2;--dmuted:#78857d;--dred:#c83846;--damber:#9a6500}
 .dash *{box-sizing:border-box}.dash-head{display:flex;justify-content:space-between;align-items:flex-end;gap:14px;margin-bottom:13px}.dash-head h1{margin:0;font-size:25px;letter-spacing:-.6px}.dash-head p{margin:4px 0 0;color:var(--dmuted);font-size:11px}
 .dash-period{display:flex;gap:4px;padding:4px;background:#edf3ee;border-radius:11px;overflow:auto}.dash-period a{white-space:nowrap;padding:8px 10px;border-radius:8px;color:#65736a;font-size:10px;font-weight:900}.dash-period a.active{background:#fff;color:var(--dg);box-shadow:0 2px 8px rgba(27,64,40,.07)}
 .dash-kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px}.dash-kpi{background:#fff;border:1px solid var(--dline);border-radius:15px;padding:13px;min-width:0;box-shadow:0 9px 25px rgba(42,89,59,.05)}.dash-kpi-top{display:flex;align-items:center;justify-content:space-between;gap:7px}.dash-kpi span{font-size:9px;color:var(--dmuted);font-weight:850}.dash-kpi i{font-style:normal;width:28px;height:28px;border-radius:9px;background:#f0f6f2;display:grid;place-items:center;color:var(--dg);font-weight:900}.dash-kpi b{display:block;margin-top:9px;font-size:18px;line-height:1.15;overflow-wrap:anywhere}.dash-kpi small{display:block;margin-top:5px;color:var(--dmuted);font-size:8px;font-weight:750}
 .dash-grid-main{display:grid;grid-template-columns:1.45fr .8fr;gap:11px;margin-top:11px}.dash-grid-half{display:grid;grid-template-columns:1.08fr .92fr;gap:11px;margin-top:11px}.dash-grid-bottom{display:grid;grid-template-columns:1fr 1fr;gap:11px;margin-top:11px}.dash-panel{background:#fff;border:1px solid var(--dline);border-radius:16px;overflow:hidden;box-shadow:0 9px 25px rgba(42,89,59,.05)}.dash-ph{padding:13px 14px 9px;display:flex;align-items:center;justify-content:space-between;gap:10px}.dash-ph h2{margin:0;font-size:16px}.dash-ph p{margin:3px 0 0;color:var(--dmuted);font-size:9px}.dash-link{background:#eef7f1;border:1px solid #c8dfd0;color:var(--dg);border-radius:9px;padding:7px 9px;font-size:9px;font-weight:900}
 .dash-chart-wrap{padding:0 13px 12px}.dash-chart{height:220px;border-radius:13px;position:relative;overflow:hidden;background:linear-gradient(to right,rgba(220,232,224,.48) 1px,transparent 1px) 0 0/16.66% 100%,linear-gradient(to bottom,rgba(220,232,224,.5) 1px,transparent 1px) 0 0/100% 20%,linear-gradient(180deg,#fbfdfb,#f6faf7)}.dash-chart svg{width:100%;height:100%;display:block}.dash-legend{display:flex;gap:12px;padding-top:7px;color:#65736a;font-size:9px;font-weight:800}.dash-dot{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:4px}.dash-dot.sale{background:#0d7a43}.dash-dot.paid{background:#668d74}.dash-dot.profit{background:#d19a3c}.dash-axis{display:flex;justify-content:space-between;color:#89958d;font-size:8px;padding-top:5px}
 .dash-today{padding:3px 13px 13px;display:grid;gap:7px}.dash-today-row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 10px;background:#f7faf7;border-radius:10px}.dash-today-row span{font-size:9px;color:var(--dmuted);font-weight:800}.dash-today-row b{font-size:11px;text-align:right}
 .dash-loads{padding:0 11px 11px;display:grid;gap:8px}.dash-load{border:1px solid var(--dline);border-radius:12px;padding:10px}.dash-load-top{display:flex;justify-content:space-between;align-items:center;gap:8px}.dash-load-title b{font-size:12px;font-weight:900;color:var(--text)}.dash-load-title span{display:block;margin-top:2px;color:var(--dmuted);font-size:9px}.dash-badge{padding:5px 7px;border-radius:999px;background:var(--dsoft);color:var(--dg);font-size:8px;font-weight:900;white-space:nowrap}.dash-badge.warn{background:#fff2dd;color:#8a5d00}.dash-load-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-top:8px}.dash-mi{background:#f7faf7;border-radius:8px;padding:7px;min-width:0}.dash-mi span{display:block;font-size:7px;color:var(--dmuted);font-weight:800}.dash-mi b{display:block;font-size:9px;margin-top:3px;overflow-wrap:anywhere}.dash-progress{height:6px;background:#edf2ee;border-radius:999px;overflow:hidden;margin-top:8px}.dash-progress i{display:block;height:100%;background:linear-gradient(90deg,#0d7a43,#42a46d);border-radius:999px}
 .dash-debts{padding:0 11px 11px}.dash-debt-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px}.dash-ds{background:#f7faf7;border-radius:9px;padding:8px}.dash-ds span{display:block;font-size:7px;color:var(--dmuted);font-weight:800}.dash-ds b{display:block;margin-top:3px;font-size:11px}.dash-debt-item{display:flex;justify-content:space-between;gap:8px;align-items:center;padding:8px 0;border-top:1px solid #edf1ee}.dash-debt-item:first-child{border-top:0}.dash-debt-item a{font-size:10px;font-weight:900}.dash-debt-item span{display:block;color:var(--dmuted);font-size:8px;margin-top:2px}.dash-debt-money{font-size:10px;font-weight:900;color:#8b5c00;white-space:nowrap}
 .dash-rank{padding:0 11px 11px;overflow:auto}.dash-rank table{width:100%;border-collapse:collapse;font-size:9px;min-width:520px}.dash-rank th{text-align:left;padding:8px 7px;background:#f4f8f5;color:var(--dmuted);font-size:8px}.dash-rank td{padding:8px 7px;border-top:1px solid #edf1ee}.dash-rank-num{width:23px;height:23px;border-radius:8px;background:#edf5ef;color:var(--dg);display:grid;place-items:center;font-weight:900}
 .dash-alerts{padding:0 11px 11px;display:grid;gap:7px}.dash-alert{display:grid;grid-template-columns:30px 1fr auto;align-items:center;gap:8px;padding:9px;border-radius:10px;background:#f8faf8}.dash-alert.red{background:#fff0f2}.dash-alert.amber{background:#fff5de}.dash-alert.green{background:#eaf6ee}.dash-alert-ico{width:29px;height:29px;border-radius:9px;background:rgba(255,255,255,.72);display:grid;place-items:center;font-weight:900}.dash-alert b{font-size:10px}.dash-alert span{display:block;margin-top:2px;font-size:8px;color:#68756d}.dash-alert small{font-size:8px;color:#6e7a72;font-weight:800}
 .dash-activity{margin-top:11px}.dash-timeline{padding:0 13px 8px}.dash-act{display:grid;grid-template-columns:9px 1fr auto;gap:8px;padding:9px 0}.dash-act-dot{width:7px;height:7px;border-radius:50%;background:var(--dg);margin-top:4px}.dash-act-main{border-bottom:1px solid #edf1ee;padding-bottom:8px}.dash-act-main b{font-size:10px}.dash-act-main span{display:block;margin-top:2px;color:var(--dmuted);font-size:8px}.dash-act time{font-size:8px;color:var(--dmuted)}
 .dash-empty{padding:14px;color:var(--dmuted);font-size:10px}
 @media(max-width:1180px){.dash-kpis{grid-template-columns:repeat(3,1fr)}.dash-grid-main,.dash-grid-half,.dash-grid-bottom{grid-template-columns:1fr}}
 @media(max-width:760px){.dash-head{display:grid;align-items:start;gap:9px;margin-bottom:10px}.dash-head h1{font-size:20px}.dash-period{width:100%}.dash-kpis{grid-template-columns:1fr 1fr;gap:7px}.dash-kpi{padding:11px;border-radius:13px;box-shadow:none}.dash-kpi b{font-size:15px}.dash-grid-main,.dash-grid-half,.dash-grid-bottom{grid-template-columns:1fr;gap:9px;margin-top:9px}.dash-panel{border-radius:14px;box-shadow:none}.dash-ph{padding:11px 11px 8px}.dash-ph h2{font-size:14px}.dash-chart-wrap{padding:0 9px 9px}.dash-chart{height:180px}.dash-today{padding:2px 10px 10px}.dash-loads,.dash-debts,.dash-alerts{padding-left:9px;padding-right:9px;padding-bottom:9px}.dash-load-metrics{grid-template-columns:1fr 1fr}.dash-debt-stats{grid-template-columns:1fr 1fr}.dash-debt-stats .dash-ds:last-child{grid-column:1/-1}.dash-grid-bottom.manager{display:grid}.dash-rank{padding-left:9px;padding-right:9px}.dash-timeline{padding-left:10px;padding-right:10px}}
 </style>`;
}

export async function dashboardPage(res,url,u){
 if(url.pathname!=='/')return false;
 const d=await data(u);
 const allowed=new Set(['today','7d','30d','month','all']);
 const range=allowed.has(url.searchParams.get('range'))?url.searchParams.get('range'):'today';
 const rangeLabels={today:'Bugun','7d':'7 kun','30d':'30 kun',month:'Shu oy',all:'Barchasi'};
 const today=startOfToday(),start=rangeStart(range,today);
 const periodSales=d.S.filter(x=>inRange(x,start));
 const periodPays=d.P.filter(x=>inRange(x,start));
 const periodExpenses=d.E.filter(x=>inRange(x,start));
 const allLoads=[...d.L,...d.A];
 const loadById=new Map(allLoads.map(x=>[+x.id,x]));
 const salesTotal=sum(periodSales,x=>x.total);
 const received=sum(periodSales,x=>x.paid_amount)+sum(periodPays,x=>x.amount);
 const currentDebt=sum(d.C,x=>x.debt);
 const expenseTotal=sum(periodExpenses,x=>x.amount);
 const profit=profitFor(periodSales,periodExpenses,loadById);
 const stock=sum(d.L,x=>x.stock_kg);

 const todaySales=d.S.filter(x=>inRange(x,today));
 const todayPays=d.P.filter(x=>inRange(x,today));
 const todayExpenses=d.E.filter(x=>inRange(x,today));
 const todayReceived=sum(todaySales,x=>x.paid_amount)+sum(todayPays,x=>x.amount);
 const todayNewDebt=sum(todaySales,x=>x.debt_amount);
 const todayRepaid=sum(todayPays,x=>x.amount);
 const todayProfit=profitFor(todaySales,todayExpenses,loadById);

 const chart=chartData(range,today,periodSales,periodPays,periodExpenses,loadById);
 const salesVals=chart.values.map(x=>x.sales),paidVals=chart.values.map(x=>x.paid),profitVals=chart.values.map(x=>Math.max(0,x.profit));
 const maxV=Math.max(1,...salesVals,...paidVals,...profitVals);
 const salesPts=linePoints(salesVals,maxV),paidPts=linePoints(paidVals,maxV),profitPts=linePoints(profitVals,maxV);
 const axisFirst=chart.labels[0]||'',axisMid=chart.labels[Math.floor((chart.labels.length-1)/2)]||'',axisLast=chart.labels[chart.labels.length-1]||'';

 const loadCards=d.L.slice().sort((a,b)=>n(b.sold_kg)/Math.max(n(b.arrived_kg),1)-n(a.sold_kg)/Math.max(n(a.arrived_kg),1)).slice(0,6).map(L=>{
  const LS=d.S.filter(x=>+x.load_id===+L.id),LE=d.E.filter(x=>+x.load_id===+L.id);
  const sold=n(L.sold_kg),progress=pct(sold,n(L.arrived_kg)),lp=profitFor(LS,LE,loadById);
  return `<a class="dash-load" href="/load/${L.id}"><div class="dash-load-top"><div class="dash-load-title"><b>${e(L.name)}</b><span>${e(L.product)}${u.role==='manager'?' · '+e(L.seller_name):''}</span></div><span class="dash-badge ${n(L.stock_kg)<0?'warn':''}">${progress}% sotilgan</span></div><div class="dash-load-metrics"><div class="dash-mi"><span>Kelgan</span><b>${qty(L.arrived_kg)} kg</b></div><div class="dash-mi"><span>Sotilgan</span><b>${qty(sold)} kg</b></div><div class="dash-mi"><span>Qoldiq</span><b>${qty(L.stock_kg)} kg</b></div><div class="dash-mi"><span>Foyda</span><b>${shortMoney(lp)}</b></div></div><div class="dash-progress"><i style="width:${capPct(progress)}%"></i></div></a>`;
 }).join('');

 const openCredits=d.S.filter(x=>n(x.remaining_debt)>0);
 const debtors=d.C.filter(x=>n(x.debt)>0).sort((a,b)=>n(b.debt)-n(a.debt));
 const openByCustomer=new Map();
 openCredits.forEach(x=>openByCustomer.set(+x.customer_id,(openByCustomer.get(+x.customer_id)||0)+1));
 const topDebts=debtors.slice(0,5).map(c=>`<div class="dash-debt-item"><div><a href="/debts/customer/${c.id}">${e(c.name)}</a><span>${openByCustomer.get(+c.id)||0} ta ochiq nasiya${u.role==='manager'?' · '+e(c.seller_name):''}</span></div><div class="dash-debt-money">${shortMoney(c.debt)}</div></div>`).join('');

 let ranking='';
 if(u.role==='manager'){
  const sellerMap=new Map();
  for(const x of [...d.S,...d.L,...d.E,...d.C])if(x.seller_id&&!sellerMap.has(+x.seller_id))sellerMap.set(+x.seller_id,x.seller_name||'Sotuvchi');
  const rank=[...sellerMap].map(([id,name])=>{
   const S=periodSales.filter(x=>+x.seller_id===id),P=periodPays.filter(x=>+x.seller_id===id),E=periodExpenses.filter(x=>+x.seller_id===id);
   return {id,name,sales:sum(S,x=>x.total),received:sum(S,x=>x.paid_amount)+sum(P,x=>x.amount),debt:sum(S,x=>x.remaining_debt),profit:profitFor(S,E,loadById)};
  }).sort((a,b)=>b.sales-a.sales);
  ranking=`<section class="dash-panel"><div class="dash-ph"><div><h2>Sotuvchilar reytingi</h2><p>${rangeLabels[range]} natijalari</p></div></div><div class="dash-rank"><table><thead><tr><th>#</th><th>Sotuvchi</th><th>Savdo</th><th>Tushgan</th><th>Nasiya</th><th>Foyda</th></tr></thead><tbody>${rank.map((x,i)=>`<tr><td><span class="dash-rank-num">${i+1}</span></td><td><b>${e(x.name)}</b></td><td>${shortMoney(x.sales)}</td><td>${shortMoney(x.received)}</td><td>${shortMoney(x.debt)}</td><td><b>${shortMoney(x.profit)}</b></td></tr>`).join('')||'<tr><td colspan="6">Ma’lumot yo‘q</td></tr>'}</tbody></table></div></section>`;
 }

 const alerts=[];
 const negative=d.L.filter(x=>n(x.stock_kg)<0);
 if(negative.length)alerts.push(`<div class="dash-alert red"><div class="dash-alert-ico">!</div><div><b>${negative.length} ta yuk qoldig‘i minusda</b><span>${negative.slice(0,2).map(x=>`${e(x.name)}: ${qty(x.stock_kg)} kg`).join(' · ')}</span></div><small>tekshiring</small></div>`);
 const low=d.L.filter(x=>n(x.arrived_kg)>0&&n(x.stock_kg)>=0&&n(x.stock_kg)/n(x.arrived_kg)<=.1);
 if(low.length)alerts.push(`<div class="dash-alert amber"><div class="dash-alert-ico">▣</div><div><b>${low.length} ta yuk qoldig‘i 10% dan kam</b><span>${low.slice(0,3).map(x=>e(x.name)).join(' · ')}</span></div><small>qoldiq</small></div>`);
 const now=Date.now(),overdue=openCredits.filter(x=>now-new Date(x.created_at).getTime()>10*DAY);
 if(overdue.length)alerts.push(`<div class="dash-alert amber"><div class="dash-alert-ico">◴</div><div><b>${overdue.length} ta nasiya 10 kundan oshgan</b><span>Jami ${money(sum(overdue,x=>x.remaining_debt))}</span></div><small>nasiya</small></div>`);
 if(debtors[0])alerts.push(`<div class="dash-alert ${n(debtors[0].debt)>=10000000?'red':'amber'}"><div class="dash-alert-ico">₴</div><div><b>${e(debtors[0].name)} — eng katta qarzdor</b><span>${money(debtors[0].debt)} · ${openByCustomer.get(+debtors[0].id)||0} ta ochiq nasiya</span></div><small>mijoz</small></div>`);
 const recentArchive=d.A.filter(x=>x.archived_at).sort((a,b)=>new Date(b.archived_at)-new Date(a.archived_at))[0];
 if(recentArchive&&now-new Date(recentArchive.archived_at).getTime()<3*DAY)alerts.push(`<div class="dash-alert green"><div class="dash-alert-ico">✓</div><div><b>${e(recentArchive.name)} yakunlandi</b><span>Yuk arxivga o‘tkazilgan</span></div><small>${dt(recentArchive.archived_at)}</small></div>`);
 if(!alerts.length)alerts.push(`<div class="dash-alert green"><div class="dash-alert-ico">✓</div><div><b>Jiddiy ogohlantirish yo‘q</b><span>Hozircha hammasi nazoratda.</span></div><small>yaxshi</small></div>`);

 const events=[
  ...d.S.map(x=>({at:x.created_at,html:`<b>${e(x.seller_name)} → ${e(x.customer_name||'Naqd savdo')}</b><span>${money(x.total)} savdo${n(x.debt_amount)>0?' · '+money(x.debt_amount)+' nasiya':''}</span>`})),
  ...d.P.map(x=>({at:x.created_at,html:`<b>${e(x.customer_name)} qarz qaytardi</b><span>${money(x.amount)}${u.role==='manager'?' · '+e(x.seller_name):''}</span>`})),
  ...d.E.map(x=>({at:x.created_at,html:`<b>${e(x.name)} xarajat</b><span>${money(x.amount)}${x.load_name?' · '+e(x.load_name):''}</span>`})),
  ...d.A.filter(x=>x.archived_at).map(x=>({at:x.archived_at,html:`<b>${e(x.name)} yakunlandi</b><span>${e(x.product)} · arxivga o‘tkazildi</span>`}))
 ].sort((a,b)=>new Date(b.at)-new Date(a.at)).slice(0,8);
 const activity=events.map(x=>`<div class="dash-act"><div class="dash-act-dot"></div><div class="dash-act-main">${x.html}</div><time>${dt(x.at)}</time></div>`).join('');

 const periodLinks=Object.entries(rangeLabels).map(([k,v])=>`<a class="${range===k?'active':''}" href="/?range=${k}">${v}</a>`).join('');
 const body=`${dashboardCss()}<div class="dash">
 <div class="dash-head"><div><h1>Umumiy dashboard</h1><p>${u.role==='manager'?'Barcha sotuvchilar va biznes holati':'Sizning savdo va hisob ko‘rsatkichlaringiz'}</p></div><div class="dash-period">${periodLinks}</div></div>
 <section class="dash-kpis">
  <div class="dash-kpi"><div class="dash-kpi-top"><span>Jami savdo</span><i>₴</i></div><b>${money(salesTotal)}</b><small>${rangeLabels[range]}</small></div>
  <div class="dash-kpi"><div class="dash-kpi-top"><span>Tushgan pul</span><i>↓</i></div><b>${money(received)}</b><small>Savdo + qaytgan qarz</small></div>
  <div class="dash-kpi"><div class="dash-kpi-top"><span>Qolgan nasiya</span><i>◴</i></div><b>${money(currentDebt)}</b><small>Hozirgi umumiy qarz</small></div>
  <div class="dash-kpi"><div class="dash-kpi-top"><span>Jami foyda</span><i>↗</i></div><b>${money(profit)}</b><small>${rangeLabels[range]}</small></div>
  <div class="dash-kpi"><div class="dash-kpi-top"><span>Jami xarajat</span><i>−</i></div><b>${money(expenseTotal)}</b><small>${rangeLabels[range]}</small></div>
  <div class="dash-kpi"><div class="dash-kpi-top"><span>Qoldiq</span><i>▣</i></div><b>${qty(stock)} kg</b><small>${d.L.length} ta faol yuk</small></div>
 </section>
 <div class="dash-grid-main">
  <section class="dash-panel"><div class="dash-ph"><div><h2>Savdo dinamikasi</h2><p>${range==='today'?'Bugungi 4 soatlik kesim':'Davr bo‘yicha savdo, tushgan pul va foyda'}</p></div></div><div class="dash-chart-wrap"><div class="dash-chart"><svg viewBox="0 0 1000 220" preserveAspectRatio="none"><polyline points="${salesPts}" fill="none" stroke="#0d7a43" stroke-width="5" vector-effect="non-scaling-stroke"/><polyline points="${paidPts}" fill="none" stroke="#668d74" stroke-width="3" stroke-dasharray="8 6" vector-effect="non-scaling-stroke"/><polyline points="${profitPts}" fill="none" stroke="#d19a3c" stroke-width="3" vector-effect="non-scaling-stroke"/></svg></div><div class="dash-axis"><span>${e(axisFirst)}</span><span>${e(axisMid)}</span><span>${e(axisLast)}</span></div><div class="dash-legend"><span><i class="dash-dot sale"></i>Savdo</span><span><i class="dash-dot paid"></i>Tushgan pul</span><span><i class="dash-dot profit"></i>Foyda</span></div></div></section>
  <section class="dash-panel"><div class="dash-ph"><div><h2>Bugungi holat</h2><p>Bugungi operatsiyalar</p></div></div><div class="dash-today"><div class="dash-today-row"><span>Bugungi savdo</span><b>${money(sum(todaySales,x=>x.total))}</b></div><div class="dash-today-row"><span>Tushgan pul</span><b>${money(todayReceived)}</b></div><div class="dash-today-row"><span>Yangi nasiya</span><b>${money(todayNewDebt)}</b></div><div class="dash-today-row"><span>Qarz qaytdi</span><b>${money(todayRepaid)}</b></div><div class="dash-today-row"><span>Xarajat</span><b>${money(sum(todayExpenses,x=>x.amount))}</b></div><div class="dash-today-row"><span>Bugungi foyda</span><b>${money(todayProfit)}</b></div></div></section>
 </div>
 <div class="dash-grid-half">
  <section class="dash-panel"><div class="dash-ph"><div><h2>Faol yuklar</h2><p>Qoldiq va sotilish holati</p></div><a class="dash-link" href="/loads">Barchasi →</a></div><div class="dash-loads">${loadCards||'<div class="dash-empty">Faol yuk yo‘q</div>'}</div></section>
  <section class="dash-panel"><div class="dash-ph"><div><h2>Nasiyalar</h2><p>Ochiq qarzlar nazorati</p></div><a class="dash-link" href="/debts">Ko‘rish →</a></div><div class="dash-debts"><div class="dash-debt-stats"><div class="dash-ds"><span>Qolgan nasiya</span><b>${shortMoney(currentDebt)}</b></div><div class="dash-ds"><span>Ochiq nasiya</span><b>${openCredits.length} ta</b></div><div class="dash-ds"><span>Qarzdor mijoz</span><b>${debtors.length} ta</b></div></div>${topDebts||'<div class="dash-empty">Ochiq nasiya yo‘q</div>'}</div></section>
 </div>
 <div class="dash-grid-bottom ${u.role==='manager'?'manager':''}">${ranking}<section class="dash-panel"><div class="dash-ph"><div><h2>Muhim ogohlantirishlar</h2><p>E’tibor talab qiladigan holatlar</p></div></div><div class="dash-alerts">${alerts.slice(0,5).join('')}</div></section></div>
 <section class="dash-panel dash-activity"><div class="dash-ph"><div><h2>Oxirgi harakatlar</h2><p>Tizimdagi so‘nggi operatsiyalar</p></div></div><div class="dash-timeline">${activity||'<div class="dash-empty">Hozircha harakat yo‘q</div>'}</div></section>
 </div>`;
 send(res,layout(u,'Bosh sahifa',body));
 return true;
}
