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
