// Two isolated browser contexts against the credential-free Next fixture app.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4324";
assert.equal(new URL(base).hostname, "127.0.0.1");
const output = process.env.GLOBE_QA_OUTPUT;
assert.ok(output, "Set GLOBE_QA_OUTPUT for screenshot evidence");
await mkdir(output, { recursive: true });
const jobs = [0, 1, 2].map(n => ({ id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
  title: `Retained engineer ${n}`, company: `Fixture ${n}`, source: "fixture",
  last_seen_at: "2026-09-22T00:00:00Z", first_seen_at: "2026-09-22T00:00:00Z",
  experience: null, description_available: false, seniority_origin: "title", extraction_state: "not-extracted",
  location: "Rehovot, Israel", remote: true, seniority: "Junior", stack: ["React"], salary: null,
  url: "https://example.test", apply_url: null, posted_at: null, status: "new", status_reason: null,
  score: 85 - n, fit_line: null, recommendation: "apply", alive: true }));
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const contexts = await Promise.all([0, 1].map(() => browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" })));
const pages = await Promise.all(contexts.map(context => context.newPage()));
const errors = [];
const fixture = { failHydration: false, hydrationCalls: 0, newRoles: 0 };
for (const page of pages) {
  page.on("pageerror", error => errors.push(error.message));
  await page.clock.install();
  await page.route("**/api/**", route => {
    const url = new URL(route.request().url());
    const filtered = url.searchParams.get("filter") === "new-for-me" ? jobs.filter(job => job.status === "new") : jobs;
    // The new-roles poll (since=) sees one arriving role while fixture.newRoles is set.
    if (url.searchParams.has("since")) return route.fulfill({ json: { jobs: fixture.newRoles ? [{ ...jobs[0], id: "00000000-0000-4000-8000-000000000099", title: "Arriving role", company: "Arriving" }] : [] } });
    if (url.pathname === "/api/jobs") {
      const ids = url.searchParams.get("ids")?.split(",");
      if (ids) fixture.hydrationCalls += 1;
      if (ids && fixture.failHydration) return route.fulfill({ status: 503, json: { error: "fixture offline" } });
      return route.fulfill({ json: { jobs: ids ? jobs.filter(job => ids.includes(job.id)) : filtered.filter(job => job.id !== jobs[2].id) } });
    }
    if (url.pathname === "/api/jobs/globe") return route.fulfill({ json: { jobs: filtered,
      points: filtered.map(job => ({ posting_id: job.id, lat: 31.9, lng: 34.8, precision: "city", source: "fixture", resolved_at: "2026-09-22T00:00:00Z" })),
      total_count: filtered.length, resolved_count: filtered.length, unresolved_count: 0, attribution: "fixture" } });
    const job = jobs.find(candidate => url.pathname.startsWith(`/api/jobs/${candidate.id}`));
    if (!job) return route.fulfill({ status: 404, json: { error: "fixture only" } });
    if (url.pathname.endsWith("/status")) {
      const patch = route.request().postDataJSON();
      if (!patch.automatic || job.status === "new") job.status = patch.status;
      return route.fulfill({ json: { status: job.status, reason: null } });
    }
    return route.fulfill({ json: { job: { ...job, raw_jd: null, reasons: [], score_payload: null, brain: null, scored_at: null } } });
  });
}
const card = (page, n) => page.locator(`article[data-posting-id="${jobs[n].id}"]`);
// The board no longer refreshes itself: the next poll offers the pill, and Show reloads.
async function refresh(page) {
  fixture.newRoles = 1;
  await page.clock.fastForward(91_000);
  await page.locator("[data-new-roles]").click();
  fixture.newRoles = 0;
}
// In New for me a kept card that moved on from "new" is settled: dimmed content plus a text status chip.
const keptChip = (page, n) => card(page, n).locator("[data-kept-status]");
try {
  const [a, b] = pages;
  await Promise.all(pages.map(page => page.goto(base)));
  await expect(card(a, 0)).toBeVisible();
  await card(b, 0).getByRole("button", { name: "Open Retained engineer 0 at Fixture 0", exact: true }).click();
  await b.getByRole("dialog").getByRole("combobox", { name: "Application status" }).click();
  await b.getByRole("option", { name: "Applied", exact: true }).click();
  // Explicit mutation removes the card only in the initiating tab.
  await expect(card(b, 0)).toHaveCount(0);
  const before = fixture.hydrationCalls;
  await refresh(a);
  await expect.poll(() => fixture.hydrationCalls).toBeGreaterThan(before);
  await expect(card(a, 0)).toBeVisible();
  await expect(card(a, 0)).toHaveAttribute("data-settled", "");
  await expect(keptChip(a, 0)).toHaveText("Applied");
  await expect(card(a, 1)).not.toHaveAttribute("data-settled", "");
  await expect(keptChip(a, 1)).toHaveCount(0);
  assert.equal(await card(a, 0).evaluate(article => getComputedStyle(article).opacity), "1", "the frame (hover border, focus ring) is not dimmed");
  await card(a, 0).getByRole("button").first().focus();
  assert.notEqual(await card(a, 0).evaluate(article => getComputedStyle(article).boxShadow), "none", "focus ring still visible on a settled card");
  await a.screenshot({ path: `${output}/list-kept-applied.png` });
  assert.deepEqual(await a.locator("article[data-posting-id]").evaluateAll(cards => cards.map(row => row.dataset.postingId)), jobs.slice(0, 2).map(job => job.id));
  await card(a, 0).getByRole("button").first().click();
  await expect(a.getByRole("dialog").getByRole("combobox", { name: "Application status" })).toHaveText("Applied");
  await a.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
  await a.getByRole("dialog").waitFor({ state: "hidden" });
  // A bookmark is an existing card indicator of retained summary truth, unlike
  // the drawer detail GET which independently reads the latest status.
  jobs[0].status = "worth_checking";
  await refresh(a);
  await expect(card(a, 0).locator("[data-kept-status]")).toHaveText("Worth checking");
  await a.screenshot({ path: `${output}/list-retained.png` });
  fixture.failHydration = true;
  await refresh(a);
  await expect(a.getByText(/Showing previous results/)).toBeVisible();
  await expect(card(a, 0).locator("[data-kept-status]")).toHaveText("Worth checking");
  fixture.failHydration = false;
  await a.getByRole("button", { name: "Globe", exact: true }).click();
  await expect(card(a, 2)).toBeVisible({ timeout: 30000 });
  await expect(card(a, 0).locator("[data-kept-status]")).toHaveText("Worth checking");
  // ID 2 exists only in the globe cohort, beyond the list fixture's row limit.
  await b.evaluate(async id => {
    await fetch(`/api/jobs/${id}/status`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "worth_checking" }) });
  }, jobs[2].id);
  await refresh(a);
  await expect(card(a, 2).locator("[data-kept-status]")).toHaveText("Worth checking");
  await expect(card(a, 0).locator("[data-kept-status]")).toHaveText("Worth checking");
  await a.screenshot({ path: `${output}/globe-retained.png` });
  await a.getByRole("button", { name: "Globe", exact: true }).click();
  await a.getByRole("button", { name: "All roles", exact: true }).click();
  await a.getByRole("button", { name: "New for me", exact: true }).click();
  await expect(card(a, 0)).toHaveCount(0);
  assert.deepEqual(errors, []);
  console.log("PASS: two contexts; background Applied retained with the settled cue; explicit Applied removed locally; list/globe bookmarks refresh; failed hydration warns; leaving the list view clears list retention.");
} finally { await browser.close(); }
