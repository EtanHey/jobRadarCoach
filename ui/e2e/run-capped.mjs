// Entry point for docs.local/tools/run-suite-capped.sh; includes app + runner + browser in its tree.
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => /^(PATH|HOME|TMPDIR|TMP|TEMP|CI|PLAYWRIGHT_BROWSERS_PATH|JRC_E2E_.*)$/.test(key)));
env.E2E_TELEMETRY_DISABLED = '1';
env.NEXT_TELEMETRY_DISABLED = '1';
if (env.CI) delete env.JRC_E2E_MODEL_CONFIG;
const args = (process.env.JRC_E2E_ARGS ?? '').split(' ').filter(Boolean);
if (args.some(arg => /headed|workers|video/.test(arg))) throw new Error('Unsafe runner override');
const child = spawn(process.execPath, [resolve('node_modules/e2e/dist/cli/bin.js'), 'run', ...args], { stdio: 'inherit', env });
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
child.on('exit', code => process.exit(code ?? 1));
