import assert from 'node:assert/strict';
import { test } from 'node:test';
import { globeDiameterRatio, routeFixtureExternal, isFixtureLogo404 } from '../browser-tests/globe-fixture.mjs';

function pixels(background: number[], diameter: number) {
  const width = 200, height = 100, channels = 3;
  const data = Buffer.alloc(width * height * channels);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const color = Math.abs(x - width / 2) < diameter / 2 ? [100, 150, 180] : background;
    data.set(color, (y * width + x) * channels);
  }
  return { data, info: { width, height, channels } };
}
for (const background of [[8, 15, 28], [229, 238, 246]]) {
  test(`diameter measures geography against rendered space ${background}`, () => {
    const { data, info } = pixels(background, 80);
    assert.ok(Math.abs(globeDiameterRatio(data, info) - .8) < .03);
    // Browser screenshots round fractional CSS bounds out into the page background.
    data.set([255, 255, 255], (Math.floor(info.height / 2) * info.width + info.width - 1) * info.channels);
    assert.ok(Math.abs(globeDiameterRatio(data, info) - .8) < .03);
    const blank = pixels(background, 0);
    assert.equal(globeDiameterRatio(blank.data, blank.info), 0);
    const small = pixels(background, 40);
    assert.ok(globeDiameterRatio(small.data, small.info) < .7, 'undersized globe still fails the layout bound');
    const oversized = pixels(background, 140);
    assert.ok(globeDiameterRatio(oversized.data, oversized.info) > 1.05, 'oversized globe still fails the layout bound');
  });
}
for (const background of [[8, 15, 28], [229, 238, 246]]) {
  test(`near-full-width globe keeps space as its reference ${background}`, () => {
    const width = 200, height = 200, channels = 3;
    const data = Buffer.alloc(width * height * channels);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const color = Math.hypot(x - 100, y - 100) < 98 ? [100, 150, 180] : background;
      data.set(color, (y * width + x) * channels);
    }
    assert.ok(Math.abs(globeDiameterRatio(data, { width, height, channels }) - .98) < .02);
  });
}
test('logo fixture is a synthetic 404; other external hosts stay blocked', async () => {
  const calls: unknown[] = [];
  const route = { fulfill: (value: unknown) => calls.push(value), abort: () => calls.push('abort'), continue: () => calls.push('continue') };
  await routeFixtureExternal(route, new URL('https://img.logo.dev/example.test?token=pk_synthetic'));
  assert.deepEqual(calls, [{ status: 404, body: '' }]);
  calls.length = 0;
  await routeFixtureExternal(route, new URL('https://img.logo.dev.evil.test/example.test'));
  await routeFixtureExternal(route, new URL('https://basemaps.cartocdn.com/style.json'));
  assert.deepEqual(calls, ['abort', 'continue']);
});
test('only the expected logo 404 console message is exempt', () => {
  const message = (url: string, text: string) => ({ location: () => ({ url }), text: () => text });
  const text = 'Failed to load resource: the server responded with a status of 404 (Not Found)';
  assert.equal(isFixtureLogo404(message('https://img.logo.dev/example.test', text)), true);
  assert.equal(isFixtureLogo404(message('http://127.0.0.1:4387/api/jobs', text)), false);
  assert.equal(isFixtureLogo404(message('https://img.logo.dev/example.test', 'Unexpected runtime error')), false);
});
