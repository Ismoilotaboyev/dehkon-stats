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
 .dash{display:grid;gap:16px}.dash *{box-sizing:border-box}
 .dash-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:14px}.dash-head h1{margin:0;font-size:26px;font-weight:700;letter-spacing:-.01em}.dash-head p{margin:0;color:var(--muted);font-size:14px}
 .dash-head-actions{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
 .dash-period{display:flex;gap:2px;padding:4px;background:#E6EBE4;border-radius:12px;overflow:auto}.dash-period a{white-space:nowrap;padding:8px 12px;border-radius:9px;font-size:14px;font-weight:500;color:#3F4E46;min-height:36px;display:flex;align-items:center}.dash-period a.active{background:#fff;color:var(--text);font-weight:600}
 .dash-btn{display:inline-flex;align-items:center;gap:6px;height:44px;padding:0 18px;border-radius:12px;background:var(--green);color:#fff;font-weight:600;font-size:15px}.dash-btn:hover{background:var(--green2)}.dash-btn.plus:before{content:"+";font-size:18px;font-weight:500;margin-right:2px}.dash-btn.ghost{background:#fff;color:var(--text);border:1px solid #C9D3C6}.dash-btn.ghost:hover{background:#FAFBF9}
 .dash-alerts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
 .dash-alert{display:flex;align-items:center;gap:14px;padding:14px 16px;border-radius:14px;border:1px solid;background:#fff}
 .dash-alert>div:nth-child(2){flex:1;min-width:0}.dash-alert b{display:block;font-size:15px;font-weight:600}.dash-alert span{display:block;font-size:13px;margin-top:2px}.dash-alert small{font-size:12px;font-weight:600;white-space:nowrap}
 .dash-alert-ico{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;flex:0 0 36px;color:#fff;font-weight:700}
 .dash-alert-link{font-size:14px;font-weight:600;white-space:nowrap;text-decoration:underline;text-underline-offset:3px}
 .dash-alert.red{background:var(--red-bg);border-color:#F4C7C1;color:#7A1A10}.dash-alert.red .dash-alert-ico{background:var(--danger)}
 .dash-alert.amber{background:#FFF8EE;border-color:#F2DDBF;color:#6B3A00}.dash-alert.amber .dash-alert-ico{background:var(--amber)}
 .dash-alert.green{background:var(--ok-bg);border-color:#BFDCC9;color:#0F4A2C}.dash-alert.green .dash-alert-ico{background:var(--green)}
 .dash-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
 .dash-kpi{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px 20px;min-width:0}.dash-kpi span{display:block;font-size:13px;color:var(--muted);font-weight:500}.dash-kpi b{display:block;font-size:28px;font-weight:700;letter-spacing:-.02em;margin-top:8px;line-height:1.15;overflow-wrap:anywhere}.dash-kpi small{display:block;font-size:13px;color:var(--muted);margin-top:6px}
 .dash-kpi .pos{color:var(--green)}.dash-kpi .neg{color:var(--danger)}
 .dash-kpi.debt{background:#FFF8EE;border-color:#F2DDBF}.dash-kpi.debt span,.dash-kpi.debt small{color:#7A4A12}.dash-kpi.debt b{color:var(--amber)}
 .dash-panel{background:#fff;border:1px solid var(--line);border-radius:16px;min-width:0;overflow:hidden}
 .dash-ph{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:18px 20px 8px}.dash-ph h2{margin:0;font-size:17px;font-weight:600}.dash-ph p{margin:3px 0 0;font-size:13px;color:var(--muted)}
 .dash-link{font-size:14px;font-weight:600;color:var(--green)}
 .dash-split{padding:18px 20px}.dash-split-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px}.dash-split-head h2{margin:0;font-size:17px;font-weight:600}.dash-split-head span{font-size:14px;color:var(--muted)}
 .dash-split-bar{display:flex;height:16px;border-radius:8px;overflow:hidden;background:#EEF1EC;margin-top:14px}.dash-split-bar i.paid{background:var(--green)}.dash-split-bar i.debt{background:#E8A04A}
 .dash-split-legend{display:flex;flex-wrap:wrap;gap:10px 28px;margin-top:12px;font-size:14px;color:var(--muted)}.dash-split-legend span{display:flex;align-items:center;gap:8px}.dash-split-legend b{color:var(--text);font-weight:600}
 .dash-dot{width:10px;height:10px;border-radius:3px;display:inline-block}.dash-dot.sale{background:var(--green)}.dash-dot.paid{background:#5B8A6E}.dash-dot.profit{background:#E8A04A}
 .dash-chart-wrap{padding:4px 20px 18px}.dash-chart{height:220px;border-radius:12px;background:repeating-linear-gradient(to bottom,#F3F5F1 0 1px,transparent 1px 44px)}.dash-chart svg{width:100%;height:100%}.dash-axis{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-top:6px}.dash-legend{display:flex;gap:18px;font-size:13px;color:var(--muted);margin-top:10px}.dash-legend span{display:flex;align-items:center;gap:6px}
 .dash-grid-half{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px;align-items:start}
 .dash-loads{padding:0 20px 8px}.dash-load{display:block;padding:14px 0;border-bottom:1px solid #EEF1EC;color:var(--text)}.dash-load:last-child{border-bottom:0}
 .dash-load-top{display:flex;justify-content:space-between;align-items:baseline;gap:12px}.dash-load-title{min-width:0}.dash-load-title b{display:block;font-size:15px;font-weight:600}.dash-load-title span{display:block;font-size:13px;color:var(--muted);margin-top:2px}
 .dash-load-profit{font-size:14px;font-weight:600;white-space:nowrap;color:var(--muted)}.dash-load-profit.pos{color:var(--green)}.dash-load-profit.neg{color:var(--danger)}
 .dash-progress{height:8px;border-radius:4px;background:#EEF1EC;margin-top:10px;overflow:hidden}.dash-progress i{display:block;height:100%;background:var(--green);border-radius:4px}
 .dash-load-foot{display:flex;justify-content:space-between;gap:12px;font-size:13px;color:var(--muted);margin-top:6px;font-variant-numeric:tabular-nums}
 .dash-debts{padding:0 20px 8px}.dash-debt-item{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid #EEF1EC;color:var(--text)}.dash-debt-item:last-child{border-bottom:0}
 .dash-av{width:36px;height:36px;border-radius:10px;background:#F1F4EF;color:#2E3F35;display:grid;place-items:center;font-size:13px;font-weight:600;flex:0 0 36px}
 .dash-debt-main{flex:1;min-width:0}.dash-debt-main b{display:block;font-size:15px;font-weight:600}.dash-debt-main>span{display:block;font-size:12px;color:var(--muted);margin-top:1px}
 .dash-debt-bar{height:6px;border-radius:3px;background:#F6EDE1;margin-top:6px;overflow:hidden}.dash-debt-bar i{display:block;height:100%;background:#E8A04A}
 .dash-debt-money{font-size:15px;font-weight:600;color:var(--amber);white-space:nowrap;font-variant-numeric:tabular-nums}
 .dash-rank{padding:0 20px 14px;overflow:auto}.dash-rank table{width:100%;border-collapse:collapse;font-size:14px;min-width:560px}.dash-rank th{text-align:left}.dash-rank td:not(:nth-child(-n+2)),.dash-rank th:not(:nth-child(-n+2)){text-align:right}.dash-rank-num{display:inline-grid;place-items:center;width:26px;height:26px;border-radius:8px;background:#F1F4EF;font-weight:600}
 .dash-timeline{padding:0 20px 10px}.dash-act{display:grid;grid-template-columns:10px 1fr auto;gap:12px;padding:12px 0;border-bottom:1px solid #EEF1EC;align-items:start}.dash-act:last-child{border-bottom:0}.dash-act-dot{width:8px;height:8px;border-radius:50%;background:var(--green);margin-top:7px}.dash-act-main b{display:block;font-size:14px;font-weight:600}.dash-act-main span{display:block;font-size:13px;color:var(--muted);margin-top:2px;font-variant-numeric:tabular-nums}.dash-act time{font-size:12px;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}
 .dash-empty{padding:16px 0;color:var(--muted);font-size:14px}
 @media(max-width:1100px){.dash-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
 @media(max-width:760px){.dash{gap:12px}.dash-head{display:grid;gap:10px}.dash-head h1{font-size:22px}.dash-head-actions{display:grid;grid-template-columns:1fr 1fr}.dash-period{grid-column:1/-1}.dash-btn{justify-content:center}.dash-kpis{gap:8px}.dash-kpi{padding:14px}.dash-kpi b{font-size:19px}.dash-kpi small{font-size:12px}.dash-grid-half{grid-template-columns:1fr}.dash-alerts{grid-template-columns:1fr}.dash-alert{padding:12px}.dash-ph{padding:14px 14px 6px}.dash-loads,.dash-debts,.dash-timeline{padding:0 14px 6px}.dash-split{padding:14px}.dash-split-legend{display:grid;gap:8px}.dash-act{grid-template-columns:10px 1fr}.dash-act time{grid-column:2}}
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
  const pcls=lp<0?'neg':lp>0?'pos':'';
  return `<a class="dash-load" href="/load/${L.id}"><div class="dash-load-top"><div class="dash-load-title"><b>${e(L.name)}</b><span>${e(L.product)}${u.role==='manager'?' · '+e(L.seller_name):''}</span></div><b class="dash-load-profit ${pcls}">${lp>0?'+':''}${shortMoney(lp)}</b></div><div class="dash-progress"><i style="width:${capPct(progress)}%"></i></div><div class="dash-load-foot"><span>${qty(sold)} / ${qty(L.arrived_kg)} kg sotildi · ${progress}%</span><span class="${n(L.stock_kg)<0?'neg':''}">Qoldiq ${qty(L.stock_kg)} kg</span></div></a>`;
 }).join('');

 const openCredits=d.S.filter(x=>n(x.remaining_debt)>0);
 const debtors=d.C.filter(x=>n(x.debt)>0).sort((a,b)=>n(b.debt)-n(a.debt));
 const openByCustomer=new Map();
 openCredits.forEach(x=>openByCustomer.set(+x.customer_id,(openByCustomer.get(+x.customer_id)||0)+1));
 const maxDebt=Math.max(1,...debtors.slice(0,5).map(c=>n(c.debt)));
 const initials=v=>String(v||'').split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0]).join('').toUpperCase();
 const topDebts=debtors.slice(0,5).map(c=>`<a class="dash-debt-item" href="/debts/customer/${c.id}"><span class="dash-av">${e(initials(c.name))}</span><div class="dash-debt-main"><b>${e(c.name)}</b><span>${openByCustomer.get(+c.id)||0} ta ochiq nasiya${u.role==='manager'?' · '+e(c.seller_name):''}</span><div class="dash-debt-bar"><i style="width:${capPct(Math.round(n(c.debt)/maxDebt*100))}%"></i></div></div><div class="dash-debt-money">${money(c.debt)}</div></a>`).join('');

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
 if(debtors[0])alerts.push(`<div class="dash-alert ${n(debtors[0].debt)>=10000000?'red':'amber'}"><div class="dash-alert-ico">₴</div><div><b>${e(debtors[0].name)} — eng katta qarzdor</b><span>${money(debtors[0].debt)} · ${openByCustomer.get(+debtors[0].id)||0} ta ochiq nasiya</span></div><a class="dash-alert-link" href="/debts/customer/${debtors[0].id}">Ko‘rish</a></div>`);
 const recentArchive=d.A.filter(x=>x.archived_at).sort((a,b)=>new Date(b.archived_at)-new Date(a.archived_at))[0];
 if(recentArchive&&now-new Date(recentArchive.archived_at).getTime()<3*DAY)alerts.push(`<div class="dash-alert green"><div class="dash-alert-ico">✓</div><div><b>${e(recentArchive.name)} yakunlandi</b><span>Yuk arxivga o‘tkazilgan</span></div><small>${dt(recentArchive.archived_at)}</small></div>`);
 

 const events=[
  ...d.S.map(x=>({at:x.created_at,html:`<b>${e(x.seller_name)} → ${e(x.customer_name||'Naqd savdo')}</b><span>${money(x.total)} savdo${n(x.debt_amount)>0?' · '+money(x.debt_amount)+' nasiya':''}</span>`})),
  ...d.P.map(x=>({at:x.created_at,html:`<b>${e(x.customer_name)} qarz qaytardi</b><span>${money(x.amount)}${u.role==='manager'?' · '+e(x.seller_name):''}</span>`})),
  ...d.E.map(x=>({at:x.created_at,html:`<b>${e(x.name)} xarajat</b><span>${money(x.amount)}${x.load_name?' · '+e(x.load_name):''}</span>`})),
  ...d.A.filter(x=>x.archived_at).map(x=>({at:x.archived_at,html:`<b>${e(x.name)} yakunlandi</b><span>${e(x.product)} · arxivga o‘tkazildi</span>`}))
 ].sort((a,b)=>new Date(b.at)-new Date(a.at)).slice(0,8);
 const activity=events.map(x=>`<div class="dash-act"><div class="dash-act-dot"></div><div class="dash-act-main">${x.html}</div><time>${dt(x.at)}</time></div>`).join('');

 const periodLinks=Object.entries(rangeLabels).map(([k,v])=>`<a class="${range===k?'active':''}" href="/?range=${k}"${range===k?' aria-current="page"':''}>${v}</a>`).join('');
 const periodPaid=sum(periodSales,x=>x.paid_amount),periodDebt=sum(periodSales,x=>x.debt_amount),periodRepaid=sum(periodPays,x=>x.amount);
 const paidPct=salesTotal>0?Math.round(periodPaid/salesTotal*100):0,debtPct=salesTotal>0?100-paidPct:0;
 const profitCls=profit<0?'neg':profit>0?'pos':'';
 const chartHtml=range==='today'?'':`<section class="dash-panel"><div class="dash-ph"><div><h2>Savdo dinamikasi</h2><p>Davr bo‘yicha savdo, tushgan pul va foyda</p></div></div><div class="dash-chart-wrap"><div class="dash-chart"><svg viewBox="0 0 1000 220" preserveAspectRatio="none" role="img" aria-label="Savdo dinamikasi grafigi"><polyline points="${salesPts}" fill="none" stroke="#1B7A4B" stroke-width="4" vector-effect="non-scaling-stroke"/><polyline points="${paidPts}" fill="none" stroke="#5B8A6E" stroke-width="2.5" stroke-dasharray="8 6" vector-effect="non-scaling-stroke"/><polyline points="${profitPts}" fill="none" stroke="#E8A04A" stroke-width="2.5" vector-effect="non-scaling-stroke"/></svg></div><div class="dash-axis"><span>${e(axisFirst)}</span><span>${e(axisMid)}</span><span>${e(axisLast)}</span></div><div class="dash-legend"><span><i class="dash-dot sale"></i>Savdo</span><span><i class="dash-dot paid"></i>Tushgan pul</span><span><i class="dash-dot profit"></i>Foyda</span></div></div></section>`;
 const body=`${dashboardCss()}<div class="dash">
 <div class="dash-head"><div><p class="dash-sub">${u.role==='manager'?'Barcha sotuvchilar bo‘yicha':'Sizning savdo va hisob ko‘rsatkichlaringiz'}</p></div><div class="dash-head-actions"><div class="dash-period" role="group" aria-label="Davr">${periodLinks}</div><a class="dash-btn ghost plus" href="/loads">Yangi yuk</a><a class="dash-btn plus" href="/sales">Savdo</a></div></div>
 ${alerts.length?`<section class="dash-alerts" aria-label="Muhim ogohlantirishlar">${alerts.slice(0,4).join('')}</section>`:''}
 <section class="dash-kpis" aria-label="Asosiy ko‘rsatkichlar">
  <div class="dash-kpi"><span>Savdo · ${rangeLabels[range]}</span><b>${money(salesTotal)}</b><small>${periodSales.length} ta savdo · ${qty(sum(periodSales,x=>x.kg))} kg</small></div>
  <div class="dash-kpi"><span>Tushgan pul</span><b class="pos">${money(received)}</b><small>Naqd + qaytgan qarz</small></div>
  <div class="dash-kpi"><span>Foyda · ${rangeLabels[range]}</span><b class="${profitCls}">${profit>0?'+':''}${money(profit)}</b><small>Savdo − tannarx − xarajat</small></div>
  <div class="dash-kpi debt"><span>Qolgan nasiya</span><b>${money(currentDebt)}</b><small>${debtors.length} mijoz · ${openCredits.length} ochiq nasiya</small></div>
 </section>
 <section class="dash-panel dash-split" aria-label="Savdo qanday to‘landi"><div class="dash-split-head"><h2>Savdo qanday to‘landi</h2><span>Jami ${money(salesTotal)}</span></div><div class="dash-split-bar" role="img" aria-label="Naqd ${paidPct} foiz, nasiya ${debtPct} foiz"><i class="paid" style="width:${paidPct}%"></i><i class="debt" style="width:${debtPct}%"></i></div><div class="dash-split-legend"><span><i class="dash-dot sale"></i>Naqd olindi <b>${money(periodPaid)} · ${paidPct}%</b></span><span><i class="dash-dot profit"></i>Nasiyaga ketdi <b>${money(periodDebt)} · ${debtPct}%</b></span><span>Qarz qaytdi <b>${money(periodRepaid)}</b></span><span>Xarajat <b>${money(expenseTotal)}</b></span></div></section>
 ${chartHtml}
 <div class="dash-grid-half">
  <section class="dash-panel"><div class="dash-ph"><div><h2>Faol yuklar</h2><p>${d.L.length} ta yuk · ${qty(stock)} kg qoldiq</p></div><a class="dash-link" href="/loads">Barchasi</a></div><div class="dash-loads">${loadCards||'<div class="dash-empty">Faol yuk yo‘q</div>'}</div></section>
  <section class="dash-panel"><div class="dash-ph"><div><h2>Eng katta qarzdorlar</h2><p>${shortMoney(currentDebt)} · ${debtors.length} mijoz</p></div><a class="dash-link" href="/debts">Hammasi</a></div><div class="dash-debts">${topDebts||'<div class="dash-empty">Ochiq nasiya yo‘q</div>'}</div></section>
 </div>
 ${ranking}
 <section class="dash-panel dash-activity"><div class="dash-ph"><div><h2>Oxirgi harakatlar</h2><p>Tizimdagi so‘nggi operatsiyalar</p></div><a class="dash-link" href="/sales">Barcha savdolar</a></div><div class="dash-timeline">${activity||'<div class="dash-empty">Hozircha harakat yo‘q</div>'}</div></section>
 </div>`;
 send(res,layout(u,'Bosh sahifa',body));
 return true;
}
