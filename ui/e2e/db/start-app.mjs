// Unmodified auth + API routes in a fresh app copy, with no production .env files.
import { spawn } from 'node:child_process';
import { cp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { cert, key, root, origin, email, cleanEnv, status } from './local.mjs';
import '../../scripts/build-map-worker.mjs';
const target = resolve('.e2e/db-app');
await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });
for (const name of ['app', 'components', 'lib', 'public', 'proxy.ts', 'package.json', 'tsconfig.json', 'postcss.config.mjs']) await cp(name, resolve(target, name), { recursive: true });
await symlink(resolve('node_modules'), resolve(target, 'node_modules'), 'dir');
await writeFile(resolve(target, 'next-env.d.ts'), '/// <reference types="next" />\n/// <reference types="next/image-types/global" />\n');
await writeFile(resolve(target, 'next.config.ts'), `export default { turbopack: { root: ${JSON.stringify(resolve('.'))} }, allowedDevOrigins: ['127.0.0.1'], devIndicators: false };`);
const css = resolve(target, 'app/globals.css');
await writeFile(css, (await readFile(css, 'utf8')).replace('@import "tailwindcss";', '@import "tailwindcss" source(none);\n@source "../components";\n@source "../app";'));
const local = await status();
const owner = JSON.parse(await readFile(resolve(root, 'owner.json'), 'utf8'));
// Next dev overwrites NODE_EXTRA_CA_CERTS when custom HTTPS certs are supplied.
const env = { ...cleanEnv(), NODE_OPTIONS: '--use-openssl-ca --max-old-space-size=768', SSL_CERT_FILE: cert, NEXT_TELEMETRY_DISABLED: '1',
  SUPABASE_URL: local.API_URL, SUPABASE_SERVICE_ROLE_KEY: local.SERVICE_ROLE_KEY,
  NEXT_PUBLIC_SUPABASE_URL: local.API_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: local.ANON_KEY,
  JRC_OWNER_USER_IDS: owner.id, JRC_OWNER_RECOVERY_ENABLED: 'true', JRC_OWNER_RECOVERY_EMAIL: email, UI_ORIGIN: origin };
const child = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'dev', target, '--hostname', '127.0.0.1', '--port', '4343', '--experimental-https', '--experimental-https-key', key, '--experimental-https-cert', cert], { env, stdio: ['ignore', 'pipe', 'pipe'] });
for (const [stream, output] of [[child.stdout, process.stdout], [child.stderr, process.stderr]]) {
  let pending = '';
  stream.on('data', chunk => {
    pending += chunk; const lines = pending.split('\n'); pending = lines.pop();
    for (const line of lines) output.write(line.replace(/([?&](?:code|token|token_hash|access_token|refresh_token)=)[^&\s]+/g, '$1[redacted]') + '\n');
  });
}
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('exit', code => process.exit(code ?? 1));
