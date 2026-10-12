import {runLegacyPage2IqromImport,runLegacyPage3IqromImport} from './migrations-legacy.js';
await runLegacyPage2IqromImport();
await runLegacyPage3IqromImport();
await import('./server.js');
