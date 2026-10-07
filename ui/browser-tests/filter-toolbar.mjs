// Run through docs.local/tools/run-suite-capped.sh; app and headless shell share the cap.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { chromium, expect } from '@playwright/test';
const output = resolve(process.env.GLOBE_QA_OUTPUT ?? '.e2e/filter-toolbar');
await mkdir(output, { recursive: true });
const reservation = createServer();
await new Promise(ok => reservation.listen(0, '127.0.0.1', ok));
const port = String(reservation.address().port);
await new Promise(ok => reservation.close(ok));
const base = `http://127.0.0.1:${port}`;
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => /^(PATH|HOME|TMPDIR|TMP|TEMP|PLAYWRIGHT_BROWSERS_PATH)$/.test(key)));
let startup = (await readFile('e2e/start-app.mjs', 'utf8')).replace("resolve('.e2e/app')", "resolve('.e2e/filter-toolbar-app')").replace('process.argv[2]', JSON.stringify(port));
if (process.env.FILTER_BASELINE === '1') {
  const baseline = execFileSync('git', ['show', `${process.env.FILTER_BASELINE_REF ?? '2e75fe32175fa9365f4dbb86a5fb1a184d11e151'}:ui/components/job-toolbar.tsx`], { encoding: 'utf8' });
  startup = startup.replace("const child = spawn(process.execPath, ['node_modules/next", `await writeFile(resolve(target, 'components/job-toolbar.tsx'), ${JSON.stringify(baseline)});\nconst child = spawn(process.execPath, ['node_modules/next`);
}
const app = spawn(process.execPath, ['--input-type=module', '-e', startup], { env: { ...env, NEXT_TELEMETRY_DISABLED: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
let log = '';
app.stdout.on('data', data => { log += data; });
app.stderr.on('data', data => { log += data; });
let browser;
const receipts = [], failures = [];
const role = { id: '00000000-0000-4000-8000-000000000001', title: 'Pilot engineer', company: 'Synthetic Labs',
  source: 'fixture', last_seen_at: '2026-10-04T00:00:00Z', first_seen_at: '2026-10-04T00:00:00Z',
  posted_at: '2026-09-01T00:00:00Z', last_published_at: '2026-10-03T00:00:00Z', experience: null,
  description_available: true, seniority_origin: 'title', extraction_state: 'not-extracted', location: 'Rehovot, Israel',
  remote: true, seniority: 'Junior', stack: ['React'], salary: null, url: 'https://example.test',
  apply_url: null, status: 'new', status_reason: null, score: 85, fit_line: null, recommendation: 'apply', alive: true };
try {
  const deadline = Date.now() + 120_000;
  while (true) {
    try { if (log.includes('Ready in') && (await fetch(base)).ok) break; } catch {}
    if (app.exitCode !== null || Date.now() > deadline) throw new Error(`Fixture startup failed: ${log}`);
    await new Promise(ok => setTimeout(ok, 300));
  }
  browser = await chromium.launch({ headless: true, channel: 'chromium-headless-shell' });
  for (const width of [1100, 900, 1440, 1280, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== base) return route.abort();
      if (url.pathname === '/api/jobs') return route.fulfill({ json: { jobs: url.searchParams.has("since") ? [] : [role] } });
      if (url.pathname.startsWith('/api/')) return route.fulfill({ status: 404, json: { error: 'Synthetic fixture only' } });
      return route.continue();
    });
    try {
      await page.goto(base);
      const toolbar = page.locator('[data-job-toolbar]');
      await expect(toolbar).toBeVisible();
      const rows = await toolbar.locator('[role=combobox], summary, button').evaluateAll(nodes => {
        const boxes = nodes.filter(node => node.checkVisibility()).map(node => node.getBoundingClientRect()).filter(box => box.width && box.height);
        return [...new Set(boxes.map(box => Math.round(box.bottom)))].length;
      });
      await page.screenshot({ path: `${output}/toolbar-${width}.png` });
      if (width >= 900) assert.ok(rows <= 2, `${width}px filter bar has ${rows} rows (max 2)`);
      if (process.env.FILTER_LAYOUT_ONLY !== '1') {
        const toggle = toolbar.getByRole('button', { name: /Filters/ });
        if (width >= 900) {
          await expect(toggle).toHaveAttribute('aria-expanded', 'true');
          await toggle.click();
          await expect(toolbar.getByRole('combobox')).toHaveCount(0);
          await expect(toggle).toHaveAttribute('aria-expanded', 'false');
          await page.reload();
          await expect(toggle).toHaveAttribute('aria-expanded', 'false');
          await toggle.click();
          await expect(toolbar.getByRole('combobox', { name: 'Location', exact: true })).toBeVisible();
          await page.reload();
          await expect(toggle).toHaveAttribute('aria-expanded', 'true');
          await toolbar.getByRole('combobox', { name: 'Seniority', exact: true }).click();
          await page.getByRole('option', { name: 'Hide senior+ (keep unknown)', exact: true }).click();
          await expect(toggle).toContainText('2');
          const wideRows = await toolbar.locator('[role=combobox], summary, button').evaluateAll(nodes => [...new Set(nodes.filter(node => node.checkVisibility()).map(node => Math.round(node.getBoundingClientRect().bottom)))].length);
          assert.ok(wideRows <= 2, `${width}px long-label layout has ${wideRows} rows`);
          await toggle.click();
          await toolbar.getByRole('button', { name: 'Reset view', exact: true }).click();
          await expect(toggle).toHaveAttribute('aria-expanded', 'true');
          await expect(toolbar.getByRole('combobox', { name: 'Seniority', exact: true })).toHaveText('All levels');
        } else {
          await toggle.click();
          const dialog = page.getByRole('dialog');
          await expect(dialog.getByRole('combobox', { name: 'Location', exact: true })).toBeVisible();
          await page.screenshot({ path: `${output}/toolbar-${width}-drawer.png` });
          await dialog.getByRole('button', { name: 'Show roles', exact: true }).click();
          await expect(toggle).toBeFocused();
        }
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'no horizontal overflow');
        assert.deepEqual(errors, []);
      }
      receipts.push({ width, rows });
    } catch (error) { failures.push(error.message); console.log(`FAIL: ${error.message}`); }
    finally { await context.close(); }
  }
  console.log(JSON.stringify(receipts));
  assert.deepEqual(failures, []);
} finally {
  await browser?.close();
  app.kill('SIGTERM');
  if (app.exitCode === null) await new Promise(ok => app.once('exit', ok));
  await writeFile(`${output}/app.log`, log);
  await writeFile(`${output}/receipts.json`, JSON.stringify({ receipts, failures }, null, 2));
}
