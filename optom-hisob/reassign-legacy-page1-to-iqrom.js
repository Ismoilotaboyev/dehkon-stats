import {db,Q,init} from './core.js';

const BATCH='notebook-2026-10-13-page-1';
await init();
const iqrom=(await Q(`SELECT id,name FROM users WHERE email='iqrom@optom.uz' LIMIT 1`))[0];
if(!iqrom)throw new Error('Iqrom user not found');

const client=await db.connect();
try{
  await client.query('BEGIN');
  await client.query(`SELECT pg_advisory_xact_lock(hashtext($1))`,[BATCH+':reassign-iqrom']);
  const rows=(await client.query(`SELECT id,customer_id,seller_id,amount,import_key FROM legacy_debts WHERE import_key LIKE $1 ORDER BY id`,[BATCH+'-%'])).rows;
  const customerIds=[...new Set(rows.map(r=>+r.customer_id))];
  if(!rows.length)throw new Error('Legacy import batch not found');
  const beforeSellerIds=[...new Set(rows.map(r=>+r.seller_id))];
  await client.query(`UPDATE legacy_debts SET seller_id=$1 WHERE import_key LIKE $2`,[iqrom.id,BATCH+'-%']);
  if(customerIds.length)await client.query(`UPDATE customers SET seller_id=$1 WHERE id=ANY($2::int[])`,[iqrom.id,customerIds]);
  await client.query('COMMIT');
  console.log(`LEGACY_REASSIGN done rows=${rows.length} customers=${customerIds.length} total=${rows.reduce((s,r)=>s+Number(r.amount||0),0)} to=${iqrom.name} before_sellers=${beforeSellerIds.join(',')}`);
}catch(err){
  try{await client.query('ROLLBACK')}catch{}
  throw err;
}finally{
  client.release();
  await db.end();
}
