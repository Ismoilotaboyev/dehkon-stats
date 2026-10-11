import http from 'node:http';
import crypto from 'node:crypto';
import {AP,SP,PORT,Q,body,cookies,send,go,init,user} from './core.js';
import {login} from './ui.js';
import {loadsPage} from './pages-loads.js';
import {mainPages} from './pages-main.js';
import {debtCustomerPage} from './pages-debt-profile.js';
import {otherPages} from './pages-other.js';
import {actions} from './actions.js';
import {I18N_SNIPPET} from './i18n-client.js';

await init();

const sellerPassword=email=>({
 'iqrom@optom.uz':process.env.IQROM_PASSWORD,
 'palvannazar@optom.uz':process.env.PALVANNAZAR_PASSWORD,
 'rufat@optom.uz':process.env.RUFAT_PASSWORD,
 'asror@optom.uz':process.env.ASROR_PASSWORD
}[email]||SP);

const server=http.createServer(async(r,res)=>{try{
 const rawEnd=res.end.bind(res);
 res.end=(chunk,...args)=>{if(typeof chunk==='string'&&chunk.includes('</body>')&&!chunk.includes('optom_hisob_lang'))chunk=chunk.replace('</body>',`${I18N_SNIPPET}</body>`);return rawEnd(chunk,...args)};
 const url=new URL(r.url||'/',`http://${r.headers.host||'localhost'}`);
 if(url.pathname==='/api/health')return send(res,JSON.stringify({ok:true,version:'i18n-v1'}),200,{'content-type':'application/json'});
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
 let am=url.pathname.match(/^\/attachment\/(\d+)\/(image|audio)$/);
 if(r.method==='GET'&&am){let saleId=+am[1],kind=am[2],A=(await Q(`SELECT s.seller_id,a.image_data,a.image_mime,a.audio_data,a.audio_mime FROM sales s LEFT JOIN sale_attachments a ON a.sale_id=s.id WHERE s.id=$1`,[saleId]))[0];if(!A||(U.role!=='manager'&&A.seller_id!==U.id))return send(res,'Topilmadi',404);let data=kind==='image'?A.image_data:A.audio_data,mime=kind==='image'?A.image_mime:A.audio_mime;if(!data)return send(res,'Fayl yo‘q',404);res.writeHead(200,{'content-type':mime||'application/octet-stream','content-disposition':'inline','cache-control':'private, max-age=604800'});return res.end(data)}
 if(r.method==='POST'&&url.pathname.startsWith('/action/'))return actions(r,res,url,U);
 if(r.method==='GET'){
   if(await loadsPage(res,url,U))return;
   if(await mainPages(res,url,U))return;
   if(await debtCustomerPage(res,url,U))return;
   if(await otherPages(res,url,U))return;
 }
 return go(res,'/');
}catch(err){console.error(err);return send(res,'<h1>Xatolik</h1><p>Server xatosi yuz berdi.</p>',500)}});
server.listen(PORT,'0.0.0.0',()=>console.log('Optom Hisob listening on',PORT));
