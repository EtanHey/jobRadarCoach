import assert from 'node:assert/strict';

// A container table, never a real Docker/Supabase process. Also used by the cap child.
export function fakeStack({ stale = false, fail = '', signal = '', hang = false, stop = '' } = {}) {
  const project = 'jrc-p12-test-db';
  const label = `com.supabase.cli.project=${project}`;
  const events = [];
  const containers = [{ id: 'unrelated', project: 'other', running: true, restart: 'always' }];
  const ours = () => containers.filter(c => c.project === project);
  const add = () => containers.push(...['db', 'auth'].map(id => ({ id, project, running: id === 'db', restart: 'unless-stopped' })));
  if (stale) { add(); if (stale === 'stopped') for (const c of ours()) c.running = false; }
  const deps = {
    checkServer: async () => {},
    database: async (action, options) => {
      events.push(action);
      if (action === 'up') {
        assert.equal(ours().some(c => c.running), false, 'stale stack must stop before up');
        if (!ours().length) add();
        for (const c of ours()) c.running = c.id === 'db';
        if (fail !== 'up') await options.protect?.();
      }
      if (action === 'seed') {
        containers.splice(containers.findIndex(c => c.id === 'db'), 1);
        containers.push({ id: 'db2', project, running: true, restart: 'unless-stopped' });
        await options.protect?.();
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
    run: async (args, { signal: abort }) => {
      const step = args.includes('build') ? 'build' : 'test';
      events.push(step);
      if (step === 'build') assert.ok(ours().every(c => c.restart === 'no'), 'reset replacement must be protected before build');
      if (step === fail) throw new Error(`failed ${step}`);
      if (step === 'test' && signal) queueMicrotask(() => process.emit(signal));
      if (step === 'test' && (signal || hang)) await new Promise(resolve => abort.addEventListener('abort', resolve, { once: true }));
    },
  };
  return { deps, containers, events };
}

