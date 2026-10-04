// Per-device memory of Logo.dev lookups that returned nothing. Logo.dev counts 404s against the free plan's hard monthly
// cap and sends no cache headers on them, so without this every page view re-asks for the same missing logos.
// Hits need no entry: image responses carry Cache-Control max-age=86400 (logo.dev/docs/platform/caching), and storing
// image bytes ourselves is a paid-plan license (logo.dev/docs/platform/self-hosting). Only lookup outcomes live here.

export const LOGO_MISS_STORAGE_KEY = "job-radar.logo-misses.v1";
export const LOGO_MISS_LIMIT = 1000;
const DAY = 24 * 60 * 60 * 1000;
// First miss: one day, so a 202 "still indexing" or a network blip retries tomorrow. Repeat miss: 30 days.
const FIRST_MISS_TTL = DAY;
const REPEAT_MISS_TTL = 30 * DAY;

type Entry = { at: number; strikes: number };
type MissStorage = { getItem(key: string): string | null; setItem(key: string, value: string): void };
export type LogoMissCache = { isMiss(src: string): boolean; recordMiss(src: string): void; recordHit(src: string): void };

/** The Logo.dev lookup a URL makes (path only), so neither the token nor a key rotation leaks into or resets the cache. */
export function logoMissKey(src: string): string | null {
  try {
    const url = new URL(src);
    return url.hostname === "img.logo.dev" ? url.pathname : null;
  } catch {
    return null;
  }
}

const ttl = (entry: Entry) => entry.strikes >= 2 ? REPEAT_MISS_TTL : FIRST_MISS_TTL;

export function createLogoMissCache(storage: MissStorage | null, now: () => number = Date.now): LogoMissCache {
  const read = (): Record<string, Entry> => {
    try {
      const parsed: unknown = JSON.parse(storage?.getItem(LOGO_MISS_STORAGE_KEY) ?? "{}");
      return parsed && typeof parsed === "object" ? parsed as Record<string, Entry> : {};
    } catch {
      return {};
    }
  };
  let entries = read();
  const write = (change: (current: Record<string, Entry>) => void) => {
    // Merge with what other tabs stored since we loaded, then keep the newest LOGO_MISS_LIMIT unexpired entries.
    const merged = { ...entries, ...read() };
    change(merged);
    const time = now();
    entries = Object.fromEntries(Object.entries(merged)
      .filter(([, entry]) => time - entry.at < REPEAT_MISS_TTL)
      .sort(([, a], [, b]) => b.at - a.at)
      .slice(0, LOGO_MISS_LIMIT));
    try { storage?.setItem(LOGO_MISS_STORAGE_KEY, JSON.stringify(entries)); } catch { /* blocked storage: keep this page's memory only */ }
  };
  return {
    isMiss(src) {
      const key = logoMissKey(src);
      const entry = key ? entries[key] : undefined;
      return entry !== undefined && now() - entry.at < ttl(entry);
    },
    recordMiss(src) {
      const key = logoMissKey(src);
      if (key) write(current => { current[key] = { at: now(), strikes: (current[key]?.strikes ?? 0) + 1 }; });
    },
    recordHit(src) {
      const key = logoMissKey(src);
      if (key && entries[key]) write(current => { delete current[key]; });
    },
  };
}

let browserCache: LogoMissCache | null | undefined;
/** The page-wide cache backed by localStorage; null on the server or when storage is unavailable. */
export function browserLogoMissCache(): LogoMissCache | null {
  if (browserCache !== undefined) return browserCache;
  try {
    browserCache = typeof window === "undefined" ? null : createLogoMissCache(window.localStorage);
  } catch {
    browserCache = createLogoMissCache(null);
  }
  return browserCache;
}
