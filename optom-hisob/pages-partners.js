import {Q,n,e,money,body,send,go,audit} from './core.js';
import {layout} from './ui.js';

let ready;
const ensurePartner=()=>ready||(ready=(async()=>{
 await Q(`CREATE TABLE IF NOT EXISTS partner_events(
  id SERIAL PRIMARY KEY,
  owner_seller_id INT NOT NULL REFERENCES users(id),
  actor_user_id INT NOT NULL REFERENCES users(id),
  event_type TEXT NOT NULL,
  customer_id INT REFERENCES customers(id),
  sale_id INT REFERENCES sales(id),
  payment_id INT REFERENCES payments(id),
  load_id INT REFERENCES loads(id),
  amount NUMERIC DEFAULT 0,
  cash_effect NUMERIC DEFAULT 0,
  payment_type TEXT,
  note TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
 )`);
 await Q(`CREATE INDEX IF NOT EXISTS partner_events_owner_idx ON partner_events(owner_seller_id,id DESC)`);
 await Q(`CREATE INDEX IF NOT EXISTS partner_events_actor_idx ON partner_events(actor_user_id,id DESC)`);
 await Q(`CREATE INDEX IF NOT EXISTS partner_events_pair_idx ON partner_events(actor_user_id,owner_seller_id,id DESC)`);
})());

const payLabel=x=>x==='card'?'Karta':x==='bank'?'Bank':'Naqd';
const eventLabel=x=>x==='debt_payment'?'Nasiya qaytimi':x==='sale'?'Sherik savdo':x==='settlement'?'Pul topshirildi':x;
const ownerRule=(u,ownerId)=>u.role==='manager'||(+ownerId!==+u.id);
const actorName=u=>String(u.name||'Sotuvchi');

async function sellerOptions(u){
 const rows=await Q(`SELECT id,name FROM users WHERE role='seller' ORDER BY name`);
 return rows.filter(x=>u.role==='manager'||+x.id!==+u.id);
}

async function debtTargets(u){
 const sellerWhere=u.role==='manager'?'':` AND c.seller_id<>$1`,params=u.role==='manager'?[]:[u.id];
 const old=await Q(`SELECT c.id customer_id,c.name customer_name,c.seller_id,u.name seller_name,
  GREATEST(c.opening_debt-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.customer_id=c.id AND p.sale_id IS NULL),0),0) remaining
  FROM customers c JOIN users u ON u.id=c.seller_id
  WHERE c.archived_at IS NULL${sellerWhere}
  ORDER BY u.name,c.name`,params);
 const sales=await Q(`SELECT s.id sale_id,s.customer_id,c.name customer_name,s.seller_id,u.name seller_name,l.name load_name,l.product,
  GREATEST(s.debt_amount-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.sale_id=s.id),0),0) remaining
  FROM sales s JOIN customers c ON c.id=s.customer_id JOIN users u ON u.id=s.seller_id JOIN loads l ON l.id=s.load_id
  WHERE s.debt_amount>0 AND c.archived_at IS NULL${u.role==='manager'?'':' AND s.seller_id<>$1'}
  ORDER BY u.name,c.name,s.id DESC`,params);
 const out=[];
 for(const x of old)if(n(x.remaining)>0)out.push({key:`old:${x.customer_id}`,owner:+x.seller_id,ownerName:x.seller_name,customer:+x.customer_id,label:`${x.customer_name} · Eski qarz`,remaining:n(x.remaining)});
 for(const x of sales)if(n(x.remaining)>0)out.push({key:`sale:${x.sale_id}`,owner:+x.seller_id,ownerName:x.seller_name,customer:+x.customer_id,label:`${x.customer_name} · ${x.load_name} · ${x.product}`,remaining:n(x.remaining)});
 return out;
}

async function activeLoads(u){
 const params=u.role==='manager'?[]:[u.id];
 return Q(`SELECT l.id,l.seller_id,l.name,l.product,l.arrived_kg,u.name seller_name,
  l.arrived_kg-COALESCE((SELECT SUM(s.kg) FROM sales s WHERE s.load_id=l.id),0) stock_kg
  FROM loads l JOIN users u ON u.id=l.seller_id
  WHERE l.archived_at IS NULL${u.role==='manager'?'':' AND l.seller_id<>$1'}
  ORDER BY u.name,l.id DESC`,params);
}

async function partnerCustomers(u){
 const params=u.role==='manager'?[]:[u.id];
 return Q(`SELECT c.id,c.seller_id,c.name,c.phone,c.place,u.name seller_name FROM customers c JOIN users u ON u.id=c.seller_id
  WHERE c.archived_at IS NULL${u.role==='manager'?'':' AND c.seller_id<>$1'} ORDER BY u.name,c.name`,params);
}

async function balances(u){
 if(u.role==='manager')return Q(`SELECT pe.actor_user_id,au.name actor_name,pe.owner_seller_id,ou.name owner_name,COALESCE(SUM(pe.cash_effect),0) balance
  FROM partner_events pe JOIN users au ON au.id=pe.actor_user_id JOIN users ou ON ou.id=pe.owner_seller_id
  GROUP BY pe.actor_user_id,au.name,pe.owner_seller_id,ou.name HAVING COALESCE(SUM(pe.cash_effect),0)<>0 ORDER BY balance DESC`);
 return Q(`SELECT pe.actor_user_id,au.name actor_name,pe.owner_seller_id,ou.name owner_name,COALESCE(SUM(pe.cash_effect),0) balance
  FROM partner_events pe JOIN users au ON au.id=pe.actor_user_id JOIN users ou ON ou.id=pe.owner_seller_id
  WHERE pe.actor_user_id=$1 OR pe.owner_seller_id=$1
  GROUP BY pe.actor_user_id,au.name,pe.owner_seller_id,ou.name HAVING COALESCE(SUM(pe.cash_effect),0)<>0 ORDER BY balance DESC`,[u.id]);
}

async function history(u){
 const params=u.role==='manager'?[]:[u.id];
 return Q(`SELECT pe.*,au.name actor_name,ou.name owner_name,c.name customer_name,l.name load_name
  FROM partner_events pe JOIN users au ON au.id=pe.actor_user_id JOIN users ou ON ou.id=pe.owner_seller_id
  LEFT JOIN customers c ON c.id=pe.customer_id LEFT JOIN loads l ON l.id=pe.load_id
  ${u.role==='manager'?'':'WHERE pe.actor_user_id=$1 OR pe.owner_seller_id=$1'}
  ORDER BY pe.id DESC LIMIT 150`,params);
}

export async function partnersPage(res,url,u){
 if(url.pathname!=='/partners')return false;
 await ensurePartner();
 const sellers=await sellerOptions(u),targets=await debtTargets(u),loads=await activeLoads(u),customers=await partnerCustomers(u),bs=await balances(u),hist=await history(u);
 const heldByMe=bs.filter(x=>+x.actor_user_id===+u.id&&n(x.balance)>0).reduce((a,x)=>a+n(x.balance),0);
 const mineWithOthers=bs.filter(x=>+x.owner_seller_id===+u.id&&n(x.balance)>0).reduce((a,x)=>a+n(x.balance),0);
 const allBalance=bs.filter(x=>n(x.balance)>0).reduce((a,x)=>a+n(x.balance),0);
 const ownBalance=u.role==='manager'?allBalance:heldByMe;
 const incomingBalance=u.role==='manager'?allBalance:mineWithOthers;
 const targetOpts=targets.map(x=>`<option value="${e(x.key)}" data-owner="${x.owner}" data-left="${x.remaining}">${e(x.ownerName)} · ${e(x.label)} · ${money(x.remaining)}</option>`).join('');
 const loadOpts=loads.filter(x=>n(x.stock_kg)>0).map(x=>`<option value="${x.id}" data-owner="${x.seller_id}">${e(x.seller_name)} · ${e(x.name)} · ${e(x.product)} · ${n(x.stock_kg).toLocaleString('uz-UZ')} kg</option>`).join('');
 const customerOpts=customers.map(x=>`<option value="${x.id}" data-owner="${x.seller_id}">${e(x.seller_name)} · ${e(x.name)}${x.place?' · '+e(x.place):''}</option>`).join('');
 const settleOwners=sellers.map(x=>{const b=bs.find(y=>+y.actor_user_id===+u.id&&+y.owner_seller_id===+x.id),bal=n(b?.balance);return bal>0?`<option value="${x.id}" data-balance="${bal}">${e(x.name)} · ${money(bal)}</option>`:''}).join('');
 const balanceRows=bs.filter(x=>n(x.balance)>0).map(x=>`<tr><td><b>${e(x.actor_name)}</b></td><td>→</td><td><b>${e(x.owner_name)}</b></td><td><b>${money(x.balance)}</b></td><td><span class="partner-badge warn">Topshirilmagan</span></td></tr>`).join('')||'<tr><td colspan="5" class="muted">Topshirilmagan sherik puli yo‘q</td></tr>';
 const histRows=hist.map(x=>`<tr><td>${new Intl.DateTimeFormat('uz-UZ',{timeZone:'Asia/Tashkent',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(x.created_at))}</td><td>${eventLabel(x.event_type)}</td><td>${e(x.owner_name)}</td><td><b>${e(x.actor_name)}</b></td><td>${e(x.customer_name||x.load_name||'—')}</td><td><b>${money(x.amount)}</b></td><td>${n(x.cash_effect)>0?'<span class="partner-badge warn">Qo‘lida +'+money(x.cash_effect)+'</span>':n(x.cash_effect)<0?'<span class="partner-badge ok">Topshirdi '+money(Math.abs(n(x.cash_effect)))+'</span>':'<span class="partner-badge">Pul olinmadi</span>'}</td></tr>`).join('')||'<tr><td colspan="7" class="muted">Sherik amallari hali yo‘q</td></tr>';
 const forms=u.role==='manager'?`<div class="partner-note"><b>Manager rejimi.</b> Siz barcha sherik hisoblarini va tarixni ko‘rasiz. Operatsiyani sotuvchilar o‘z akkauntidan bajaradi.</div>`:`
 <div class="partner-tabs"><button class="active" type="button" data-partner-tab="debt">Nasiya olish</button><button type="button" data-partner-tab="sale">Boshqa yukdan savdo</button><button type="button" data-partner-tab="settle">Pul topshirish</button></div>
 <section class="partner-action active" data-partner-panel="debt">
  <form method="post" action="/action/partner-payment" class="partner-form">
   <div class="partner-note"><b>Boshqa sotuvchining nasiyasini qabul qilish.</b> Qarz egasining daftaridan kamayadi, sizning qo‘lingizdagi sherik puliga qo‘shiladi.</div>
   <label class="field">Nasiya<select name="target" required><option value="">Nasiyani tanlang</option>${targetOpts}</select></label>
   <label class="field">Qabul qilingan summa<input name="amount" type="number" min="1" step="1" required></label>
   <label class="field">Izoh<input name="note" placeholder="Ixtiyoriy"></label>
   <button class="btn green">Pulni qabul qildim</button>
  </form>
 </section>
 <section class="partner-action" data-partner-panel="sale">
  <form method="post" action="/action/partner-sale" class="partner-form" data-partner-sale-form>
   <div class="partner-note"><b>Boshqa sotuvchining yukidan savdo.</b> Yuk qoldig‘i, savdo, foyda va nasiya yuk egasiga yoziladi. Tarixda siz bajarganingiz saqlanadi.</div>
   <label class="field">Yuk<select name="loadId" required data-partner-load><option value="">Yukni tanlang</option>${loadOpts}</select></label>
   <label class="field">KG<input name="kg" type="number" min="0.01" step="0.01" required></label>
   <label class="field">Qop<input name="bags" type="number" min="0" step="1" value="0"></label>
   <label class="field">Narx / KG<input name="price" type="number" min="0" step="1" required></label>
   <label class="field">To‘lov turi<select name="mode" data-partner-mode><option value="cash">Naqd</option><option value="debt">To‘liq nasiya</option><option value="partial">Qisman to‘lov + nasiya</option></select></label>
   <label class="field" data-partner-customer-field style="display:none">Mijoz<select name="customerId" data-partner-customer><option value="">Mijozni tanlang</option>${customerOpts}</select></label>
   <label class="field" data-partner-paid-field style="display:none">Hozir bergan puli<input name="paid" type="number" min="0" value="0"></label>
   <label class="field">Izoh<input name="note" placeholder="Ixtiyoriy"></label>
   <button class="btn green">Savdoni saqlash</button>
  </form>
 </section>
 <section class="partner-action" data-partner-panel="settle">
  <form method="post" action="/action/partner-settlement" class="partner-form">
   <div class="partner-note"><b>Sherik pulini egasiga topshirish.</b> Bu faqat sizning qo‘lingizdagi balansni kamaytiradi; mijoz qarzi ikkinchi marta o‘zgarmaydi.</div>
   <label class="field">Kimga<select name="ownerId" required><option value="">Sotuvchini tanlang</option>${settleOwners}</select></label>
   <label class="field">Topshirilayotgan summa<input name="amount" type="number" min="1" step="1" required></label>
   <label class="field">To‘lov turi<select name="paymentType"><option value="cash">Naqd</option><option value="card">Karta</option><option value="bank">Bank</option></select></label>
   <label class="field">Izoh<input name="note" placeholder="Ixtiyoriy"></label>
   <button class="btn green">Topshirildi</button>
  </form>
 </section>`;
 const css=`<style>
 .partner-summary{grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:12px}.partner-card-accent{background:#173b28;color:#fff;border-color:#173b28}.partner-card-accent span{color:#bcd0c3}.partner-tabs{display:flex;gap:5px;background:#edf2ed;padding:5px;border-radius:13px;margin:14px 16px 0}.partner-tabs button{flex:1;border:0;border-radius:9px;background:transparent;padding:10px;font-weight:900;color:#65736a;cursor:pointer}.partner-tabs button.active{background:#fff;color:var(--green);box-shadow:0 2px 8px rgba(20,45,30,.08)}.partner-action{display:none}.partner-action.active{display:block}.partner-form{padding:16px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.partner-form .btn{align-self:end;min-height:46px}.partner-note{grid-column:1/-1;background:#fff7e5;border:1px solid #ead8ac;color:#765800;border-radius:11px;padding:10px 12px;font-size:11px;line-height:1.45;margin:12px 16px}.partner-form .partner-note{margin:0}.partner-badge{display:inline-flex;padding:5px 8px;border-radius:999px;background:#eef2ed;color:#607067;font-size:9px;font-weight:900}.partner-badge.warn{background:#fff2dd;color:#8a5d00}.partner-badge.ok{background:#eaf5ed;color:#126c43}.partner-section-head{padding:15px 17px 8px}.partner-section-head h2{margin:0;font-size:16px}.partner-section-head .muted{margin-top:3px}.partner-table{overflow:auto}.partner-table table{min-width:760px}.partner-help{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;padding:0 16px 16px}.partner-help>div{background:#f6f8f5;border-radius:11px;padding:11px}.partner-help b{display:block;font-size:11px}.partner-help span{display:block;color:var(--muted);font-size:10px;margin-top:4px;line-height:1.4}@media(max-width:900px){.partner-summary{grid-template-columns:1fr 1fr}.partner-form{grid-template-columns:1fr 1fr}}@media(max-width:760px){.partner-summary{grid-template-columns:1fr 1fr!important}.partner-tabs{margin:10px 10px 0;overflow:auto}.partner-tabs button{min-width:130px;white-space:nowrap}.partner-form{grid-template-columns:1fr;padding:12px}.partner-note{margin:10px}.partner-help{grid-template-columns:1fr;padding:0 10px 10px}.partner-table{padding:0 10px 10px}.partner-panel{background:#fff}}
 </style>`;
 const body=`${css}<div class="cards partner-summary"><div class="card partner-card-accent"><span>${u.role==='manager'?'Jami topshirilmagan sherik puli':'Mening qo‘limda boshqalarniki'}</span><b>${money(ownBalance)}</b></div><div class="card"><span>${u.role==='manager'?'Nazoratdagi sherik balansi':'Mening pulim boshqalarda'}</span><b>${money(incomingBalance)}</b></div><div class="card"><span>Sherik amallari</span><b>${hist.length} ta</b></div></div>
 <section class="panel partner-panel"><div class="partner-section-head"><h2>Sherik sotuvchi</h2><div class="muted">Sotuvchi yo‘qligida uning nasiyasi va yuk savdosini egasini o‘zgartirmasdan yuritish.</div></div>${forms}<div class="partner-help"><div><b>Egasi o‘zgarmaydi</b><span>Yuk, savdo, foyda va nasiya asl sotuvchiga tegishli qoladi.</span></div><div><b>Kim bajardi saqlanadi</b><span>Har sherik amalida qaysi sotuvchi bajargani tarixda qoladi.</span></div><div><b>Pul alohida balansda</b><span>Qabul qilingan naqd pul egasiga topshirilmaguncha “qo‘lida” deb turadi.</span></div></div></section>
 <section class="panel"><div class="partner-section-head"><h2>Sherik pullari</h2><div class="muted">Kimning qo‘lida kimning puli turgani.</div></div><div class="partner-table"><table><tr><th>Pul kimda</th><th></th><th>Pul egasi</th><th>Qoldiq</th><th>Holat</th></tr>${balanceRows}</table></div></section>
 <section class="panel"><div class="partner-section-head"><h2>Sherik amallari tarixi</h2><div class="muted">Nasiya qaytimi, boshqa yukdan savdo va pul topshirishlar.</div></div><div class="partner-table"><table><tr><th>Sana</th><th>Amal</th><th>Egasi</th><th>Bajardi</th><th>Mijoz / Yuk</th><th>Summa</th><th>Pul holati</th></tr>${histRows}</table></div></section>
 <script>(()=>{const tabs=[...document.querySelectorAll('[data-partner-tab]')],panels=[...document.querySelectorAll('[data-partner-panel]')];tabs.forEach(b=>b.addEventListener('click',()=>{tabs.forEach(x=>x.classList.toggle('active',x===b));panels.forEach(x=>x.classList.toggle('active',x.dataset.partnerPanel===b.dataset.partnerTab))}));const f=document.querySelector('[data-partner-sale-form]');if(!f)return;const load=f.querySelector('[data-partner-load]'),mode=f.querySelector('[data-partner-mode]'),customer=f.querySelector('[data-partner-customer]'),cf=f.querySelector('[data-partner-customer-field]'),pf=f.querySelector('[data-partner-paid-field]');const sync=()=>{const credit=mode.value!=='cash',partial=mode.value==='partial',owner=load.options[load.selectedIndex]?.dataset.owner||'';cf.style.display=credit?'block':'none';pf.style.display=partial?'block':'none';customer.required=credit;[...customer.options].forEach((o,i)=>{if(i)o.hidden=!!owner&&o.dataset.owner!==owner});if(customer.selectedOptions[0]?.hidden)customer.value=''};load.addEventListener('change',sync);mode.addEventListener('change',sync);sync()})()</script>`;
 send(res,layout(u,'Sherik sotuvchi',body));return true;
}

export async function partnerAction(r,res,url,u){
 await ensurePartner();
 const p=url.pathname,b=await body(r);
 if(p==='/action/partner-payment'){
  const raw=String(b.target||''),[kind,idRaw]=raw.split(':'),id=+idRaw,requested=Math.max(0,n(b.amount));if(!requested||!id)return go(res,'/partners');
  let ownerId,customerId,saleId=null,remaining=0;
  if(kind==='old'){
   const C=(await Q(`SELECT c.*,GREATEST(c.opening_debt-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.customer_id=c.id AND p.sale_id IS NULL),0),0) remaining FROM customers c WHERE c.id=$1`,[id]))[0];
   if(!C||!ownerRule(u,C.seller_id))return go(res,'/partners');ownerId=+C.seller_id;customerId=+C.id;remaining=n(C.remaining);
  }else if(kind==='sale'){
   const S=(await Q(`SELECT s.*,GREATEST(s.debt_amount-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.sale_id=s.id),0),0) remaining FROM sales s WHERE s.id=$1`,[id]))[0];
   if(!S||!S.customer_id||!ownerRule(u,S.seller_id))return go(res,'/partners');ownerId=+S.seller_id;customerId=+S.customer_id;saleId=+S.id;remaining=n(S.remaining);
  }else return go(res,'/partners');
  const amount=Math.min(requested,remaining);if(amount<=0)return go(res,'/partners');
  const note=[`Sherik: ${actorName(u)} qabul qildi`,String(b.note||'').trim()].filter(Boolean).join(' · ');
  const P=(await Q(`INSERT INTO payments(seller_id,customer_id,sale_id,amount,note) VALUES($1,$2,$3,$4,$5) RETURNING id`,[ownerId,customerId,saleId,amount,note]))[0];
  const E=(await Q(`INSERT INTO partner_events(owner_seller_id,actor_user_id,event_type,customer_id,sale_id,payment_id,amount,cash_effect,payment_type,note) VALUES($1,$2,'debt_payment',$3,$4,$5,$6,$6,'cash',$7) RETURNING id`,[ownerId,u.id,customerId,saleId,P?.id||null,amount,String(b.note||'')]))[0];
  if(E)await audit(u,'partner_event',E.id,{}, {event_type:'debt_payment',owner_seller_id:ownerId,customer_id:customerId,sale_id:saleId,amount,cash_effect:amount});
  return go(res,'/partners');
 }
 if(p==='/action/partner-sale'){
  const L=(await Q(`SELECT * FROM loads WHERE id=$1`,[+b.loadId]))[0];if(!L||L.archived_at||!ownerRule(u,L.seller_id))return go(res,'/partners');
  const sold=n((await Q(`SELECT COALESCE(SUM(kg),0) s FROM sales WHERE load_id=$1`,[L.id]))[0]?.s),kg=n(b.kg);if(kg<=0||sold+kg>n(L.arrived_kg))return go(res,'/partners');
  const price=Math.max(0,n(b.price)),total=kg*price,mode=['cash','debt','partial'].includes(String(b.mode))?String(b.mode):'cash';let paid=mode==='cash'?total:mode==='partial'?Math.min(total,Math.max(0,n(b.paid))):0,debt=Math.max(0,total-paid),cid=null;
  if(mode!=='cash'){
   const C=(await Q(`SELECT * FROM customers WHERE id=$1`,[+b.customerId]))[0];if(!C||C.archived_at||+C.seller_id!==+L.seller_id)return go(res,'/partners');cid=C.id;
  }
  const S=(await Q(`INSERT INTO sales(seller_id,load_id,customer_id,kg,bags,price_per_kg,total,paid_amount,debt_amount) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id`,[L.seller_id,L.id,cid,kg,n(b.bags),price,total,paid,debt]))[0];
  const note=[`Sherik savdo: ${actorName(u)}`,String(b.note||'').trim()].filter(Boolean).join(' · ');
  const E=(await Q(`INSERT INTO partner_events(owner_seller_id,actor_user_id,event_type,customer_id,sale_id,load_id,amount,cash_effect,payment_type,note) VALUES($1,$2,'sale',$3,$4,$5,$6,$7,$8,$9) RETURNING id`,[L.seller_id,u.id,cid,S?.id||null,L.id,total,paid,paid>0?'cash':null,note]))[0];
  if(E)await audit(u,'partner_event',E.id,{}, {event_type:'sale',owner_seller_id:+L.seller_id,load_id:+L.id,sale_id:S?.id||null,total,paid,debt});
  return go(res,'/partners');
 }
 if(p==='/action/partner-settlement'){
  if(u.role==='manager')return go(res,'/partners');const ownerId=+b.ownerId;if(!ownerId||ownerId===+u.id)return go(res,'/partners');
  const available=n((await Q(`SELECT COALESCE(SUM(cash_effect),0) b FROM partner_events WHERE actor_user_id=$1 AND owner_seller_id=$2`,[u.id,ownerId]))[0]?.b),amount=Math.min(Math.max(0,n(b.amount)),available);if(amount<=0)return go(res,'/partners');
  const pt=['cash','card','bank'].includes(String(b.paymentType))?String(b.paymentType):'cash';
  const E=(await Q(`INSERT INTO partner_events(owner_seller_id,actor_user_id,event_type,amount,cash_effect,payment_type,note) VALUES($1,$2,'settlement',$3,$4,$5,$6) RETURNING id`,[ownerId,u.id,amount,-amount,pt,String(b.note||'')]))[0];
  if(E)await audit(u,'partner_event',E.id,{}, {event_type:'settlement',owner_seller_id:ownerId,amount,cash_effect:-amount,payment_type:pt});
  return go(res,'/partners');
 }
 return false;
}
