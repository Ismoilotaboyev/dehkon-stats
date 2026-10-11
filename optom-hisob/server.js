import http from 'node:http';
import crypto from 'node:crypto';
import {AP,SP,PORT,Q,body,cookies,send,go,init,user} from './core.js';
import {login} from './ui.js';
import {loadsPage} from './pages-loads.js';
import {debtsPage} from './pages-debts.js';
import {dashboardPage} from './pages-dashboard.js';
import {mainPages} from './pages-main.js';
import {debtCustomerPage} from './pages-debt-profile.js';
import {salesCustomersPage} from './pages-sales-customers.js';
import {expensesPage} from './pages-expenses.js';
import {otherPages} from './pages-other.js';
import {actions} from './actions.js';
import {I18N_SNIPPET} from './i18n-client.js';
import {WORDING_SNIPPET} from './wording-client.js';
import {VOICE_RECORDER_SNIPPET} from './voice-recorder-client.js';
import {DEBT_RECONCILE_SNIPPET} from './debt-reconcile-client.js';
import {CUSTOMER_SEARCH_BRIDGE_SNIPPET} from './customer-search-bridge-client.js';
import {LOAD_ARCHIVE_SNIPPET} from './load-archive-client.js';

await init();

const sellerPassword=email=>({
 'iqrom@optom.uz':process.env.IQROM_PASSWORD,
 'palvannazar@optom.uz':process.env.PALVANNAZAR_PASSWORD,
 'rufat@optom.uz':process.env.RUFAT_PASSWORD,
 'asror@optom.uz':process.env.ASROR_PASSWORD
}[email]||SP);

function sendAttachment(r,res,data,mime,kind){
 const buf=Buffer.isBuffer(data)?data:Buffer.from(data);
 const size=buf.length;
 const common={
  'content-type':mime||'application/octet-stream',
  'content-disposition':'inline',
  'cache-control':'private, max-age=604800',
  'x-content-type-options':'nosniff'
 };
 if(kind!=='audio'){
  res.writeHead(200,{...common,'content-length':size});
  return r.method==='HEAD'?res.end():res.end(buf);
 }
 const range=String(r.headers.range||'');
 const base={...common,'accept-ranges':'bytes'};
 if(!range){
  res.writeHead(200,{...base,'content-length':size});
  return r.method==='HEAD'?res.end():res.end(buf);
 }
 const m=range.match(/^bytes=(\d*)-(\d*)$/);
 if(!m){res.writeHead(416,{...base,'content-range':`bytes */${size}`});return res.end()}
 let start=m[1]?Number(m[1]):NaN,end=m[2]?Number(m[2]):NaN;
 if(Number.isNaN(start)){
  const suffix=end;
  if(!Number.isFinite(suffix)||suffix<=0){res.writeHead(416,{...base,'content-range':`bytes */${size}`});return res.end()}
  start=Math.max(0,size-suffix);end=size-1;
 }else{
  if(Number.isNaN(end)||end>=size)end=size-1;
 }
 if(start<0||end<start||start>=size){res.writeHead(416,{...base,'content-range':`bytes */${size}`});return res.end()}
 const chunk=buf.subarray(start,end+1);
 res.writeHead(206,{...base,'content-range':`bytes ${start}-${end}/${size}`,'content-length':chunk.length});
 return r.method==='HEAD'?res.end():res.end(chunk);
}

const server=http.createServer(async(r,res)=>{try{
 res.setHeader('cache-control','no-store, no-cache, must-revalidate');
 res.setHeader('pragma','no-cache');
 res.setHeader('expires','0');
 const rawEnd=res.end.bind(res);
 res.end=(chunk,...args)=>{
  if(typeof chunk==='string'&&chunk.includes('</body>')){
   let extra='';
   if(!chunk.includes('optom_hisob_lang'))extra+=`${I18N_SNIPPET}${WORDING_SNIPPET}${VOICE_RECORDER_SNIPPET}${DEBT_RECONCILE_SNIPPET}${CUSTOMER_SEARCH_BRIDGE_SNIPPET}`;
   if(!chunk.includes('data-load-finish-control'))extra+=LOAD_ARCHIVE_SNIPPET;
   if(extra)chunk=chunk.replace('</body>',`${extra}</body>`);
  }
  return rawEnd(chunk,...args)
 };
 const url=new URL(r.url||'/',`http://${r.headers.host||'localhost'}`);
 if(url.pathname==='/api/health')return send(res,JSON.stringify({ok:true,version:'dashboard-v1'}),200,{'content-type':'application/json'});
 if(r.method==='POST'&&url.pathname==='/login'){
   const b=await body(r),email=String(b.email||'').trim().toLowerCase();
   const U=(await Q(`SELECT id,name,email,role FROM users WHERE email=$1`,[email]))[0];
   const expected=U?.role==='manager'?AP:sellerPassword(email);
   if(!U||!expected||String(b.password||'')!==expected)return go(res,'/?error=1');
   const t=crypto.randomUUID()+crypto.randomUUID();
   await Q(`INSERT INTO sessions(token,user_id,expires_at) VALUES($1,$2,now()+interval '7 days')`,[t,U.id]);
   return go(res,'/',{'set-cookie':`session=${encodeURIComponent(t)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=604800`});
 }
 if(r.method==='POST'&&url.pathname==='/logout'){
   const t=cookies(r).session;if(t)await Q(`DELETE FROM sessions WHERE token=$1`,[t]);
   return go(res,'/',{'set-cookie':'session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0'});
 }
 const U=await user(r);
 if(!U){if(r.method==='GET'&&url.pathname==='/')return send(res,login(url.searchParams.get('error')==='1'));return go(res,'/')}
 let lm=url.pathname.match(/^\/api\/load\/(\d+)\/status$/);
 if(r.method==='GET'&&lm){
  const L=(await Q(`SELECT id,seller_id,archived_at FROM loads WHERE id=$1`,[+lm[1]]))[0];
  if(!L||(U.role!=='manager'&&L.seller_id!==U.id))return send(res,JSON.stringify({ok:false}),404,{'content-type':'application/json'});
  return send(res,JSON.stringify({ok:true,archived:!!L.archived_at,archived_at:L.archived_at||null}),200,{'content-type':'application/json'});
 }
 let am=url.pathname.match(/^\/attachment\/(\d+)\/(image|audio)$/);
 if((r.method==='GET'||r.method==='HEAD')&&am){
  let saleId=+am[1],kind=am[2],A=(await Q(`SELECT s.seller_id,a.image_data,a.image_mime,a.audio_data,a.audio_mime FROM sales s LEFT JOIN sale_attachments a ON a.sale_id=s.id WHERE s.id=$1`,[saleId]))[0];
  if(!A||(U.role!=='manager'&&A.seller_id!==U.id))return send(res,'Topilmadi',404);
  let data=kind==='image'?A.image_data:A.audio_data,mime=kind==='image'?A.image_mime:A.audio_mime;
  if(!data)return send(res,'Fayl yo‘q',404);
  return sendAttachment(r,res,data,mime,kind);
 }
 if(r.method==='POST'&&url.pathname.startsWith('/action/'))return actions(r,res,url,U);
 if(r.method==='GET'){
   if(await loadsPage(res,url,U))return;
   if(await debtsPage(res,url,U))return;
   if(await dashboardPage(res,url,U))return;
   if(await mainPages(res,url,U))return;
   if(await debtCustomerPage(res,url,U))return;
   if(await salesCustomersPage(res,url,U))return;
   if(await expensesPage(res,url,U))return;
   if(await otherPages(res,url,U))return;
 }
 return go(res,'/');
}catch(err){console.error(err);return send(res,'<h1>Xatolik</h1><p>Server xatosi yuz berdi.</p>',500)}});
server.listen(PORT,'0.0.0.0',()=>console.log('Optom Hisob listening on',PORT));
