import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
export const root = resolve('.e2e/db-stack');
export const project = 'jrc-p12-test-db';
export const origin = 'https://127.0.0.1:4343';
export const email = 'p12-owner@example.test';
export const password = 'Local-only-P12-password-123!';
export const cert = resolve(root, 'supabase/cert.pem');
export const key = resolve(root, 'supabase/key.pem');
export const cleanEnv = () => Object.fromEntries(Object.entries(process.env).filter(([k]) => /^(PATH|HOME|TMPDIR|TMP|TEMP|CI|PLAYWRIGHT_BROWSERS_PATH|DOCKER_HOST|DOCKER_CONTEXT)$/.test(k)));
export function localStatus(status) {
  for (const [field, expected] of Object.entries({ API_URL: 'https://127.0.0.1:55431', MAILPIT_URL: 'http://127.0.0.1:55434' })) {
    if (status[field] !== expected) throw new Error(`Refusing non-test ${field}`);
  }
  const db = new URL(status.DB_URL);
  if (db.protocol !== 'postgresql:' || db.hostname !== '127.0.0.1' || db.port !== '55432' || db.pathname !== '/postgres') throw new Error('Refusing non-test DB_URL');
  if (!status.ANON_KEY || !status.SERVICE_ROLE_KEY) throw new Error('Missing local API keys');
  return status;
}
// CLI output can contain local keys; capture it, never print it or inherit credentials.
export function command(executable, args, { input, env = cleanEnv(), cwd } = {}) {
  return new Promise((ok, fail) => {
    const child = spawn(executable, args, { env, cwd, stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '', stderr = '';
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', fail);
    child.on('exit', code => code === 0 ? ok(stdout) : fail(new Error(`${executable} ${args[0]} failed (${code}): ${stderr.replace(/eyJ[\w.-]+|sb_(?:secret|publishable)_[\w-]+/g, '[local key]').slice(-3000)}`)));
    child.stdin.end(input);
  });
}
export const cli = (...args) => command('supabase', [...args, '--workdir', root]);
export const status = async () => localStatus(JSON.parse(await cli('status', '-o', 'json')));
