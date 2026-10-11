// Run with npm run test:ui-polish (e2e/cap.sh); app and headless shell share the cap.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { resolve } from 'node:path';
import { chromium, expect } from '@playwright/test';
const output = resolve(process.env.GLOBE_QA_OUTPUT ?? '.e2e/ui-polish');
await mkdir(output, { recursive: true });
const reservation = createServer();
await new Promise(ok => reservation.listen(0, '127.0.0.1', ok));
const port = String(reservation.address().port);
await new Promise(ok => reservation.close(ok));
const base = `http://127.0.0.1:${port}`;
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => /^(PATH|HOME|TMPDIR|TMP|TEMP|PLAYWRIGHT_BROWSERS_PATH)$/.test(key)));
const startup = (await readFile('e2e/start-app.mjs', 'utf8')).replace("resolve('.e2e/app')", "resolve('.e2e/ui-polish-app')").replace('process.argv[2]', JSON.stringify(port));
const app = spawn(process.execPath, ['--input-type=module', '-e', startup], { env: { ...env, NEXT_TELEMETRY_DISABLED: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
let log = '';
app.stdout.on('data', data => { log += data; });
app.stderr.on('data', data => { log += data; });
let browser;
const receipts = [], failures = [];
const role = { id: '00000000-0000-4000-8000-000000000001', title: 'Fixture engineer', company: 'Synthetic Labs',
  source: 'fixture', last_seen_at: '2026-10-07T00:00:00Z', first_seen_at: '2026-10-07T00:00:00Z',
  posted_at: null, experience: null, description_available: false, seniority_origin: 'title', extraction_state: 'not-extracted',
  location: 'Rehovot, Israel', remote: true, seniority: 'Junior', stack: ['React'], salary: null,
  url: 'https://example.test', apply_url: null, status: 'interview_technical', status_reason: null,
  score: 1, fit_line: null, recommendation: 'apply', alive: true };
const check = async (name, action) => { try { await action(); } catch (error) { failures.push(`${name}: ${error.message}`); } };
try {
  const deadline = Date.now() + 120_000;
  while (true) {
    try { if (log.includes('Ready in') && (await fetch(base)).ok) break; } catch {}
    if (app.exitCode !== null || Date.now() > deadline) throw new Error(`Fixture startup failed: ${log}`);
    await new Promise(ok => setTimeout(ok, 300));
  }
  browser = await chromium.launch({ headless: true, channel: 'chromium-headless-shell', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  for (const width of [1440, 1280, 1100, 900, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.addInitScript(() => {
      window.EventSource = class { addEventListener() {} close() {} };
      localStorage.clear();
    });
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith('/style.json')) return route.fulfill({ json: { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#143047' } }] } });
      if (url.origin !== base) return route.fulfill({ status: 200, body: '' });
      if (url.pathname === '/api/jobs/globe') return route.fulfill({ json: { jobs: [role], points: [{ posting_id: role.id, lat: 31.8928, lng: 34.8113, precision: 'city', source: 'fixture', resolved_at: '2026-10-07T00:00:00Z' }], total_count: 1, resolved_count: 1, unresolved_count: 0, attribution: 'Synthetic fixture' } });
      if (url.pathname === '/api/jobs/sources') return route.fulfill({ json: { sources: [role.source] } });
      if (url.pathname === '/api/jobs') return route.fulfill({ json: { jobs: url.searchParams.has('since') ? [] : [role] } });
      if (url.pathname.startsWith('/api/')) return route.fulfill({ status: 200, json: {} });
      return route.continue();
    });
    try {
      await page.goto(base);
      await expect(page.locator('[data-posting-id]')).toHaveCount(1);
      const toolbar = page.locator('[data-job-toolbar]');
      const toggle = toolbar.getByRole('button', { name: /Filters/ }).filter({ visible: true });
      await check(`${width} singular heading`, () => expect(page.locator('.board-heading-regular-meta').first()).toHaveText('1 role'));
      await check(`${width} tab help`, async () => {
        for (const label of ['All roles', 'New for me', 'Seen', 'Not scored']) {
          const tab = page.getByRole('button', { name: label, exact: true });
          await expect(tab).toHaveAttribute('title', /.+/);
          await expect(tab).toHaveAccessibleDescription(/.+/);
        }
      });
      await check(`${width} full low-score status`, async () => {
        const chip = page.locator('[data-card-status]');
        assert.ok(await chip.evaluate(node => node.scrollHeight <= node.clientHeight + 1), 'status text must not be clipped');
        assert.ok(await chip.evaluate(node => node.clientHeight <= 30), 'Technical interview must fit legibly in two lines');
      });
      // Fresh storage must open New for me without treating its defaults as filters.
      await expect(page.getByRole('button', { name: 'New for me', exact: true })).toHaveAttribute('aria-pressed', 'true');
      if (width >= 768) await toggle.click();
      await check(`${width} fresh default chips and badge`, async () => {
        await expect(toggle).toHaveText('Filters');
        await expect(toolbar.getByRole('button', { name: /^Clear / }).filter({ visible: true })).toHaveCount(0);
      });
      await page.screenshot({ path: `${output}/default-${width}.png`, fullPage: true });
      await toggle.click();
      const controls = width < 768 ? page.getByRole('dialog') : toolbar;
      await controls.getByRole('combobox', { name: 'Sort', exact: true }).click();
      await page.getByRole('option', { name: 'Recently found', exact: true }).click();
      if (width < 768) await expect(controls).toContainText('0 active filters.');
      else await expect(toggle).toHaveText('Filters');
      await controls.getByRole('combobox', { name: 'Location', exact: true }).click();
      await page.getByRole('option', { name: 'Israel', exact: true }).click();
      await controls.getByRole('group', { name: 'Found in the past' }).getByRole('button', { name: '7 d', exact: true }).click();
      if (width < 768) {
        await expect(controls).toContainText('2 active filters.');
        await expect(controls.getByRole('combobox', { name: 'Location', exact: true })).toHaveText('Israel');
        await page.screenshot({ path: `${output}/filters-${width}.png` });
        await controls.getByRole('button', { name: 'Show roles', exact: true }).click();
      }
      else {
        if (width <= 1280) {
          const rows = await toolbar.locator('[role=combobox], summary, button').evaluateAll(nodes => [...new Set(nodes.filter(n => n.checkVisibility()).map(n => Math.round(n.getBoundingClientRect().bottom)))].length);
          assert.ok(rows <= 2, `${width}px expanded filters: ${rows} rows`);
        }
        await toggle.click();
      }
      await check(`${width} active chips`, async () => {
        await expect(toggle).toContainText('2');
        await expect(toolbar.getByRole('button', { name: 'Clear Location: Israel', exact: true }).filter({ visible: true })).toBeVisible();
        await expect(toolbar.getByRole('button', { name: 'Clear Found: past 7 days', exact: true }).filter({ visible: true })).toBeVisible();
      });
      await page.screenshot({ path: `${output}/polish-${width}.png`, fullPage: true });
      await check(`${width} Not scored archive chips`, async () => {
        let archiveUrl;
        page.on('request', req => { if (req.url().includes('/api/jobs?') && new URL(req.url()).searchParams.get('filter') === 'not-scored') archiveUrl = req.url(); });
        await page.getByRole('button', { name: 'Not scored', exact: true }).click();
        await expect(page.getByRole('button', { name: 'Not scored', exact: true })).toHaveAttribute('aria-pressed', 'true');
        await expect.poll(() => archiveUrl).toBeTruthy();
        const chips = await toolbar.getByRole('button', { name: /^Clear / }).filter({ visible: true }).allTextContents();
        assert.ok(!chips.some(label => label.startsWith('Found:')), 'archive ignores found_within but displays it as an active filter');
        await expect(toggle).toHaveText('Filters1 active');
        assert.deepEqual(chips, ['Location: Israel']);
      });
      await page.getByRole('button', { name: 'All roles', exact: true }).click();
      await check(`${width} independent clear`, async () => {
        await toolbar.getByRole('button', { name: 'Clear Location: Israel', exact: true }).filter({ visible: true }).click({ timeout: 1500 });
        await expect(toggle).toContainText('1');
        await expect(toolbar.getByRole('button', { name: 'Clear Found: past 7 days', exact: true }).filter({ visible: true })).toBeVisible();
        await toolbar.getByRole('button', { name: 'Clear Found: past 7 days', exact: true }).filter({ visible: true }).click();
        await expect(toggle).toHaveText('Filters');
      });
      await check(`${width} archive availability, clear and restore`, async () => {
        await toggle.click();
        await controls.getByRole('combobox', { name: 'Availability', exact: true }).click();
        await page.getByRole('option', { name: 'Inactive', exact: true }).click();
        await controls.getByRole('combobox', { name: 'Location', exact: true }).click();
        await page.getByRole('option', { name: 'Israel', exact: true }).click();
        await controls.getByRole('group', { name: 'Found in the past' }).getByRole('button', { name: '7 d', exact: true }).click();
        if (width < 768) await controls.getByRole('button', { name: 'Show roles', exact: true }).click();
        else await toggle.click();
        await expect(toggle).toHaveText('Filters3 active');
        await page.getByRole('button', { name: 'Not scored', exact: true }).click();
        await expect(toggle).toHaveText('Filters1 active');
        const activeChips = toolbar.getByRole('button', { name: /^Clear / }).filter({ visible: true });
        await expect(activeChips).toHaveCount(1);
        await expect(activeChips).toHaveText('Location: Israel');
        await activeChips.click();
        await expect(toggle).toHaveText('Filters');
        const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('job-radar.board-preferences')));
        assert.equal(saved.view.availability, 'inactive');
        assert.equal(saved.view.found_within, '7d');
        assert.equal(saved.view.location, '');
        await page.screenshot({ path: `${output}/archive-cleared-${width}.png`, fullPage: true });
        await page.getByRole('button', { name: 'All roles', exact: true }).click();
        await expect(toggle).toHaveText('Filters2 active');
        await expect(toolbar.getByRole('button', { name: 'Clear Availability: Inactive', exact: true }).filter({ visible: true })).toBeVisible();
        await expect(toolbar.getByRole('button', { name: 'Clear Found: past 7 days', exact: true }).filter({ visible: true })).toBeVisible();
        await toolbar.getByRole('button', { name: 'Clear Availability: Inactive', exact: true }).filter({ visible: true }).click();
        await toolbar.getByRole('button', { name: 'Clear Found: past 7 days', exact: true }).filter({ visible: true }).click();
        await expect(toggle).toHaveText('Filters');
      });
      await check(`${width} per-tab defaults and fit clear`, async () => {
        for (const label of ['Seen', 'Not scored', 'All roles', 'New for me']) {
          await page.getByRole('button', { name: label, exact: true }).click();
          await expect(toggle).toHaveText('Filters');
          await expect(toolbar.getByRole('button', { name: /^Clear / }).filter({ visible: true })).toHaveCount(0);
        }
        await toggle.click();
        await controls.getByRole('combobox', { name: 'Fit', exact: true }).click();
        await page.getByRole('option', { name: 'Any fit', exact: true }).click();
        if (width < 768) await controls.getByRole('button', { name: 'Show roles', exact: true }).click();
        else await toggle.click();
        await expect(toggle).toHaveText('Filters1 active');
        await toolbar.getByRole('button', { name: 'Clear Fit: Any fit', exact: true }).filter({ visible: true }).click();
        await expect(toggle).toHaveText('Filters');
        await expect(page.getByRole('button', { name: 'New for me', exact: true })).toHaveAttribute('aria-pressed', 'true');
        const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('job-radar.board-preferences')));
        assert.equal(saved.view.fit, 'recommended');
      });
      if (width === 1440) await check('headless globe renders synthetic point without WebGL errors', async () => {
        await page.getByRole('button', { name: 'Globe', exact: true }).click();
        await expect(page.locator('[data-projection="globe"]')).toBeVisible({ timeout: 30000 });
        await expect(page.locator('.maplibregl-canvas')).toBeVisible();
        await expect(page.locator('#globe-visible-heading')).toHaveText('On screen');
        await expect(page.locator('[data-posting-id]')).toHaveCount(1);
        await page.screenshot({ path: `${output}/globe-smoke.png` });
      });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'no horizontal overflow');
      assert.deepEqual(errors, []);
      receipts.push({ width, errors });
    } finally { await context.close(); }
  }
  console.log(JSON.stringify({ receipts, failures }));
  assert.deepEqual(failures, []);
} finally {
  await browser?.close();
  app.kill('SIGTERM');
  if (app.exitCode === null) await new Promise(ok => app.once('exit', ok));
  await writeFile(`${output}/app.log`, log);
  await writeFile(`${output}/receipts.json`, JSON.stringify({ receipts, failures }, null, 2));
}
