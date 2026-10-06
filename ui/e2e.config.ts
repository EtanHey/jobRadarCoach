import type { E2EConfig } from 'e2e';
import { web } from '@e2e-dev/web';
import { pathToFileURL } from 'node:url';
process.env.E2E_TELEMETRY_DISABLED = '1';
const configured = !process.env.CI && process.env.JRC_E2E_MODEL_CONFIG;
const agents = configured ? { default: (await import(pathToFileURL(configured).href)).default } : undefined;
export default {
  tests: ['e2e/*.e2e.ts'], workers: 1, retries: 0, timeout: 60_000,
  trace: 'off', video: 'off', cache: { mode: 'read-write', dir: '.e2e/cache' },
  output: process.env.JRC_E2E_OUTPUT ?? '.e2e/results',
  ...(agents ? { agents } : {}),
  targets: [{ name: 'chromium-headless', engine: web({ browser: 'chromium', viewport: { width: 1440, height: 1000 } }),
    app: { url: 'http://127.0.0.1:0', command: { executable: 'node', args: ['e2e/start-app.mjs', '{port}'],
      startupTimeout: 120_000, log: '.e2e/app.log', env: { NEXT_TELEMETRY_DISABLED: '1', JRC_E2E_MUTATION: process.env.JRC_E2E_MUTATION ?? '' } } } }],
} satisfies E2EConfig;
