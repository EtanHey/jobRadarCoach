// Invoke through the fleet cap locally, or e2e/cap.sh in CI. No runner overrides.
import { spawn } from 'node:child_process';
import { rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { cleanEnv, cli, command, project, requireLocalDocker } from './local.mjs';
import { database } from './db.mjs';

// Supabase CLI v2.116.0: apps/cli-go/internal/utils/docker.go, CliProjectLabel.
const projectFilter = `label=com.supabase.cli.project=${project}`;
async function containers(deps, { all = false, names = false, signal } = {}) {
  const output = await deps.command('docker', [
    'ps', ...(all ? ['--all'] : []), '--filter', projectFilter,
    '--format', names ? '{{.Names}}' : '{{.ID}}',
  ], { signal });
  return output.trim().split(/\s+/).filter(Boolean);
}
async function disableRestart(deps, options) {
  const ids = await containers(deps, { ...options, all: true });
  if (ids.length) await deps.command('docker', ['update', '--restart=no', ...ids], options);
}
async function stopProject(deps, phase = 'teardown') {
  const errors = [];
  // Also protect partial starts and leftovers if stop fails or gets killed.
  try { await disableRestart(deps); } catch (error) { errors.push(error); }
  try { await deps.cli('stop', '--project-id', project); } catch (error) { errors.push(error); }
  try {
    const survivors = await containers(deps, { names: true });
    if (survivors.length) throw new Error(`DB e2e ${phase} left running containers: ${survivors.join(', ')}; stop with: JRC_LOCAL_DOCKER=1 supabase stop --project-id ${project} --workdir .e2e/db-stack`);
  } catch (error) { errors.push(error); }
  if (errors.length === 1) throw errors[0];
  if (errors.length) throw new AggregateError(errors, errors.map(error => error.message).join('; '));
}
async function run(args, { signal }) {
  const child = spawn(process.execPath, args, { env: { ...cleanEnv(), JRC_LOCAL_DOCKER: process.env.JRC_LOCAL_DOCKER }, signal, stdio: 'inherit' });
  const code = await new Promise((ok, fail) => {
    // AbortError can precede exit; wait for close before settling the work.
    let error;
    child.on('error', value => { error = value; });
    child.on('close', code => error ? fail(error) : ok(code));
  });
  if (code !== 0) throw new Error(`DB e2e child failed (${code ?? 'signal'})`);
}
export async function runSuite(deps = { database, run, rm, cli, command }) {
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
  let failed = false, pending;
  try {
    const work = async () => {
      if (local && (await containers(deps, { ...options, all: true })).length) await stopProject(deps, 'preflight');
      const databaseOptions = { ...options, ...(local ? { protect: () => disableRestart(deps, options) } : {}) };
      for (const step of [
        () => deps.database('up', databaseOptions),
        () => deps.database('seed', databaseOptions),
        () => deps.rm('.e2e/db-auth.json', { force: true }),
        () => deps.run(['e2e/db/start-app.mjs', 'build'], options),
        () => deps.run(['node_modules/@playwright/test/cli.js', 'test', '--config', 'e2e/db/playwright.config.ts'], options),
      ]) {
        controller.signal.throwIfAborted();
        await step();
      }
    };
    pending = work();
    await Promise.race([pending, interrupted]);
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    if (controller.signal.aborted && pending) {
      let timer;
      try {
        await Promise.race([
          pending.catch(() => {}),
          new Promise(resolve => { timer = setTimeout(resolve, 1500); }),
        ]);
      } finally { clearTimeout(timer); }
    }
    try {
      if (local) await stopProject(deps);
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
