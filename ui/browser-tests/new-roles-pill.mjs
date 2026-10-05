// No live sync: no SSE, no list GET after a status change, and a polled "N new roles · Show" pill.
// Real local JobBoard, synthetic APIs, Playwright clock. Run only through run-suite-capped.sh.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4390";
assert.equal(new URL(base).hostname, "127.0.0.1");
const output = process.env.GLOBE_QA_OUTPUT;
assert.ok(output, "Set GLOBE_QA_OUTPUT for screenshots");
await mkdir(output, { recursive: true });
const job = n => ({ id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
  title: `Pill engineer ${n}`, company: `Fixture ${n}`, source: "fixture",
  last_seen_at: "2026-10-05T08:00:00Z", first_seen_at: `2026-10-05T08:00:00.${String(n).padStart(6, "0")}+00:00`,
  experience: null, description_available: false, seniority_origin: "title", extraction_state: "not-extracted",
  location: "Rehovot, Israel", remote: true, seniority: "Junior", stack: ["React"], salary: null,
  url: "https://example.test", apply_url: null, posted_at: null, status: "new", status_reason: null,
  score: 90 - n, fit_line: null, recommendation: "apply", alive: true });
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const failures = [];
const scenarios = [
  { name: "desktop-light", viewport: { width: 1440, height: 1000 }, colorScheme: "light", full: true },
  { name: "phone-dark", viewport: { width: 390, height: 844 }, colorScheme: "dark", full: false },
];
try {
  for (const scenario of scenarios) {
    const context = await browser.newContext({ viewport: scenario.viewport, colorScheme: scenario.colorScheme, reducedMotion: "reduce" });
    const page = await context.newPage();
    const jobs = [0, 1, 2].map(job);
    const published = new Set(jobs.map(row => row.id));
    const log = [];
    const errors = [];
    try {
      page.on("pageerror", error => errors.push(error.message));
      await page.clock.install();
      await page.addInitScript(() => {
        window.sseOpened = 0;
        const Native = window.EventSource;
        window.EventSource = class extends Native { constructor(...args) { window.sseOpened += 1; super(...args); } };
      });
      await page.route("**/api/**", async route => {
        const request = route.request();
        const url = new URL(request.url());
        log.push(`${request.method()} ${url.pathname}${url.searchParams.has("ids") ? " ids" : ""}`);
        const visible = jobs.filter(row => published.has(row.id));
        const inFilter = rows => url.searchParams.get("filter") === "new-for-me" ? rows.filter(row => row.status === "new") : rows;
        if (url.pathname === "/api/jobs/new-count") {
          const since = url.searchParams.get("since");
          return route.fulfill({ json: { count: inFilter(visible).filter(row => row.first_seen_at > since).length } });
        }
        if (url.pathname === "/api/jobs") {
          const ids = url.searchParams.get("ids")?.split(",");
          return route.fulfill({ json: { jobs: structuredClone(ids ? jobs.filter(row => ids.includes(row.id)) : inFilter(visible)) } });
        }
        const row = jobs.find(candidate => url.pathname.startsWith(`/api/jobs/${candidate.id}`));
        if (!row) return route.fulfill({ status: 404, json: { error: "fixture only" } });
        if (url.pathname.endsWith("/status")) {
          const patch = request.postDataJSON();
          if (!patch.automatic || row.status === "new") row.status = patch.status;
          return route.fulfill({ json: { status: row.status, reason: null } });
        }
        return route.fulfill({ json: { job: { ...row, raw_jd: null, reasons: [], score_payload: null, brain: null, scored_at: null } } });
      });
      const card = n => page.locator(`article[data-posting-id="${jobs[n].id}"]`);
      const listReads = () => log.filter(line => line === "GET /api/jobs").length;
      const pill = page.locator("[data-new-roles]");
      // Two roles exist but are not yet published when the page loads.
      published.delete(jobs[1].id); published.delete(jobs[2].id);
      jobs.push(job(3), job(4));
      published.add(jobs[3].id); published.add(jobs[4].id);
      jobs[3].first_seen_at = "2026-10-05T07:00:00Z"; jobs[4].first_seen_at = "2026-10-05T07:00:01Z";
      await page.goto(base);
      await expect(card(0)).toBeVisible();
      await page.clock.runFor(2_000);
      assert.equal(await page.evaluate(() => window.sseOpened), 0, "the board opens no EventSource");
      assert.ok(!log.some(line => line.includes("/api/events")), "no /api/events request");
      if (scenario.full) {
        // Opening a card marks it Seen automatically; the PATCH reply is the whole update.
        const reads = listReads();
        await card(3).getByRole("button", { name: "Open Pill engineer 3 at Fixture 3", exact: true }).click();
        const status = page.getByRole("dialog").getByRole("combobox", { name: "Application status" });
        await expect(status).toHaveText("Seen");
        await page.clock.runFor(1_000);
        assert.equal(listReads(), reads, "automatic Seen does not GET the list");
        await status.click();
        await page.getByRole("option", { name: "Applied", exact: true }).click();
        await expect(status).toHaveText("Applied");
        await expect(card(3)).toHaveCount(0);
        await page.clock.runFor(1_000);
        assert.equal(listReads(), reads, "an explicit status change does not GET the list");
        await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
        await page.getByRole("dialog").waitFor({ state: "hidden" });
        // Seen stays in the visit cohort with the settled cue.
        await card(4).getByRole("button", { name: "Open Pill engineer 4 at Fixture 4", exact: true }).click();
        await expect(page.getByRole("dialog").getByRole("combobox", { name: "Application status" })).toHaveText("Seen");
        await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
        await page.getByRole("dialog").waitFor({ state: "hidden" });
        await expect(card(4)).toHaveAttribute("data-settled", "");
        assert.equal(listReads(), reads, "no list GET across the whole status flow");
      }
      await expect(pill).toHaveCount(0);
      const before = await card(0).boundingBox();
      published.add(jobs[1].id);
      const counted = page.waitForResponse(response => new URL(response.url()).pathname === "/api/jobs/new-count");
      await page.clock.runFor(91_000);
      await counted;
      await expect(pill).toHaveText("1 new role·Show");
      assert.deepEqual(await card(0).boundingBox(), before, "the pill does not shift the list");
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "no horizontal overflow");
      // Focus asks again after the quiet gap.
      published.add(jobs[2].id);
      await page.clock.runFor(16_000);
      const focused = page.waitForResponse(response => new URL(response.url()).pathname === "/api/jobs/new-count");
      await page.evaluate(() => window.dispatchEvent(new Event("focus")));
      await focused;
      await expect(pill).toHaveText("2 new roles·Show");
      await expect(page.getByRole("status").filter({ has: pill })).toHaveCount(1);
      await page.screenshot({ path: `${output}/${scenario.name}-pill.png` });
      await pill.focus();
      await page.keyboard.press("Shift+Tab");
      await page.keyboard.press("Tab");
      await expect(pill).toBeFocused();
      assert.equal(await pill.evaluate(element => element.matches(":focus-visible") && getComputedStyle(element).outlineStyle !== "none"), true, "keyboard focus shows a ring");
      await page.screenshot({ path: `${output}/${scenario.name}-pill-focus.png`, clip: { x: 0, y: 0, width: scenario.viewport.width, height: 420 } });
      const reads = listReads();
      await pill.click();
      await expect(card(1)).toBeVisible();
      await expect(card(2)).toBeVisible();
      await expect(pill).toHaveCount(0);
      assert.equal(listReads(), reads + 1, "Show loads the list once");
      if (scenario.full) assert.ok(log.includes("GET /api/jobs ids"), "the retained Seen card is hydrated by ID");
      await expect(page.getByRole("heading", { name: "Your roles", exact: true })).toBeFocused();
      if (scenario.full) {
        await expect(card(4)).toHaveAttribute("data-settled", "");
        await expect(card(3)).toHaveCount(0);
      }
      // After loading, nothing is newer than the list.
      await page.clock.runFor(91_000);
      await expect(pill).toHaveCount(0);
      await page.screenshot({ path: `${output}/${scenario.name}-shown.png` });
      assert.equal(await page.evaluate(() => window.sseOpened), 0);
      assert.deepEqual(errors, []);
      console.log(`${scenario.name}: PASS no SSE; ${scenario.full ? "auto-Seen + Applied with zero list GETs; " : ""}poll + focus pill; Show loads once and keeps the cohort`);
    } catch (error) { failures.push(`${scenario.name}: ${error.message}`); console.log(`FAIL ${scenario.name}: ${error.message.slice(0, 600)}`); }
    finally { await context.close(); }
  }
  assert.deepEqual(failures, []);
} finally { await browser.close(); }
