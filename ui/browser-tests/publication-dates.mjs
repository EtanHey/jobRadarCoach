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
const output = resolve(root, "../docs.local/l5-visual");
await mkdir(output, { recursive: true });
const bundle = await build({ write: false, bundle: true, format: "iife", jsx: "automatic", tsconfig: resolve(root, "tsconfig.json"),
  define: { "process.env.NODE_ENV": '"production"', "process.env": "{}" }, stdin: { resolveDir: root, loader: "tsx", contents: `
import { createRoot } from "react-dom/client";
import { useRef, useState } from "react";
import { JobCard } from "./components/job-card";
import { JobDrawer } from "./components/job-drawer";
import { filterJobGroups } from "./lib/job-filters";
const base = { company: "Fixture", source: "fixture", location: "Tel Aviv, Israel", remote: true,
  seniority: null, stack: [], salary: null, url: "https://example.test", apply_url: null,
  score: 80, status: "new", status_reason: null, alive: null, fit_line: null, recommendation: null,
  last_seen_at: "2026-10-04T00:00:00Z", experience: null, description_available: false,
  seniority_origin: "unknown", extraction_state: "not-extracted" };
const rows = [
  { ...base, id: "00000000-0000-4000-8000-000000000001", title: "Older republished role",
    posted_at: "2026-09-01T12:00:00Z", last_published_at: "2026-10-03T12:00:00Z", first_seen_at: "2026-10-04T10:00:00Z" },
  { ...base, id: "00000000-0000-4000-8000-000000000002", title: "New original role",
    posted_at: "2026-10-02T12:00:00Z", last_published_at: "2026-10-02T12:00:00Z", first_seen_at: "2026-10-02T12:00:00Z" },
];
const options = { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" };
function App() {
  const openerRef = useRef(null), [selected, selectJob] = useState(null);
  const selectedJob = rows.find(row => row.id === selected);
  return <main className="mx-auto max-w-5xl p-4"><h1 className="mb-4 text-xl font-semibold">Best Fit · publication date fixture</h1>
    <section className="grid gap-4 sm:grid-cols-2">{filterJobGroups(rows, options).map(({job}) =>
      <JobCard key={job.id} job={job} openerRef={openerRef} selectJob={selectJob}>{null}</JobCard>)}</section>
    <JobDrawer selected={selected} selectedJob={selectedJob} selectJob={selectJob} openerRef={openerRef}
      detail={selectedJob ? {...selectedJob, raw_jd: null, reasons: [], score_payload: null, brain: null, scored_at: null} : null}
      detailError="" retryDetail={() => {}} /></main>;
}
createRoot(document.getElementById("root")).render(<App/>);` } });
const css = (await postcss([tailwind({ base: root })]).process(await readFile(resolve(root, "app/globals.css"), "utf8"), { from: resolve(root, "app/globals.css") })).css;
const server = createServer((req, res) => {
  if (req.url === "/app.js") { res.setHeader("Content-Type", "text/javascript"); return res.end(bundle.outputFiles[0].text); }
  if (req.url === "/style.css") { res.setHeader("Content-Type", "text/css"); return res.end(css); }
  res.setHeader("Content-Type", "text/html");
  res.end('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/style.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>');
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ headless: true });
try {
  for (const width of [1280, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on("pageerror", error => { errors.push(error.message); console.error("PAGEERROR", error.message); });
    await page.route("**/*", route => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
    await page.addInitScript(() => { Date.now = () => Date.parse("2026-10-04T12:00:00Z"); });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.getByRole("heading", { name: "New original role" }).waitFor({ timeout: 10000 });
    assert.deepEqual(await page.locator("article h2").allTextContents(), ["New original role", "Older republished role"]);
    const old = page.locator('article[data-posting-id$="000001"]');
    assert.match(await old.innerText(), /Posted 33d ago · Republished 1d ago · Found 2h ago/);
    assert.equal(await old.locator("time").count(), 3);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: resolve(output, `cards-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: "Open Older republished role at Fixture", exact: true }).click();
    const drawer = page.getByRole("dialog");
    await drawer.waitFor();
    assert.match(await drawer.innerText(), /Posted 33d ago · Republished 1d ago · Found 2h ago/);
    await page.screenshot({ path: resolve(output, `drawer-${width}.png`), fullPage: true, animations: "disabled" });
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log("PASS: original-date tie order, 3 date timestamps, drawer dates, no horizontal overflow; desktop 1280 and mobile 390.");
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
