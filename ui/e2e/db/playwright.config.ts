import { defineConfig } from '@playwright/test';
import { origin } from './local.mjs';

export default defineConfig({
  testDir: '.', workers: 1, retries: 0, timeout: 90_000,
  outputDir: '../../.e2e/db-results', reporter: 'list',
  use: { baseURL: origin, ignoreHTTPSErrors: true, headless: true, viewport: { width: 1200, height: 800 }, reducedMotion: 'reduce',
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] }, trace: 'off', video: 'off' },
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    { name: 'smoke', testMatch: /smoke\.spec\.ts/, dependencies: ['setup'], use: { storageState: '.e2e/db-auth.json' } },
  ],
  webServer: { command: 'node e2e/db/start-app.mjs', cwd: process.cwd(), url: `${origin}/login`, ignoreHTTPSErrors: true, reuseExistingServer: false, timeout: 120_000, stdout: 'pipe' },
});
