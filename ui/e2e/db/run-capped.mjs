// Invoke through the fleet cap locally, or e2e/cap.sh in CI. No runner overrides.
import { spawn } from 'node:child_process';
import { rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { cleanEnv, cli, project, requireLocalDocker } from './local.mjs';
import { database } from './db.mjs';
async function run(args, { signal }) {
  const child = spawn(process.execPath, args, { env: { ...cleanEnv(), JRC_LOCAL_DOCKER: process.env.JRC_LOCAL_DOCKER }, signal, stdio: 'inherit' });
  const code = await new Promise((ok, fail) => { child.on('error', fail); child.on('exit', ok); });
  if (code !== 0) throw new Error(`DB e2e child failed (${code ?? 'signal'})`);
}
export async function runSuite(deps = { database, run, rm, cli }) {
  requireLocalDocker();
  const local = process.env.CI !== 'true';
  const controller = new AbortController();
  const options = { signal: controller.signal };
  let interrupt, terminate;
  const interrupted = new Promise((_, reject) => {
    const stop = signal => {
      const error = new Error(`DB e2e interrupted by ${signal}`);
      reject(error);
      controller.abort(error); // Node forwards cancellation to active spawned children.
    };
    interrupt = () => stop('SIGINT'); terminate = () => stop('SIGTERM');
    process.on('SIGINT', interrupt); process.on('SIGTERM', terminate);
  });
  let failed = false;
  try {
    const work = async () => {
      for (const step of [
        () => deps.database('up', options), () => deps.database('seed', options),
        () => deps.rm('.e2e/db-auth.json', { force: true }),
        () => deps.run(['e2e/db/start-app.mjs', 'build'], options),
        () => deps.run(['node_modules/@playwright/test/cli.js', 'test', '--config', 'e2e/db/playwright.config.ts'], options),
      ]) {
        controller.signal.throwIfAborted();
        await step();
      }
    };
    await Promise.race([work(), interrupted]);
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    try {
      if (local) await deps.cli('stop', '--project-id', project);
    } catch (error) {
      console.error(error.stack ?? error.message);
      if (!failed) throw error;
    } finally {
      process.off('SIGINT', interrupt); process.off('SIGTERM', terminate);
    }
  }
}
if (import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try { await runSuite(); }
  catch (error) { console.error(error.stack ?? error.message); process.exitCode = 1; }
}
