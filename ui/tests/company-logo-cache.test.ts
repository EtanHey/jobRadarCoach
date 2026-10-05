import assert from "node:assert/strict";
import { test } from "node:test";
import { confirmLogoMiss, createLogoMissCache, logoMissKey, LOGO_MISS_LIMIT, LOGO_MISS_STORAGE_KEY } from "../lib/company-logo-cache";

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

test("malformed entries in otherwise valid JSON are ignored, never thrown on", () => {
  const stored = { "/null.com": null, "/string.com": "x", "/number.com": 5, "/bad-at.com": { at: "soon", strikes: 1 },
    "/bad-strikes.com": { at: 1, strikes: "two" }, "/ok.com": { at: 1, strikes: 2 } };
  const storage = memoryStorage({ [LOGO_MISS_STORAGE_KEY]: JSON.stringify(stored) });
  const cache = createLogoMissCache(storage, () => 2);
  for (const path of ["null.com", "string.com", "number.com", "bad-at.com", "bad-strikes.com"]) {
    assert.doesNotThrow(() => cache.isMiss(url(path)), path);
    assert.equal(cache.isMiss(url(path)), false, path);
  }
  assert.equal(cache.isMiss(url("ok.com")), true, "well-formed entries survive");
  assert.doesNotThrow(() => cache.recordMiss(url("null.com")));
  assert.equal(cache.isMiss(url("null.com")), true);
  assert.deepEqual(Object.keys(JSON.parse(storage.data.get(LOGO_MISS_STORAGE_KEY) ?? "{}")).sort(), ["/null.com", "/ok.com"], "rewrites drop the junk");
  const array = createLogoMissCache(memoryStorage({ [LOGO_MISS_STORAGE_KEY]: "[1,2]" }), () => 2);
  assert.equal(array.isMiss(url("ok.com")), false);
});

test("non-object or unparsable stored JSON reads as an empty cache", () => {
  for (const raw of ["5", "\"str\"", "null", "true", "[1,2]", "{not json", ""]) {
    const cache = createLogoMissCache(memoryStorage({ [LOGO_MISS_STORAGE_KEY]: raw }), () => 2);
    assert.doesNotThrow(() => cache.isMiss(url("acme.com")), raw);
    assert.equal(cache.isMiss(url("acme.com")), false, raw);
    assert.doesNotThrow(() => cache.recordMiss(url("acme.com")), raw);
  }
});

test("only a confirmed provider 404 counts as a miss; transport and auth failures never do", async () => {
  const src = url("name/Nowhere%20Widgets");
  const fetchWith = (outcome: number | Error) => {
    const calls: Array<{ input: string; init?: RequestInit }> = [];
    const fetcher = async (input: string, init?: RequestInit) => {
      calls.push({ input, init });
      if (outcome instanceof Error) throw outcome;
      return new Response(null, { status: outcome });
    };
    return { calls, fetcher };
  };
  const notFound = fetchWith(404);
  assert.equal(await confirmLogoMiss(src, notFound.fetcher), true);
  assert.equal(notFound.calls[0].input, src);
  assert.equal(notFound.calls[0].init?.mode, "cors");
  assert.equal(notFound.calls[0].init?.method ?? "GET", "GET", "GET, not HEAD: a keyless HEAD 404s regardless, a GET reports the real status");
  for (const status of [200, 202, 401, 403, 429, 500, 503]) assert.equal(await confirmLogoMiss(src, fetchWith(status).fetcher), false, String(status));
  assert.equal(await confirmLogoMiss(src, fetchWith(new TypeError("Failed to fetch")).fetcher), false, "network/CORS failure");
  assert.equal(await confirmLogoMiss(src, null), false, "no host fetcher: nothing is ever confirmed");
  const local = fetchWith(404);
  assert.equal(await confirmLogoMiss("/companies/wix.png", local.fetcher), false);
  assert.equal(local.calls.length, 0, "never confirms non-Logo.dev URLs");
});
