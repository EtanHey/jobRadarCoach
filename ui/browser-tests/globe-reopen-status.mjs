// Browser regression for a status mutation while Globe is off. Run on the isolated auth fixture.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";

const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4318";
assert.equal(new URL(base).hostname, "127.0.0.1");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const jobs = [0, 1].map(n => ({ id: id(n), title: `Reopen engineer ${n}`, company: `Fixture ${n}`,
  source: "fixture", last_seen_at: "2026-09-22T00:00:00Z", first_seen_at: "2026-09-22T00:00:00Z",
  experience: "3+ years", description_available: false, seniority_origin: "title", extraction_state: "not-extracted",
  location: "Rehovot, Israel", remote: true, seniority: "Junior", stack: ["React"], salary: null,
  url: "https://example.test", apply_url: null, posted_at: null, status: "new", status_reason: null,
  score: 85, fit_line: null, recommendation: "apply" }));
const points = jobs.map((job, n) => ({ posting_id: job.id, lat: 31.8 + n * .1, lng: 34.8 + n * .1,
  precision: "city", source: "fixture", resolved_at: "2026-09-22T00:00:00Z" }));
const globePayload = () => {
  const visible = jobs.filter(job => job.status !== "applied");
  const visibleIds = new Set(visible.map(job => job.id));
  return { jobs: visible, points: points.filter(point => visibleIds.has(point.posting_id)),
    total_count: visible.length, resolved_count: visible.length, unresolved_count: 0,
    attribution: "© OpenStreetMap contributors" };
};
let holdGlobe = false;
let releaseGlobe;
const held = new Promise(resolve => { releaseGlobe = resolve; });
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
await page.addInitScript(() => { window.EventSource = class { addEventListener() {} close() {} }; });
await page.route("**/api/**", async route => {
  const url = new URL(route.request().url());
  if (url.pathname === "/api/jobs/globe") {
    if (holdGlobe) await held;
    return route.fulfill({ json: globePayload() });
  }
  if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs: jobs.filter(job => job.status !== "applied") } });
  if (url.pathname === "/api/events") return route.fulfill({ contentType: "text/event-stream", body: "event: ready\ndata: {}\n\n" });
  const job = jobs.find(job => url.pathname === `/api/jobs/${job.id}`);
  if (job) return route.fulfill({ json: { job: { ...job, raw_jd: null, reasons: [], score_payload: null, brain: null, scored_at: null } } });
  const statusJob = jobs.find(job => url.pathname === `/api/jobs/${job.id}/status`);
  if (statusJob) {
    const patch = route.request().postDataJSON();
    statusJob.status = patch.status;
    return route.fulfill({ json: { status: statusJob.status, reason: null } });
  }
  return route.fulfill({ status: 404, json: { error: "fixture only" } });
});
try {
  await page.goto(base);
  const globe = page.getByRole("button", { name: "Globe", exact: true });
  await globe.click();
  await page.getByRole("heading", { name: "On screen", exact: true }).waitFor();
  await page.getByRole("button", { name: "Open Reopen engineer 0 at Fixture 0", exact: true }).waitFor();
  await globe.click();
  await page.getByRole("button", { name: "Open Reopen engineer 0 at Fixture 0", exact: true }).click();
  const status = page.getByRole("dialog").getByRole("combobox", { name: "Application status" });
  await status.waitFor();
  await status.click();
  await page.getByRole("option", { name: "Applied", exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('[aria-label="Open Reopen engineer 0 at Fixture 0"]'));
  await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  holdGlobe = true;
  const pending = page.waitForRequest(request => new URL(request.url()).pathname === "/api/jobs/globe");
  await globe.click();
  await pending;
  await page.getByRole("heading", { name: "On screen", exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Open Reopen engineer 0 at Fixture 0", exact: true }).count(), 0,
    "a status change while Globe is off must not reappear while the refresh is held");
  assert.equal(await page.getByRole("button", { name: "Open Reopen engineer 1 at Fixture 1", exact: true }).count(), 1);
  await page.waitForTimeout(500);
  assert.equal(await page.getByRole("button", { name: "Open Reopen engineer 0 at Fixture 0", exact: true }).count(), 0);
  releaseGlobe();
  await page.waitForTimeout(100);
  assert.deepEqual(errors, []);
  console.log("globe-reopen-status: PASS");
} finally {
  releaseGlobe();
  await browser.close();
}
