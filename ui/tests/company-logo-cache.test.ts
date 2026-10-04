import assert from "node:assert/strict";
import { test } from "node:test";
import { createLogoMissCache, logoMissKey, LOGO_MISS_LIMIT, LOGO_MISS_STORAGE_KEY } from "../lib/company-logo-cache";

const DAY = 24 * 60 * 60 * 1000;
const url = (path: string, token = "pk_one") => `https://img.logo.dev/${path}?token=${token}&size=128&format=png&theme=light&fallback=404`;

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return { data, getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value); } };
}

test("the cache key is the lookup, never the token", () => {
  assert.equal(logoMissKey(url("name/Nowhere%20Widgets")), "/name/Nowhere%20Widgets");
  assert.equal(logoMissKey(url("acme.com", "pk_one")), logoMissKey(url("acme.com", "pk_rotated")));
  assert.equal(logoMissKey("/companies/wix.png"), null, "local catalog files are never cached as misses");
  assert.equal(logoMissKey("not a url"), null);
});

test("a first miss is remembered for a day, so 202-indexing or a blip retries tomorrow", () => {
  let now = 1_000_000;
  const storage = memoryStorage();
  const cache = createLogoMissCache(storage, () => now);
  assert.equal(cache.isMiss(url("acme.com")), false);
  cache.recordMiss(url("acme.com"));
  assert.equal(cache.isMiss(url("acme.com")), true);
  assert.equal(cache.isMiss(url("acme.com", "pk_rotated")), true, "a rotated key does not forget misses");
  now += DAY - 1;
  assert.equal(cache.isMiss(url("acme.com")), true);
  now += 2;
  assert.equal(cache.isMiss(url("acme.com")), false, "retry after a day");
});

test("a repeated miss is remembered for 30 days", () => {
  let now = 5_000_000;
  const cache = createLogoMissCache(memoryStorage(), () => now);
  cache.recordMiss(url("name/Nowhere"));
  now += DAY + 1;
  cache.recordMiss(url("name/Nowhere"));
  now += 29 * DAY;
  assert.equal(cache.isMiss(url("name/Nowhere")), true);
  now += DAY + 1;
  assert.equal(cache.isMiss(url("name/Nowhere")), false);
});

test("a successful load clears a remembered miss", () => {
  const cache = createLogoMissCache(memoryStorage(), () => 1);
  cache.recordMiss(url("acme.com"));
  cache.recordHit(url("acme.com"));
  assert.equal(cache.isMiss(url("acme.com")), false);
});

test("misses survive a reload and are shared through storage", () => {
  const storage = memoryStorage();
  createLogoMissCache(storage, () => 10).recordMiss(url("acme.com"));
  assert.match(storage.data.get(LOGO_MISS_STORAGE_KEY) ?? "", /acme\.com/);
  assert.doesNotMatch(storage.data.get(LOGO_MISS_STORAGE_KEY) ?? "", /pk_/, "the key is never written to storage");
  assert.equal(createLogoMissCache(storage, () => 20).isMiss(url("acme.com")), true);
});

test("storage stays bounded: expired entries go first, then the oldest", () => {
  let now = 0;
  const storage = memoryStorage();
  const cache = createLogoMissCache(storage, () => now);
  for (let n = 0; n < LOGO_MISS_LIMIT + 25; n += 1) { now += 1; cache.recordMiss(url(`name/Company${n}`)); }
  const stored = JSON.parse(storage.data.get(LOGO_MISS_STORAGE_KEY) ?? "{}");
  assert.equal(Object.keys(stored).length, LOGO_MISS_LIMIT);
  assert.equal(cache.isMiss(url("name/Company0")), false, "the oldest entries were dropped");
  assert.equal(cache.isMiss(url(`name/Company${LOGO_MISS_LIMIT + 24}`)), true);
});

test("broken or blocked storage never breaks logos", () => {
  const throwing = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  const cache = createLogoMissCache(throwing, () => 1);
  assert.doesNotThrow(() => cache.recordMiss(url("acme.com")));
  assert.equal(cache.isMiss(url("acme.com")), true, "still remembered for this page");
  const corrupt = createLogoMissCache(memoryStorage({ [LOGO_MISS_STORAGE_KEY]: "{not json" }), () => 1);
  assert.equal(corrupt.isMiss(url("acme.com")), false);
  assert.equal(createLogoMissCache(null, () => 1).isMiss(url("acme.com")), false);
});
