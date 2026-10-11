import http from 'node:http';
import crypto from 'node:crypto';
import {AP,SP,PORT,Q,body,cookies,send,go,init,user} from './core.js';
import {login} from './ui.js';
import {mainPages} from './pages-main.js';
import {otherPages} from './pages-other.js';
import {actions} from './actions.js';

await init();

const sellerPassword=email=>({
 'iqrom@optom.uz':process.env.IQROM_PASSWORD,
 'palvannazar@optom.uz':process.env.PALVANNAZAR_PASSWORD,
 'rufat@optom.uz':process.env.RUFAT_PASSWORD,
 'asror@optom.uz':process.env.ASROR_PASSWORD
}[email]||SP);

const server=http.createServer(async(r,res)=>{try{
 const url=new URL(r.url||'/',`http://${r.headers.host||'localhost'}`);
 if(url.pathname==='/api/health')return send(res,JSON.stringify({ok:true,version:'individual-seller-passwords-v1'}),200,{'content-type':'application/json'});
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
 if(r.method==='POST'&&url.pathname.startsWith('/action/'))return actions(r,res,url,U);
 if(r.method==='GET'){
   if(await mainPages(res,url,U))return;
   if(await otherPages(res,url,U))return;
 }
 return go(res,'/');
}catch(err){console.error(err);return send(res,'<h1>Xatolik</h1><p>Server xatosi yuz berdi.</p>',500)}});
server.listen(PORT,'0.0.0.0',()=>console.log('Optom Hisob listening on',PORT));
