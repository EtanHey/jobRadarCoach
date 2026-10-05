// Real local JobBoard, synthetic APIs. Run only through run-suite-capped.sh.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4326";
assert.equal(new URL(base).hostname, "127.0.0.1");
const output = process.env.GLOBE_QA_OUTPUT;
assert.ok(output, "Set GLOBE_QA_OUTPUT for screenshots");
await mkdir(output, { recursive: true });
const job = n => ({ id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
  title: `Status engineer ${n}`, company: `Fixture ${n}`, source: "fixture",
  last_seen_at: "2026-09-22T00:00:00Z", first_seen_at: "2026-09-22T00:00:00Z",
  experience: null, description_available: false, seniority_origin: "title", extraction_state: "not-extracted",
  location: "Rehovot, Israel", remote: true, seniority: "Junior", stack: ["React"], salary: null,
  url: "https://example.test", apply_url: null, posted_at: null, status: "new", status_reason: null,
  score: 85 - n, fit_line: null, recommendation: "apply", alive: true });
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const failures = [];
try {
  for (const mode of ["list", "globe"]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
    const page = await context.newPage();
    const jobs = [0, 1].map(job);
    const state = { patches: 0, reads: 0, held: 0, hold: false };
    let release = null;
    const held = new Promise(resolve => { release = resolve; });
    const errors = [];
    try {
      page.on("pageerror", error => errors.push(error.message));
      await page.route("**/api/**", async route => {
        const url = new URL(route.request().url());
        if (url.pathname === "/api/jobs" || url.pathname === "/api/jobs/globe") {
          state.reads += 1;
          const ids = url.searchParams.get("ids")?.split(",");
          const filtered = ids ? jobs.filter(row => ids.includes(row.id)) : url.searchParams.get("filter") === "new-for-me" ? jobs.filter(row => row.status === "new") : jobs;
          const rows = structuredClone(filtered);
          const payload = url.pathname === "/api/jobs" ? { jobs: rows } : { jobs: rows,
            points: rows.map(row => ({ posting_id: row.id, lat: 31.9, lng: 34.8, precision: "city", source: "fixture", resolved_at: "2026-09-22T00:00:00Z" })),
            total_count: rows.length, resolved_count: rows.length, unresolved_count: 0, attribution: "fixture" };
          if (state.hold) { state.held += 1; await held; }
          return route.fulfill({ json: payload });
        }
        const row = jobs.find(candidate => url.pathname.startsWith(`/api/jobs/${candidate.id}`));
        if (!row) return route.fulfill({ status: 404, json: { error: "fixture only" } });
        if (url.pathname.endsWith("/status")) {
          state.patches += 1;
          const patch = route.request().postDataJSON();
          if (!patch.automatic || row.status === "new") row.status = patch.status;
          return route.fulfill({ json: { status: row.status, reason: null } });
        }
        return route.fulfill({ json: { job: { ...row, raw_jd: null, reasons: [], score_payload: null, brain: null, scored_at: null } } });
      });
      await page.goto(base);
      const card = page.locator(`article[data-posting-id="${jobs[0].id}"]`);
      await expect(card).toBeVisible();
      if (mode === "globe") {
        await page.getByRole("button", { name: "Globe", exact: true }).click();
        await expect(page.getByRole("heading", { name: "On screen", exact: true })).toBeVisible();
        // Globe opening deliberately does not auto-mark Seen; emulate server truth.
        jobs[0].status = "seen";
      }
      await card.getByRole("button", { name: "Open Status engineer 0 at Fixture 0", exact: true }).click();
      if (mode === "globe") await card.getByRole("button", { name: "View job details", exact: true }).click();
      const dialog = page.getByRole("dialog");
      const status = dialog.getByRole("combobox", { name: "Application status" });
      await expect(status).toHaveText("Seen");
      await page.waitForTimeout(300);
      await page.evaluate(id => {
        const selector = `article[data-posting-id="${id}"]`;
        const original = document.querySelector(selector);
        window.cardProbe = { original, removed: 0 };
        window.cardObserver = new MutationObserver(records => {
          for (const record of records) for (const node of record.removedNodes) {
            if (node === original || node.contains(original)) window.cardProbe.removed += 1;
          }
        });
        window.cardObserver.observe(document.body, { childList: true, subtree: true });
      }, jobs[0].id);
      state.hold = true;
      await status.click();
      await page.getByRole("option", { name: "New", exact: true }).click();
      await expect(status).toHaveText("New");
      await page.waitForTimeout(300);
      assert.equal(state.held, 0, "the PATCH reply is the update; no list or globe read follows");
      const probe = await page.evaluate(id => ({ removed: window.cardProbe.removed,
        sameNode: document.querySelector(`article[data-posting-id="${id}"]`) === window.cardProbe.original }), jobs[0].id);
      console.log(`${mode}: New card probe ${JSON.stringify(probe)}`);
      if (probe.removed || !probe.sameNode) failures.push(`${mode}: New removed/re-added original card (${JSON.stringify(probe)})`);
      const before = { patches: state.patches, reads: state.reads };
      await status.click();
      await page.getByRole("option", { name: "New", exact: true }).click();
      await page.waitForTimeout(300);
      assert.deepEqual({ patches: state.patches, reads: state.reads }, before, "same-value New must not PATCH or refetch");
      assert.equal(await page.evaluate(() => window.cardProbe.removed), probe.removed, "same-value must not touch the card");
      if (probe.sameNode) await page.screenshot({ path: `${output}/${mode}-new.png` });
      // Explicit Applied still drops the card without a read.
      state.hold = false;
      await status.click();
      await page.getByRole("option", { name: "Applied", exact: true }).click();
      await expect(status).toHaveText("Applied");
      await expect(card).toHaveCount(0);
      await page.waitForTimeout(300);
      assert.equal(state.reads, before.reads, "Applied does not refetch");
      await expect(card).toHaveCount(0);
      await expect(dialog).toBeVisible();
      assert.deepEqual(errors, []);
      console.log(`${mode}: probe=${JSON.stringify(probe)}; zero reads after New/Applied; same-value zero PATCH; Applied removal pass`);
    } catch (error) { failures.push(`${mode}: ${error.message}`); }
    finally { release(); await context.close(); }
  }
  assert.deepEqual(failures, []);
} finally { await browser.close(); }
