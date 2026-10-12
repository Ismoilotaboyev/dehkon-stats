import {runLegacyPage2IqromImport,runLegacyPage3IqromImport} from './migrations-legacy.js';
import {ensurePartnerSellers} from './migrations-partner-sellers.js';
await runLegacyPage2IqromImport();
await runLegacyPage3IqromImport();
await ensurePartnerSellers();
await import('./server.js');
