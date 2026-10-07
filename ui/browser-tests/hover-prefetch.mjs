// Real local JobBoard, synthetic APIs. Run only through run-suite-capped.sh.
// Hover or keyboard focus warms the drawer's detail query; opening is then served from cache.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4391";
assert.equal(new URL(base).hostname, "127.0.0.1");
const output = process.env.GLOBE_QA_OUTPUT;
assert.ok(output, "Set GLOBE_QA_OUTPUT for screenshots");
await mkdir(output, { recursive: true });
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const job = n => ({ id: id(n), title: `Prefetch engineer ${n}`, company: `Fixture ${n}`, source: "fixture",
  last_seen_at: "2026-09-22T00:00:00Z", first_seen_at: "2026-09-22T00:00:00Z",
  experience: null, description_available: true, seniority_origin: "title", extraction_state: "not-extracted",
  location: "Rehovot, Israel", remote: true, seniority: "Junior", stack: ["React"], salary: null,
  url: "https://example.test", apply_url: null, posted_at: null, status: "new", status_reason: null,
  score: 90 - n, fit_line: null, recommendation: "apply", alive: true });
const jobs = Array.from({ length: 15 }, (_, n) => job(n));
const receipts = [];
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 2200 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  const requests = [];
  const errors = [];
  const failures = [];
  try {
    page.setDefaultTimeout(15000);
    page.on("pageerror", error => errors.push(error.message));
    page.on("requestfailed", request => failures.push({ path: new URL(request.url()).pathname, error: request.failure()?.errorText }));
    await page.addInitScript(() => {
      localStorage.setItem("job-radar.board-preferences", JSON.stringify({ version: 3, filter: "all", view: { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "all", sort: "fit" } }));
    });
    await page.route("**/api/**", route => {
      const request = route.request(), url = new URL(request.url());
      requests.push({ method: request.method(), path: url.pathname, poll: url.searchParams.has("since") });
      if(url.pathname==="/api/jobs/new-roles"){return route.fulfill({json:{count:0,truncated:false,...(route.request().method()==="GET"?{companies:[]}: {})}});}
      if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs: url.searchParams.has("since") ? [] : structuredClone(jobs) } });
      const row = jobs.find(candidate => url.pathname.startsWith(`/api/jobs/${candidate.id}`));
      if (!row) return route.fulfill({ status: 404, json: { error: "fixture only" } });
      if (url.pathname.endsWith("/status")) {
        const patch = request.postDataJSON();
        if (!patch.automatic || row.status === "new") row.status = patch.status;
        return route.fulfill({ json: { status: row.status, reason: null } });
      }
      return route.fulfill({ json: { job: { ...row, raw_jd: `Fixture body ${row.id}`, reasons: [], score_payload: null, brain: null, scored_at: null } } });
    });
    const detailReads = n => requests.filter(r => r.method === "GET" && r.path === `/api/jobs/${id(n)}`).length;
    const allDetailReads = () => requests.filter(r => r.method === "GET" && /^\/api\/jobs\/[0-9a-f-]{36}$/.test(r.path)).length;
    const patches = () => requests.filter(r => r.method === "PATCH").length;
    // The fake clock can reach the 90 s New-roles poll (`since`); that is not a list refetch.
    const listReads = () => requests.filter(r => r.method === "GET" && r.path === "/api/jobs" && !r.poll).length;
    const statusOf = dialog => dialog.getByRole("combobox", { name: "Application status" });
    const card = n => page.locator(`article[data-posting-id="${id(n)}"]`);
    const opener = n => page.getByRole("button", { name: `Open Prefetch engineer ${n} at Fixture ${n}`, exact: true });
    const dialog = page.getByRole("dialog");
    const settle = () => page.waitForTimeout(500);
    const parkPointer = () => page.mouse.move(5, 5);
    async function closeWithOneEscape() {
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
    }

    // Fake timers that still tick in real time; cases 7-8 jump past the 30 s staleTime.
    await page.clock.install();
    await page.goto(base);
    await expect(card(12)).toBeVisible();
    await parkPointer();
    await settle();
    const baselineLists = listReads();
    assert.equal(allDetailReads(), 0, "no detail read before any intent");

    // 1. Hover past the intent delay warms exactly one read; opening adds none and focuses the description.
    await card(0).hover();
    await expect.poll(() => detailReads(0), { timeout: 3000 }).toBe(1);
    assert.equal(patches(), 0, "hover prefetch never marks Seen");
    await opener(0).click();
    await expect(dialog.getByText(`Fixture body ${id(0)}`, { exact: true })).toBeVisible();
    await settle();
    assert.equal(detailReads(0), 1, "opening a warmed card adds zero detail requests");
    assert.ok(await page.evaluate(() => document.activeElement?.hasAttribute("data-job-description")), "drawer focuses the description");
    await expect.poll(patches).toBe(1);
    assert.equal(requests.filter(r => r.method === "PATCH" && r.path === `/api/jobs/${id(0)}/status`).length, 1, "auto-Seen once, on open");
    await closeWithOneEscape();
    await parkPointer();
    receipts.push({ case: "hover warms, open served from cache, one auto-Seen on open", detail0: detailReads(0), patches: patches() });

    // 2. A quick sweep across ten cards stays under the intent delay: bounded reads, never a PATCH.
    const beforeSweep = allDetailReads(), patchesBeforeSweep = patches();
    // Measure first so the timed loop is only pointer moves (~30 ms per card, well under the 150 ms intent).
    const boxes = [];
    for (let n = 1; n <= 10; n++) boxes.push(await card(n).boundingBox());
    for (const box of boxes) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 2 });
      await page.waitForTimeout(30);
    }
    await parkPointer();
    await settle();
    const sweepReads = allDetailReads() - beforeSweep;
    assert.ok(sweepReads <= 2, `ten quick hovers caused ${sweepReads} detail reads (want <= 2)`);
    assert.equal(patches(), patchesBeforeSweep, "hovering never PATCHes Seen");
    receipts.push({ case: "quick sweep across 10 cards", detailReads: sweepReads, patches: patches() - patchesBeforeSweep });

    // 3. Fresh cache: re-hovering a warmed card, or lingering repeatedly, does not refetch.
    await card(11).hover();
    await expect.poll(() => detailReads(11), { timeout: 3000 }).toBe(1);
    await parkPointer();
    await card(11).hover();
    await settle();
    await card(0).hover();
    await settle();
    await parkPointer();
    assert.equal(detailReads(11), 1, "staleTime respected on re-hover");
    assert.equal(detailReads(0), 1, "opened card stays cached");
    receipts.push({ case: "re-hover within staleTime", detail11: detailReads(11), detail0: detailReads(0) });

    // 4. Hidden tab: no prefetch.
    await page.evaluate(() => Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" }));
    await card(12).hover();
    await settle();
    await parkPointer();
    assert.equal(detailReads(12), 0, "no prefetch while the tab is hidden");
    await page.evaluate(() => { delete document.visibilityState; });
    receipts.push({ case: "hidden tab", detail12: detailReads(12) });

    // 5. Touch pointers (scrolling a phone list) never prefetch.
    await card(12).dispatchEvent("pointerover", { pointerType: "touch", bubbles: true });
    await settle();
    assert.equal(detailReads(12), 0, "no prefetch on touch");
    await card(12).dispatchEvent("pointerout", { pointerType: "touch", bubbles: true });
    receipts.push({ case: "touch pointer", detail12: detailReads(12) });

    // 6. Keyboard focus warms the card; Enter opens from cache.
    await opener(12).focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await expect.poll(() => detailReads(12), { timeout: 3000 }).toBe(1);
    await page.keyboard.press("Enter");
    await expect(dialog.getByText(`Fixture body ${id(12)}`, { exact: true })).toBeVisible();
    await settle();
    assert.equal(detailReads(12), 1, "keyboard open adds zero detail requests");
    await closeWithOneEscape();
    receipts.push({ case: "keyboard focus warms, Enter opens from cache", detail12: detailReads(12) });

    // 7. A status write is not a detail read: open, reopen at +20 s, reopen at +40 s must GET again
    //    (30 s from the last GET). The +20 s opening also saves a manual status, so both writers are covered.
    await card(13).hover();
    await expect.poll(() => detailReads(13), { timeout: 3000 }).toBe(1);
    const patchesBeforeAge = patches();
    await opener(13).click();
    await expect(statusOf(dialog)).toHaveText("Seen");
    await closeWithOneEscape();
    await parkPointer();
    await page.clock.fastForward(20_000);
    await opener(13).click();
    await expect.poll(patches).toBe(patchesBeforeAge + 2);
    await statusOf(dialog).click();
    await page.getByRole("option", { name: "New", exact: true }).click();
    await expect(statusOf(dialog)).toHaveText("New");
    await expect.poll(patches).toBe(patchesBeforeAge + 3);
    await settle();
    assert.equal(detailReads(13), 1, "reopening inside 30 s is served from cache");
    await closeWithOneEscape();
    await parkPointer();
    await page.clock.fastForward(20_000);
    await opener(13).click();
    await expect.poll(() => detailReads(13), { timeout: 3000 }).toBe(2);
    await expect(statusOf(dialog)).toHaveText("Seen");
    await settle();
    assert.equal(detailReads(13), 2, "one refresh, 30 s after the last GET despite status writes at +20 s");
    await closeWithOneEscape();
    await parkPointer();
    receipts.push({ case: "open, +20 s auto+manual status, +40 s refetches", detail13: detailReads(13), patches: patches() - patchesBeforeAge });

    // 8. A stale prefetched New role: its refresh lands with a changed body while the automatic Seen
    //    PATCH is held. The refresh must not abort this opening's Seen, and the role must leave New.
    await card(14).hover();
    await expect.poll(() => detailReads(14), { timeout: 3000 }).toBe(1);
    await parkPointer();
    await page.clock.fastForward(31_000);
    let heldPatch;
    await page.route(`**/api/jobs/${id(14)}/status`, route => {
      requests.push({ method: route.request().method(), path: new URL(route.request().url()).pathname });
      heldPatch = route;
    });
    jobs[14].raw_jd = "Fresh description changed after cached open";
    jobs[14].score = 10;
    await page.route(`**/api/jobs/${id(14)}`, async route => {
      requests.push({ method: "GET", path: new URL(route.request().url()).pathname });
      await page.waitForTimeout(300);
      return route.fulfill({ json: { job: { ...jobs[14], reasons: [], score_payload: null, brain: null, scored_at: null } } });
    });
    await opener(14).click();
    await expect.poll(() => Boolean(heldPatch)).toBe(true);
    await expect(dialog.getByText(jobs[14].raw_jd, { exact: true })).toBeVisible();
    await settle();
    jobs[14].status = "seen";
    await heldPatch.fulfill({ json: { status: "seen", reason: null } });
    await expect(statusOf(dialog)).toHaveText("Seen");
    await settle();
    const seenFailures = failures.filter(failure => failure.path === `/api/jobs/${id(14)}/status`);
    assert.deepEqual(seenFailures, [], "a stale detail refresh must not abort this opening's automatic Seen");
    assert.equal(requests.filter(r => r.method === "PATCH" && r.path === `/api/jobs/${id(14)}/status`).length, 1, "one auto-Seen for this opening");
    assert.equal(detailReads(14), 2, "one refresh of the stale prefetch");
    await closeWithOneEscape();
    await page.unroute(`**/api/jobs/${id(14)}/status`);
    await page.unroute(`**/api/jobs/${id(14)}`);
    receipts.push({ case: "stale prefetched New role: refresh overlaps held auto-Seen", detail14: detailReads(14), seenFailures: seenFailures.length });

    assert.equal(listReads(), baselineLists, "prefetch and auto-Seen never refetch the list");
    assert.deepEqual(errors, []);
    await page.screenshot({ path: `${output}/hover-prefetch.png` });
  } finally {
    await context.close();
  }
} finally {
  await browser.close();
  await writeFile(`${output}/hover-prefetch-receipt.json`, JSON.stringify(receipts, null, 2));
}
console.log(JSON.stringify(receipts));
