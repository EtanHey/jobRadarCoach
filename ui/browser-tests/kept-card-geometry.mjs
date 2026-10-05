// Synthetic loopback proof that the New-for-me kept-card cue never changes card geometry: for the shortest and longest
// status labels, a kept card matches an otherwise identical still-new card in height, header height and title width,
// in the 390 px list, the desktop list, and the globe rail at desktop and 390 px. All API calls are answered in-browser.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";

const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4380";
const output = process.env.GLOBE_QA_OUTPUT;
assert.equal(new URL(base).hostname, "127.0.0.1");
if (output) await mkdir(output, { recursive: true });

const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
// "new" is the baseline; "seen" is the shortest label, "interview_technical" ("Technical interview") the longest.
const statuses = ["new", "seen", "interview_technical", "interview_final", "worth_checking", "not_relevant"];
// Distinct but equal-length titles and companies, so duplicate grouping keeps every card and widths stay comparable.
const title = n => `Senior full-stack platform engineer ${"ABCDEF"[n]}, developer experience and tooling`;
const jobs = statuses.map((status, n) => ({ id: id(n), title: title(n), company: `Fixture Systems ${"ABCDEF"[n]}`, source: "fixture",
  last_seen_at: "2026-10-04T00:00:00Z", first_seen_at: "2026-10-04T00:00:00Z", experience: "3+ years", description_available: false,
  seniority_origin: "title", extraction_state: "not-extracted", location: "Rehovot, Israel", remote: false, seniority: "Junior",
  stack: ["React", "TypeScript"], salary: null, url: "https://example.test", apply_url: null, posted_at: null, status, status_reason: null,
  score: 80, fit_line: null, recommendation: "apply", alive: true }));
const globe = { jobs, points: jobs.map(job => ({ posting_id: job.id, lat: 31.9, lng: 34.8, precision: "city", source: "fixture", resolved_at: "2026-10-04T00:00:00Z" })),
  total_count: jobs.length, resolved_count: jobs.length, unresolved_count: 0, attribution: "© OpenStreetMap contributors" };

const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const failures = [], passed = [];

function measure(page, scope) {
  return page.locator(`${scope} article[data-posting-id]`).evaluateAll(cards => cards.map(card => {
    const box = element => element.getBoundingClientRect();
    const chip = card.querySelector("[data-card-status]");
    const row = chip?.parentElement;
    return { id: card.dataset.postingId, height: Math.round(box(card).height), header: Math.round(box(card.children[1]).height),
      title: Math.round(box(card.querySelector("h2")).width), cardRight: box(card).right,
      chip: chip && { text: chip.textContent, label: chip.getAttribute("title"), height: box(chip).height, right: box(chip).right, rowHeight: box(row).height } };
  }));
}
function checkGeometry(cards, where) {
  const baseline = cards.find(card => card.id === id(0));
  assert.ok(baseline, `${where}: baseline card present`);
  assert.equal(baseline.chip, null, `${where}: a still-new card has no chip`);
  for (const card of cards.filter(item => item.id !== id(0))) {
    const status = statuses[Number(card.id.slice(-12))];
    assert.ok(card.chip, `${where} ${status}: chip rendered`);
    assert.equal(card.height, baseline.height, `${where} ${status}: card height unchanged`);
    assert.equal(card.header, baseline.header, `${where} ${status}: header height unchanged`);
    assert.equal(card.title, baseline.title, `${where} ${status}: title width unchanged`);
    assert.ok(card.chip.height <= card.chip.rowHeight + 0.5, `${where} ${status}: chip fits its single-line row`);
    assert.ok(card.chip.right <= card.cardRight, `${where} ${status}: chip stays inside the card`);
  }
  for (const card of cards.filter(item => item.id !== id(0))) assert.ok(card.chip.label, `${where} ${statuses[Number(card.id.slice(-12))]}: full label kept for hover`);
}

for (const [name, viewport] of [["390", { width: 390, height: 844 }], ["desktop", { width: 1440, height: 900 }]]) {
  const context = await browser.newContext({ viewport, reducedMotion: "reduce" });
  try {
    await context.addInitScript(() => {
      localStorage.setItem("job-radar.board-preferences", JSON.stringify({ version: 3, filter: "new-for-me",
        view: { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" } }));
      localStorage.setItem("job-globe-dragged", "1");
      class FixtureEvents extends EventTarget { constructor() { super(); setTimeout(() => this.dispatchEvent(new Event("ready")), 20); } close() { this.closed = true; } }
      window.EventSource = FixtureEvents;
    });
    const page = await context.newPage(), errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => {
      const url = new URL(route.request().url());
      if (url.hostname !== "127.0.0.1") return url.hostname.endsWith(".cartocdn.com") ? route.continue() : route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (route.request().method() !== "GET") return route.fulfill({ status: 405, json: { error: "Read-only fixture" } });
      if (url.pathname === "/api/jobs/globe") return route.fulfill({ json: globe });
      if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs } });
      return route.fulfill({ status: 404, json: { error: "fixture only" } });
    });
    await page.goto(base);
    await page.locator("article[data-posting-id]").nth(statuses.length - 1).waitFor();
    try {
      checkGeometry(await measure(page, "main"), `${name} list`);
      assert.ok(await page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth), `${name} list: no horizontal overflow`);
      if (output) await page.screenshot({ path: `${output}/${name}-list.png`, fullPage: name === "390" });
      passed.push(`${name} list`);
    } catch (error) { failures.push(`${name} list: ${error.message.split("\n")[0]}`); }
    await page.getByRole("button", { name: "Globe", exact: true }).click();
    await page.waitForFunction(count => document.querySelectorAll("#globe-rail article[data-posting-id]").length === count, statuses.length, { timeout: 30000 });
    try {
      checkGeometry(await measure(page, "#globe-rail"), `${name} rail`);
      assert.ok(await page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth), `${name} rail: no horizontal overflow`);
      if (output) { if (name === "390") await page.locator("#globe-rail").scrollIntoViewIfNeeded(); await page.screenshot({ path: `${output}/${name}-rail.png` }); }
      passed.push(`${name} rail`);
    } catch (error) { failures.push(`${name} rail: ${error.message.split("\n")[0]}`); }
    assert.deepEqual(errors, []);
  } finally { await context.close(); }
}
await browser.close();
console.log(JSON.stringify({ passed, failures }, null, 1));
if (failures.length) process.exitCode = 1;
