import {runLegacyPage2IqromImport} from './migrations-legacy.js';
await runLegacyPage2IqromImport();
await import('./server.js');
