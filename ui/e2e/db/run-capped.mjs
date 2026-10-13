// Invoke through the fleet cap locally, or e2e/cap.sh in CI. No runner overrides.
import { spawn } from 'node:child_process';
import { rm } from 'node:fs/promises';
import { cleanEnv } from './local.mjs';
import { database } from './db.mjs';
await database('up');
await database('seed');
await rm('.e2e/db-auth.json', { force: true });
async function run(args) {
  const child = spawn(process.execPath, args, { env: cleanEnv(), stdio: 'inherit' });
  const stop = signal => child.kill(signal);
  const interrupt = () => stop('SIGINT'), terminate = () => stop('SIGTERM');
  process.on('SIGINT', interrupt); process.on('SIGTERM', terminate);
  const code = await new Promise((ok, fail) => { child.on('error', fail); child.on('exit', ok); });
  process.off('SIGINT', interrupt); process.off('SIGTERM', terminate);
  if (code !== 0) process.exit(code ?? 1);
}
await run(['e2e/db/start-app.mjs', 'build']);
await run(['node_modules/@playwright/test/cli.js', 'test', '--config', 'e2e/db/playwright.config.ts']);
