import {Pool} from 'pg';
import Busboy from 'busboy';
export const db=new Pool({connectionString:process.env.DATABASE_URL});
export const AP=process.env.ADMIN_PASSWORD||'',SP=process.env.SELLER_PASSWORD||'',PORT=+process.env.PORT||8080;
export const n=v=>+v||0,e=v=>String(v??'').replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m])),money=v=>new Intl.NumberFormat('uz-UZ').format(n(v))+' so‘m',qty=v=>new Intl.NumberFormat('uz-UZ').format(n(v)),dt=v=>new Date(v).toLocaleDateString('uz-UZ');
export const Q=async(t,p=[])=>(await db.query(t,p)).rows;
export const body=r=>new Promise((resolve,reject)=>{
 const ct=String(r.headers['content-type']||'');
 if(!ct.toLowerCase().startsWith('multipart/form-data')){
  let s='';r.on('data',d=>s+=d);r.on('end',()=>resolve(Object.fromEntries(new URLSearchParams(s))));r.on('error',reject);return;
 }
 let out={},files={},pending=0,finished=false;
 const done=()=>{if(finished&&pending===0)resolve({...out,__files:files})};
 try{
  const bb=Busboy({headers:r.headers,limits:{files:2,fileSize:12*1024*1024,fields:40}});
  bb.on('field',(name,val)=>out[name]=val);
  bb.on('file',(name,file,info)=>{pending++;let chunks=[],truncated=false;file.on('limit',()=>truncated=true);file.on('data',d=>chunks.push(d));file.on('end',()=>{if(!truncated&&chunks.length)files[name]={data:Buffer.concat(chunks),mime:String(info.mimeType||''),filename:String(info.filename||'')};pending--;done()})});
  bb.on('error',reject);bb.on('finish',()=>{finished=true;done()});r.pipe(bb);
 }catch(err){reject(err)}
});
export const cookies=r=>Object.fromEntries(String(r.headers.cookie||'').split(';').map(x=>x.trim()).filter(Boolean).map(x=>{let i=x.indexOf('=');return[x.slice(0,i),decodeURIComponent(x.slice(i+1))]}));
export const send=(r,b,c=200,h={})=>{r.writeHead(c,{'content-type':'text/html;charset=utf-8',...h});r.end(b)};
export const go=(r,to,h={})=>{r.writeHead(303,{location:to,...h});r.end()};
export async function init(){
 await Q(`CREATE TABLE IF NOT EXISTS users(id SERIAL PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL,created_at TIMESTAMPTZ DEFAULT now())`);
 await Q(`CREATE TABLE IF NOT EXISTS loads(id SERIAL PRIMARY KEY,seller_id INT NOT NULL REFERENCES users(id),name TEXT NOT NULL,product TEXT NOT NULL,arrived_kg NUMERIC DEFAULT 0,arrived_bags NUMERIC DEFAULT 0,purchase_amount NUMERIC DEFAULT 0,profit_mode TEXT NOT NULL DEFAULT 'own',commission_per_kg NUMERIC DEFAULT 0,created_at TIMESTAMPTZ DEFAULT now())`);
 await Q(`ALTER TABLE loads ADD COLUMN IF NOT EXISTS profit_mode TEXT NOT NULL DEFAULT 'own'`);
 await Q(`ALTER TABLE loads ADD COLUMN IF NOT EXISTS commission_per_kg NUMERIC DEFAULT 0`);
 await Q(`CREATE TABLE IF NOT EXISTS customers(id SERIAL PRIMARY KEY,seller_id INT NOT NULL REFERENCES users(id),name TEXT NOT NULL,phone TEXT,place TEXT,opening_debt NUMERIC DEFAULT 0,created_at TIMESTAMPTZ DEFAULT now())`);
 await Q(`CREATE TABLE IF NOT EXISTS sales(id SERIAL PRIMARY KEY,seller_id INT NOT NULL REFERENCES users(id),load_id INT NOT NULL REFERENCES loads(id),customer_id INT REFERENCES customers(id),kg NUMERIC DEFAULT 0,bags NUMERIC DEFAULT 0,price_per_kg NUMERIC DEFAULT 0,total NUMERIC DEFAULT 0,debt_amount NUMERIC DEFAULT 0,created_at TIMESTAMPTZ DEFAULT now())`);
 await Q(`CREATE TABLE IF NOT EXISTS sale_attachments(id SERIAL PRIMARY KEY,sale_id INT UNIQUE NOT NULL REFERENCES sales(id) ON DELETE CASCADE,image_data BYTEA,image_mime TEXT,audio_data BYTEA,audio_mime TEXT,created_at TIMESTAMPTZ DEFAULT now())`);
 await Q(`CREATE TABLE IF NOT EXISTS payments(id SERIAL PRIMARY KEY,seller_id INT NOT NULL REFERENCES users(id),customer_id INT NOT NULL REFERENCES customers(id),amount NUMERIC DEFAULT 0,note TEXT,created_at TIMESTAMPTZ DEFAULT now())`);
 await Q(`CREATE TABLE IF NOT EXISTS expenses(id SERIAL PRIMARY KEY,seller_id INT NOT NULL REFERENCES users(id),load_id INT REFERENCES loads(id),name TEXT NOT NULL,amount NUMERIC DEFAULT 0,note TEXT,created_at TIMESTAMPTZ DEFAULT now())`);
 await Q(`CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,expires_at TIMESTAMPTZ NOT NULL,created_at TIMESTAMPTZ DEFAULT now())`);
 for(const x of [['Boshqaruvchi','manager@optom.uz','manager'],['Iqrom Mashariov','iqrom@optom.uz','seller'],['Palvannazar','palvannazar@optom.uz','seller'],['Rufat','rufat@optom.uz','seller'],['Asror','asror@optom.uz','seller']]) await Q(`INSERT INTO users(name,email,password_hash,role) VALUES($1,$2,'-',$3) ON CONFLICT(email) DO NOTHING`,x);
}
export async function user(r){let t=cookies(r).session;if(!t)return null;return (await Q(`SELECT u.id,u.name,u.email,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=$1 AND s.expires_at>now()`,[t]))[0]||null}
export const sellers=()=>Q(`SELECT id,name FROM users WHERE role='seller' ORDER BY name`);
export async function data(u){let p=u.role==='manager'?[]:[u.id],w=u.role==='manager'?'':' WHERE l.seller_id=$1',s=u.role==='manager'?'':' WHERE s.seller_id=$1',c=u.role==='manager'?'':' WHERE c.seller_id=$1',x=u.role==='manager'?'':' WHERE e.seller_id=$1';let L=await Q(`SELECT l.*,u.name seller_name,COALESCE((SELECT SUM(s.kg) FROM sales s WHERE s.load_id=l.id),0) sold_kg,l.arrived_kg-COALESCE((SELECT SUM(s.kg) FROM sales s WHERE s.load_id=l.id),0) stock_kg FROM loads l JOIN users u ON u.id=l.seller_id${w} ORDER BY l.id DESC`,p),S=await Q(`SELECT s.*,u.name seller_name,c.name customer_name,l.name load_name,(a.image_data IS NOT NULL) has_image,(a.audio_data IS NOT NULL) has_audio FROM sales s JOIN users u ON u.id=s.seller_id LEFT JOIN customers c ON c.id=s.customer_id JOIN loads l ON l.id=s.load_id LEFT JOIN sale_attachments a ON a.sale_id=s.id${s} ORDER BY s.id DESC`,p),C=await Q(`SELECT c.*,u.name seller_name,GREATEST(c.opening_debt+COALESCE((SELECT SUM(s.debt_amount) FROM sales s WHERE s.customer_id=c.id),0)-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.customer_id=c.id),0),0) debt FROM customers c JOIN users u ON u.id=c.seller_id${c} ORDER BY debt DESC`,p),E=await Q(`SELECT e.*,u.name seller_name,l.name load_name FROM expenses e JOIN users u ON u.id=e.seller_id LEFT JOIN loads l ON l.id=e.load_id${x} ORDER BY e.id DESC`,p);return{L,S,C,E}}
