// Invoke through the fleet cap locally, or e2e/cap.sh in CI. No runner overrides.
import { spawn } from 'node:child_process';
import { rm } from 'node:fs/promises';
import { cleanEnv } from './local.mjs';
import { database } from './db.mjs';
await database('up');
await database('seed');
await rm('.e2e/db-auth.json', { force: true });
const child = spawn(process.execPath, ['node_modules/@playwright/test/cli.js', 'test', '--config', 'e2e/db/playwright.config.ts'], { env: cleanEnv(), stdio: 'inherit' });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('exit', code => process.exit(code ?? 1));
