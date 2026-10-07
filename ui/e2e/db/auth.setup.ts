import { test, expect } from '@playwright/test';
import { email } from './local.mjs';

test('sign in through real owner recovery and callback', async ({ page, request }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login/);
  expect((await request.get('/api/jobs')).status()).toBe(401);
  await request.delete('http://127.0.0.1:55434/api/v1/messages');
  const recovery = page.waitForResponse(response => new URL(response.url()).pathname === '/auth/recovery');
  await page.getByRole('button', { name: 'Send setup or recovery link' }).click();
  const sent = await recovery;
  expect(sent.status()).toBe(202);
  await expect(page.getByRole('status')).toHaveText('Recovery link sent to the configured owner inbox.');
  let id = '';
  await expect.poll(async () => {
    const inbox = await (await request.get('http://127.0.0.1:55434/api/v1/messages')).json();
    id = inbox.messages.find((message: { ID: string; To: { Address: string }[] }) => message.To.some(to => to.Address === email))?.ID ?? '';
    return id;
  }).not.toBe('');
  const mail = await (await request.get(`http://127.0.0.1:55434/api/v1/message/${id}`)).json();
  const link = mail.HTML.match(/href="([^"]+)"/)?.[1]?.replaceAll('&amp;', '&');
  expect(new URL(link).origin).toBe('https://127.0.0.1:55431');
  await page.goto(link);
  await expect(page.getByRole('heading', { name: 'Your roles' })).toBeVisible();
  await page.context().storageState({ path: '.e2e/db-auth.json' });
});
