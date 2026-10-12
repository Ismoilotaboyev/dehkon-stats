import {db,Q,n,e,money,body,send,go,audit} from './core.js';
import {listTools,recordMenu,actionForm} from './list-tools.js';

let ready;
export const ensureLegacyDebts=()=>ready||(ready=(async()=>{
 await Q(`CREATE TABLE IF NOT EXISTS legacy_debts(
  id SERIAL PRIMARY KEY,
  seller_id INT NOT NULL REFERENCES users(id),
  customer_id INT NOT NULL REFERENCES customers(id),
  amount NUMERIC NOT NULL DEFAULT 0,
  legacy_date DATE NOT NULL DEFAULT CURRENT_DATE,
  source TEXT,
  note TEXT,
  archived_at TIMESTAMPTZ,
  created_by INT REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT now()
 )`);
 await Q(`CREATE TABLE IF NOT EXISTS legacy_debt_attachments(
  id SERIAL PRIMARY KEY,
  legacy_debt_id INT UNIQUE NOT NULL REFERENCES legacy_debts(id) ON DELETE CASCADE,
  image_data BYTEA,
  image_mime TEXT,
  audio_data BYTEA,
  audio_mime TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
 )`);
 await Q(`CREATE INDEX IF NOT EXISTS legacy_debts_customer_idx ON legacy_debts(customer_id,legacy_date,id)`);
 await Q(`CREATE INDEX IF NOT EXISTS legacy_debts_seller_idx ON legacy_debts(seller_id,id DESC)`);
 await Q(`CREATE INDEX IF NOT EXISTS legacy_debts_archived_idx ON legacy_debts(archived_at,id DESC)`);
})());

const validImage=f=>f&&(/^image\//i.test(f.mime)||/\.(jpg|jpeg|png|webp|heic)$/i.test(f.filename));
const validAudio=f=>f&&(/^audio\//i.test(f.mime)||/\.(m4a|mp3|wav|aac|ogg|webm)$/i.test(f.filename));
const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tashkent',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const own=(u,row)=>row&&(u.role==='manager'||+row.seller_id===+u.id);
const snap=x=>({customer_id:+x.customer_id,seller_id:+x.seller_id,amount:n(x.amount),legacy_date:String(x.legacy_date||''),source:String(x.source||''),note:String(x.note||''),archived_at:x.archived_at||null});

async function legacyRows(u){
 await ensureLegacyDebts();
 const params=u.role==='manager'?[]:[u.id],where=u.role==='manager'?'':' WHERE ld.seller_id=$1';
 const rows=await Q(`SELECT ld.*,c.name customer_name,c.phone,c.place,c.opening_debt,u.name seller_name,cb.name created_by_name,
  (a.image_data IS NOT NULL) has_image,(a.audio_data IS NOT NULL) has_audio
  FROM legacy_debts ld
  JOIN customers c ON c.id=ld.customer_id
  JOIN users u ON u.id=ld.seller_id
  LEFT JOIN users cb ON cb.id=ld.created_by
  LEFT JOIN legacy_debt_attachments a ON a.legacy_debt_id=ld.id
  ${where}
  ORDER BY ld.legacy_date ASC,ld.id ASC`,params);
 if(!rows.length)return rows;
 const customerIds=[...new Set(rows.map(x=>+x.customer_id))];
 const paid=await Q(`SELECT customer_id,COALESCE(SUM(amount),0) amount FROM payments WHERE sale_id IS NULL AND customer_id=ANY($1::int[]) GROUP BY customer_id`,[customerIds]);
 const paidMap=new Map(paid.map(x=>[+x.customer_id,n(x.amount)]));
 const grouped=new Map();
 for(const r of rows){if(!grouped.has(+r.customer_id))grouped.set(+r.customer_id,[]);grouped.get(+r.customer_id).push(r)}
 for(const arr of grouped.values()){
  const totalLegacy=arr.reduce((s,x)=>s+n(x.amount),0);
  const baseOpening=Math.max(0,n(arr[0].opening_debt)-totalLegacy);
  let available=Math.max(0,(paidMap.get(+arr[0].customer_id)||0)-baseOpening);
  for(const r of arr){r.repaid=Math.min(n(r.amount),available);r.remaining=Math.max(0,n(r.amount)-r.repaid);available=Math.max(0,available-r.repaid)}
 }
 return rows.sort((a,b)=>String(b.legacy_date).localeCompare(String(a.legacy_date))||b.id-a.id);
}

export async function legacyDebtSection(u,d){
 const rows=await legacyRows(u),totalRemaining=rows.reduce((s,x)=>s+n(x.remaining),0),openCount=rows.filter(x=>n(x.remaining)>0).length;
 const customers=(d.C||[]).filter(x=>!x.archived_at);
 const options=customers.map(x=>`<option value="${x.id}">${e(x.name)}${u.role==='manager'?' · '+e(x.seller_name):''}${x.phone?' · '+e(x.phone):''}</option>`).join('');
 const form=`<details class="legacy-add"><summary>+ Eski nasiya</summary><form class="form legacy-form" method="post" action="/action/legacy-debt" enctype="multipart/form-data"><div class="legacy-note"><b>Eski daftar nasiyasi.</b> Yuk tanlanmaydi. Bu summa ombor, KG/qop, yuk foydasi va savdo statistikasiga kirmaydi — faqat mijoz qarziga qo‘shiladi.</div><div class="grid"><label class="field">Mijoz<select name="customerId" required><option value="">Mijozni tanlang</option>${options}</select></label><label class="field">Qarz olingan sana<input name="legacyDate" type="date" value="${today()}" required></label><label class="field">Eski nasiya summasi<input name="amount" type="number" min="1" step="1" inputmode="numeric" required></label><label class="field">Mahsulot / manba<input name="source" placeholder="Masalan: Piyoz · Eski daftar"></label><label class="field">Izoh<input name="note" placeholder="Ixtiyoriy izoh"></label><label class="field">🖼 Daftar rasmi <span class="muted">(ixtiyoriy)</span><input name="image" type="file" accept="image/*" capture="environment"></label><label class="field">🎙 Ovoz <span class="muted">(ixtiyoriy)</span><input name="audio" type="file" accept="audio/*"></label></div><button class="btn green" style="margin-top:12px">Eski nasiyani saqlash</button></form></details>`;
 const media=x=>`${x.has_image?`<a class="btn soft legacy-small" target="_blank" href="/legacy-debt-attachment/${x.id}/image">🖼 Rasm</a>`:''}${x.has_audio?`<audio controls preload="none" src="/legacy-debt-attachment/${x.id}/audio"></audio>`:''}${!x.has_image&&!x.has_audio?'<span class="muted">—</span>':''}`;
 const desktop=rows.map(x=>{const archived=!!x.archived_at,search=e([x.customer_name,x.phone,x.place,x.seller_name,x.source,x.note,x.legacy_date,x.amount,x.remaining].join(' ')),items=[`<a href="/debts/customer/${x.customer_id}">Mijozni ko‘rish</a>`,actionForm(archived?'/action/unarchive-legacy-debt':'/action/archive-legacy-debt',x.id,archived?'Arxivdan chiqarish':'Arxivlash','archive-action','/debts')];return `<tr data-list-item data-list-status="${archived?'archive':'active'}" data-list-search="${search}"><td>${e(String(x.legacy_date).slice(0,10))}</td><td><a class="link" href="/debts/customer/${x.customer_id}"><b>${e(x.customer_name)}</b></a><div class="muted">${e(x.phone||'')} ${x.place?'· '+e(x.place):''}</div></td>${u.role==='manager'?`<td>${e(x.seller_name)}</td>`:''}<td><span class="legacy-badge">Eski daftar</span><div class="muted legacy-source">${e(x.source||'Yukka bog‘lanmagan')}</div></td><td><b>${money(x.amount)}</b></td><td>${money(x.repaid)}</td><td class="legacy-remain"><b>${money(x.remaining)}</b></td><td>${media(x)}</td><td>${archived?'<span class="archive-badge">Arxiv</span>':n(x.remaining)>0?'Ochiq':'Yopilgan'}</td><td>${recordMenu(items)}</td></tr>`}).join('');
 const mobile=rows.map(x=>{const archived=!!x.archived_at,search=e([x.customer_name,x.phone,x.place,x.seller_name,x.source,x.note,x.legacy_date,x.amount,x.remaining].join(' ')),items=[actionForm(archived?'/action/unarchive-legacy-debt':'/action/archive-legacy-debt',x.id,archived?'Arxivdan chiqarish':'Arxivlash','archive-action','/debts')];return `<article class="legacy-card" data-list-item data-list-status="${archived?'archive':'active'}" data-list-search="${search}"><div class="legacy-card-top"><span>${e(String(x.legacy_date).slice(0,10))}</span><span class="${archived?'archive-badge':'legacy-badge'}">${archived?'Arxiv':'Eski daftar'}</span></div><a class="legacy-name" href="/debts/customer/${x.customer_id}">${e(x.customer_name)}</a><div class="legacy-sub">${e(x.source||'Yukka bog‘lanmagan')}${u.role==='manager'?' · '+e(x.seller_name):''}</div><div class="legacy-stats"><div><span>Jami nasiya</span><b>${money(x.amount)}</b></div><div><span>Qaytargan</span><b>${money(x.repaid)}</b></div></div><div class="legacy-remaining"><span>Qoldiq</span><b>${money(x.remaining)}</b></div>${(x.has_image||x.has_audio)?`<div class="legacy-media">${media(x)}</div>`:''}<div class="legacy-actions"><a class="btn green" href="/debts/customer/${x.customer_id}">Ko‘rish</a>${recordMenu(items)}</div></article>`}).join('');
 const css=`<style>
 .legacy-panel{margin-bottom:12px}.legacy-add>summary{padding:14px 16px;font-weight:900;color:var(--green);cursor:pointer}.legacy-note{grid-column:1/-1;background:#fff7e5;border:1px solid #ead8ac;color:#795700;border-radius:11px;padding:10px 11px;font-size:11px;line-height:1.45;margin-bottom:10px}.legacy-form input[type=file]{background:#f4fbf6;border:1px dashed #a9cbb5}.legacy-titlebar{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:14px 16px 8px}.legacy-titlebar h2{margin:0;font-size:17px}.legacy-titlebar .muted{font-size:10px}.legacy-badge{display:inline-flex;background:#fff4df;color:#8a6200;border-radius:999px;padding:5px 8px;font-size:9px;font-weight:900}.legacy-source{margin-top:4px}.legacy-remain{color:#8a5200}.legacy-small{min-height:32px!important;padding:6px 8px!important;font-size:10px!important}.legacy-desktop audio,.legacy-card audio{width:150px;height:32px;vertical-align:middle}.legacy-mobile{display:none}.legacy-mini-summary{display:flex;gap:7px;flex-wrap:wrap;padding:0 14px 10px}.legacy-mini-summary span{background:#f5f7f4;border-radius:999px;padding:6px 9px;font-size:10px;color:var(--muted);font-weight:800}.legacy-mini-summary b{color:var(--text)}
 @media(max-width:760px){.legacy-panel{background:transparent;border:0;box-shadow:none;overflow:visible}.legacy-panel>.legacy-add{background:#fff;border:1px solid var(--line);border-radius:14px;margin-bottom:10px;overflow:hidden}.legacy-form{padding-left:12px!important;padding-right:12px!important}.legacy-titlebar{background:#fff;border:1px solid var(--line);border-radius:14px 14px 0 0;padding:12px}.legacy-mini-summary{background:#fff;border-left:1px solid var(--line);border-right:1px solid var(--line);padding:0 12px 10px}.legacy-desktop{display:none!important}.legacy-mobile{display:grid;gap:9px;padding:10px;background:#fff;border:1px solid var(--line);border-top:0;border-radius:0 0 14px 14px}.legacy-card{border:1px solid var(--line);border-radius:13px;padding:12px}.legacy-card-top{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:10px;color:var(--muted);font-weight:800}.legacy-name{display:block;font-size:16px;font-weight:900;margin-top:7px}.legacy-sub{font-size:10px;color:var(--muted);margin-top:3px}.legacy-stats{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:10px}.legacy-stats>div,.legacy-remaining{background:#f6f9f6;border-radius:9px;padding:8px}.legacy-stats span,.legacy-remaining span{display:block;font-size:8px;color:var(--muted);font-weight:800}.legacy-stats b,.legacy-remaining b{display:block;font-size:11px;margin-top:3px}.legacy-remaining{margin-top:7px;background:#fff7e8}.legacy-remaining b{color:#8a5200;font-size:14px}.legacy-media{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:8px}.legacy-actions{display:grid;grid-template-columns:1fr auto;gap:7px;margin-top:9px}.legacy-actions .btn{min-height:44px}}
 </style>`;
 const html=`${css}<section class="panel legacy-panel">${form}<div data-list-scope><div class="legacy-titlebar"><div><h2>Eski daftar nasiyalari</h2><div class="muted">Yukka bog‘lanmagan eski qarzlar</div></div></div><div class="legacy-mini-summary"><span>Qolgan eski nasiya: <b>${money(totalRemaining)}</b></span><span>Ochiq yozuv: <b>${openCount} ta</b></span></div>${listTools('Mijoz, sana, summa yoki manba bo‘yicha qidirish...')}<div class="legacy-desktop table"><table><tr><th>Sana</th><th>Mijoz</th>${u.role==='manager'?'<th>Savdogar</th>':''}<th>Manba</th><th>Jami</th><th>Qaytargan</th><th>Qoldiq</th><th>Rasm / Ovoz</th><th>Holat</th><th>Amal</th></tr>${desktop||`<tr><td colspan="10">Eski nasiya yo‘q</td></tr>`}</table></div><div class="legacy-mobile">${mobile||'<div class="legacy-card">Eski nasiya yo‘q</div>'}</div><div class="list-empty" data-list-empty>Eski nasiya topilmadi</div></div></section>`;
 return{html,totalRemaining,openCount,count:rows.length};
}

export async function legacyDebtAction(r,res,url,u){
 await ensureLegacyDebts();const p=url.pathname,b=await body(r),back=String(b.returnTo||'/debts').startsWith('/')?String(b.returnTo||'/debts'):'/debts';
 if(p==='/action/legacy-debt'){
  const C=(await Q(`SELECT * FROM customers WHERE id=$1`,[+b.customerId]))[0];if(!own(u,C)||C.archived_at)return go(res,'/debts');const amount=Math.max(0,n(b.amount));if(amount<=0)return go(res,'/debts');const legacyDate=/^\d{4}-\d{2}-\d{2}$/.test(String(b.legacyDate||''))?String(b.legacyDate):today(),source=String(b.source||'').trim(),note=String(b.note||'').trim(),files=b.__files||{},image=validImage(files.image)?files.image:null,audio=validAudio(files.audio)?files.audio:null;
  const client=await db.connect();let L;try{await client.query('BEGIN');L=(await client.query(`INSERT INTO legacy_debts(seller_id,customer_id,amount,legacy_date,source,note,created_by) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *`,[C.seller_id,C.id,amount,legacyDate,source,note,u.id])).rows[0];if(image||audio)await client.query(`INSERT INTO legacy_debt_attachments(legacy_debt_id,image_data,image_mime,audio_data,audio_mime) VALUES($1,$2,$3,$4,$5)`,[L.id,image?.data||null,image?.mime||null,audio?.data||null,audio?.mime||null]);await client.query(`UPDATE customers SET opening_debt=COALESCE(opening_debt,0)+$1 WHERE id=$2`,[amount,C.id]);await client.query('COMMIT')}catch(err){await client.query('ROLLBACK');throw err}finally{client.release()}if(L)await audit(u,'legacy_debt',L.id,{},snap(L));return go(res,'/debts')
 }
 const L=(await Q(`SELECT * FROM legacy_debts WHERE id=$1`,[+b.id]))[0];if(!own(u,L))return go(res,back);
 if(p==='/action/archive-legacy-debt'||p==='/action/unarchive-legacy-debt'){const before=snap(L),at=p==='/action/archive-legacy-debt'?new Date().toISOString():null;await Q(`UPDATE legacy_debts SET archived_at=$1 WHERE id=$2`,[at,L.id]);await audit(u,'legacy_debt',L.id,before,{...before,archived_at:at});return go(res,back)}
 return go(res,back);
}

export async function legacyDebtAttachment(r,res,u,id,kind,sendAttachment){
 await ensureLegacyDebts();const A=(await Q(`SELECT ld.seller_id,a.image_data,a.image_mime,a.audio_data,a.audio_mime FROM legacy_debts ld LEFT JOIN legacy_debt_attachments a ON a.legacy_debt_id=ld.id WHERE ld.id=$1`,[+id]))[0];if(!A||!own(u,A)){send(res,'Topilmadi',404);return true}const data=kind==='image'?A.image_data:A.audio_data,mime=kind==='image'?A.image_mime:A.audio_mime;if(!data){send(res,'Fayl yo‘q',404);return true}sendAttachment(r,res,data,mime,kind);return true;
}
