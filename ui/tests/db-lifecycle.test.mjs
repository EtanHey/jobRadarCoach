import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runSuite } from '../e2e/db/run-capped.mjs';

// A container table, never a real Docker/Supabase process. Also used by the cap child.
function fakeStack({ stale = false, fail = '', signal = '', hang = false, stop = '' } = {}) {
  const project = 'jrc-p12-test-db';
  const label = `com.supabase.cli.project=${project}`;
  const events = [];
  const containers = [{ id: 'unrelated', project: 'other', running: true, restart: 'always' }];
  const ours = () => containers.filter(c => c.project === project);
  const add = () => containers.push(...['db', 'auth'].map(id => ({ id, project, running: id === 'db', restart: 'unless-stopped' })));
  if (stale) add();
  const deps = {
    database: async (action, options) => {
      events.push(action);
      if (action === 'up') {
        assert.equal(ours().some(c => c.running), false, 'stale stack must stop before up');
        if (!ours().length) add();
        for (const c of ours()) c.running = c.id === 'db';
        if (fail !== 'up') await options.afterStart?.();
      }
      if (action === fail) throw new Error(`failed ${action}`);
    },
    command: async (exe, args) => {
      assert.equal(exe, 'docker');
      events.push(args.join(' '));
      if (args[0] === 'ps') {
        assert.ok(args.includes(`label=${label}`), 'exact Supabase project label required');
        const selected = ours().filter(c => args.includes('--all') || c.running);
        return selected.map(c => args.includes('{{.Names}}') ? `supabase_${c.id}_${project}` : c.id).join('\n');
      }
      assert.deepEqual(args.slice(0, 2), ['update', '--restart=no']);
      if (fail === 'update') throw new Error('failed update');
      for (const id of args.slice(2)) {
        const c = ours().find(c => c.id === id);
        assert.ok(c, 'must not update other projects');
        c.restart = 'no';
      }
      return '';
    },
    cli: async (...args) => {
      assert.deepEqual(args, ['stop', '--project-id', project]);
      events.push('stop');
      if (stop !== 'survivor') for (const c of ours()) c.running = false;
      if (stop === 'error') throw new Error('stop failed');
    },
    rm: async () => {},
    run: async args => {
      const step = args.includes('build') ? 'build' : 'test';
      events.push(step);
      if (step === fail) throw new Error(`failed ${step}`);
      if (step === 'test' && signal) queueMicrotask(() => process.emit(signal));
      if (step === 'test' && (signal || hang)) await new Promise(() => {});
    },
  };
  return { deps, containers, events };
}

function localTest(name, fn) {
  test(name, { timeout: 15000 }, async t => {
    t.mock.method(console, 'error', () => {});
    const saved = { CI: process.env.CI, JRC_LOCAL_DOCKER: process.env.JRC_LOCAL_DOCKER };
    process.env.CI = 'false'; process.env.JRC_LOCAL_DOCKER = '1';
    try { await fn(t); }
    finally {
      for (const [key, value] of Object.entries(saved)) {
        if (value === undefined) delete process.env[key]; else process.env[key] = value;
      }
    }
  });
}

function stopped(stack) {
  assert.ok(stack.containers.filter(c => c.project === 'jrc-p12-test-db').every(c => !c.running && c.restart === 'no'));
  assert.deepEqual(stack.containers[0], { id: 'unrelated', project: 'other', running: true, restart: 'always' });
}

for (const fail of ['', 'up', 'seed', 'build', 'test', 'update']) {
  localTest(`local ${fail || 'success'} leaves project containers stopped${fail === 'update' ? ' and refuses seed' : ' and not restartable'}`, async () => {
    const stack = fakeStack({ fail });
    if (fail) await assert.rejects(runSuite(stack.deps), new RegExp(`failed ${fail}`));
    else await runSuite(stack.deps);
    if (fail === 'update') {
      assert.ok(stack.containers.filter(c => c.project === 'jrc-p12-test-db').every(c => !c.running));
      assert.ok(!stack.events.includes('seed'));
    } else stopped(stack);
    if (!fail || ['seed', 'build', 'test'].includes(fail)) {
      assert.match(stack.events[stack.events.indexOf('up') + 2], /^update --restart=no db auth$/);
      assert.ok(stack.events.indexOf('seed') > stack.events.findIndex(e => e.startsWith('update')));
    }
  });
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  localTest(`${signal} stops the project and removes signal handlers`, async () => {
    const before = [process.listenerCount('SIGINT'), process.listenerCount('SIGTERM')];
    const stack = fakeStack({ signal });
    await assert.rejects(runSuite(stack.deps), new RegExp(signal));
    stopped(stack);
    assert.deepEqual([process.listenerCount('SIGINT'), process.listenerCount('SIGTERM')], before);
  });
}

localTest('a stale stack is stopped and verified before a new start', async () => {
  const stack = fakeStack({ stale: true });
  await runSuite(stack.deps);
  stopped(stack);
  assert.ok(stack.events.indexOf('stop') < stack.events.indexOf('up'));
  assert.equal(stack.events.filter(e => e === 'stop').length, 2);
});

for (const stale of [false, true]) {
  localTest(`${stale ? 'preflight' : 'teardown'} rejects a lying stop and names survivors`, async () => {
    const stack = fakeStack({ stale, stop: 'survivor' });
    await assert.rejects(runSuite(stack.deps), /supabase_db_jrc-p12-test-db/);
    assert.ok(stack.containers.filter(c => c.project === 'jrc-p12-test-db').every(c => c.restart === 'no'));
    if (stale) assert.ok(!stack.events.includes('up'));
  });
}

localTest('a failed stop rejects even when no container survives', async () => {
  const stack = fakeStack({ stop: 'error' });
  await assert.rejects(runSuite(stack.deps), /stop failed/);
  stopped(stack);
  assert.match(stack.events.at(-1), /^ps /, 'verify even when stop throws');
});

localTest('CI keeps lifecycle ownership in the workflow', async () => {
  process.env.CI = 'true';
  const calls = [];
  await runSuite({
    database: async action => { calls.push(action); },
    run: async () => {}, rm: async () => {},
    command: async () => { throw new Error('CI must not add Docker lifecycle calls'); },
    cli: async () => { throw new Error('CI stop belongs to workflow'); },
  });
  assert.deepEqual(calls, ['up', 'seed']);
});

async function fakeCommands(t) {
  const dir = await mkdtemp(join(tmpdir(), 'jrc-db-commands-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const cwd = join(dir, 'ui');
  for (const path of ['ui/e2e/db', 'ui/.e2e/db-stack/supabase', 'supabase/migrations', 'bin']) {
    await mkdir(join(dir, path), { recursive: true });
  }
  for (const path of ['e2e/db/config.toml', '.e2e/db-stack/supabase/cert.pem', '.e2e/db-stack/supabase/key.pem']) {
    await writeFile(join(cwd, path), 'synthetic');
  }
  const log = join(dir, 'commands.jsonl');
  for (const name of ['docker', 'supabase']) await writeFile(join(dir, 'bin', name), `#!${process.execPath}
    const fs = require('node:fs');
    const args = process.argv.slice(2);
    fs.appendFileSync(${JSON.stringify(log)}, JSON.stringify([${JSON.stringify(name)}, ...args]) + '\\n');
    if (${JSON.stringify(name)} === 'docker' && args[0] === 'ps') console.log('supabase_db_jrc-p12-test-db');
    if (args[0] === 'status') console.log(JSON.stringify({
      API_URL: 'https://127.0.0.1:55431', MAILPIT_URL: 'http://127.0.0.1:55434',
      DB_URL: 'postgresql://127.0.0.1:55432/postgres', ANON_KEY: 'fake', SERVICE_ROLE_KEY: 'fake'
    }));
  `, { mode: 0o700 });
  const env = { ...process.env, PATH: `${join(dir, 'bin')}:${process.env.PATH}` };
  return { cwd, env, log };
}

async function childResult(executable, args, options) {
  const child = spawn(executable, args, { ...options, timeout: 10000, stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => { output += chunk; });
  const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
  return { code, output };
}

localTest('real database up calls restart hook between CLI start and status (fake executable)', async t => {
  const fake = await fakeCommands(t);
  const result = await childResult(process.execPath, ['--input-type=module', '-e', `
    import { appendFileSync } from 'node:fs';
    import { database } from ${JSON.stringify(new URL('../e2e/db/db.mjs', import.meta.url).href)};
    await database('up', { afterStart: () => appendFileSync(${JSON.stringify(fake.log)}, '["after-start"]\\n') });
  `, 'fake-driver'], fake);
  assert.equal(result.code, 0, result.output);
  const events = (await readFile(fake.log, 'utf8')).trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(events.map(e => e[0] === 'supabase' ? e[1] : e[0]), ['start', 'after-start', 'status']);
});

localTest('real runner exits nonzero naming stale survivors (fake executables)', async t => {
  const fake = await fakeCommands(t);
  const result = await childResult(process.execPath, [new URL('../e2e/db/run-capped.mjs', import.meta.url).pathname], fake);
  assert.equal(result.code, 1, result.output);
  assert.match(result.output, /teardown left running containers: supabase_db_jrc-p12-test-db/);
  const commands = (await readFile(fake.log, 'utf8')).trim().split('\n').map(line => JSON.parse(line));
  assert.ok(commands.some(args => args[0] === 'supabase' && args[1] === 'stop'));
  assert.ok(!commands.some(args => args.includes('--no-backup') || args.includes('start')));
});

localTest('portable cap sends TERM and exits 137 after verified fake teardown', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'jrc-db-cap-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const receipt = join(dir, 'receipt.json');
  const driver = join(dir, 'suite.mjs');
  await writeFile(driver, `
    import assert from 'node:assert/strict';
    import { writeFileSync } from 'node:fs';
    import { runSuite } from ${JSON.stringify(new URL('../e2e/db/run-capped.mjs', import.meta.url).href)};
    ${fakeStack.toString()}
    const stack = fakeStack({ hang: true });
    const keepAlive = setInterval(() => {}, 100);
    try { await runSuite(stack.deps); }
    catch (error) { process.exitCode = 1; }
    finally { clearInterval(keepAlive); writeFileSync(${JSON.stringify(receipt)}, JSON.stringify(stack)); }
  `);
  const child = spawn('sh', [new URL('../e2e/cap.sh', import.meta.url).pathname, driver, '999999', '0'], {
    env: { ...process.env }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(() => { if (child.exitCode === null) child.kill('SIGTERM'); });
  let output = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => { output += chunk; });
  const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('exit', resolve); });
  assert.equal(code, 137, output);
  assert.match(output, /CAP-KILL/);
  stopped(JSON.parse(await readFile(receipt, 'utf8')));
});
