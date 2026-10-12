import {db} from './core.js';

export async function runLegacyPage1IqromMigration(){
 const key='legacy-page1-owner-iqrom-v1';
 const client=await db.connect();
 try{
  await client.query('BEGIN');
  await client.query(`CREATE TABLE IF NOT EXISTS app_migrations(key TEXT PRIMARY KEY,applied_at TIMESTAMPTZ DEFAULT now(),note TEXT)`);
  const done=(await client.query(`SELECT 1 FROM app_migrations WHERE key=$1`,[key])).rows[0];
  if(done){await client.query('COMMIT');return}
  const iqrom=(await client.query(`SELECT id,name FROM users WHERE email='iqrom@optom.uz' LIMIT 1`)).rows[0];
  if(!iqrom)throw new Error('Iqrom user not found');
  const batch='notebook-2026-10-13-page-1';
  const rows=(await client.query(`SELECT id,customer_id,amount FROM legacy_debts WHERE import_key LIKE $1 ORDER BY id`,[batch+'-%'])).rows;
  if(rows.length!==14)throw new Error(`Expected 14 legacy rows, found ${rows.length}`);
  const customerIds=[...new Set(rows.map(r=>+r.customer_id))];
  await client.query(`UPDATE legacy_debts SET seller_id=$1 WHERE import_key LIKE $2`,[iqrom.id,batch+'-%']);
  await client.query(`UPDATE customers SET seller_id=$1 WHERE id=ANY($2::int[])`,[iqrom.id,customerIds]);
  const total=rows.reduce((s,r)=>s+Number(r.amount||0),0);
  await client.query(`INSERT INTO app_migrations(key,note) VALUES($1,$2)`,[key,`14 legacy notebook debts reassigned to ${iqrom.name}; total=${total}`]);
  await client.query('COMMIT');
  console.log(`LEGACY_REASSIGN done rows=${rows.length} customers=${customerIds.length} total=${total} to=${iqrom.name}`);
 }catch(err){
  try{await client.query('ROLLBACK')}catch{}
  throw err;
 }finally{client.release()}
}

const norm=s=>String(s||'').normalize('NFKC').toLowerCase().replace(/[’‘ʻʼ`´]/g,"'").replace(/[.,]/g,'').replace(/\s+/g,' ').trim();

export async function runLegacyPage2IqromImport(){
 const migrationKey='legacy-page2-iqrom-import-v1';
 const batch='notebook-2026-10-13-page-2';
 const rows=[
  ['Malohat Pavilyon',1372000],
  ['Gulnoza Pavilyon',802000],
  ['Manzura Darmon',7800000],
  ['Zokir Xiva',1195000],
  ['Matluba Pavilyon',1560000],
  ['Sonajon G‘oybu',807000],
  ['Nazokat Roza Pavilyon',630000],
  ['Ro‘zigul Pavilyon',462000],
  ['Otomurot Shovot',4800000],
  ['Rano oy Pavilyon',858000],
  ['Shohrux Xiva',3283000],
  ['Dilmurod Xiva Gazel',576000],
  ['Klora Xonqa',14650000],
  ['Otonazar Qo‘shko‘pir',528000],
  ['Vahhob Beruniy',11916000],
  ['Dilfuza Shovot',504000],
  ['Roza Zumrat',122000]
 ];
 const client=await db.connect();
 try{
  await client.query('BEGIN');
  await client.query(`CREATE TABLE IF NOT EXISTS app_migrations(key TEXT PRIMARY KEY,applied_at TIMESTAMPTZ DEFAULT now(),note TEXT)`);
  const done=(await client.query(`SELECT 1 FROM app_migrations WHERE key=$1`,[migrationKey])).rows[0];
  if(done){await client.query('COMMIT');return}
  await client.query(`ALTER TABLE legacy_debts ADD COLUMN IF NOT EXISTS import_key TEXT`);
  await client.query(`CREATE UNIQUE INDEX IF NOT EXISTS legacy_debts_import_key_uidx ON legacy_debts(import_key) WHERE import_key IS NOT NULL`);
  const iqrom=(await client.query(`SELECT id,name FROM users WHERE email='iqrom@optom.uz' LIMIT 1`)).rows[0];
  if(!iqrom)throw new Error('Iqrom user not found');

  const oldSonajon=(await client.query(`SELECT customer_id FROM legacy_debts WHERE import_key='notebook-2026-10-13-page-1-08' LIMIT 1`)).rows[0];
  if(oldSonajon){
   await client.query(`UPDATE customers SET name=$1,seller_id=$2,archived_at=NULL,debt_archived_at=NULL WHERE id=$3`,['Sonajon G‘oybu',iqrom.id,+oldSonajon.customer_id]);
   await client.query(`UPDATE legacy_debts SET seller_id=$1 WHERE customer_id=$2`,[iqrom.id,+oldSonajon.customer_id]);
  }

  const customers=(await client.query(`SELECT id,name,seller_id,archived_at FROM customers WHERE seller_id=$1 ORDER BY archived_at NULLS FIRST,id`,[iqrom.id])).rows;
  let created=0,matched=0,inserted=0,total=0;
  for(let i=0;i<rows.length;i++){
   const [name,amount]=rows[i],importKey=`${batch}-${String(i+1).padStart(2,'0')}`;
   const has=(await client.query(`SELECT id FROM legacy_debts WHERE import_key=$1`,[importKey])).rows[0];
   if(has)continue;
   let C=customers.find(c=>norm(c.name)===norm(name));
   if(C){
    matched++;
    await client.query(`UPDATE customers SET archived_at=NULL,debt_archived_at=NULL WHERE id=$1`,[C.id]);
   }else{
    C=(await client.query(`INSERT INTO customers(seller_id,name,phone,place,opening_debt) VALUES($1,$2,'','',0) RETURNING id,name,seller_id,archived_at`,[iqrom.id,name])).rows[0];
    customers.push(C);created++;
   }
   await client.query(`INSERT INTO legacy_debts(seller_id,customer_id,amount,legacy_date,source,note,created_by,import_key) VALUES($1,$2,$3,NULL,$4,$5,$6,$7)`,[iqrom.id,C.id,amount,'Eski daftar','Daftardan import qilingan · sana yo‘q',iqrom.id,importKey]);
   await client.query(`UPDATE customers SET opening_debt=COALESCE(opening_debt,0)+$1 WHERE id=$2`,[amount,C.id]);
   inserted++;total+=amount;
  }
  const finalRows=(await client.query(`SELECT amount FROM legacy_debts WHERE import_key LIKE $1`,[batch+'-%'])).rows;
  const finalTotal=finalRows.reduce((s,r)=>s+Number(r.amount||0),0);
  if(finalRows.length!==17||finalTotal!==51865000)throw new Error(`Legacy page2 verification failed rows=${finalRows.length} total=${finalTotal}`);
  await client.query(`INSERT INTO app_migrations(key,note) VALUES($1,$2)`,[migrationKey,`17 legacy notebook debts imported for ${iqrom.name}; total=${finalTotal}; created=${created}; matched=${matched}`]);
  await client.query('COMMIT');
  console.log(`LEGACY_PAGE2_IMPORT done inserted=${inserted} created=${created} matched=${matched} total=${finalTotal} seller=${iqrom.name}`);
 }catch(err){
  try{await client.query('ROLLBACK')}catch{}
  throw err;
 }finally{client.release()}
}

export async function runLegacyPage3IqromImport(){
 const migrationKey='legacy-page3-iqrom-import-v1';
 const batch='notebook-2026-10-13-page-3';
 const rows=[
  {name:'Alisher Shovot',amount:1000000,aliases:[]},
  {name:'Murod og‘a',amount:970000,aliases:["Murod og'a"]},
  {name:'Darmonjon Gashir',amount:1076000,aliases:['Darmonjon gashr','Darmonjon Gashir']},
  {name:'Asror Yangiarik',amount:990000,aliases:['Asror Yangiarik','Asror Yangiariq']},
  {name:'Karomat Sori',amount:263000,aliases:[]},
  {name:'Aziza Razzoq Xonqa',amount:2683000,aliases:[]}
 ];
 const client=await db.connect();
 try{
  await client.query('BEGIN');
  await client.query(`CREATE TABLE IF NOT EXISTS app_migrations(key TEXT PRIMARY KEY,applied_at TIMESTAMPTZ DEFAULT now(),note TEXT)`);
  const done=(await client.query(`SELECT 1 FROM app_migrations WHERE key=$1`,[migrationKey])).rows[0];
  if(done){await client.query('COMMIT');return}
  await client.query(`ALTER TABLE legacy_debts ADD COLUMN IF NOT EXISTS import_key TEXT`);
  await client.query(`CREATE UNIQUE INDEX IF NOT EXISTS legacy_debts_import_key_uidx ON legacy_debts(import_key) WHERE import_key IS NOT NULL`);
  const iqrom=(await client.query(`SELECT id,name FROM users WHERE email='iqrom@optom.uz' LIMIT 1`)).rows[0];
  if(!iqrom)throw new Error('Iqrom user not found');
  const customers=(await client.query(`SELECT id,name,seller_id,archived_at FROM customers WHERE seller_id=$1 ORDER BY archived_at NULLS FIRST,id`,[iqrom.id])).rows;
  let created=0,matched=0,inserted=0;
  for(let i=0;i<rows.length;i++){
   const r=rows[i],importKey=`${batch}-${String(i+1).padStart(2,'0')}`;
   const has=(await client.query(`SELECT id FROM legacy_debts WHERE import_key=$1`,[importKey])).rows[0];
   if(has)continue;
   const names=[r.name,...r.aliases].map(norm);
   let C=customers.find(c=>names.includes(norm(c.name)));
   if(C){
    matched++;
    if(r.name==='Darmonjon Gashir'&&norm(C.name)!==norm(r.name)){
     await client.query(`UPDATE customers SET name=$1 WHERE id=$2`,[r.name,C.id]);
     C.name=r.name;
    }
    await client.query(`UPDATE customers SET archived_at=NULL,debt_archived_at=NULL WHERE id=$1`,[C.id]);
   }else{
    C=(await client.query(`INSERT INTO customers(seller_id,name,phone,place,opening_debt) VALUES($1,$2,'','',0) RETURNING id,name,seller_id,archived_at`,[iqrom.id,r.name])).rows[0];
    customers.push(C);created++;
   }
   await client.query(`INSERT INTO legacy_debts(seller_id,customer_id,amount,legacy_date,source,note,created_by,import_key) VALUES($1,$2,$3,NULL,$4,$5,$6,$7)`,[iqrom.id,C.id,r.amount,'Eski daftar','Daftardan import qilingan · sana yo‘q',iqrom.id,importKey]);
   await client.query(`UPDATE customers SET opening_debt=COALESCE(opening_debt,0)+$1 WHERE id=$2`,[r.amount,C.id]);
   inserted++;
  }
  const finalRows=(await client.query(`SELECT amount FROM legacy_debts WHERE import_key LIKE $1`,[batch+'-%'])).rows;
  const finalTotal=finalRows.reduce((s,r)=>s+Number(r.amount||0),0);
  if(finalRows.length!==6||finalTotal!==6982000)throw new Error(`Legacy page3 verification failed rows=${finalRows.length} total=${finalTotal}`);
  await client.query(`INSERT INTO app_migrations(key,note) VALUES($1,$2)`,[migrationKey,`6 legacy notebook debts imported for ${iqrom.name}; total=${finalTotal}; created=${created}; matched=${matched}`]);
  await client.query('COMMIT');
  console.log(`LEGACY_PAGE3_IMPORT done inserted=${inserted} created=${created} matched=${matched} total=${finalTotal} seller=${iqrom.name}`);
 }catch(err){
  try{await client.query('ROLLBACK')}catch{}
  throw err;
 }finally{client.release()}
}
