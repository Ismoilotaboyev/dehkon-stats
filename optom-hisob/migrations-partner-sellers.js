import {Q} from './core.js';

export async function ensurePartnerSellers(){
  await Q(`UPDATE users SET name='Palvannazar Direktor' WHERE email='palvannazar@optom.uz'`);
  await Q(`INSERT INTO users(name,email,password_hash,role)
    VALUES('Quvondiq','quvondiq@optom.uz','-','seller')
    ON CONFLICT(email) DO UPDATE SET name=EXCLUDED.name,role='seller'`);
}
