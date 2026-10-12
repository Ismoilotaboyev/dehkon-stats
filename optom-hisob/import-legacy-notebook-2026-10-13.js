import {db,Q,init} from './core.js';

const BATCH='notebook-2026-10-13-page-1';
const rows=[
 ['Muzaffar G‘ozovot',343000],
 ['Sayyora Yangi bozor',300000],
 ['Karomat Sori',327000],
 ['Sanjar xona',3277000],
 ['Xolira Beruniy',2558000],
 ['N. III ulgonoy',876000],
 ['Rajabboy Abror',637000],
 ['Sonajon Zoybu',624000],
 ['Zuxra Toir s/t',970000],
 ['Darmonjon Zair',220000],
 ['Ro‘ya ona Zoybu',228000],
 ['Sayyora Zoybu',280000],
 ['Hikmat darital',1785000],
 ['Gulbahor optom',225000]
];

const norm=s=>String(s||'').normalize('NFKC').toLowerCase().replace(/[’‘ʻʼ`´]/g,"'").replace(/[.,]/g,'').replace(/\s+/g,' ').trim();

await init();
await Q(`CREATE TABLE IF NOT EXISTS legacy_debts(
 id SERIAL PRIMARY KEY,
 seller_id INT NOT NULL REFERENCES users(id),
 customer_id INT NOT NULL REFERENCES customers(id),
 amount NUMERIC NOT NULL DEFAULT 0,
 legacy_date DATE,
 source TEXT,
 note TEXT,
 archived_at TIMESTAMPTZ,
 created_by INT REFERENCES users(id),
 created_at TIMESTAMPTZ DEFAULT now()
)`);
await Q(`ALTER TABLE legacy_debts ALTER COLUMN legacy_date DROP NOT NULL`);
await Q(`ALTER TABLE legacy_debts ADD COLUMN IF NOT EXISTS import_key TEXT`);
await Q(`CREATE UNIQUE INDEX IF NOT EXISTS legacy_debts_import_key_uidx ON legacy_debts(import_key) WHERE import_key IS NOT NULL`);

const manager=(await Q(`SELECT id,name FROM users WHERE role='manager' ORDER BY id LIMIT 1`))[0];
if(!manager)throw new Error('Manager user not found');

const client=await db.connect();
try{
 await client.query('BEGIN');
 await client.query(`SELECT pg_advisory_xact_lock(hashtext($1))`,[BATCH]);
 const existingKeys=(await client.query(`SELECT import_key FROM legacy_debts WHERE import_key LIKE $1`,[BATCH+'-%'])).rows;
 if(existingKeys.length===rows.length){
  console.log(`LEGACY_IMPORT already_done rows=${existingKeys.length}`);
  await client.query('COMMIT');
 }else{
  const customers=(await client.query(`SELECT id,name,seller_id,archived_at FROM customers ORDER BY archived_at NULLS FIRST,id`)).rows;
  let created=0,matched=0,inserted=0,total=0;
  for(let i=0;i<rows.length;i++){
   const [name,amount]=rows[i],key=`${BATCH}-${String(i+1).padStart(2,'0')}`;
   const has=(await client.query(`SELECT id FROM legacy_debts WHERE import_key=$1`,[key])).rows[0];
   if(has){console.log(`LEGACY_IMPORT skip key=${key}`);continue}
   const hits=customers.filter(c=>norm(c.name)===norm(name));
   let C=hits[0];
   if(C){matched++;console.log(`LEGACY_IMPORT matched name=${name} customer_id=${C.id}`)}
   else{
    C=(await client.query(`INSERT INTO customers(seller_id,name,phone,place,opening_debt) VALUES($1,$2,'','',0) RETURNING id,name,seller_id,archived_at`,[manager.id,name])).rows[0];
    customers.push(C);created++;console.log(`LEGACY_IMPORT created name=${name} customer_id=${C.id}`)
   }
   const L=(await client.query(`INSERT INTO legacy_debts(seller_id,customer_id,amount,legacy_date,source,note,created_by,import_key) VALUES($1,$2,$3,NULL,$4,$5,$6,$7) RETURNING id`,[C.seller_id,C.id,amount,'Eski daftar','Daftardan import qilingan · sana yo‘q',manager.id,key])).rows[0];
   await client.query(`UPDATE customers SET opening_debt=COALESCE(opening_debt,0)+$1 WHERE id=$2`,[amount,C.id]);
   inserted++;total+=amount;
   console.log(`LEGACY_IMPORT inserted id=${L.id} name=${name} amount=${amount}`)
  }
  await client.query('COMMIT');
  console.log(`LEGACY_IMPORT done inserted=${inserted} created=${created} matched=${matched} total=${total}`)
 }
}catch(err){
 try{await client.query('ROLLBACK')}catch{}
 throw err;
}finally{
 client.release();
 await db.end();
}
