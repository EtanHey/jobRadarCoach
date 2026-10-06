import { test } from '@e2e-dev/web';
import { expect } from 'e2e';
import { installFixture, role, modelEnabled } from './fixture';

for (const hybrid of [false, true]) {
  const mode = hybrid ? 'hybrid' : 'deterministic';
  test(`a status: one PATCH and no list GET (${mode})`, async f => {
    test.skip(hybrid && !modelEnabled, 'No local/subscription model configured');
    const state = await installFixture(f.browser, f.app.baseUrl);
    await f.app.open('/');
    await expect(f.screen.getByRole('button', `Open ${role.title} at ${role.company}`)).toBeVisible();
    await f.screen.getByRole('button', `Open ${role.title} at ${role.company}`).tap();
    const status = f.screen.getByRole('combobox', 'Application status');
    await expect(status).toHaveText('Seen');
    await f.browser.evaluate(() => new Promise<null>(resolve => setTimeout(() => resolve(null), 400)));
    const before = { ...state };
    if (hybrid) await f.agent.act('Change Application status to Applied');
    else {
      await status.tap();
      await f.screen.getByRole('option', 'Applied').tap();
    }
    await expect(status).toHaveText('Applied');
    // Quiet window covers the 800 ms prefetch and 1500 ms delayed-refresh regression.
    await f.browser.evaluate(() => new Promise<null>(resolve => setTimeout(() => resolve(null), 3000)));
    expect(state.patches - before.patches).toBe(1);
    expect(state.listReads - before.listReads).toBe(0);
    if (hybrid) await f.agent.assert('The job drawer shows Application status Applied');
    expect(state.patches - before.patches).toBe(1);
    expect(state.listReads - before.listReads).toBe(0);
  });
  test(`c drawer: description focused and one Escape (${mode})`, async f => {
    test.skip(hybrid && !modelEnabled, 'No local/subscription model configured');
    await installFixture(f.browser, f.app.baseUrl);
    await f.app.open('/');
    const open = f.screen.getByRole('button', `Open ${role.title} at ${role.company}`);
    await expect(open).toBeVisible();
    if (hybrid) await f.agent.act(`Open the job ${role.title} at ${role.company}`);
    else await open.tap();
    await expect(f.screen.getByRole('dialog')).toBeVisible();
    await expect.poll(() => f.browser.evaluate(() => document.activeElement?.hasAttribute('data-job-description') ?? false)).toBe(true);
    await f.browser.keyboard.press('Escape');
    await expect(f.screen.getByRole('dialog')).toHaveCount(0);
    if (hybrid) await f.agent.assert('The job drawer is closed and the job board is visible');
  });
  for (const hidden of [false, true]) test(`${hidden ? 'd hidden' : 'b visible'} new role (${mode})`, async f => {
    test.skip(hybrid && !modelEnabled, 'No local/subscription model configured');
    const state = await installFixture(f.browser, f.app.baseUrl);
    await f.app.open('/');
    await expect(f.screen.getByRole('button', `Open ${role.title} at ${role.company}`)).toBeVisible();
    if (hidden) await f.screen.getByRole('textbox', /Search/).fill(role.title);
    state.addRole = true;
    await f.browser.evaluate(() => { const now = Date.now(); Date.now = () => now + 91_000; window.dispatchEvent(new Event('focus')); return null; });
    await expect.poll(() => state.pollReads).toBeGreaterThan(0);
    // Quiet window covers the 800 ms prefetch and 1500 ms delayed-refresh regression.
    await f.browser.evaluate(() => new Promise<null>(resolve => setTimeout(() => resolve(null), 3000)));
    const pill = f.browser.locator('[data-new-roles]');
    if (hidden) await expect(pill).toHaveCount(0);
    else {
      await expect(pill).toBeVisible();
      await expect(f.screen.getByRole('button', 'Open Incoming engineer at Synthetic Labs')).toHaveCount(0);
      if (hybrid) await f.agent.act('Show the new role using the new roles notice');
      else await pill.tap();
      await expect(f.screen.getByRole('button', 'Open Incoming engineer at Synthetic Labs')).toBeVisible();
      await expect(pill).toHaveCount(0);
    }
    if (hybrid) await f.agent.assert(hidden ? 'No new roles notice is visible' : 'Incoming engineer is visible and the new roles notice is gone');
    if (hidden) await expect(pill).toHaveCount(0);
  });
}
