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
const output = resolve(root, "../docs.local/p5/visual");
await mkdir(output, { recursive: true });
const bundle = await build({ write: false, bundle: true, format: "iife", jsx: "automatic", tsconfig: resolve(root, "tsconfig.json"),
  define: { "process.env.NODE_ENV": '"production"', "process.env": "{}" }, stdin: { resolveDir: root, loader: "tsx", contents: `
import { createRoot } from "react-dom/client";
import { useRef, useState } from "react";
import { JobCard } from "./components/job-card";
import { JobDrawer } from "./components/job-drawer";
import { filterJobGroups } from "./lib/job-filters";
import { relatedDuplicateJobs } from "./lib/job-dedup";
const base = { company: "Fixture", source: "fixture", location: "Tel Aviv, Israel", remote: true,
  seniority: null, stack: [], salary: null, url: "https://example.test", apply_url: null,
  score: 80, status: "new", status_reason: null, alive: null, fit_line: null, recommendation: null,
  last_seen_at: "2026-10-04T00:00:00Z", experience: null, description_available: false,
  seniority_origin: "unknown", extraction_state: "not-extracted" };
const rows = [
  { ...base, id: "00000000-0000-4000-8000-000000000005", title: "ATS republished", source: "greenhouse", score: 90,
    posted_at: "2026-09-01T12:00:00Z", last_published_at: "2026-10-03T12:00:00Z", first_seen_at: "2026-10-04T10:00:00Z" },
  { ...base, id: "00000000-0000-4000-8000-000000000006", title: "ATS republished", source: "linkedin",
    posted_at: "2026-08-01T12:00:00Z", last_published_at: "2026-10-04T12:00:00Z", first_seen_at: "2026-08-01T12:00:00Z" },
  { ...base, id: "00000000-0000-4000-8000-000000000001", title: "Linked role", location: "Haifa District, Israel", source: "linkedin", external_id: "old",
    apply_url: null, url: "https://www.linkedin.com/jobs/view/111", posted_at: "2026-09-01T12:00:00Z", first_seen_at: "2026-09-01T12:00:00Z" },
  { ...base, id: "00000000-0000-4000-8000-000000000002", title: "Linked role", location: "Haifa, Israel", source: "greenhouse", external_id: "123",
    url: "https://job-boards.greenhouse.io/fixture/jobs/123", posted_at: "2026-10-03T12:00:00Z", first_seen_at: "2026-10-04T10:00:00Z" },
  { ...base, id: "00000000-0000-4000-8000-000000000003", title: "Explicit repost", location: "Haifa, Israel", source:"linkedin", url:"https://www.linkedin.com/jobs/view/333",
    linkedin_reposted_signal:{label:"Reposted 2 weeks ago",checked_at:"2026-10-04T10:00:00Z",url:"https://www.linkedin.com/jobs/view/333"},
    posted_at: "2026-10-02T12:00:00Z", first_seen_at: "2026-10-02T12:00:00Z" },
  { ...base, id: "00000000-0000-4000-8000-000000000004", title: "Independent opening", location: "Tel Aviv, Israel",
    posted_at: "2026-10-01T12:00:00Z", first_seen_at: "2026-10-01T12:00:00Z" },
];
const options = { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" };
function App() {
  const openerRef = useRef(null), [selected, selectJob] = useState(null);
  const selectedJob = rows.find(row => row.id === selected);
  return <main className="mx-auto max-w-5xl p-4"><h1 className="mb-4 text-xl font-semibold">Explicit LinkedIn repost · synthetic fixture</h1>
    <section className="grid gap-4 sm:grid-cols-2">{filterJobGroups(rows, options).map(({job,alternates}) =>
      <JobCard key={job.id} job={job} alternateCount={alternates.length} openerRef={openerRef} selectJob={selectJob}>{null}</JobCard>)}</section>
    <JobDrawer selected={selected} selectedJob={selectedJob} selectJob={selectJob} openerRef={openerRef}
      detail={selectedJob ? {...selectedJob, raw_jd: null, reasons: [], score_payload: null, brain: null, scored_at: null} : null}
      relatedJobs={relatedDuplicateJobs(rows, selected, selectedJob)} detailError="" retryDetail={() => {}} /></main>;
}
createRoot(document.getElementById("root")).render(<App/>);` } });
const css = (await postcss([tailwind({ base: root })]).process(await readFile(resolve(root, "app/globals.css"), "utf8"), { from: resolve(root, "app/globals.css") })).css;
const server = createServer((req, res) => {
  if (req.url === "/app.js") { res.setHeader("Content-Type", "text/javascript"); return res.end(bundle.outputFiles[0].text); }
  if (req.url === "/style.css") { res.setHeader("Content-Type", "text/css"); return res.end(css); }
  res.setHeader("Content-Type", "text/html");
  return res.end('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/style.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>');
});
await new Promise(ready => server.listen(0, "127.0.0.1", ready));
let browser = null;
// Linked group dates: the earliest original plus the latest publication, as date-icon buttons.
async function expectLinkedDates(scope) {
  assert.deepEqual(await scope.locator("[data-posting-dates]").first().locator("[data-date-kind]").evaluateAll(nodes => nodes.map(node => node.dataset.dateKind)), ["posted", "republished", "found"]);
  await scope.getByRole("button", { name: "Posted 2026-09-01, 33 days ago" }).waitFor();
  await scope.getByRole("button", { name: "Republished 2026-10-03, 1 day ago" }).waitFor();
  await scope.getByRole("button", { name: /^Found by JRC 2026-10-04 .*, 2 hours ago$/ }).waitFor();
}
try {
  browser = await chromium.launch({ headless: true });
  for (const width of [1280, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on("pageerror", error => { errors.push(error.message); console.error("PAGEERROR", error.message); });
    await page.route("**/*", route => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
    await page.addInitScript(() => { Date.now = () => Date.parse("2026-10-04T12:00:00Z"); });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.locator("article").first().waitFor({ timeout: 10000 });
    assert.deepEqual(await page.locator("article h2").allTextContents(), ["ATS republished", "Explicit repost", "Independent opening", "Linked role"]);
    const old = page.locator('article[data-posting-id$="000002"]');
    assert.equal(await old.locator("[data-repost-marker]").count(), 0, "linked date ranges must not infer a repost");
    const ats = page.locator('article[data-posting-id$="000005"]');
    assert.equal(await ats.locator("[data-repost-marker]").count(), 1, "grouped ATS republish evidence must survive");
    assert.equal(await ats.locator("[data-repost-marker]").innerText(), "Reposted: republished 2026-10-03");
    assert.match(await ats.innerText(), /2 listings/);
    await ats.getByRole("button", { name: /^Republished 2026-10-04,/ }).waitFor();
    assert.equal(await page.locator("article [data-repost-marker]").count(), 2);
    assert.equal(await page.locator('article[data-posting-id$="000003"] [data-repost-marker]').innerText(), "Reposted 2 weeks ago");
    await expectLinkedDates(old);
    assert.equal(await old.locator("time").count(), 3);
    assert.match(await old.innerText(), /2 listings/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: resolve(output, `cards-${width}.png`), fullPage: true });
    await page.getByRole("button", {name:"Open ATS republished at Fixture",exact:true}).click();
    const atsDrawer = page.getByRole("dialog");
    await atsDrawer.waitFor();
    assert.equal(await atsDrawer.locator("[data-repost-marker]").count(), 1, "grouped ATS drawer must retain listing evidence");
    assert.equal(await atsDrawer.locator("[data-repost-marker]").innerText(), "Reposted: republished 2026-10-03");
    await atsDrawer.getByRole("button", { name: /^Republished 2026-10-04,/ }).first().waitFor();
    await page.screenshot({path:resolve(output, `ats-drawer-${width}.png`),fullPage:true,animations:"disabled"});
    await atsDrawer.getByText("Other listings for this role (1)").click();
    await atsDrawer.getByRole("button", { name: /listing .*00000006/ }).click();
    assert.equal(await atsDrawer.locator("[data-repost-marker]").count(), 0, "LinkedIn alternate has no explicit repost label");
    await page.keyboard.press("Escape");
    await atsDrawer.waitFor({state:"hidden"});
    await page.getByRole("button", {name:"Open Explicit repost at Fixture",exact:true}).click();
    await page.getByRole("dialog").waitFor();
    assert.equal(await page.getByRole("dialog").locator("[data-repost-marker]").innerText(), "Reposted 2 weeks ago");
    assert.equal(await page.getByRole("dialog").locator("[data-repost-marker]").getAttribute("title"), "LinkedIn: Reposted 2 weeks ago · checked 2026-10-04");
    await page.screenshot({path:resolve(output, `explicit-drawer-${width}.png`),fullPage:true,animations:"disabled"});
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({state:"hidden"});
    await page.getByRole("button", { name: "Open Linked role at Fixture", exact: true }).click();
    const drawer = page.getByRole("dialog");
    await drawer.waitFor();
    assert.equal(await drawer.locator("[data-repost-marker]").count(), 0);
    await expectLinkedDates(drawer);
    await drawer.getByText("Other listings for this role (1)").click();
    assert.match(await drawer.innerText(), /linkedin/);
    await drawer.getByRole("button", { name: /listing .*00000001/ }).click();
    assert.match(await drawer.innerText(), /Other listings for this role \(1\)/);
    await drawer.getByRole("button", { name: "Posted 2026-09-01, 33 days ago" }).waitFor();
    await page.screenshot({ path: resolve(output, `drawer-${width}.png`), fullPage: true, animations: "disabled" });
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log("PASS: grouped ATS listing evidence independent of aggregate dates on card and drawer; explicit stored LinkedIn label on card and drawer, absent for inferred group dates, alternates and date icons retained, no overflow or page errors; desktop 1280 and mobile 390.");
} finally { await browser?.close(); await new Promise(closed => server.close(closed)); }
