// Synthetic real components/CSS; loopback only, no owner session or provider reads.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { build } from 'esbuild';
import postcss from 'postcss';
import tailwind from '@tailwindcss/postcss';
import { chromium, expect } from '@playwright/test';
const root = resolve(import.meta.dirname, '..'), output = process.env.GLOBE_QA_OUTPUT;
assert.ok(output, 'Set GLOBE_QA_OUTPUT for durable receipts');
await mkdir(output, { recursive: true });
const bundle = await build({ write: false, bundle: true, format: 'iife', jsx: 'automatic', tsconfig: resolve(root, 'tsconfig.json'),
  define: { 'process.env.NODE_ENV': '"production"', 'process.env': '{}' }, stdin: { resolveDir: root, loader: 'tsx', contents: `
import { createRoot } from 'react-dom/client';
import { useRef } from 'react';
import { JobCard } from './components/job-card';
const job = { id: '00000000-0000-4000-8000-000000000001', company: 'Synthetic employer', title: 'Frontend engineer', source: 'linkedin',
  location: 'Tel Aviv', remote: null, seniority: null, stack: [], salary: null, experience: null,
  url: 'https://example.test', apply_url: null, score: 70, status: 'new', status_reason: null, alive: false,
  fit_line: null, recommendation: 'review', last_seen_at: '2026-10-11T00:30:00Z', first_seen_at: '2026-10-10T12:00:00Z', posted_at: null,
  description_available: false, seniority_origin: 'unknown', extraction_state: 'not-extracted',
  linkedin_closed_signal: { phrase: 'no longer accepting applications', checked_at: '2026-10-11T00:30:00Z', url: 'https://www.linkedin.com/jobs/view/123' } };
function App() { const ref = useRef(null); return <main className='mx-auto max-w-xl p-4'><JobCard job={job} openerRef={ref} selectJob={() => {}}>{null}</JobCard></main>; }
createRoot(document.getElementById('root')).render(<App/>);` } });
const css = (await postcss([tailwind({ base: root })]).process(await readFile(resolve(root, 'app/globals.css'), 'utf8'), { from: resolve(root, 'app/globals.css') })).css;
const server = createServer((req, res) => {
  if (req.url === '/app.js') { res.setHeader('Content-Type', 'text/javascript'); return res.end(bundle.outputFiles[0].text); }
  if (req.url === '/style.css') { res.setHeader('Content-Type', 'text/css'); return res.end(css); }
  res.setHeader('Content-Type', 'text/html');
  res.end('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/style.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>');
});
await new Promise(ready => server.listen(0, '127.0.0.1', ready));
let browser;
const receipts = [];
try {
  browser = await chromium.launch({ headless: true });
  for (const [zone, date] of [['America/Los_Angeles', '2026-10-10'], ['Asia/Jerusalem', '2026-10-11']]) for (const width of [1280, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 650 }, timezoneId: zone });
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    const badge = page.locator('[data-linkedin-closed-signal]');
    await expect(badge).toHaveAttribute('title', `LinkedIn: no longer accepting applications · checked ${date}`);
    await expect(badge.locator('time')).toHaveText(date);
    await expect(badge).toHaveAttribute('href', 'https://www.linkedin.com/jobs/view/123');
    await badge.focus();
    await expect(badge).toBeFocused();
    const layout = await badge.evaluate(node => { const box = node.getBoundingClientRect();
      return { left: box.left, right: box.right, clipped: node.scrollWidth > node.clientWidth }; });
    assert.ok(layout.left >= 0 && layout.right <= width && !layout.clipped, JSON.stringify(layout));
    assert.deepEqual(errors, []);
    await page.screenshot({ path: `${output}/${zone.split('/')[1]}-${width}.png` });
    receipts.push({ zone, width, date, layout, errors });
    await context.close();
  }
  console.log(`PASS ${receipts.length} badge cases: local midnight, evidence link, keyboard focus and viewport bounds`);
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
  await writeFile(`${output}/receipt.json`, JSON.stringify(receipts, null, 2));
}
