import assert from "node:assert/strict";
import { chromium } from "@playwright/test";

const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4332";
assert.equal(new URL(base).hostname, "127.0.0.1");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const jobs = Array.from({ length: 15 }, (_, n) => ({ id: id(n), title: `Fixture engineer ${n}`,
  company: `Fixture ${n}`, source: "fixture", last_seen_at: "2026-09-22T00:00:00Z",
  first_seen_at: "2026-09-22T00:00:00Z", experience: "3+ years", description_available: false,
  seniority_origin: "title", extraction_state: "not-extracted", location: "Rehovot, Israel",
  remote: true, seniority: "Junior", stack: ["React"], salary: null, url: "https://example.test",
  apply_url: null, posted_at: null, status: "new", status_reason: null, score: 85,
  fit_line: null, recommendation: "apply" }));
const points = jobs.map((job, n) => ({ posting_id: job.id, lat: 31.8 + n * .08,
  lng: 34.8 + n * .08, precision: "city", source: "fixture", resolved_at: "2026-09-22T00:00:00Z" }));
const payload = { jobs, points, total_count: jobs.length, resolved_count: jobs.length,
  unresolved_count: 0, attribution: "© OpenStreetMap contributors" };
const browser = await chromium.launch({ headless: process.env.GLOBE_HEADFUL !== "1", args: process.env.GLOBE_SWIFTSHADER === "0" ? [] : ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const receipts = [];
try {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }, { width: 390, height: 844 }]) {
    for (const reducedMotion of ["no-preference", "reduce"]) {
      const context = await browser.newContext({ viewport, reducedMotion });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.addInitScript(() => {
        window.EventSource = class { addEventListener() {} close() {} };
        window.__transitions = [];
        const native = document.startViewTransition?.bind(document);
        if (native) document.startViewTransition = callback => {
          const record = { start: performance.now(), ready: null, done: null };
          window.__transitions.push(record);
          const transition = native(callback);
          transition.ready.then(() => { record.ready = performance.now(); record.animations = document.getAnimations().map(animation => ({ duration: animation.effect?.getTiming().duration, name: animation.animationName, pseudo: animation.effect?.pseudoElement })); }).catch(() => {});
          transition.finished.then(() => { record.done = performance.now(); });
          return transition;
        };
      });
      await page.route("**/api/**", route => {
        const path = new URL(route.request().url()).pathname;
        if (path === "/api/jobs/globe") return route.fulfill({ json: payload });
        if (path === "/api/jobs") return route.fulfill({ json: { jobs } });
        if (path === "/api/events") return route.fulfill({ contentType: "text/event-stream", body: "event: ready\ndata: {}\n\n" });
        return route.fulfill({ status: 404, json: { error: "fixture only" } });
      });
      try {
        await page.goto(base);
        const globe = page.getByRole("button", { name: "Globe", exact: true });
        await globe.waitFor();
        await page.locator(".globe-slot .job-globe").waitFor({ state: "attached" });
        assert.equal(await globe.locator("svg.lucide-globe").count(), 1);
        assert.equal(await globe.getAttribute("aria-pressed"), "false");
        await page.evaluate(() => {
          window.__mapWidths = [];
          window.__sampling = true;
          const sample = () => {
            if (!window.__sampling) return;
            if (document.querySelector('button[aria-label="Globe"]')?.getAttribute("aria-pressed") === "true") {
              const canvas = document.querySelector(".globe-slot .maplibregl-canvas");
              if (canvas) window.__mapWidths.push(canvas.clientWidth);
            }
            requestAnimationFrame(sample);
          };
          requestAnimationFrame(sample);
        });
        await page.locator("body").click({ position: { x: 2, y: 2 } });
        await page.keyboard.press("g");
        await page.getByRole("heading", { name: "On screen" }).waitFor({ timeout: 30000 });
        assert.equal(await globe.getAttribute("aria-pressed"), "true");
        const legend = page.locator("[data-globe-legend]");
        assert.equal(await legend.count(), 1);
        assert.equal(await legend.evaluate(node => node.parentElement?.classList.contains("job-results-summary")), true);
        if (viewport.width >= 1280) {
          const selectBox = await page.getByRole("combobox", { name: "Location" }).boundingBox();
          const globeBox = await globe.boundingBox();
          const resetBox = await page.getByRole("button", { name: "Reset view" }).boundingBox();
          const centers = { select: selectBox.y + selectBox.height / 2,
            globe: globeBox.y + globeBox.height / 2, reset: resetBox.y + resetBox.height / 2 };
          assert.ok(Math.abs(centers.select - centers.globe) <= 1, JSON.stringify(centers));
          assert.ok(Math.abs(centers.select - centers.reset) <= 1, JSON.stringify(centers));
        }
        await page.waitForFunction(() => document.querySelector("[data-projection]")?.getAttribute("data-zoom"));
        if (reducedMotion === "no-preference") {
          const transitions = await page.evaluate(() => window.__transitions);
          assert.equal(transitions.length, 1);
          await page.waitForFunction(() => window.__transitions[0]?.done !== null);
          const timings = await page.evaluate(() => ({ ready: window.__transitions[0].ready - window.__transitions[0].start,
            done: window.__transitions[0].done - window.__transitions[0].start, animations: window.__transitions[0].animations }));
          const viewAnimations = timings.animations.filter(animation => animation.pseudo?.startsWith("::view-transition"));
          assert.ok(viewAnimations.length > 0 && viewAnimations.every(animation => animation.duration === 420), `view transition durations ${JSON.stringify(viewAnimations)}`);
          if (process.env.GLOBE_STRICT_TIMING === "1") assert.ok(timings.done <= 600, `transition wall time ${timings.done}ms`);
          receipts.push({ viewport: viewport.width, reducedMotion, readyMs: timings.ready, finishedMs: timings.done, animationCount: viewAnimations.length });
        } else assert.equal(await page.evaluate(() => window.__transitions.length), 0);
        const mapWidths = await page.evaluate(() => { window.__sampling = false; return window.__mapWidths; });
        const finalWidth = await page.locator(".globe-slot .maplibregl-canvas").evaluate(canvas => canvas.clientWidth);
        assert.ok(finalWidth > 0, "map canvas has its final width");
        assert.ok(mapWidths.every(width => width === finalWidth), `map widths: ${JSON.stringify(mapWidths)}`);
        await page.waitForFunction(() => !document.documentElement.dataset.globeTransition);
        let savedCamera;
        if (viewport.width === 1440 && reducedMotion === "no-preference") {
          await page.getByText("Drag to spin · scroll to zoom").waitFor();
          await page.waitForTimeout(700);
          await page.getByRole("button", { name: "Zoom in" }).click();
          await page.waitForTimeout(400);
          const before = await page.locator("[data-projection]").evaluate(node => ({ center: node.dataset.center, zoom: node.dataset.zoom }));
          const canvasBox = await page.locator(".maplibregl-canvas").boundingBox();
          await page.mouse.move(canvasBox.x + canvasBox.width / 2, canvasBox.y + canvasBox.height / 2);
          await page.mouse.down();
          await page.mouse.move(canvasBox.x + canvasBox.width / 2 + 45, canvasBox.y + canvasBox.height / 2 + 30, { steps: 5 });
          await page.mouse.up();
          await page.getByText("Drag to spin · scroll to zoom").waitFor({ state: "hidden" });
          await page.waitForTimeout(500);
          savedCamera = await page.locator("[data-projection]").evaluate(node => ({ center: node.dataset.center, zoom: node.dataset.zoom }));
          assert.notEqual(savedCamera.center, before.center, "drag moves the camera");
        }
        const search = page.getByPlaceholder("Search title, company, or stack");
        await search.focus();
        await page.keyboard.press("g");
        assert.equal(await globe.getAttribute("aria-pressed"), "true");
        await globe.click();
        await page.waitForFunction(() => document.querySelector('button[aria-label="Globe"]')?.getAttribute("aria-pressed") === "false");
        assert.equal(await globe.getAttribute("aria-pressed"), "false");
        if (reducedMotion === "no-preference") {
          await page.waitForFunction(() => window.__transitions[1]?.done !== null);
          assert.equal(await page.evaluate(() => window.__transitions.length), 2);
        } else assert.equal(await page.evaluate(() => window.__transitions.length), 0);
        if (viewport.width === 1440 && reducedMotion === "no-preference") {
          await page.waitForFunction(() => !document.documentElement.dataset.globeTransition);
          await globe.click();
          await page.waitForFunction(() => document.querySelector('button[aria-label="Globe"]')?.getAttribute("aria-pressed") === "true");
          await page.waitForFunction(() => document.querySelector("[data-projection]")?.getAttribute("data-zoom"));
          await page.waitForTimeout(150);
          const restoredCamera = await page.locator("[data-projection]").evaluate(node => ({ center: node.dataset.center, zoom: node.dataset.zoom }));
          assert.deepEqual(restoredCamera, savedCamera, "reopen restores the exact camera");
          assert.equal(await page.getByText("Drag to spin · scroll to zoom").count(), 0, "hint stays dismissed after reopen");
          await page.locator(".globe-rail [data-posting-id] > button").first().click();
          await page.locator('[data-globe-selected="true"]').first().waitFor();
          await page.keyboard.press("Escape");
          assert.equal(await page.locator('[data-globe-selected="true"]').count(), 0, "Escape clears the selected globe card");
        }
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    }
  }
} finally { await browser.close(); }
console.log(`globe-toolbar-motion: PASS ${JSON.stringify(receipts)}`);
