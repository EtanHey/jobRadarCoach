import { test, expect } from '@playwright/test';

test('real database board, drawer, durable status and globe', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'All roles', exact: true }).click();
  const card = page.getByRole('button', { name: 'Open Frontend Engineer at Synthetic P12 Studio 1', exact: true });
  await expect(card).toBeVisible();
  await card.click();
  const drawer = page.getByRole('dialog');
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText('Synthetic local-only job description');
  const patch = page.waitForResponse(r => r.url().endsWith('/12000000-0000-4000-8000-000000000001/status') && r.request().method() === 'PATCH' && r.request().postDataJSON().status === 'applied');
  await page.getByRole('combobox', { name: 'Application status' }).click();
  await page.getByRole('option', { name: 'Applied', exact: true }).click();
  expect((await patch).status()).toBe(200);
  await page.reload();
  await card.click();
  await expect(page.getByRole('combobox', { name: 'Application status' })).toHaveText('Applied');
  const detail = await page.request.get('/api/jobs/12000000-0000-4000-8000-000000000001');
  expect((await detail.json()).job.status).toBe('applied');
  await page.keyboard.press('Escape');
  // Real toolbar -> Next route -> PostgREST -> SQL, including reverse transitions.
  for (const [label, value, option, count] of [
    ['Work mode', 'remote', 'Remote', 0], ['Work mode', 'on-site', 'On-site', 3],
    ['Location', 'united-states', 'United States', 0],
    ['Location', 'israel', 'Israel', 3], ['Seniority', 'Senior', 'Senior', 0],
    ['Seniority', 'Junior', 'Junior', 3],
  ] as const) {
    const response = page.waitForResponse(r => {
      const url = new URL(r.url());
      return url.pathname === '/api/jobs' && url.searchParams.get(label === 'Work mode' ? 'work_mode' : label.toLowerCase()) === value;
    });
    await page.getByRole('combobox', { name: label, exact: true }).click();
    await page.getByRole('option', { name: option, exact: true }).click();
    const reply = await response;
    expect(reply.status()).toBe(200);
    expect((await reply.json()).jobs).toHaveLength(count);
    await expect(page.getByRole('button', { name: /^Open .* at Synthetic P12 Studio/ })).toHaveCount(count);
  }
  await page.screenshot({ path: '.e2e/db-results/facets.png', fullPage: true });
  const globe = page.waitForResponse(r => new URL(r.url()).pathname === '/api/jobs/globe');
  await page.getByRole('button', { name: 'Globe', exact: true }).click();
  const response = await globe;
  expect(response.status()).toBe(200);
  expect((await response.json()).resolved_count).toBe(3);
  await expect(page.locator('.job-globe canvas')).toBeVisible();
  // Real CDN tiles and software WebGL can outlast Playwright's default five seconds.
  await expect(page.getByRole('group', { name: 'Globe controls' })).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: '.e2e/db-results/globe.png', fullPage: true });
});


test('source vocabulary survives direct switches, empty facets and saved views', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'All roles', exact: true }).click();
  const cards = page.getByRole('button', { name: /^Open .* at Synthetic P12 Studio/ });
  await expect(cards).toHaveCount(3);
  async function choose(label: string, option: string) {
    await page.getByRole('combobox', { name: label, exact: true }).click();
    await page.getByRole('option', { name: option, exact: true }).click();
  }
  async function sources() {
    await page.getByRole('combobox', { name: 'Source', exact: true }).click();
    for (const source of ['fixture', 'fixture-b', 'fixture-c']) {
      await expect(page.getByRole('option', { name: source, exact: true })).toBeVisible();
    }
    await page.keyboard.press('Escape');
  }
  await sources();
  await choose('Source', 'fixture');
  await expect(cards).toHaveCount(1);
  await sources();
  await choose('Source', 'fixture-b');
  await expect(page.getByRole('button', { name: 'Open Platform Engineer at Synthetic P12 Studio 2', exact: true })).toBeVisible();
  await choose('Work mode', 'Remote');
  await expect(cards).toHaveCount(0);
  await sources();
  await page.reload();
  await expect(page.getByRole('combobox', { name: 'Work mode', exact: true })).toHaveText('Remote');
  await sources();
  await choose('Source', 'fixture-c');
  await expect(cards).toHaveCount(0);
  await choose('Work mode', 'On-site');
  await expect(page.getByRole('button', { name: 'Open UI Engineer at Synthetic P12 Studio 3', exact: true })).toBeVisible();
  await choose('Source', 'All sources');
  await expect(cards).toHaveCount(3);
  await page.screenshot({ path: '.e2e/db-results/source-recovery.png', fullPage: true });
});
