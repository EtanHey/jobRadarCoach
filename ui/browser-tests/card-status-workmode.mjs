// Synthetic loopback proof for the card status chip and work-mode icon, and the drawer's status save feedback.
// Cards: every non-new card names its status under the score box in All roles, New for me and the globe rail;
// terminal statuses dim everywhere and Seen dims only in New for me; the work mode is an icon with an accessible name; the location row is never
// truncated by the chip at 390 px. Drawer: a failed status save shows a spinner while waiting, then an inline
// error under the select with the select back on the server value, and no drawer banner.
// All API calls are answered in-browser. Run only through run-suite-capped.sh, one suite at a time.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";

const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4390";
const output = process.env.GLOBE_QA_OUTPUT;
assert.equal(new URL(base).hostname, "127.0.0.1");
if (output) await mkdir(output, { recursive: true });

const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const statuses = ["new", "seen", "applied", "rejected", "interview_technical", "worth_checking"];
const dimmed = new Set(["applied", "rejected"]);
const remotes = [true, null, false, null, true, false];
const modeLabel = remote => remote === true ? "Remote" : remote === false ? "On-site" : "Work mode unspecified";
// The locations Etan saw truncated on 390 px cards, plus ordinary ones.
const locations = ["Rehovot, Israel", "Tel Aviv-Yafo, Israel (Hybrid)", "Yavne, Israel (Hybrid)", "Haifa, Israel", "Herzliya, Israel", "Petah Tikva, Israel"];
// Distinct but equal-length titles and companies, so duplicate grouping keeps every card and widths stay comparable.
const title = n => `Senior full-stack platform engineer ${"ABCDEF"[n]}, developer experience and tooling`;
const freshJobs = () => statuses.map((status, n) => ({ id: id(n), title: title(n), company: `Fixture Systems ${"ABCDEF"[n]}`, source: "fixture",
  last_seen_at: "2026-10-04T00:00:00Z", first_seen_at: "2026-10-04T00:00:00Z", experience: "3+ years", description_available: false,
  seniority_origin: "title", extraction_state: "not-extracted", location: locations[n], remote: remotes[n], seniority: "Junior",
  stack: ["React", "TypeScript"], salary: null, url: "https://example.test", apply_url: null, posted_at: null, status, status_reason: null,
  score: 80 - n, fit_line: null, recommendation: "apply", alive: true }));

const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const failures = [], passed = [];

async function openBoard({ viewport, colorScheme, filter, jobs, patch }) {
  const context = await browser.newContext({ viewport, colorScheme, reducedMotion: "reduce" });
  await context.addInitScript(savedFilter => {
    localStorage.setItem("job-radar.board-preferences", JSON.stringify({ version: 3, filter: savedFilter,
      view: { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" } }));
    localStorage.setItem("job-globe-dragged", "1");
    class FixtureEvents extends EventTarget { constructor() { super(); setTimeout(() => this.dispatchEvent(new Event("ready")), 20); } close() { this.closed = true; } }
    window.EventSource = FixtureEvents;
  }, filter);
  const page = await context.newPage(), errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.hostname !== "127.0.0.1") return url.hostname.endsWith(".cartocdn.com") ? route.continue() : route.abort();
    if (!url.pathname.startsWith("/api/")) return route.continue();
    if (url.pathname === "/api/jobs/globe") return route.fulfill({ json: { jobs, total_count: jobs.length, resolved_count: jobs.length, unresolved_count: 0,
      points: jobs.map(job => ({ posting_id: job.id, lat: 31.9, lng: 34.8, precision: "city", source: "fixture", resolved_at: "2026-10-04T00:00:00Z" })),
      attribution: "© OpenStreetMap contributors" } });
    if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs } });
    const row = jobs.find(job => url.pathname.startsWith(`/api/jobs/${job.id}`));
    if (!row) return route.fulfill({ status: 404, json: { error: "fixture only" } });
    if (url.pathname.endsWith("/status")) {
      if (route.request().method() !== "PATCH" || !patch) return route.fulfill({ status: 405, json: { error: "Read-only fixture" } });
      return patch(route, row);
    }
    return route.fulfill({ json: { job: { ...row, raw_jd: null, reasons: [], score_payload: null, brain: null, scored_at: null } } });
  });
  await page.goto(base);
  await page.locator("article[data-posting-id]").nth(jobs.length - 1).waitFor();
  return { context, page, errors };
}

function measure(page, scope) {
  return page.locator(`${scope} article[data-posting-id]`).evaluateAll(cards => cards.map(card => {
    const box = element => element.getBoundingClientRect();
    const header = card.children[1], score = card.querySelector('[aria-label^="Fit score"]'), chip = card.querySelector("[data-card-status]");
    const mode = card.querySelector("[data-work-mode]"), place = mode?.parentElement, location = mode?.nextElementSibling;
    const h2 = card.querySelector("h2");
    return { id: card.dataset.postingId, header: box(header), title: box(h2).width, titleOpacity: getComputedStyle(h2.parentElement).opacity,
      score: box(score), scoreColumn: box(score.parentElement), chip: chip && { text: chip.textContent, label: chip.getAttribute("title"), box: box(chip), clipped: chip.scrollHeight - chip.clientHeight },
      cardRight: box(card).right,
      mode: mode && { label: mode.getAttribute("aria-label"), role: mode.getAttribute("role"), svg: Boolean(mode.querySelector("svg")) },
      place: place && box(place), locationOverflow: location ? location.scrollWidth - location.clientWidth : null, locationText: location?.textContent };
  }));
}

// Master's title widths for these fixtures (review R1 of #401): the chip must never take width from the title.
const minimumTitleWidth = { "390": 190, desktop: 272 };

function checkCards(cards, where, minTitle, dimSeen = false) {
  assert.equal(cards.length, statuses.length, `${where}: every card rendered`);
  const baseline = cards.find(card => card.id === id(0));
  for (const card of cards) {
    const n = Number(card.id.slice(-12)), status = statuses[n], at = `${where} ${status}`;
    assert.ok(card.mode, `${at}: work-mode icon rendered`);
    assert.deepEqual([card.mode.role, card.mode.label, card.mode.svg], ["img", modeLabel(remotes[n]), true], `${at}: icon named by its work mode`);
    assert.equal(card.locationText, locations[n], `${at}: the location row carries only the location`);
    assert.ok(card.locationOverflow <= 0, `${at}: location not truncated (${card.locationOverflow}px over)`);
    assert.equal(card.titleOpacity, dimmed.has(status) || (dimSeen && status === "seen") ? "0.6" : "1", `${at}: dim terminal statuses (and Seen in New for me)`);
    assert.equal(Math.round(card.header.height), Math.round(baseline.header.height), `${at}: header height unchanged by the chip`);
    assert.equal(Math.round(card.title), Math.round(baseline.title), `${at}: title width unchanged by the chip`);
    assert.ok(card.scoreColumn.width <= card.score.width + 0.5, `${at}: the score column stays score-sized (${card.scoreColumn.width} > ${card.score.width})`);
    if (minTitle) assert.ok(card.title >= minTitle, `${at}: title keeps master's width (${card.title} < ${minTitle})`);
    if (status === "new") { assert.equal(card.chip, null, `${at}: no chip`); continue; }
    assert.ok(card.chip, `${at}: chip rendered`);
    assert.ok(card.chip.label, `${at}: full label kept for hover`);
    assert.ok(card.chip.box.top >= card.score.bottom - 0.5, `${at}: chip sits under the score box`);
    assert.ok(Math.abs(card.chip.box.right - card.score.right) <= 1, `${at}: chip right-aligned with the score box`);
    assert.ok(card.chip.clipped <= 1, `${at}: chip label is not clipped (${card.chip.clipped}px hidden)`);
    assert.ok(card.chip.box.bottom <= card.header.bottom + 0.5 && card.chip.box.bottom <= card.place.top, `${at}: chip stays in the header, above the location row`);
    assert.ok(card.chip.box.right <= card.cardRight, `${at}: chip inside the card`);
  }
}

const shot = async (page, name, options) => { if (output) await page.screenshot({ path: `${output}/${name}.png`, ...options }); };

for (const [vp, viewport] of [["390", { width: 390, height: 844 }], ["desktop", { width: 1440, height: 900 }]]) {
  for (const colorScheme of ["light", "dark"]) {
    for (const filter of ["all", "new-for-me"]) {
      const where = `${vp} ${colorScheme} ${filter}`;
      const { context, page, errors } = await openBoard({ viewport, colorScheme, filter, jobs: freshJobs() });
      try {
        try {
          checkCards(await measure(page, "main"), `${where} list`, minimumTitleWidth[vp], filter === "new-for-me");
          assert.ok(await page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth), `${where} list: no horizontal overflow`);
          await shot(page, `${vp}-${colorScheme}-${filter}-list`, { fullPage: vp === "390" });
          passed.push(`${where} list`);
        } catch (error) { failures.push(`${where} list: ${error.message.split("\n")[0]}`); }
        if (filter === "all") {
          await page.getByRole("button", { name: "Globe", exact: true }).click();
          await page.waitForFunction(count => document.querySelectorAll("#globe-rail article[data-posting-id]").length === count, statuses.length, { timeout: 30000 });
          try {
            checkCards(await measure(page, "#globe-rail"), `${where} rail`);
            assert.ok(await page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth), `${where} rail: no horizontal overflow`);
            if (vp === "390") await page.locator("#globe-rail").scrollIntoViewIfNeeded();
            await shot(page, `${vp}-${colorScheme}-rail`);
            passed.push(`${where} rail`);
          } catch (error) { failures.push(`${where} rail: ${error.message.split("\n")[0]}`); }
        }
        assert.deepEqual(errors, [], `${where}: no page errors`);
      } catch (error) { failures.push(`${where}: ${error.message.split("\n")[0]}`); }
      finally { await context.close(); }
    }
  }
}

// Drawer: a failed manual status save waits for the server with a spinner, then reverts with an inline error.
for (const [vp, viewport, colorScheme] of [["desktop", { width: 1440, height: 900 }, "light"], ["390", { width: 390, height: 844 }, "dark"]]) {
  const where = `${vp} ${colorScheme} drawer`;
  const state = { manual: 0, fail: true, release: null };
  const patch = async (route, row) => {
    const body = route.request().postDataJSON();
    if (body.automatic) return route.fulfill({ json: { status: row.status, reason: row.status_reason } });
    state.manual += 1;
    await new Promise(resolve => { state.release = resolve; });
    if (state.fail) return route.fulfill({ status: 503, json: { error: "Database unavailable." } });
    row.status = body.status;
    return route.fulfill({ json: { status: row.status, reason: null } });
  };
  const { context, page, errors } = await openBoard({ viewport, colorScheme, filter: "all", jobs: freshJobs(), patch });
  try {
    const card = page.locator(`article[data-posting-id="${id(1)}"]`);
    await card.getByRole("button", { name: `Open ${title(1)} at Fixture Systems B`, exact: true }).click();
    const dialog = page.getByRole("dialog");
    const status = dialog.getByRole("combobox", { name: "Application status" });
    await expect(status).toHaveText("Seen");
    await expect(dialog.locator("[data-work-mode]")).toHaveText("Work mode unspecified");

    await status.click();
    await page.getByRole("option", { name: "Worth checking", exact: true }).click();
    await expect.poll(() => state.manual).toBe(1);
    const saving = dialog.locator("[data-status-saving]");
    await expect(saving).toBeVisible();
    await expect(status).toHaveAttribute("aria-busy", "true");
    await expect(dialog.getByRole("status").filter({ hasText: "Saving status" })).toHaveCount(1);
    await shot(page, `${vp}-${colorScheme}-drawer-saving`);
    state.release();

    const inline = dialog.locator("fieldset").getByRole("alert");
    await expect(inline).toContainText("Status not saved, still Seen. The database is unavailable. Try again shortly.");
    await expect(dialog.getByRole("alert")).toHaveCount(1); // no drawer banner besides the inline error
    await expect(saving).toHaveCount(0);
    await expect(status).toHaveText("Seen");
    const [select, alert] = [await status.boundingBox(), await inline.boundingBox()];
    assert.ok(alert.y >= select.y + select.height, `${where}: the error sits under the select`);
    await expect(card.locator("[data-card-status]")).toHaveText("Seen");
    await shot(page, `${vp}-${colorScheme}-drawer-error`);

    state.fail = false;
    await status.click();
    await page.getByRole("option", { name: "Worth checking", exact: true }).click();
    await expect.poll(() => state.manual).toBe(2);
    state.release();
    await expect(status).toHaveText("Worth checking");
    await expect(dialog.getByRole("alert")).toHaveCount(0);
    await expect(card.locator("[data-card-status]")).toHaveText("Worth checking");
    assert.deepEqual(errors, [], `${where}: no page errors`);
    passed.push(where);
  } catch (error) { failures.push(`${where}: ${error.message.split("\n")[0]}`); }
  finally { state.release?.(); await context.close(); }
}

await browser.close();
console.log(JSON.stringify({ passed, failures }, null, 1));
if (failures.length) process.exitCode = 1;
