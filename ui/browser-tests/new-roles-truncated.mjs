// A truncated new-roles page whose sampled postings are all hidden by the view must still offer Show.
// Real local JobBoard, synthetic APIs, Playwright clock. Run only through run-suite-capped.sh.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4390";
assert.equal(new URL(base).hostname, "127.0.0.1");
const output = process.env.GLOBE_QA_OUTPUT;
assert.ok(output, "Set GLOBE_QA_OUTPUT for screenshots");
await mkdir(output, { recursive: true });
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const job = (n, overrides = {}) => ({ id: id(n),
  title: `Truncated engineer ${n}`, company: `Fixture ${n}`, source: "fixture",
  last_seen_at: "2026-10-05T08:00:00Z", first_seen_at: "2026-10-05T08:00:00Z",
  experience: null, description_available: false, seniority_origin: "title", extraction_state: "not-extracted",
  location: "Rehovot, Israel", remote: true, seniority: "Junior", stack: ["React"], salary: null,
  url: "https://example.test", apply_url: null, posted_at: null, status: "new", status_reason: null,
  score: 90, fit_line: null, recommendation: "apply", alive: true, ...overrides });
// `hidden` arrivals newest-first (hidden by the default "recommended" fit), then one matching role.
const arrivals = hidden => Array.from({ length: hidden + 1 }, (_, n) => job(n + 1, {
  first_seen_at: `2026-10-05T09:00:00.${String(1000 - n).padStart(6, "0")}+00:00`,
  ...(n < hidden ? { score: 20, recommendation: "skip" } : {}),
}));
const cases = [
  { name: "sentinel-match", hidden: 100, viewport: { width: 1280, height: 900 }, colorScheme: "light" },
  { name: "beyond-sentinel-match", hidden: 140, viewport: { width: 390, height: 844 }, colorScheme: "dark" },
];
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const failures = [];
try {
  for (const item of cases) {
    const context = await browser.newContext({ viewport: item.viewport, colorScheme: item.colorScheme, reducedMotion: "reduce" });
    const page = await context.newPage();
    const errors = [];
    const rows = arrivals(item.hidden);
    const match = rows.at(-1);
    let published = false;
    try {
      page.on("pageerror", error => errors.push(error.message));
      await page.clock.install();
      await page.route("**/api/**", route => {
        const url = new URL(route.request().url());
        if (url.pathname !== "/api/jobs") return route.fulfill({ status: 404, json: { error: "fixture only" } });
        const since = url.searchParams.get("since");
        const all = (published ? [...rows, job(0)] : [job(0)]).filter(row => !since || row.first_seen_at > since);
        return route.fulfill({ json: { jobs: all.slice(0, Number(url.searchParams.get("limit") ?? 50)) } });
      });
      await page.goto(base);
      await expect(page.locator("article[data-posting-id]")).toHaveCount(1);
      published = true;
      const polled = page.waitForResponse(response => new URL(response.url()).searchParams.has("since"));
      await page.clock.runFor(91_000);
      await polled;
      const pill = page.locator("[data-new-roles]");
      await expect(pill).toHaveText("New roles may be available·Show");
      await page.screenshot({ path: `${output}/${item.name}-notice.png` });
      await pill.click();
      await expect(page.locator(`article[data-posting-id="${match.id}"]`)).toBeVisible();
      await expect(page.locator("article[data-posting-id]")).toHaveCount(2);
      await expect(pill).toHaveCount(0);
      await page.screenshot({ path: `${output}/${item.name}-shown.png` });
      assert.deepEqual(errors, []);
      console.log(`${item.name}: PASS ${item.hidden} hidden arrivals + 1 match → notice; Show reveals the match`);
    } catch (error) { failures.push(`${item.name}: ${error.message}`); console.log(`FAIL ${item.name}: ${error.message.slice(0, 400)}`); }
    finally { await context.close(); }
  }
  assert.deepEqual(failures, []);
} finally { await browser.close(); }
