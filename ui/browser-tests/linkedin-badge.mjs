// Running app, synthetic read-only data: advisory evidence never removes a role.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";

// Start the credential-free fixture with: node e2e/start-app.mjs 4367
const base = process.env.BADGE_QA_URL ?? "http://127.0.0.1:4367";
assert.equal(new URL(base).hostname, "127.0.0.1");
const output = process.env.BADGE_QA_OUTPUT;
if (output) await mkdir(output, { recursive: true });
const signal = { phrase: "no longer accepting applications", checked_at: "2026-10-07T13:00:00Z", url: "https://www.linkedin.com/jobs/view/1234567890" };
const jobs = ["new", "seen"].map((status, n) => ({
  id: `00000000-0000-4000-8000-00000000000${n}`, title: `Synthetic ${status} engineer`, company: `Fixture ${n}`, source: "linkedin",
  last_seen_at: signal.checked_at, experience: null, description_available: true, seniority_origin: "unknown", extraction_state: "not-extracted",
  location: "Tel Aviv, Israel", remote: false, seniority: null, stack: [], salary: null, url: signal.url, apply_url: null,
  posted_at: null, first_seen_at: signal.checked_at, status, status_reason: null, score: 80, fit_line: null, recommendation: null,
  alive: null, linkedin_closed_signal: signal,
}));
const browser = await chromium.launch({ headless: true });
try {
  for (const width of [1440, 390]) for (const filter of ["all", "new-for-me", "seen"]) {
    for (const job of jobs) job.linkedin_closed_signal = signal;
    const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: "reduce" });
    try {
      await context.addInitScript(filter => {
        localStorage.setItem("job-radar.board-preferences", JSON.stringify({ version: 3, filter,
          view: { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" } }));
        window.EventSource = class extends EventTarget { close() {} };
      }, filter);
      const page = await context.newPage(), errors = [], writes = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.route("**/*", route => {
        const req = route.request(), url = new URL(req.url());
        if (url.hostname !== "127.0.0.1") return route.abort();
        if (!url.pathname.startsWith("/api/")) return route.continue();
        if (req.method() === "PATCH" && jobs.some(job => url.pathname === `/api/jobs/${job.id}/status`)) {
          writes.push(req.method()); return route.fulfill({ json: { status: req.postDataJSON().status, reason: null } });
        }
        if (req.method() !== "GET") return route.fulfill({ status: 405, json: {} });
        if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs: jobs.filter(job => filter === "all" || job.status === (filter === "new-for-me" ? "new" : "seen")) } });
        const job = jobs.find(job => url.pathname === `/api/jobs/${job.id}`);
        if (job) return route.fulfill({ json: { job: { ...job, raw_jd: "Synthetic public fixture description.", reasons: [], score_payload: null, brain: null, scored_at: null } } });
        return route.fulfill({ status: 404, json: {} });
      });
      await page.goto(base);
      const cards = page.locator("article[data-posting-id]");
      await cards.first().waitFor();
      assert.equal(await cards.count(), filter === "all" ? 2 : 1);
      const badge = cards.first().locator("[data-linkedin-closed-signal]");
      await badge.waitFor({ timeout: 5000 });
      assert.equal(await badge.getAttribute("href"), signal.url);
      assert.equal(await badge.textContent(), "LinkedIn: no longer accepting applications · checked 2026-10-07");
      assert.ok(await badge.evaluate(el => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x + 5, r.y + 5)); }));
      const bounds = await badge.boundingBox(), cardBounds = await cards.first().boundingBox();
      assert.ok(bounds.x >= cardBounds.x && bounds.x + bounds.width <= cardBounds.x + cardBounds.width + 1);
      assert.ok(await badge.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
      if (output) await page.screenshot({ path: `${output}/${width}-${filter}-card.png` });
      await cards.first().getByRole("button", { name: /^Open Synthetic/ }).click();
      const drawer = page.getByRole("dialog");
      await drawer.locator("[data-linkedin-closed-signal]").waitFor();
      assert.equal(await drawer.locator("[data-linkedin-closed-signal]").getAttribute("href"), signal.url);
      if (output) await page.screenshot({ path: `${output}/${width}-${filter}-drawer.png` });
      assert.deepEqual(errors, []);
      assert.equal(await drawer.getByRole("alert").count(), 0);
      // Automatic status changes are fulfilled entirely in the synthetic fixture.
      assert.ok(writes.every(method => method === "PATCH"));
      // A later validated open observation projects null through the same API.
      for (const job of jobs) job.linkedin_closed_signal = null;
      await page.reload();
      await cards.first().waitFor();
      assert.equal(await cards.count(), filter === "all" ? 2 : 1);
      assert.equal(await cards.locator("[data-linkedin-closed-signal]").count(), 0);
      await cards.first().getByRole("button", { name: /^Open Synthetic/ }).click();
      await drawer.waitFor();
      assert.equal(await drawer.locator("[data-linkedin-closed-signal]").count(), 0);
      if (output) await page.screenshot({ path: `${output}/${width}-${filter}-cleared.png` });
      assert.deepEqual(errors, []);
      console.log(`${width}/${filter}: active cards retained; badge shown then cleared on card and drawer; no clipping`);
    } finally { await context.close(); }
  }
} finally { await browser.close(); }
