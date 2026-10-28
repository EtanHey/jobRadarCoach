import assert from 'node:assert/strict';
import { test } from 'node:test';
import { command } from '../e2e/db/local.mjs';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runSuite } from '../e2e/db/run-capped.mjs';

import { fakeStack } from './fixtures/db-fake-stack.mjs';

const capShell = process.env.JRC_CAP_TEST_SHELL || '/bin/sh';

for (const phase of ['preparing', 'listening', 'output closed', 'controller died']) {
  localTest(`server exits when start-app dies while ${phase}`, async t => {
    const fake = await fakeCommands(t);
    await writeFile(join(fake.cwd, '.e2e/db-stack/owner.json'), '{"id":"synthetic"}');
    const next = join(fake.cwd, 'node_modules/next');
    await mkdir(next, { recursive: true });
    await writeFile(join(next, 'package.json'), '{"type":"module","exports":"./index.mjs"}');
    const pidFile = join(fake.cwd, 'server-pid');
    await writeFile(join(next, 'index.mjs'), `
      import { writeFileSync } from 'node:fs';
      export default () => ({
        prepare: async () => {
          writeFileSync(${JSON.stringify(pidFile)}, String(process.pid));
          ${phase === 'preparing' ? 'await new Promise(() => setInterval(() => {}, 100));' : ''}
          ${phase === 'output closed' ? 'await new Promise(resolve => setTimeout(resolve, 500));' : ''}
        },
        getRequestHandler: () => (req, res) => res.end('synthetic'), close: async () => {},
      });
    `);
    const root = join(fake.cwd, '.e2e/db-stack/supabase');
    const tls = await childResult('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', join(root, 'key.pem'), '-out', join(root, 'cert.pem'), '-days', '1', '-subj', '/CN=localhost']);
    assert.equal(tls.code, 0, tls.output);
    const parent = spawn(process.execPath, [new URL('../e2e/db/start-app.mjs', import.meta.url).pathname], {
      cwd: fake.cwd, env: { ...fake.env, CI: 'false', JRC_LOCAL_DOCKER: '1' }, stdio: ['pipe', 'pipe', 'pipe'],
    });
    let output = '', pid;
    parent.stdout.on('data', chunk => { output += chunk; });
    parent.stderr.on('data', chunk => { output += chunk; });
    t.after(() => {
      parent.kill('SIGKILL');
      if (pid) { try { process.kill(pid, 'SIGKILL'); } catch {} }
    });
    await waitForFile(pidFile);
    pid = Number(await readFile(pidFile, 'utf8'));
    if (phase === 'listening' || phase === 'controller died') {
      for (let i = 0; i < 100 && !output.includes('Production test app ready'); i++) await new Promise(resolve => setTimeout(resolve, 20));
      assert.match(output, /Production test app ready/);
    }
    if (phase === 'controller died') {
      const exited = new Promise(resolve => parent.once('exit', (code, signal) => resolve({ code, signal })));
      parent.stdin.end(); // Playwright's pipe closes when its process dies.
      let timer;
      try {
        assert.deepEqual(await Promise.race([exited, new Promise(resolve => { timer = setTimeout(() => resolve('still running'), 1500); })]), { code: 0, signal: null });
      } finally { clearTimeout(timer); }
    } else if (phase === 'output closed') {
      const exited = new Promise(resolve => parent.once('exit', (code, signal) => resolve({ code, signal })));
      parent.stdout.destroy(); // Playwright has exited before the server's first output.
      assert.deepEqual(await exited, { code: 1, signal: null });
      assert.match(output, /EPIPE/);
    } else parent.kill('SIGKILL');
    for (let i = 0; i < 100 && alive(pid); i++) await new Promise(resolve => setTimeout(resolve, 20));
    assert.equal(alive(pid), false, `server PID ${pid} survived its parent: ${output}`);
  });
}

function alive(pid) {
  try { process.kill(pid, 0); return true; } catch { return false; }
}

// 'reused pid' is R524's probe: an unrelated same-cwd listener now holds the receipt's PID.
for (const ownership of ['owned', 'other cwd', 'missing receipt', 'reused pid', 'reused pid, other start']) {
  localTest(`teardown rejects a survivor (${ownership}) and signals only its own listener`, async t => {
    const dir = await mkdtemp(join(tmpdir(), 'jrc-server-check-'));
    t.after(() => rm(dir, { recursive: true, force: true }));
    const receipt = join(dir, 'receipt.json');
    const ready = join(dir, 'ready.json');
    await mkdir(join(dir, 'other'));
    const writes = ownership === 'owned' || ownership === 'other cwd';
    const child = spawn(process.execPath, ['--input-type=module', '-e', `
      import { createServer } from 'node:net';
      import { renameSync, writeFileSync } from 'node:fs';
      import { processStart } from ${JSON.stringify(new URL('../e2e/db/local.mjs', import.meta.url).href)};
      const started = await processStart(process.pid);
      const server = createServer();
      server.listen(0, '127.0.0.1', () => {
        ${writes ? `writeFileSync(${JSON.stringify(receipt)}, JSON.stringify({ pid: process.pid, started }));` : ''}
        // Atomic, so the reader never sees an empty file.
        writeFileSync(${JSON.stringify(ready + '.tmp')}, JSON.stringify(server.address()));
        renameSync(${JSON.stringify(ready + '.tmp')}, ${JSON.stringify(ready)});
      });
    `], { cwd: dir, stdio: 'ignore' });
    t.after(() => child.kill('SIGKILL'));
    await waitForFile(ready);
    // The original server exited and the kernel handed its PID to this listener.
    if (ownership === 'reused pid') await writeFile(receipt, JSON.stringify({ pid: child.pid }));
    if (ownership === 'reused pid, other start') await writeFile(receipt, JSON.stringify({ pid: child.pid, started: 'Thu Jan  1 00:00:00 1970' }));
    const { port } = JSON.parse(await readFile(ready, 'utf8'));
    const { checkServer } = await import('../e2e/db/run-capped.mjs');
    await assert.rejects(checkServer(receipt, { port, cwd: ownership === 'other cwd' ? join(dir, 'other') : dir }), new RegExp(`survivor.*${child.pid}`));
    for (let i = 0; i < 100 && ownership === 'owned' && alive(child.pid); i++) await new Promise(resolve => setTimeout(resolve, 20));
    assert.equal(alive(child.pid), ownership !== 'owned');
  });
}

localTest('the survivor check has one wall-clock deadline, not per-call timeouts', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'jrc-server-deadline-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await writeFile(join(dir, 'lsof'), '#!/bin/sh\nexec sleep 30\n', { mode: 0o755 });
  const path = process.env.PATH;
  process.env.PATH = `${dir}:${path}`;
  t.after(() => { process.env.PATH = path; });
  const { checkServer } = await import('../e2e/db/run-capped.mjs');
  const started = Date.now();
  await assert.rejects(checkServer(join(dir, 'receipt.json'), { port: 1, cwd: dir, timeout: 500 }), /deadline/);
  assert.ok(Date.now() - started < 2000, `check took ${Date.now() - started} ms`);
});

for (const tool of ['lsof', 'ps']) {
  localTest(`the survivor deadline holds when ${tool} ignores SIGTERM`, async t => {
    const dir = await mkdtemp(join(tmpdir(), 'jrc-server-stubborn-'));
    const pidFile = join(dir, 'pid');
    t.after(async () => {
      try { process.kill(Number(await readFile(pidFile, 'utf8')), 'SIGKILL'); } catch {}
      await rm(dir, { recursive: true, force: true });
    });
    await writeFile(join(dir, tool), `#!/bin/sh\ntrap "" TERM\necho $$ > "${pidFile}"\nwhile :; do :; done\n`, { mode: 0o755 });
    const path = process.env.PATH;
    process.env.PATH = `${dir}:${path}`;
    t.after(() => { process.env.PATH = path; });
    const { checkServer } = await import('../e2e/db/run-capped.mjs');
    const { processStart } = await import('../e2e/db/local.mjs');
    const check = tool === 'lsof'
      ? checkServer(join(dir, 'receipt.json'), { port: 1, cwd: dir, timeout: 500 }).then(() => 'resolved', error => error.message)
      : processStart(process.pid, { timeout: 500 });
    let timer;
    const outcome = await Promise.race([check, new Promise(resolve => { timer = setTimeout(resolve, 2000, 'still pending'); })]);
    clearTimeout(timer);
    assert.match(String(outcome), tool === 'lsof' ? /deadline/ : /^null$/);
  });
}

localTest('the listener check still runs when container teardown fails', async () => {
  const stack = fakeStack({ stop: 'error' });
  let checked = false;
  stack.deps.checkServer = async receipt => { assert.match(receipt, /db-server-.*\.json$/); checked = true; };
  await assert.rejects(runSuite(stack.deps), /stop failed/);
  assert.equal(checked, true);
});

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
    checkServer: async () => {},
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

for (const code of [0, 7, 143]) {
  localTest(`portable cap preserves runner output and exit ${code}`, async t => {
    const dir = await mkdtemp(join(tmpdir(), 'jrc-cap-exit-'));
    t.after(() => rm(dir, { recursive: true, force: true }));
    const driver = join(dir, 'suite.mjs');
    await writeFile(driver, `console.log('suite output'); ${code === 143 ? "process.kill(process.pid, 'SIGTERM')" : `process.exitCode = ${code}`};`);
    const result = await childResult(capShell, [new URL('../e2e/cap.sh', import.meta.url).pathname, driver, '999999', '999999']);
    assert.equal(result.code, code, result.output);
    assert.match(result.output, /suite output/);
  });
}

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
  const child = spawn(capShell, [new URL('../e2e/cap.sh', import.meta.url).pathname, driver, '999999', '0'], {
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

for (const trigger of ['cap', 'SIGINT', 'SIGTERM', 'group-SIGINT']) {
  localTest(`${trigger} during reset lets the runner drain and finish slow subprocess teardown`, async t => {
    const dir = await mkdtemp(join(tmpdir(), 'jrc-db-reset-cap-'));
    t.after(() => rm(dir, { recursive: true, force: true }));
    const ready = join(dir, 'ready');
    const receipt = join(dir, 'receipt.json');
    const stopping = join(dir, 'stopping');
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
          // Recreate the risky restart policy after the fake's protection hook.
          // This exercises mid-reset cleanup, not reset/protect ordering.
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
        await command(process.execPath, ['-e', \`
          if (\${stack.events.includes('reset drained')}) require('node:fs').writeFileSync(${JSON.stringify(stopping)}, 'stopping');
          setTimeout(() => {}, 3000);
        \`]);
        await stop(...args);
      };
      try { await runSuite(stack.deps); }
      catch { process.exitCode = 1; }
      finally { writeFileSync(${JSON.stringify(receipt)}, JSON.stringify(stack)); }
    `);
    const child = spawn(capShell, [new URL('../e2e/cap.sh', import.meta.url).pathname, driver, '999999', trigger === 'cap' ? '0' : '999999'], {
      detached: trigger === 'group-SIGINT',
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
      if (trigger === 'group-SIGINT') {
        process.kill(-child.pid, 'SIGINT');
        await waitForFile(stopping);
        process.kill(-child.pid, 'SIGINT');
      } else child.kill(trigger);
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
  const capped = join(dir, 'capped');
  await mkdir(bin);
  await writeFile(join(bin, 'date'), `#!/bin/sh\nif [ ! -f '${clockStarted}' ]; then touch '${clockStarted}'; echo 0; elif [ -f '${ready}' ]; then touch '${capped}'; echo 2; else echo 0; fi\n`, { mode: 0o700 });
  // Count grace ticks after the cap fires, excluding the launcher handshake wait.
  // Compress the shell's waits; the runner still ignores real TERM.
  await writeFile(join(bin, 'sleep'), `#!/bin/sh\nif [ -f '${capped}' ]; then echo "$1" >> '${ticks}'; fi\n/bin/sleep 0.01\n`, { mode: 0o700 });
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
  const result = await childResult(capShell, [new URL('../e2e/cap.sh', import.meta.url).pathname, driver, '999999', '0'], {
    env: { ...process.env, PATH: `${bin}:${process.env.PATH}` },
  });
  assert.equal(result.code, 137, result.output);
  const sleeps = (await readFile(ticks, 'utf8')).trim().split('\n');
  assert.equal(sleeps.filter(value => value === '1').length, 90, 'bounded grace exhausted');
  const pid = Number(await readFile(ready, 'utf8'));
  for (let attempt = 0; attempt < 50; attempt++) {
    try { process.kill(pid, 0); }
    catch (error) { assert.equal(error.code, 'ESRCH'); return; }
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  assert.fail(`cap left child ${pid} alive after forced cleanup`);
});

localTest('cap kills a child spawned by an orphaned subtree during runner cleanup', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'jrc-cap-orphan-'));
  const ready = join(dir, 'ready');
  const fork = join(dir, 'fork');
  const driverPid = join(dir, 'driver-pid');
  const leafPid = join(dir, 'leaf-pid');
  const driver = join(dir, 'suite.mjs');
  const wrapper = join(dir, 'wrapper.mjs');
  const native = join(dir, 'native.mjs');
  const leaf = join(dir, 'leaf.mjs');
  await writeFile(leaf, `
    import { writeFileSync } from 'node:fs';
    process.on('SIGTERM', () => {});
    writeFileSync(${JSON.stringify(leafPid)}, String(process.pid));
    setInterval(() => {}, 100);
  `);
  await writeFile(native, `
    import { spawn } from 'node:child_process';
    import { existsSync, writeFileSync } from 'node:fs';
    const parent = process.ppid;
    writeFileSync(${JSON.stringify(ready)}, 'ready');
    const poll = setInterval(() => {
      if (process.ppid !== parent && existsSync(${JSON.stringify(fork)})) {
        clearInterval(poll);
        spawn(process.execPath, [${JSON.stringify(leaf)}], { stdio: 'ignore' }).unref();
      }
    }, 20);
    setInterval(() => {}, 100);
  `);
  await writeFile(wrapper, `
    import { spawn } from 'node:child_process';
    spawn(process.execPath, [${JSON.stringify(native)}], { stdio: 'ignore' });
  `);
  await writeFile(driver, `
    import { spawn } from 'node:child_process';
    import { existsSync, writeFileSync } from 'node:fs';
    writeFileSync(${JSON.stringify(driverPid)}, String(process.pid));
    const wrapper = spawn(process.execPath, [${JSON.stringify(wrapper)}], { stdio: 'ignore' });
    process.on('SIGTERM', () => {
      wrapper.kill('SIGTERM');
      writeFileSync(${JSON.stringify(fork)}, 'fork');
      const poll = setInterval(() => {
        if (existsSync(${JSON.stringify(leafPid)})) { clearInterval(poll); process.exit(0); }
      }, 20);
    });
    setInterval(() => {}, 100);
  `);
  const child = spawn(capShell, [new URL('../e2e/cap.sh', import.meta.url).pathname, driver, '999999', '999999'], {
    detached: true, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => { output += chunk; });
  const closed = new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
  t.after(async () => {
    // Clean up only this test's session, runner group and orphan on failure.
    try { process.kill(-child.pid, 'SIGKILL'); } catch {}
    try { process.kill(-Number(await readFile(driverPid, 'utf8')), 'SIGKILL'); } catch {}
    try { process.kill(Number(await readFile(leafPid, 'utf8')), 'SIGKILL'); } catch {}
    await rm(dir, { recursive: true, force: true });
  });
  for (;;) {
    try { await readFile(ready); break; } catch { await new Promise(resolve => setTimeout(resolve, 20)); }
  }
  child.kill('SIGTERM');
  assert.equal(await closed, 130, output);
  const pid = Number(await readFile(leafPid, 'utf8'));
  for (let attempt = 0; attempt < 50; attempt++) {
    try { process.kill(pid, 0); }
    catch (error) { assert.equal(error.code, 'ESRCH'); return; }
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  assert.fail(`cap left orphan subtree child ${pid} alive after cleanup`);
});

async function waitForFile(path) {
  for (let attempt = 0; attempt < 200; attempt++) {
    try { return await readFile(path, 'utf8'); }
    catch { await new Promise(resolve => setTimeout(resolve, 20)); }
  }
  assert.fail(`timed out waiting for ${path}`);
}

for (const trigger of ['cap', 'SIGINT', 'SIGTERM']) {
  localTest(`${trigger} fallback kills detached descendants including a late detached child`, async t => {
    const dir = await mkdtemp(join(tmpdir(), 'jrc-cap-detached-'));
    const bin = join(dir, 'bin');
    const rootPid = join(dir, 'root-pid');
    const ready = join(dir, 'ready');
    const latePid = join(dir, 'late-pid');
    const driver = join(dir, 'suite.mjs');
    const leaf = join(dir, 'leaf.mjs');
    const late = join(dir, 'late.mjs');
    const clock = join(dir, 'clock');
    await mkdir(bin);
    await writeFile(join(bin, 'date'), `#!/bin/sh\nif [ ! -f '${clock}' ]; then touch '${clock}'; echo 0; elif [ -f '${ready}' ]; then echo 2; else echo 0; fi\n`, { mode: 0o700 });
    // Compress the 90 ticks, but let the TERM handler start its late child.
    await writeFile(join(bin, 'sleep'), '#!/bin/sh\nif [ "$1" = 2 ]; then /bin/sleep 0.3; else /bin/sleep 0.01; fi\n', { mode: 0o700 });
    await writeFile(late, `
      import { writeFileSync } from 'node:fs';
      process.on('SIGTERM', () => {});
      writeFileSync(${JSON.stringify(latePid)}, String(process.pid));
      setInterval(() => {}, 100);
    `);
    await writeFile(leaf, `
      import { spawn } from 'node:child_process';
      import { writeFileSync } from 'node:fs';
      let spawned = false;
      process.on('SIGTERM', () => {
        if (spawned) return;
        spawned = true;
        spawn(process.execPath, [${JSON.stringify(late)}], { detached: true, stdio: 'ignore' });
      });
      writeFileSync(${JSON.stringify(ready)}, String(process.pid));
      setInterval(() => {}, 100);
    `);
    await writeFile(driver, `
      import { spawn } from 'node:child_process';
      import { writeFileSync } from 'node:fs';
      process.on('SIGTERM', () => {});
      writeFileSync(${JSON.stringify(rootPid)}, String(process.pid));
      spawn(process.execPath, [${JSON.stringify(leaf)}], { detached: true, stdio: 'ignore' });
      setInterval(() => {}, 100);
    `);
    const child = spawn(capShell, [new URL('../e2e/cap.sh', import.meta.url).pathname, driver, '999999', trigger === 'cap' ? '0' : '999999'], {
      detached: true, env: { ...process.env, PATH: `${bin}:${process.env.PATH}` }, stdio: ['ignore', 'pipe', 'pipe'],
    });
    let output = '';
    child.stdout.on('data', chunk => { output += chunk; });
    child.stderr.on('data', chunk => { output += chunk; });
    const closed = new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
    t.after(async () => {
      // Every group here is led by a PID recorded by this fixture itself.
      for (const file of [latePid, ready, rootPid]) {
        try { process.kill(-Number(await readFile(file, 'utf8')), 'SIGKILL'); } catch {}
      }
      try { process.kill(-child.pid, 'SIGKILL'); } catch {}
      await rm(dir, { recursive: true, force: true });
    });
    await waitForFile(ready);
    if (trigger !== 'cap') child.kill(trigger);
    assert.equal(await closed, trigger === 'cap' ? 137 : 130, output);
    // Check the original survivor first so the pre-fix failure names the leak.
    for (const file of [ready, latePid]) {
      const pid = Number(await readFile(file, 'utf8'));
      for (let attempt = 0; attempt < 50; attempt++) {
        try { process.kill(pid, 0); }
        catch (error) { assert.equal(error.code, 'ESRCH'); break; }
        if (attempt === 49) assert.fail(`cap left detached child ${pid} alive (${file})`);
        await new Promise(resolve => setTimeout(resolve, 20));
      }
    }
  });
}

localTest('early terminal-group TERM preserves wrapper interruption status 130', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'jrc-cap-startup-'));
  const bin = join(dir, 'bin');
  const launching = join(dir, 'launching');
  await mkdir(bin);
  await writeFile(join(bin, 'node'), `#!/bin/sh\ntouch '${launching}'\n/bin/sleep 0.3\nexec '${process.execPath}' "$@"\n`, { mode: 0o700 });
  const child = spawn(capShell, [new URL('../e2e/cap.sh', import.meta.url).pathname, join(dir, 'unused.mjs')], {
    detached: true, env: { ...process.env, PATH: `${bin}:${process.env.PATH}` }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(async () => {
    try { process.kill(-child.pid, 'SIGKILL'); } catch {}
    await rm(dir, { recursive: true, force: true });
  });
  const closed = new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
  await waitForFile(launching);
  process.kill(-child.pid, 'SIGTERM');
  assert.equal(await closed, 130);
});
