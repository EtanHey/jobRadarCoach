import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import sharp from "sharp";

const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4327";
const output = process.env.GLOBE_QA_OUTPUT;
const phase = process.env.GLOBE_LAYOUT_PHASE ?? "after";
assert.equal(new URL(base).hostname, "127.0.0.1");
assert.ok(output);
await mkdir(output, { recursive: true });
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const jobs = Array.from({ length: 24 }, (_, n) => ({
  id: id(n), title: `Fixture engineer ${n}`, company: `Fixture ${n}`, source: "fixture",
  last_seen_at: "2026-09-22T00:00:00Z", first_seen_at: "2026-09-22T00:00:00Z",
  experience: "3+ years", description_available: false, seniority_origin: "title", extraction_state: "not-extracted",
  location: "Rehovot, Israel", remote: true, seniority: "Junior", stack: ["React"],
  salary: null, url: "https://example.test", apply_url: null, posted_at: null,
  status: "new", status_reason: null, score: 85, fit_line: null, recommendation: "apply",
}));
const points = jobs.map((job, n) => ({ posting_id: job.id, lat: 31.8 + n * .01,
  lng: 34.8 + n * .01, precision: "city", source: "fixture", resolved_at: "2026-09-22T00:00:00Z" }));
const payload = { jobs, points, total_count: jobs.length, resolved_count: jobs.length,
  unresolved_count: 0, attribution: "© OpenStreetMap contributors" };
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const receipts = [];
try {
  for (const [name, viewport] of [["desktop", { width: 1440, height: 900 }], ["mobile", { width: 390, height: 844 }]]) {
    const context = await browser.newContext({ viewport, reducedMotion: "reduce" });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
    page.on("requestfailed", request => { if (request.failure()?.errorText !== "net::ERR_ABORTED") errors.push(`${request.url()}: ${request.failure()?.errorText}`); });
    await page.addInitScript(() => { window.EventSource = class { addEventListener() {} close() {} }; });
    await page.route("**/*", route => {
      const url = new URL(route.request().url());
      if (url.hostname !== "127.0.0.1") return url.hostname.endsWith("cartocdn.com") ? route.continue() : route.abort();
      if (url.pathname === "/api/jobs/globe") return route.fulfill({ json: payload });
      if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs } });
      if (url.pathname === "/api/events") return route.fulfill({ contentType: "text/event-stream", body: "event: ready\ndata: {}\n\n" });
      return route.continue();
    });
    try {
      await page.goto(base);
      await page.getByRole("button", { name: "Globe", exact: true }).click();
      await page.getByText("Drag to explore", { exact: false }).waitFor({ timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(900);
      const metrics = await page.evaluate(() => {
        const box = selector => document.querySelector(selector)?.getBoundingClientRect();
        const globe = box(".job-globe"), rail = box(".globe-rail"), layout = box(".globe-layout");
        const legend = box("[data-globe-legend]"), toolbar = box("[data-job-toolbar]");
        const toggle = [...document.querySelectorAll("button")].find(node => node.textContent?.trim() === "Globe" && node.offsetWidth)?.getBoundingClientRect();
        const reset = [...document.querySelectorAll("button")].find(node => node.textContent?.trim() === "Reset view" && node.offsetWidth)?.getBoundingClientRect();
        const railElement = document.querySelector(".globe-rail");
        return { viewport: { width: innerWidth, height: innerHeight }, documentHeight: document.documentElement.scrollHeight,
          documentWidth: document.documentElement.scrollWidth, globe: globe && { x: globe.x, y: globe.y, width: globe.width, height: globe.height },
          rail: rail && { x: rail.x, y: rail.y, width: rail.width, height: rail.height }, layout: layout && { y: layout.y, height: layout.height },
          legend: legend && { y: legend.y, bottom: legend.bottom, height: legend.height }, toolbar: toolbar && { bottom: toolbar.bottom },
          toggle: toggle && { y: toggle.y, x: toggle.x }, reset: reset && { y: reset.y, right: reset.right },
          railScrollHeight: railElement?.scrollHeight, railClientHeight: railElement?.clientHeight,
          footerCount: document.querySelectorAll(".globe-footer").length,
          removedTextCount: [...document.querySelectorAll("p")].filter(node => node.textContent?.includes("Select a posting to see its location")).length,
          zoom: Number(document.querySelector("[data-projection]")?.getAttribute("data-zoom")),
        };
      });
      const globePng = await page.locator(".job-globe").screenshot();
      const { data, info } = await sharp(globePng).removeAlpha().raw().toBuffer({ resolveWithObject: true });
      const row = Math.floor(info.height / 2), hits = [];
      for (let x = 12; x < info.width - 12; x++) {
        const offset = (row * info.width + x) * info.channels;
        if (Math.abs(data[offset] - 8) + Math.abs(data[offset + 1] - 15) + Math.abs(data[offset + 2] - 28) > 10) hits.push(x);
      }
      metrics.globeDiameterRatio = hits.length ? (hits.at(-1) - hits[0]) / Math.min(info.width, info.height) : 0;
      await page.screenshot({ path: `${output}/${name}-${phase}.png`, fullPage: true });
      await page.screenshot({ path: `${output}/${name}-${phase}-viewport.png` });
      receipts.push({ name, metrics, errors });
      if (phase === "after") {
        assert.deepEqual(errors, []);
        assert.ok(metrics.legend && metrics.toolbar && metrics.legend.y >= metrics.toolbar.bottom - 1, "legend follows filters");
        assert.ok(metrics.toggle && metrics.reset && Math.abs(metrics.toggle.y - metrics.reset.y) < 8, "Globe sits beside Reset view");
        assert.equal(metrics.footerCount, 0);
        assert.equal(metrics.removedTextCount, 0);
        assert.ok(metrics.globeDiameterRatio > .7 && metrics.globeDiameterRatio < 1.05, "globe fills the shorter map dimension without clipping");
        assert.ok(metrics.documentWidth <= viewport.width, "no horizontal overflow");
        if (name === "desktop") {
          assert.ok(metrics.documentHeight <= viewport.height + 1, "document does not scroll in globe mode");
          assert.ok(metrics.railScrollHeight > metrics.railClientHeight + 100, "rail owns vertical scroll");
          assert.ok(Math.abs(metrics.globe.y - metrics.rail.y) < 5, "map and rail align");
          assert.ok(metrics.layout.height >= viewport.height - metrics.layout.y - 45, "map and rail fill remaining viewport above connection status");
          assert.ok(metrics.layout.y < viewport.height * .37, "header and filters are compact");
        } else {
          assert.ok(metrics.globe.y < metrics.rail.y, "mobile stacks map first");
        }
      }
    } finally { await context.close(); }
  }
} finally { await browser.close(); }
await writeFile(`${output}/layout-${phase}.json`, JSON.stringify(receipts, null, 2));
console.log(JSON.stringify(receipts));
