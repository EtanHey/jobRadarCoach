// Shared synthetic browser-fixture helpers; never use in the application.
export function globeDiameterRatio(data, { width, height, channels }) {
  const row = Math.floor(height / 2), hits = [];
  // #363 themes space. Sample the empty corner instead of assuming dark RGB.
  const background = data.subarray((12 * width + 12) * channels, (12 * width + 12) * channels + 3);
  // Fractional CSS widths round screenshot bounds outward by one raster pixel.
  for (let x = 1; x < width - 1; x++) {
    const offset = (row * width + x) * channels;
    if (Math.abs(data[offset] - background[0]) + Math.abs(data[offset + 1] - background[1]) + Math.abs(data[offset + 2] - background[2]) > 10) hits.push(x);
  }
  return hits.length ? (hits.at(-1) - hits[0]) / Math.min(width, height) : 0;
}
export function routeFixtureExternal(route, url) {
  if (url.hostname === 'img.logo.dev') return route.fulfill({ status: 404, body: '' });
  return url.hostname.endsWith('.cartocdn.com') ? route.continue() : route.abort();
}
export function isFixtureLogo404(message) {
  try {
    return new URL(message.location().url).hostname === 'img.logo.dev'
      && /^Failed to load resource: the server responded with a status of 404 /.test(message.text());
  } catch { return false; }
}
