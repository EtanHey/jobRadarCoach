// Hand-written Playwright comparator; shares synthetic data, not assertions.
import { chromium, expect } from '@playwright/test';
import type { Browser as FixtureBrowser } from '@e2e-dev/web';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { installFixture, role } from './fixture';
const socket = createServer();
await new Promise<void>(ok => socket.listen(0, '127.0.0.1', ok));
const address = socket.address();
if (!address || typeof address === 'string') throw new Error('No port');
const port = address.port;
await new Promise<void>(ok => socket.close(() => ok()));
const started = performance.now();
const server = spawn(process.execPath, ['e2e/start-app.mjs', String(port)], { stdio: 'ignore' });
let browser;
const results = [];
try {
  const base = `http://127.0.0.1:${port}`;
  for (;;) {
    if (server.exitCode !== null) throw new Error('Fixture server exited');
    if (performance.now() - started > 120000) throw new Error('Startup timeout');
    try { if ((await fetch(base)).ok) break; } catch {}
    await new Promise(ok => setTimeout(ok, 250));
  }
  browser = await chromium.launch({ headless: true });
  for (let repeat = 0; repeat < 5; repeat++) for (const flow of ['a', 'b', 'c', 'd']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    const began = performance.now();
    try {
      const adapter: Parameters<typeof installFixture>[0] = { addInitScript: async script => { await page.addInitScript(script); }, route: async (pattern: string, handler: Parameters<FixtureBrowser['route']>[1]) => {
        await page.route(pattern, route => handler({ request: { url: route.request().url(), method: route.request().method(),
          headers: route.request().headers(), postData: route.request().postData() ?? undefined },
          fulfill: async response => { await route.fulfill(response); }, continue: async () => { await route.continue(); },
          abort: async () => { await route.abort(); }, fallback: async () => { await route.fallback(); } }));
      } };
      const state = await installFixture(adapter, base);
      await page.goto(base);
      const open = page.getByRole('button', { name: `Open ${role.title} at ${role.company}`, exact: true });
      await expect(open).toBeVisible();
      if (flow === 'b' || flow === 'd') {
        if (flow === 'd') await page.getByRole('textbox', { name: /Search/ }).fill(role.title);
        state.addRole = true;
        await page.evaluate(() => { const now = Date.now(); Date.now = () => now + 91_000; window.dispatchEvent(new Event('focus')); });
        await expect.poll(() => state.pollReads).toBeGreaterThan(0);
        await page.waitForTimeout(300);
        const pill = page.locator('[data-new-roles]');
        if (flow === 'd') await expect(pill).toHaveCount(0);
        else {
          await expect(pill).toBeVisible();
          await expect(page.getByRole('button', { name: 'Open Incoming engineer at Synthetic Labs', exact: true })).toHaveCount(0);
          await pill.click();
          await expect(page.getByRole('button', { name: 'Open Incoming engineer at Synthetic Labs', exact: true })).toBeVisible();
          await expect(pill).toHaveCount(0);
        }
      } else {
        await open.click();
        const drawer = page.getByRole('dialog');
        await expect(drawer).toBeVisible();
        if (flow === 'a') {
          const status = drawer.getByRole('combobox', { name: 'Application status' });
          await expect(status).toHaveText('Seen');
          await page.waitForTimeout(400);
          const before = { ...state };
          await status.click();
          await page.getByRole('option', { name: 'Applied', exact: true }).click();
          await expect(status).toHaveText('Applied');
          await page.waitForTimeout(500);
          expect(state.patches - before.patches).toBe(1);
          expect(state.listReads - before.listReads).toBe(0);
        } else {
          await expect(page.locator('[data-job-description]')).toBeFocused();
          await page.keyboard.press('Escape');
          await expect(drawer).toHaveCount(0);
        }
      }
      results.push({ flow, repeat, passed: true, ms: Math.round(performance.now() - began) });
    } catch (error) {
      results.push({ flow, repeat, passed: false, ms: Math.round(performance.now() - began), error: String(error) });
    } finally { await context.close(); }
  }
  console.log(JSON.stringify({ results, wallMs: Math.round(performance.now() - started) }, null, 2));
  if (results.some(row => !row.passed)) process.exitCode = 1;
} finally {
  await browser?.close();
  server.kill('SIGTERM');
  await new Promise(ok => server.once('exit', ok));
}
