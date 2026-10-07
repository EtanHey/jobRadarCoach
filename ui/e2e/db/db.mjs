import { cp, mkdir, readFile, writeFile, chmod, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { cert, key, root, project, email, password, command, cli, status, cleanEnv } from './local.mjs';

export async function database(action) {
  if (action === 'up') {
    await mkdir(resolve(root, 'supabase'), { recursive: true });
    await cp('e2e/db/config.toml', resolve(root, 'supabase/config.toml'));
    await rm(resolve(root, 'supabase/migrations'), { recursive: true, force: true });
    await cp('../supabase/migrations', resolve(root, 'supabase/migrations'), { recursive: true });
    try { await readFile(cert); } catch {
      await command('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', cert, '-days', '365', '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1']);
      await chmod(key, 0o600);
    }
    console.log('Starting dedicated synthetic Supabase stack (first pull may take several minutes)');
    await cli('start', '--exclude', 'realtime,storage-api,imgproxy,postgres-meta,studio,edge-runtime,logflare,vector,supavisor');
    await status();
  } else if (action === 'seed') {
    await status(); // Refuse a different endpoint before any destructive operation.
    console.log('Resetting only jrc-p12-test-db; applying repository migrations');
    await cli('db', 'reset', '--local', '--no-seed', '--yes');
    await command('docker', ['exec', '-i', `supabase_db_${project}`, 'psql', '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1'], { input: await readFile('e2e/db/seed.sql', 'utf8') });
    const local = await status();
    // Trust only our generated certificate, without disabling Node TLS verification.
    const result = await command(process.execPath, ['--input-type=module', '-e', `
      const response = await fetch('${local.API_URL}/auth/v1/admin/users', {
        method: 'POST', headers: { apikey: process.env.LOCAL_KEY, authorization: 'Bearer ' + process.env.LOCAL_KEY, 'content-type': 'application/json' },
        body: JSON.stringify({ email: ${JSON.stringify(email)}, password: ${JSON.stringify(password)}, email_confirm: true }) });
      if (!response.ok) throw new Error('Local user creation failed: ' + response.status);
      console.log(JSON.stringify({ id: (await response.json()).id }));
    `], { env: { ...cleanEnv(), NODE_EXTRA_CA_CERTS: cert, LOCAL_KEY: local.SERVICE_ROLE_KEY } });
    await writeFile(resolve(root, 'owner.json'), result, { mode: 0o600 });
    const count = await command('docker', ['exec', `supabase_db_${project}`, 'psql', '-U', 'postgres', '-d', 'postgres', '-Atc', 'select count(*) from auth.users']);
    if (count.trim() !== '1') throw new Error('Expected exactly one local Auth user');
    console.log('Seeded 3 postings, scores, statuses, centroids and one local test user');
  } else if (action === 'down') {
    await cli('stop', '--project-id', project, '--no-backup');
  } else throw new Error('Expected up, seed or down');
}
if (import.meta.url === pathToFileURL(resolve(process.argv[1])).href) await database(process.argv[2]);
