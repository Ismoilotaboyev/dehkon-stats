import {Q} from './core.js';

export async function ensureLegacyDebts(){
 await Q(`CREATE TABLE IF NOT EXISTS legacy_debts(id SERIAL PRIMARY KEY)`);
}
