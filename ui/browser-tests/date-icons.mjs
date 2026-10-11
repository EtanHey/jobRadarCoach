// Real components/CSS in a synthetic loopback page; no owner session or provider access.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { build } from "esbuild";
import postcss from "postcss";
import tailwind from "@tailwindcss/postcss";
import { chromium } from "@playwright/test";

const root = resolve(import.meta.dirname, "..");
const output = process.env.DATE_ICONS_OUT ?? resolve(root, "../docs.local/qa/2026-10-05-date-icons");
await mkdir(output, { recursive: true });
const bundle = await build({ write: false, bundle: true, format: "iife", jsx: "automatic", tsconfig: resolve(root, "tsconfig.json"),
  define: { "process.env.NODE_ENV": '"production"', "process.env": "{}" }, stdin: { resolveDir: root, loader: "tsx", contents: `
import { createRoot } from "react-dom/client";
import { useEffect, useRef, useState } from "react";
import { JobCard } from "./components/job-card";
import { JobDrawer } from "./components/job-drawer";
import { PostingDates } from "./components/posting-dates";
import { filterJobGroups } from "./lib/job-filters";

const base = { company: "Fixture", source: "fixture", location: "Tel Aviv, Israel", remote: true,
  seniority: null, stack: [], salary: null, url: "https://example.test", apply_url: null,
  score: 80, status: "new", status_reason: null, alive: null, fit_line: null, recommendation: null,
  last_seen_at: "2026-10-04T00:00:00Z", description_available: false,
  seniority_origin: "unknown", extraction_state: "not-extracted" };
const rows = [
  { ...base, id: "00000000-0000-4000-8000-000000000001", title: "Older republished role", experience: "5+ years of backend engineering experience",
    posted_at: "2026-09-01T12:00:00Z", last_published_at: "2026-10-03T12:00:00Z", first_seen_at: "2026-10-04T10:00:00Z" },
  { ...base, id: "00000000-0000-4000-8000-000000000002", title: "New original role", score: 70, experience: "3+ years of experience",
    posted_at: "2026-10-02T12:00:00Z", last_published_at: "2026-10-02T12:00:00Z", first_seen_at: "2026-10-02T12:00:00Z" },
  { ...base, id: "00000000-0000-4000-8000-000000000003", title: "Relisted role", score: 60, experience: "4+ years building production systems",
    posted_at: "2026-09-28T12:00:00Z", last_published_at: "2026-09-28T12:00:00Z", first_seen_at: "2026-09-28T13:00:00Z" },
  { ...base, id: "00000000-0000-4000-8000-000000000004", title: "Relisted role", score: 60, experience: "4+ years building production systems",
    posted_at: "2026-08-20T12:00:00Z", last_published_at: "2026-08-20T12:00:00Z", first_seen_at: "2026-08-20T13:00:00Z" },
  { ...base, id: "00000000-0000-4000-8000-000000000005", title: "Simultaneous twin role", score: 50, experience: "2+ years of experience",
    posted_at: "2026-10-02T12:00:00Z", last_published_at: "2026-10-02T12:00:00Z", first_seen_at: "2026-10-02T12:00:00Z" },
  { ...base, id: "00000000-0000-4000-8000-000000000006", title: "Simultaneous twin role", score: 50, experience: "2+ years of experience",
    posted_at: "2026-10-02T12:00:00Z", last_published_at: "2026-10-02T12:00:00Z", first_seen_at: "2026-10-02T12:00:00Z" },
];
const options = { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" };
const compare = rows[0];
function App() {
  const openerRef = useRef(null), [selected, selectJob] = useState(null);
  const selectedJob = rows.find(row => row.id === selected);
  // Detail arrives after the drawer opens, as the real fetch does.
  const [loaded, setLoaded] = useState(null);
  useEffect(() => { const timer = setTimeout(() => setLoaded(selected), 150); return () => clearTimeout(timer); }, [selected]);
  return <main className="mx-auto min-h-screen max-w-5xl bg-background p-4 text-foreground"><h1 className="mb-4 text-xl font-semibold">Best Fit · date icons fixture</h1>
    <section className="grid gap-4 sm:grid-cols-2">{filterJobGroups(rows, options).map(({job, alternates}) =>
      <JobCard key={job.id} job={job} alternateCount={alternates.length} openerRef={openerRef} selectJob={selectJob}>{null}</JobCard>)}</section>
    <section data-compare className="mt-6 grid gap-2 rounded-xl border bg-card p-4 text-xs text-muted-foreground">
      <p className="font-medium text-foreground">Posted icon: plus vs calendar-plus</p>
      <div data-compare-variant="plus" className="flex items-center gap-3"><span className="w-28">plus (shipped)</span><PostingDates postedAt={compare.posted_at} lastPublishedAt={compare.last_published_at} firstSeenAt={compare.first_seen_at} /></div>
      <div data-compare-variant="calendar-plus" className="flex items-center gap-3"><span className="w-28">calendar-plus</span><PostingDates postedIcon="calendar-plus" postedAt={compare.posted_at} lastPublishedAt={compare.last_published_at} firstSeenAt={compare.first_seen_at} /></div>
    </section>
    <JobDrawer selected={selected} selectedJob={selectedJob} selectJob={selectJob} openerRef={openerRef}
      detail={selectedJob && loaded === selected ? {...selectedJob, raw_jd: null, reasons: [], score_payload: null, brain: null, scored_at: null} : null}
      detailError="" retryDetail={() => {}} /></main>;
}
createRoot(document.getElementById("root")).render(<App/>);` } });
const css = (await postcss([tailwind({ base: root })]).process(await readFile(resolve(root, "app/globals.css"), "utf8"), { from: resolve(root, "app/globals.css") })).css;
const server = createServer((req, res) => {
  if (req.url === "/app.js") { res.setHeader("Content-Type", "text/javascript"); return res.end(bundle.outputFiles[0].text); }
  if (req.url === "/style.css") { res.setHeader("Content-Type", "text/css"); return res.end(css); }
  res.setHeader("Content-Type", "text/html");
  return res.end(`<!doctype html><html${req.url.includes("theme=dark") ? ' class="dark"' : ""}><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/style.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>`);
});
await new Promise(ready => server.listen(0, "127.0.0.1", ready));

const tooltip = page => page.getByRole("tooltip");
async function expectTooltip(page, text) {
  await tooltip(page).filter({ hasText: text }).waitFor({ timeout: 3000 });
  // The tooltip paints on top (not hidden behind the card overlay or the drawer).
  const onTop = await tooltip(page).evaluate(node => { const box = node.getBoundingClientRect();
    return node.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)); });
  assert.equal(onTop, true, `tooltip "${text}" is covered`);
}
async function expectNoTooltip(page) { await tooltip(page).waitFor({ state: "hidden", timeout: 3000 }); }

const browser = await chromium.launch({ headless: true });
try {
  for (const theme of ["light", "dark"]) for (const width of [1280, 390]) {
    const mobile = width === 390;
    const context = await browser.newContext({ viewport: { width, height: 900 }, timezoneId: "Asia/Jerusalem", hasTouch: mobile, isMobile: mobile });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => { errors.push(error.message); console.error("PAGEERROR", error.message); });
    await page.route("**/*", route => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
    await page.addInitScript(() => { Date.now = () => Date.parse("2026-10-04T12:00:00Z"); });
    await page.goto(`http://127.0.0.1:${server.address().port}/?theme=${theme}`);
    await page.getByRole("heading", { name: "New original role" }).waitFor({ timeout: 10000 });
    const tag = `${theme}-${width}`;

    const old = page.locator('article[data-posting-id$="000001"]');
    const fresh = page.locator('article[data-posting-id$="000002"]');
    const relisted = page.locator('article[data-posting-id$="000003"]');
    // Icon kinds and accessible names; ages are compact.
    assert.deepEqual(await old.locator("[data-date-kind]").evaluateAll(nodes => nodes.map(node => node.dataset.dateKind)), ["posted", "republished", "found"]);
    assert.deepEqual(await fresh.locator("[data-date-kind]").evaluateAll(nodes => nodes.map(node => node.dataset.dateKind)), ["posted", "found"]);
    await old.getByRole("button", { name: "Posted 2026-09-01, 33 days ago" }).waitFor();
    await old.getByRole("button", { name: "Republished 2026-10-03, 1 day ago" }).waitFor();
    await old.getByRole("button", { name: "Found by JRC 2026-10-04 13:00, 2 hours ago" }).waitFor();
    assert.doesNotMatch(await old.innerText(), /ago/);
    // Only single-posting publication evidence counts; linked date ranges do not.
    assert.equal(await old.locator("[data-repost-marker]").count(), 1);
    assert.equal(await relisted.locator("[data-repost-marker]").count(), 0);
    assert.equal(await fresh.locator("[data-repost-marker]").count(), 0);
    // Same-instant twins are alternative listings, not evidence of a repost.
    const twins = page.locator("article").filter({ has: page.getByRole("heading", { name: "Simultaneous twin role" }) });
    assert.equal(await twins.count(), 1);
    assert.equal(await twins.locator("[data-repost-marker]").count(), 0);
    assert.match(await twins.innerText(), /2 listings/);
    // The experience text is never truncated and nothing overflows the viewport.
    const clipped = await page.locator("[data-experience]").evaluateAll(nodes => nodes.filter(node => node.scrollWidth > node.clientWidth + 1).map(node => node.textContent));
    assert.deepEqual(clipped, []);
    assert.match(await old.locator("[data-experience]").innerText(), /^5\+ years of backend engineering experience$/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: resolve(output, `cards-${tag}.png`), fullPage: true });
    if (theme === "light") await page.locator("[data-compare]").screenshot({ path: resolve(output, `compare-${tag}.png`) });

    const posted = old.getByRole("button", { name: /^Posted / });
    const republished = old.getByRole("button", { name: /^Republished / });
    const foundIcon = old.getByRole("button", { name: /^Found by JRC / });
    if (!mobile) {
      await posted.hover();
      await expectTooltip(page, "Posted 2026-09-01");
      await page.screenshot({ path: resolve(output, `tooltip-hover-${tag}.png`) });
      await page.mouse.move(2, 2);
      await expectNoTooltip(page);
    } else {
      await republished.tap();
      await page.waitForTimeout(400);
      await expectTooltip(page, "Republished 2026-10-03");
      assert.equal(await page.getByRole("dialog").count(), 0, "tapping a date icon must not open the drawer");
      await page.screenshot({ path: resolve(output, `tooltip-tap-${tag}.png`) });
      await republished.tap();
      await expectNoTooltip(page);
    }
    await foundIcon.focus();
    await expectTooltip(page, "Found by JRC 2026-10-04 13:00");
    await page.keyboard.press("Escape");
    await expectNoTooltip(page);
    await foundIcon.blur();

    const openOld = page.getByRole("button", { name: "Open Older republished role at Fixture", exact: true });
    const drawer = page.getByRole("dialog");
    // Opening the drawer by pointer or keyboard must not land focus on a date icon (popping its tooltip),
    // so a single Escape still closes the drawer.
    for (const how of ["pointer", "keyboard"]) {
      if (how === "pointer") await openOld.click(); else { await openOld.focus(); await page.keyboard.press("Enter"); }
      await drawer.waitFor();
      await page.waitForTimeout(400);
      assert.equal(await page.evaluate(() => document.activeElement?.closest("[data-date-kind]") ? document.activeElement.getAttribute("aria-label") : null), null, `${how} open must not focus a date icon`);
      assert.equal(await tooltip(page).count(), 0, `${how} open must not show a date tooltip`);
      await page.keyboard.press("Escape");
      await drawer.waitFor({ state: "hidden", timeout: 3000 });
    }
    await openOld.click();
    await drawer.waitFor();
    const header = drawer.locator("[data-posting-dates]").first();
    assert.deepEqual(await header.locator("[data-date-kind]").evaluateAll(nodes => nodes.map(node => node.dataset.dateKind)), ["posted", "republished", "found"]);
    const drawerRepublished = header.getByRole("button", { name: "Republished 2026-10-03, 1 day ago" });
    if (mobile) await drawerRepublished.tap(); else await drawerRepublished.focus();
    await page.waitForTimeout(400);
    await expectTooltip(page, "Republished 2026-10-03");
    await page.screenshot({ path: resolve(output, `drawer-${tag}.png`), animations: "disabled" });
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log("PASS: date icon kinds + labels, repost marker, tooltip on hover/focus/tap above cards and drawer, untruncated experience; light/dark × 1280/390.");
} finally { await browser.close(); await new Promise(closed => server.close(closed)); }
