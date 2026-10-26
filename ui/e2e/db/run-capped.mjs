// Invoke through the fleet cap locally, or e2e/cap.sh in CI. No runner overrides.
import { spawn } from 'node:child_process';
import { rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { cleanEnv, cli, project, requireLocalDocker } from './local.mjs';
import { database } from './db.mjs';
async function run(args) {
  const child = spawn(process.execPath, args, { env: cleanEnv(), stdio: 'inherit' });
  const stop = signal => child.kill(signal);
  const interrupt = () => stop('SIGINT'), terminate = () => stop('SIGTERM');
  process.on('SIGINT', interrupt); process.on('SIGTERM', terminate);
  try {
    const code = await new Promise((ok, fail) => { child.on('error', fail); child.on('exit', ok); });
    if (code !== 0) throw new Error(`DB e2e child failed (${code ?? 'signal'})`);
  } finally {
    process.off('SIGINT', interrupt); process.off('SIGTERM', terminate);
  }
}
export async function runSuite(deps = { database, run, rm, cli }) {
  requireLocalDocker();
  const local = process.env.CI !== 'true';
  try {
    await deps.database('up');
    await deps.database('seed');
    await deps.rm('.e2e/db-auth.json', { force: true });
    await deps.run(['e2e/db/start-app.mjs', 'build']);
    await deps.run(['node_modules/@playwright/test/cli.js', 'test', '--config', 'e2e/db/playwright.config.ts']);
  } finally {
    if (local) await deps.cli('stop', '--project-id', project);
  }
}
if (import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try { await runSuite(); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
