// Unmodified auth + API routes in a fresh app copy, with no production .env files.
import { spawn } from 'node:child_process';
import { cp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { cert, key, root, origin, email, cleanEnv, status } from './local.mjs';
import '../../scripts/build-map-worker.mjs';
const target = resolve('.e2e/db-app');
const building = process.argv[2] === 'build';
if (building) {
  await rm(target, { recursive: true, force: true });
  await mkdir(target, { recursive: true });
  for (const name of ['app', 'components', 'lib', 'public', 'proxy.ts', 'package.json', 'tsconfig.json', 'postcss.config.mjs']) await cp(name, resolve(target, name), { recursive: true });
  await symlink(resolve('node_modules'), resolve(target, 'node_modules'), 'dir');
  await writeFile(resolve(target, 'next-env.d.ts'), '/// <reference types="next" />\n/// <reference types="next/image-types/global" />\n');
  await writeFile(resolve(target, 'next.config.ts'), `import type { NextConfig } from 'next';
const config: NextConfig = { turbopack: { root: ${JSON.stringify(resolve('.'))} }, experimental: { cpus: 1 } };
export default config;`);
  const css = resolve(target, 'app/globals.css');
  await writeFile(css, (await readFile(css, 'utf8')).replace('@import "tailwindcss";', '@import "tailwindcss" source(none);\n@source "../components";\n@source "../app";'));
}
const local = await status();
const owner = JSON.parse(await readFile(resolve(root, 'owner.json'), 'utf8'));
// Trust the dedicated stack certificate for build and production-server requests.
const env = { ...cleanEnv(), NODE_OPTIONS: '--use-openssl-ca --max-old-space-size=1024', SSL_CERT_FILE: cert, NEXT_TELEMETRY_DISABLED: '1', NODE_ENV: 'production',
  SUPABASE_URL: local.API_URL, SUPABASE_SERVICE_ROLE_KEY: local.SERVICE_ROLE_KEY,
  NEXT_PUBLIC_SUPABASE_URL: local.API_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: local.ANON_KEY,
  JRC_OWNER_USER_IDS: owner.id, JRC_OWNER_RECOVERY_ENABLED: 'true', JRC_OWNER_RECOVERY_EMAIL: email, UI_ORIGIN: origin };
// Build before Chromium starts; production serving performs no dev compilation.
// Next start has no HTTPS flag, so its production handler runs in a local TLS server.
const args = building ? ['node_modules/next/dist/bin/next', 'build', target] : ['--input-type=module', '-e', `
  import next from 'next';
  import { createServer } from 'node:https';
  import { readFileSync } from 'node:fs';
  const app = next({ dev: false, dir: ${JSON.stringify(target)}, hostname: '127.0.0.1', port: 4343 });
  await app.prepare();
  const server = createServer({ key: readFileSync(${JSON.stringify(key)}), cert: readFileSync(${JSON.stringify(cert)}) }, app.getRequestHandler());
  server.listen(4343, '127.0.0.1', () => console.log('Production test app ready at ${origin}'));
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, async () => {
    server.close(); server.closeAllConnections(); await app.close(); process.exit(0);
  });
`];
const child = spawn(process.execPath, args, { env, stdio: ['ignore', 'pipe', 'pipe'] });
for (const [stream, output] of [[child.stdout, process.stdout], [child.stderr, process.stderr]]) {
  let pending = '';
  stream.on('data', chunk => {
    pending += chunk; const lines = pending.split('\n'); pending = lines.pop();
    for (const line of lines) output.write(line.replace(/([?&](?:code|token|token_hash|access_token|refresh_token)=)[^&\s]+/g, '$1[redacted]') + '\n');
  });
}
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('exit', code => process.exit(code ?? 1));
