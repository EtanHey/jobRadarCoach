// Synthetic regression on the real JobBoard/useGlobeData, via the capped runner.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4325";
assert.equal(new URL(base).hostname, "127.0.0.1");
const output = process.env.GLOBE_QA_OUTPUT;
assert.ok(output, "Set GLOBE_QA_OUTPUT for screenshot evidence");
await mkdir(output, { recursive: true });
const fixtureJob = n => ({ id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
  title: `Lifecycle engineer ${n}`, company: `Fixture ${n}`, source: "fixture",
  last_seen_at: "2026-09-22T00:00:00Z", first_seen_at: "2026-09-22T00:00:00Z",
  experience: null, description_available: false, seniority_origin: "title", extraction_state: "not-extracted",
  location: "Rehovot, Israel", remote: true, seniority: "Junior", stack: ["React"], salary: null,
  url: "https://example.test", apply_url: null, posted_at: null, status: "new", status_reason: null,
  score: 85 - n, fit_line: null, recommendation: "apply", alive: true });
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const failures = [];
try {
  for (const mode of ["closed", "open"]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
    const page = await context.newPage();
    const jobs = [0, 1, 2].map(fixtureJob);
    const state = { holdAll: mode === "open", allRequested: false, allLists: 0, newRequests: 0 };
    let releaseAll;
    const heldAll = new Promise(resolve => { releaseAll = resolve; });
    const errors = [];
    try {
      page.on("pageerror", error => errors.push(error.message));
      await page.addInitScript(() => {
        window.EventSource = class {
          listeners = new Map();
          constructor() { window.fixtureEvents = this; }
          addEventListener(name, listener) { this.listeners.set(name, listener); }
          close() { this.listeners.clear(); }
        };
      });
      await page.route("**/api/**", async route => {
        const url = new URL(route.request().url());
        const isNew = url.searchParams.get("filter") === "new-for-me";
        const filtered = isNew ? jobs.filter(job => job.status === "new") : jobs;
        if (url.pathname === "/api/jobs") {
          if (!isNew) state.allLists += 1;
          return route.fulfill({ json: { jobs: filtered.slice(0, 2) } });
        }
        if (url.pathname === "/api/jobs/globe") {
          if (isNew) state.newRequests += 1;
          if (!isNew && state.holdAll) { state.allRequested = true; await heldAll; }
          return route.fulfill({ json: { jobs: filtered,
            points: filtered.map(job => ({ posting_id: job.id, lat: 31.9, lng: 34.8, precision: "city", source: "fixture", resolved_at: "2026-09-22T00:00:00Z" })),
            total_count: filtered.length, resolved_count: filtered.length, unresolved_count: 0, attribution: "fixture" } });
        }
        return route.fulfill({ status: 404, json: { error: "fixture only" } });
      });
      const card = n => page.locator(`article[data-posting-id="${jobs[n].id}"]`);
      const toggle = page.getByRole("button", { name: "Globe", exact: true });
      await page.goto(base);
      await expect(card(0)).toBeVisible();
      await toggle.click();
      await expect(card(2)).toBeVisible({ timeout: 30000 });
      // A server-side change excludes list and globe-only IDs from the next visit.
      jobs[0].status = "applied";
      jobs[2].status = "seen";
      if (mode === "closed") {
        await toggle.click();
        const before = state.newRequests;
        await toggle.click();
        await expect.poll(() => state.newRequests).toBeGreaterThan(before);
        await expect(card(0)).toBeVisible();
        await expect(card(2)).toBeVisible();
        await toggle.click();
      }
      await page.getByRole("button", { name: "All roles", exact: true }).click();
      if (mode === "open") await expect.poll(() => state.allRequested).toBe(true);
      // Refresh All roles before returning, clearing master’s old list cache while
      // all globe responses remain held. Only the old globe cohort can resurrect.
      await page.evaluate(() => window.fixtureEvents.listeners.get("refresh")());
      await expect.poll(() => state.allLists).toBeGreaterThanOrEqual(2);
      await page.getByRole("button", { name: "New for me", exact: true }).click();
      if (mode === "closed") {
        await expect(card(0)).toHaveCount(0);
        await toggle.click();
      }
      await expect(card(1)).toBeVisible();
      await expect(card(0)).toHaveCount(0);
      await expect(card(2)).toHaveCount(0);
      await expect(page.getByRole("region", { name: "Job search" }).getByText("1 on the globe · 0 without a location", { exact: true })).toBeVisible();
      await page.screenshot({ path: `${output}/${mode}-reset.png` });
      assert.deepEqual(errors, []);
      console.log(`PASS: ${mode} globe resets on leaving New for me; same-visit toggle retains cards.`);
    } catch (error) {
      failures.push(`${mode}: ${error.message}`);
      console.log(`FAIL: ${mode}: ${error.message.slice(0, 700)}`);
    } finally {
      releaseAll();
      await context.close();
    }
  }
  assert.deepEqual(failures, []);
} finally { await browser.close(); }
