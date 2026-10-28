import assert from 'node:assert/strict';
import { test } from 'node:test';
import { command } from '../e2e/db/local.mjs';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runSuite } from '../e2e/db/run-capped.mjs';

import { fakeStack } from './fixtures/db-fake-stack.mjs';

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
    await assert.rejects(runSuite(stack.deps), error => {
      assert.match(error.message, new RegExp(`DB e2e ${stale ? 'preflight' : 'teardown'} left running containers`));
      assert.ok(error.message.endsWith('stop with: JRC_LOCAL_DOCKER=1 supabase stop --project-id jrc-p12-test-db --workdir .'));
      return true;
    });
    assert.ok(stack.containers.filter(c => c.project === 'jrc-p12-test-db').every(c => c.restart === 'no'));
    if (stale) assert.ok(!stack.events.includes('up'));
  });
}

localTest('preflight protects stopped leftovers before starting', async () => {
  const stack = fakeStack({ stale: 'stopped' });
  await runSuite(stack.deps);
  assert.ok(stack.events.indexOf('stop') < stack.events.indexOf('up'));
  assert.match(stack.events[0], /^ps --all /);
  stopped(stack);
});

for (const action of ['up', 'seed']) {
  localTest(`signal waits for the aborted ${action} before teardown scans`, async () => {
    const stack = fakeStack();
    const database = stack.deps.database;
    let exited = false;
    stack.deps.database = async (step, options) => {
      if (step !== action) return database(step, options);
      await new Promise(resolve => {
        options.signal.addEventListener('abort', () => setTimeout(() => {
          stack.containers.push({ id: 'late', project: 'jrc-p12-test-db', running: true, restart: 'unless-stopped' });
          exited = true;
          resolve();
        }, 30), { once: true });
        queueMicrotask(() => process.emit('SIGTERM'));
      });
    };
    await assert.rejects(runSuite(stack.deps), /SIGTERM/);
    assert.equal(exited, true, 'aborted work must settle before teardown');
    stopped(stack);
  });
}

localTest('a hung aborted child cannot block teardown beyond 1.5 seconds', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const stack = fakeStack();
  stack.deps.database = async () => {
    queueMicrotask(() => process.emit('SIGTERM'));
    await new Promise(() => {});
  };
  const result = assert.rejects(runSuite(stack.deps), /SIGTERM/);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(!stack.events.includes('stop'));
  t.mock.timers.tick(1499);
  await Promise.resolve();
  assert.ok(!stack.events.includes('stop'));
  t.mock.timers.tick(1);
  await result;
  assert.ok(stack.events.includes('stop'));
});

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

localTest('aborted command settles only after its child exits', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'jrc-db-abort-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const exited = join(dir, 'exited');
  const started = new Promise(resolve => process.once('SIGWINCH', resolve));
  const controller = new AbortController();
  const pending = command(process.execPath, ['--input-type=module', '-e', `
    import { writeFileSync } from 'node:fs';
    process.on('SIGTERM', () => setTimeout(() => {
      writeFileSync(${JSON.stringify(exited)}, 'exited'); process.exit(0);
    }, 50));
    process.kill(process.ppid, 'SIGWINCH');
    setTimeout(() => process.exit(0), 1000);
    setInterval(() => {}, 100);
  `], { signal: controller.signal });
  const rejected = assert.rejects(pending, { name: 'AbortError' });
  await started;
  controller.abort();
  await rejected;
  assert.equal(await readFile(exited, 'utf8'), 'exited');
});

async function fakeCommands(t, { fresh = false } = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'jrc-db-commands-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const cwd = join(dir, 'ui');
  for (const path of ['ui/e2e/db', ...(!fresh ? ['ui/.e2e/db-stack/supabase'] : []), 'supabase/migrations', 'bin']) {
    await mkdir(join(dir, path), { recursive: true });
  }
  for (const path of ['e2e/db/config.toml', ...(!fresh ? ['.e2e/db-stack/supabase/cert.pem', '.e2e/db-stack/supabase/key.pem'] : [])]) {
    await writeFile(join(cwd, path), 'synthetic');
  }
  const log = join(dir, 'commands.jsonl');
  for (const name of ['docker', 'supabase']) await writeFile(join(dir, 'bin', name), `#!${process.execPath}
    const fs = require('node:fs');
    const args = process.argv.slice(2);
    fs.appendFileSync(${JSON.stringify(log)}, JSON.stringify([${JSON.stringify(name)}, ...args]) + '\\n');
    if (${JSON.stringify(name)} === 'supabase') {
      const index = args.indexOf('--workdir');
      const workdir = index < 0 ? process.cwd() : args[index + 1];
      if (!fs.statSync(workdir).isDirectory()) throw new Error('workdir must be a directory');
    }
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

localTest('fresh checkout stops leftover containers in preflight and teardown without stack config', async t => {
  const fake = await fakeCommands(t, { fresh: true });
  const result = await childResult(process.execPath, ['--input-type=module', '-e', `
    import assert from 'node:assert/strict';
    import { existsSync } from 'node:fs';
    import { cli, root } from ${JSON.stringify(new URL('../e2e/db/local.mjs', import.meta.url).href)};
    import { runSuite } from ${JSON.stringify(new URL('../e2e/db/run-capped.mjs', import.meta.url).href)};
    import { fakeStack } from ${JSON.stringify(new URL('./fixtures/db-fake-stack.mjs', import.meta.url).href)};
    assert.equal(existsSync(root), false);
    const stack = fakeStack({ stale: 'stopped' });
    const stop = stack.deps.cli;
    stack.deps.cli = async (...args) => { await cli(...args); await stop(...args); };
    await runSuite(stack.deps);
    assert.equal(stack.events.filter(event => event === 'stop').length, 2);
    assert.ok(stack.events.indexOf('stop') < stack.events.indexOf('up'));
    assert.ok(stack.containers.filter(c => c.project === 'jrc-p12-test-db').every(c => !c.running));
    assert.equal(existsSync(root), false);
  `, 'fake-driver'], fake);
  assert.equal(result.code, 0, result.output);
  const commands = (await readFile(fake.log, 'utf8')).trim().split('\n').map(line => JSON.parse(line));
  assert.equal(commands.length, 2);
  for (const args of commands) {
    assert.deepEqual(args.slice(0, 4), ['supabase', 'stop', '--project-id', 'jrc-p12-test-db']);
    assert.ok(!args.includes('--no-backup'));
  }
});

localTest('real database up calls restart hook between CLI start and status (fake executable)', async t => {
  const fake = await fakeCommands(t);
  const result = await childResult(process.execPath, ['--input-type=module', '-e', `
    import { appendFileSync } from 'node:fs';
    import { database } from ${JSON.stringify(new URL('../e2e/db/db.mjs', import.meta.url).href)};
    await database('up', { protect: () => appendFileSync(${JSON.stringify(fake.log)}, '["protect"]\\n') });
  `, 'fake-driver'], fake);
  assert.equal(result.code, 0, result.output);
  const events = (await readFile(fake.log, 'utf8')).trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(events.map(e => e[0] === 'supabase' ? e[1] : e[0]), ['start', 'protect', 'status']);
});

localTest('real seed protects immediately after reset before seeding (fake executable)', async t => {
  const fake = await fakeCommands(t);
  const result = await childResult(process.execPath, ['--input-type=module', '-e', `
    import { appendFileSync } from 'node:fs';
    import { database } from ${JSON.stringify(new URL('../e2e/db/db.mjs', import.meta.url).href)};
    await database('seed', { protect: () => {
      appendFileSync(${JSON.stringify(fake.log)}, '["protect"]\\n');
      throw new Error('protection sentinel');
    } });
  `, 'fake-driver'], fake);
  assert.equal(result.code, 1, result.output);
  assert.match(result.output, /protection sentinel/);
  const events = (await readFile(fake.log, 'utf8')).trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(events.map(e => e[0] === 'supabase' ? e.slice(1, 3).join(' ') : e[0]), ['status -o', 'db reset', 'protect']);
});

localTest('real runner exits nonzero naming stale survivors (fake executables)', async t => {
  const fake = await fakeCommands(t);
  const result = await childResult(process.execPath, [new URL('../e2e/db/run-capped.mjs', import.meta.url).pathname], fake);
  assert.equal(result.code, 1, result.output);
  assert.match(result.output, /preflight left running containers: supabase_db_jrc-p12-test-db/);
  const commands = (await readFile(fake.log, 'utf8')).trim().split('\n').map(line => JSON.parse(line));
  assert.ok(commands.some(args => args[0] === 'supabase' && args[1] === 'stop'));
  assert.ok(!commands.some(args => args.includes('--no-backup') || args.includes('start')));
});

localTest('portable cap TERM-path wiring waits for driver readiness and exits 137', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'jrc-db-cap-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const receipt = join(dir, 'receipt.json');
  const driver = join(dir, 'suite.mjs');
  const ready = join(dir, 'ready');
  const bin = join(dir, 'bin');
  const clockStarted = join(dir, 'clock-started');
  await mkdir(bin);
  // Freeze the cap clock until the suite reaches test (listeners are installed).
  await writeFile(join(bin, 'date'), `#!/bin/sh\nif [ ! -f '${clockStarted}' ]; then touch '${clockStarted}'; echo 0; elif [ -f '${ready}' ]; then echo 2; else echo 0; fi\n`, { mode: 0o700 });
  await writeFile(driver, `
    import { writeFileSync } from 'node:fs';
    import { runSuite } from ${JSON.stringify(new URL('../e2e/db/run-capped.mjs', import.meta.url).href)};
    import { fakeStack } from ${JSON.stringify(new URL('./fixtures/db-fake-stack.mjs', import.meta.url).href)};
    await new Promise(resolve => setTimeout(resolve, 250));
    const stack = fakeStack({ hang: true });
    const run = stack.deps.run;
    stack.deps.run = (args, options) => {
      if (!args.includes('build')) writeFileSync(${JSON.stringify(ready)}, 'ready');
      return run(args, options);
    };
    const keepAlive = setInterval(() => {}, 100);
    try { await runSuite(stack.deps); }
    catch (error) { process.exitCode = 1; }
    finally { clearInterval(keepAlive); writeFileSync(${JSON.stringify(receipt)}, JSON.stringify(stack)); }
  `);
  const child = spawn('sh', [new URL('../e2e/cap.sh', import.meta.url).pathname, driver, '999999', '0'], {
    env: { ...process.env, PATH: `${bin}:${process.env.PATH}` }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(() => { if (child.exitCode === null) child.kill('SIGTERM'); });
  let output = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => { output += chunk; });
  const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('exit', resolve); });
  assert.equal(code, 137, output);
  assert.match(output, /CAP-KILL/);
  assert.equal(await readFile(ready, 'utf8'), 'ready');
  stopped(JSON.parse(await readFile(receipt, 'utf8')));
});

for (const trigger of ['cap', 'SIGINT', 'SIGTERM']) {
  localTest(`${trigger} during reset lets the runner drain and finish slow subprocess teardown`, async t => {
    const dir = await mkdtemp(join(tmpdir(), 'jrc-db-reset-cap-'));
    t.after(() => rm(dir, { recursive: true, force: true }));
    const ready = join(dir, 'ready');
    const receipt = join(dir, 'receipt.json');
    const driver = join(dir, 'suite.mjs');
    const bin = join(dir, 'bin');
    await mkdir(bin);
    const clockStarted = join(dir, 'clock-started');
    await writeFile(join(bin, 'date'), `#!/bin/sh\nif [ ! -f '${clockStarted}' ]; then touch '${clockStarted}'; echo 0; elif [ -f '${ready}' ]; then echo 2; else echo 0; fi\n`, { mode: 0o700 });
    await writeFile(driver, `
      import { writeFileSync } from 'node:fs';
      import { command } from ${JSON.stringify(new URL('../e2e/db/local.mjs', import.meta.url).href)};
      import { runSuite } from ${JSON.stringify(new URL('../e2e/db/run-capped.mjs', import.meta.url).href)};
      import { fakeStack } from ${JSON.stringify(new URL('./fixtures/db-fake-stack.mjs', import.meta.url).href)};
      const stack = fakeStack();
      const database = stack.deps.database;
      stack.deps.database = async (action, options) => {
        await database(action, options);
        if (action === 'seed') {
          // Reset has recreated the DB, but has not reached the protection hook.
          stack.containers.find(c => c.id === 'db2').restart = 'unless-stopped';
          try {
            await command(process.execPath, ['--input-type=module', '-e', \`
              import { writeFileSync } from 'node:fs';
              process.on('SIGTERM', () => setTimeout(() => process.exit(0), 200));
              writeFileSync(${JSON.stringify(ready)}, 'ready');
              setInterval(() => {}, 100);
            \`], options);
          } finally { stack.events.push('reset drained'); }
        }
      };
      const stop = stack.deps.cli;
      stack.deps.cli = async (...args) => {
        await command(process.execPath, ['-e', 'setTimeout(() => {}, 3000)']);
        await stop(...args);
      };
      try { await runSuite(stack.deps); }
      catch { process.exitCode = 1; }
      finally { writeFileSync(${JSON.stringify(receipt)}, JSON.stringify(stack)); }
    `);
    const child = spawn('sh', [new URL('../e2e/cap.sh', import.meta.url).pathname, driver, '999999', trigger === 'cap' ? '0' : '999999'], {
      env: { ...process.env, PATH: `${bin}:${process.env.PATH}` }, stdio: ['ignore', 'pipe', 'pipe'],
    });
    t.after(() => { if (child.exitCode === null) child.kill('SIGTERM'); });
    let output = '';
    child.stdout.on('data', chunk => { output += chunk; });
    child.stderr.on('data', chunk => { output += chunk; });
    const closed = new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
    if (trigger !== 'cap') {
      for (;;) {
        try { await readFile(ready); break; } catch { await new Promise(resolve => setTimeout(resolve, 20)); }
      }
      child.kill(trigger);
    }
    assert.equal(await closed, trigger === 'cap' ? 137 : 130, output);
    const stack = JSON.parse(await readFile(receipt, 'utf8'));
    stopped(stack);
    assert.ok(stack.events.indexOf('reset drained') < stack.events.indexOf('stop'));
    assert.ok(!stack.events.includes('build'));
  });
}

localTest('cap bounds an uncooperative runner and kills its remaining child', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'jrc-cap-force-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const ready = join(dir, 'ready');
  const ticks = join(dir, 'ticks');
  const bin = join(dir, 'bin');
  const driver = join(dir, 'suite.mjs');
  const clockStarted = join(dir, 'clock-started');
  await mkdir(bin);
  await writeFile(join(bin, 'date'), `#!/bin/sh\nif [ ! -f '${clockStarted}' ]; then touch '${clockStarted}'; echo 0; elif [ -f '${ready}' ]; then echo 2; else echo 0; fi\n`, { mode: 0o700 });
  // Compress only the shell's grace ticks; the runner still ignores real TERM.
  await writeFile(join(bin, 'sleep'), `#!/bin/sh\necho "$1" >> '${ticks}'\n/bin/sleep 0.01\n`, { mode: 0o700 });
  await writeFile(driver, `
    import { spawn } from 'node:child_process';
    process.on('SIGTERM', () => {});
    spawn(process.execPath, ['--input-type=module', '-e', \`
      import { writeFileSync } from 'node:fs';
      process.on('SIGTERM', () => {});
      writeFileSync(${JSON.stringify(ready)}, String(process.pid));
      setInterval(() => {}, 100);
    \`], { stdio: 'inherit' });
  `);
  const result = await childResult('sh', [new URL('../e2e/cap.sh', import.meta.url).pathname, driver, '999999', '0'], {
    env: { ...process.env, PATH: `${bin}:${process.env.PATH}` },
  });
  assert.equal(result.code, 137, result.output);
  const sleeps = (await readFile(ticks, 'utf8')).trim().split('\n');
  assert.equal(sleeps.filter(value => value === '1').length, 90, 'bounded grace exhausted');
  const pid = Number(await readFile(ready, 'utf8'));
  assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
});
