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
