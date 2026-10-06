// Reviewer probe (synthetic, loopback). S1: a cached inactive "Seen" view after a status change.
// S2: a stalled automatic-Seen PATCH, drawer closed, then a manual status change on another card.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
const base = process.env.GLOBE_QA_URL; assert.equal(new URL(base).hostname, "127.0.0.1");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const job = (n, status = "new") => ({ id: id(n), title: `Cache engineer ${n}`, company: `Fixture ${n}`, source: "fixture",
  last_seen_at: "2026-10-05T08:00:00Z", first_seen_at: "2026-10-05T08:00:00Z", experience: null, description_available: false,
  seniority_origin: "title", extraction_state: "not-extracted", location: "Rehovot, Israel", remote: true, seniority: "Junior",
  stack: ["React"], salary: null, url: "https://example.test", apply_url: null, posted_at: null, status, status_reason: null,
  score: 90 - n, fit_line: null, recommendation: "apply", alive: true });
const results = [];
const check = (name, ok, detail) => results.push(`${ok ? "OK  " : "FAIL"} ${name}${detail ? `: ${detail}` : ""}`);
const browser = await chromium.launch({ headless: true });
async function board(prefsFilter) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  const rows = [job(0), job(1), job(2, "seen")];
  const log = []; const held = [];
  const state = { holdPatch: false };
  await page.addInitScript(f => localStorage.setItem("job-radar.board-preferences", JSON.stringify({ version: 3, filter: f, view: { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "all", sort: "fit" } })), prefsFilter);
  await page.route("**/api/**", async route => {
    const request = route.request(); const url = new URL(request.url());
    if (url.pathname === "/api/jobs") {
      if (url.searchParams.has("since")) return route.fulfill({ json: { jobs: [] } });
      const f = url.searchParams.get("filter");
      log.push(`GET list ${f}`);
      const out = rows.filter(r => f === "all" ? true : f === "new-for-me" ? r.status === "new" : r.status === f);
      return route.fulfill({ json: { jobs: structuredClone(out) } });
    }
    const row = rows.find(r => url.pathname.startsWith(`/api/jobs/${r.id}`));
    if (!row) return route.fulfill({ status: 404, json: { error: "fixture only" } });
    if (url.pathname.endsWith("/status")) {
      const patch = request.postDataJSON(); log.push(`PATCH ${row.id.slice(-1)} ${patch.status}${patch.automatic ? " auto" : ""}`);
      if (state.holdPatch && patch.automatic) { held.push(route); return; }
      if (!patch.automatic || row.status === "new") row.status = patch.status;
      return route.fulfill({ json: { status: row.status, reason: null } });
    }
    return route.fulfill({ json: { job: { ...row, raw_jd: "body", reasons: [], score_payload: null, brain: null, scored_at: null } } });
  });
  await page.goto(base);
  return { context, page, rows, log, held, state };
}
const card = (page, n) => page.locator(`article[data-posting-id="${id(n)}"]`);
const filterBtn = (page, name) => page.getByRole("button", { name, exact: true });
const open = (page, n) => card(page, n).getByRole("button", { name: `Open Cache engineer ${n} at Fixture ${n}`, exact: true }).click();
const close = async page => { await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click(); await page.getByRole("dialog").waitFor({ state: "hidden" }); };
try {
  { // S1
    const { context, page, log } = await board("all");
    await card(page, 0).waitFor();
    await filterBtn(page, "Seen").click(); await card(page, 2).waitFor();
    await filterBtn(page, "All roles").click(); await card(page, 0).waitFor();
    const beforeAuto = log.filter(l => l.startsWith("PATCH 0 ")).length;
    const beforeActive = log.filter(l => l === "GET list all").length;
    await open(page, 0);
    await expect(page.getByRole("dialog").getByRole("combobox", { name: "Application status" })).toHaveText("Seen");
    await close(page);
    const autoPatches = log.filter(l => l.startsWith("PATCH 0 ")).length - beforeAuto;
    const autoReads = log.filter(l => l === "GET list all").length - beforeActive;
    const before = log.filter(l => l === "GET list seen").length;
    await filterBtn(page, "Seen").click(); await card(page, 2).waitFor(); await page.waitForTimeout(800);
    const seenReads = log.filter(l => l === "GET list seen").length - before;
    const shown = await card(page, 0).count();
    check("S1 revisit Seen after auto-Seen of card 0 shows card 0", shown === 1 && seenReads === 1 && autoPatches === 1 && autoReads === 0, `card0=${shown}, seen GETs on revisit=${seenReads}, autoPATCHes=${autoPatches}, activeGETs=${autoReads}`);
    await context.close();
  }
  { // S2
    const { context, page, log, held, state } = await board("all");
    await card(page, 0).waitFor();
    state.holdPatch = true;
    await open(page, 0);
    await expect.poll(() => held.length).toBe(1);
    const aborted = page.waitForEvent("requestfailed", { timeout: 2000, predicate: request => new URL(request.url()).pathname === `/api/jobs/${id(0)}/status` }).then(() => true, () => false);
    await close(page);
    const requestAborted = await aborted;
    state.holdPatch = false;
    await open(page, 1);
    const select = page.getByRole("dialog").getByRole("combobox", { name: "Application status" });
    await expect(select).toHaveText(/Seen|New/, { timeout: 3000 }).catch(() => {});
    const beforeList = log.filter(l => l.startsWith("GET list")).length;
    const disabled = await page.getByRole("dialog").locator("fieldset").first().evaluate(el => el.disabled).catch(() => "n/a");
    let changed = false;
    try {
      await select.click({ timeout: 2000 });
      await page.getByRole("option", { name: "Applied", exact: true }).click({ timeout: 2000 });
      await expect(select).toHaveText("Applied", { timeout: 3000 }); changed = true;
    } catch { changed = false; }
    const manualPatches = log.filter(l => l === "PATCH 1 applied").length;
    const activeReads = log.filter(l => l.startsWith("GET list")).length - beforeList;
    check("S2 stalled auto-Seen on card 0 does not block a status change on card 1", changed && requestAborted && manualPatches === 1 && activeReads === 0, `aborted=${requestAborted}; manualPATCHes=${manualPatches}; activeGETs=${activeReads}; fieldset.disabled=${disabled}; log=${log.filter(l => l.startsWith("PATCH")).join(" | ")}`);
    for (const r of held) await r.fulfill({ json: { status: "seen", reason: null } }).catch(() => {});
    await context.close();
  }
} finally { await browser.close(); }
console.log(results.join("\n"));
process.exit(results.some(l => l.startsWith("FAIL")) ? 1 : 0);
