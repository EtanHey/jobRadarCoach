// No live sync: no SSE, no list GET after a status change (even with a list read in flight),
// and a polled "N new roles · Show" pill whose number is the cards Show adds under the view.
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
  title: `Pill engineer ${n}`, company: `Fixture ${n}`, source: "fixture",
  last_seen_at: "2026-10-05T08:00:00Z", first_seen_at: `2026-10-05T08:00:00.${String(n).padStart(6, "0")}+00:00`,
  experience: null, description_available: false, seniority_origin: "title", extraction_state: "not-extracted",
  location: "Rehovot, Israel", remote: true, seniority: "Junior", stack: ["React"], salary: null,
  url: "https://example.test", apply_url: null, posted_at: null, status: "new", status_reason: null,
  score: 90 - n, fit_line: null, recommendation: "apply", alive: true, ...overrides });
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
    // Loaded at start: 0, 3, 4 (3 and 4 are older). Published later: 1, 2 and the edge cases:
    // 5 is hidden by the default "recommended" fit; 6 is a second posting of role 1.
    const jobs = [job(0), job(3, { first_seen_at: "2026-10-05T07:00:00Z" }), job(4, { first_seen_at: "2026-10-05T07:00:01Z" }),
      job(1), job(2), job(5, { score: 20, recommendation: "skip" }), job(6, { title: "Pill engineer 1", company: "Fixture 1" }), job(7)];
    const published = new Set([id(0), id(3), id(4)]);
    const publish = (...ns) => ns.forEach(n => published.add(id(n)));
    const log = [];
    const errors = [];
    const hold = { list: null, poll: null };
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
        const kind = url.searchParams.has("ids") ? " ids" : url.searchParams.has("since") ? " since" : "";
        log.push(`${request.method()} ${url.pathname}${kind}`);
        const visible = jobs.filter(row => published.has(row.id));
        const inFilter = rows => url.searchParams.get("filter") === "new-for-me" ? rows.filter(row => row.status === "new") : rows;
        if (url.pathname === "/api/jobs") {
          const ids = url.searchParams.get("ids")?.split(",");
          const since = url.searchParams.get("since");
          const limit = Number(url.searchParams.get("limit") ?? 50);
          // The snapshot is taken when the read starts, so a held read is stale by construction.
          const rows = structuredClone(ids ? jobs.filter(row => ids.includes(row.id))
            : inFilter(visible).filter(row => !since || row.first_seen_at > since).slice(0, limit));
          const gate = since ? hold.poll : kind ? null : hold.list;
          if (gate) { gate.started = true; await gate.promise; }
          return route.fulfill({ json: { jobs: rows } }).catch(() => { /* the board aborted this read */ });
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
      const gate = () => { const { promise, resolve } = Promise.withResolvers(); return { promise, release: resolve, started: false }; };
      const card = n => page.locator(`article[data-posting-id="${id(n)}"]`);
      const role1 = page.locator(`article[data-posting-id="${id(1)}"], article[data-posting-id="${id(6)}"]`);
      const listReads = () => log.filter(entry => entry === "GET /api/jobs").length;
      const patches = () => log.filter(entry => entry.startsWith("PATCH ")).length;
      const pill = page.locator("[data-new-roles]");
      const dialog = page.getByRole("dialog");
      const poll = async ms => {
        const answered = page.waitForResponse(response => new URL(response.url()).searchParams.has("since"));
        await page.clock.runFor(ms);
        await answered;
      };
      const openCard = async n => {
        await card(n).getByRole("button", { name: `Open Pill engineer ${n} at Fixture ${n}`, exact: true }).click();
        await expect(dialog.getByRole("combobox", { name: "Application status" })).toHaveText("Seen");
      };
      const closeDrawer = async () => {
        await dialog.getByRole("button", { name: "Close", exact: true }).click();
        await dialog.waitFor({ state: "hidden" });
      };
      await page.goto(base);
      await expect(card(0)).toBeVisible();
      await page.clock.runFor(2_000);
      assert.equal(await page.evaluate(() => window.sseOpened), 0, "the board opens no EventSource");
      assert.ok(!log.some(line => line.includes("/api/events")), "no /api/events request");
      if (scenario.full) {
        // Settled list: automatic Seen and an explicit change are each one PATCH and no GET.
        const reads = listReads();
        await openCard(3);
        await page.clock.runFor(1_000);
        assert.equal(listReads(), reads, "automatic Seen does not GET the list");
        const status = dialog.getByRole("combobox", { name: "Application status" });
        await status.click();
        await page.getByRole("option", { name: "Applied", exact: true }).click();
        await expect(status).toHaveText("Applied");
        await expect(card(3)).toHaveCount(0);
        await page.clock.runFor(1_000);
        assert.equal(listReads(), reads, "an explicit status change does not GET the list");
        await closeDrawer();
        // A role the view hides (default fit: recommended) is not a new role to this reader.
        publish(5);
        await poll(91_000);
        await page.clock.runFor(500);
        await expect(pill).toHaveCount(0);
        // Two postings of one role are one card.
        publish(1, 6);
        await poll(91_000);
        await expect(pill).toHaveText("1 new role·Show");
      }
      await expect(pill).toHaveCount(scenario.full ? 1 : 0);
      const before = await card(0).boundingBox();
      publish(scenario.full ? 2 : 1);
      if (scenario.full) {
        // Focus asks again after the quiet gap.
        await page.clock.runFor(16_000);
        const focused = page.waitForResponse(response => new URL(response.url()).searchParams.has("since"));
        await page.evaluate(() => window.dispatchEvent(new Event("focus")));
        await focused;
      } else await poll(91_000);
      await expect(pill).toHaveText(scenario.full ? "2 new roles·Show" : "1 new role·Show");
      assert.deepEqual(await card(0).boundingBox(), before, "the pill does not shift the list");
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "no horizontal overflow");
      await expect(page.getByRole("status").filter({ has: pill })).toHaveCount(1);
      await page.screenshot({ path: `${output}/${scenario.name}-pill.png` });
      await pill.focus();
      await page.keyboard.press("Shift+Tab");
      await page.keyboard.press("Tab");
      await expect(pill).toBeFocused();
      assert.equal(await pill.evaluate(element => element.matches(":focus-visible") && getComputedStyle(element).outlineStyle !== "none"), true, "keyboard focus shows a ring");
      await page.screenshot({ path: `${output}/${scenario.name}-pill-focus.png`, clip: { x: 0, y: 0, width: scenario.viewport.width, height: 420 } });
      const reads = listReads();
      const patchCount = patches();
      if (scenario.full) hold.list = gate();
      await pill.click();
      await expect(page.getByRole("heading", { name: "Your roles", exact: true })).toBeFocused();
      if (scenario.full) {
        // The Show read is held; its snapshot has cards 0 and 4 as "new".
        await expect.poll(() => hold.list.started).toBe(true);
        await openCard(0);
        assert.equal(patches(), patchCount + 1, "automatic Seen during a held read is one PATCH");
        await closeDrawer();
        await openCard(4);
        const status = dialog.getByRole("combobox", { name: "Application status" });
        await status.click();
        await page.getByRole("option", { name: "Applied", exact: true }).click();
        await expect(status).toHaveText("Applied");
        await expect(card(4)).toHaveCount(0);
        assert.equal(patches(), patchCount + 3, "automatic Seen + explicit Applied: one PATCH each");
        await closeDrawer();
        await page.clock.runFor(1_000);
        assert.equal(listReads(), reads + 1, "no list GET after a PATCH while a read is in flight");
        hold.list.release();
        hold.list = null;
      }
      await expect(role1).toHaveCount(1);
      await expect(pill).toHaveCount(0);
      await page.clock.runFor(1_000);
      assert.equal(listReads(), reads + 1, "Show loads the list once");
      if (scenario.full) {
        await expect(card(2)).toBeVisible();
        await expect(card(5)).toHaveCount(0);
        // The stale held read cannot undo the PATCH replies that landed while it was in flight.
        await expect(card(0)).toHaveAttribute("data-settled", "");
        await expect(card(4)).toHaveCount(0);
        await expect(card(3)).toHaveCount(0);
      }
      // After loading, nothing is newer than the list.
      await poll(91_000);
      await page.clock.runFor(500);
      await expect(pill).toHaveCount(0);
      await page.screenshot({ path: `${output}/${scenario.name}-shown.png` });
      if (scenario.full) {
        // A poll answered after the view changed never shows its stale number.
        publish(7);
        hold.poll = gate();
        await page.clock.runFor(91_000);
        await expect.poll(() => hold.poll.started).toBe(true);
        // The held answer counts role 7; the All roles list will not have it, so applying it would show a pill.
        published.delete(id(7));
        await page.getByRole("button", { name: "All roles", exact: true }).click();
        await expect(card(3)).toBeVisible();
        hold.poll.release();
        hold.poll = null;
        await page.clock.runFor(1_000);
        await expect(pill).toHaveCount(0);
      }
      assert.equal(await page.evaluate(() => window.sseOpened), 0);
      assert.deepEqual(errors, []);
      console.log(`${scenario.name}: PASS no SSE; ${scenario.full ? "zero-GET status flow settled and in flight; hidden-only arrival no pill; two postings = 1 role; stale poll after a filter change ignored; " : ""}pill + Show loads once`);
    } catch (error) { failures.push(`${scenario.name}: ${error.message}`); console.log(`FAIL ${scenario.name}: ${error.message.slice(0, 600)}`); }
    finally { hold.list?.release(); hold.poll?.release(); await context.close(); }
  }
  assert.deepEqual(failures, []);
} finally { await browser.close(); }
