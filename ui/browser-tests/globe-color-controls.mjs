import assert from "node:assert/strict";
import { chromium } from "@playwright/test";

const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4332";
assert.equal(new URL(base).hostname, "127.0.0.1");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scores = [85, 70, 40, null, 85, 70];
const jobs = scores.map((score, n) => ({ id: id(n), title: `Fixture role ${n}`, company: "Fixture", source: "fixture",
  last_seen_at: "2026-09-22T00:00:00Z", first_seen_at: "2026-09-22T00:00:00Z", experience: null,
  description_available: false, seniority_origin: "unknown", extraction_state: "not-extracted", location: "Rehovot, Israel",
  remote: false, seniority: null, stack: [], salary: null, url: "https://example.test", apply_url: null,
  posted_at: null, status: "new", status_reason: null, score, fit_line: null, recommendation: null }));
const points = jobs.map((job, n) => ({ posting_id: job.id, lat: 31.89 + (n > 3 ? .4 : n * .001),
  lng: 34.81 + (n > 3 ? .4 : n * .001), precision: "city", source: "fixture", resolved_at: "2026-09-22T00:00:00Z" }));
const payload = { jobs, points, total_count: jobs.length, resolved_count: jobs.length, unresolved_count: 0, attribution: "© OpenStreetMap contributors" };
const expected = { light: { space: "rgb(230, 238, 247)", ocean: "#a9d2ec", land: "#eef1e6", border: "#8d9bb0", label: "#56637a", sky: "#9cc9f5" },
  dark: { space: "rgb(5, 10, 20)", ocean: "#0c2238", land: "#1b2433", border: "#41536d", label: "#8c9ab0", sky: "#2f6fb8" } };
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  try {
    await context.addInitScript(() => {
      localStorage.setItem("job-radar-theme", "light");
      localStorage.setItem("job-radar.board-preferences", JSON.stringify({ version: 3, filter: "all", view: { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" } }));
      window.EventSource = class { addEventListener() {} close() {} };
    });
    const page = await context.newPage(), errors = [], styleUrls = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => {
      const request = route.request(), url = new URL(request.url());
      if (url.hostname.endsWith("cartocdn.com")) { if (url.pathname.endsWith("style.json")) styleUrls.push(url.pathname); return route.continue(); }
      if (url.hostname !== "127.0.0.1") return route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (request.method() !== "GET") return route.fulfill({ status: 405, json: { error: "Read only fixture" } });
      if (url.pathname === "/api/jobs/globe") return route.fulfill({ json: payload });
      if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs } });
      return route.fulfill({ status: 404, json: { error: "Fixture only" } });
    });
    await page.goto(base);
    await page.getByRole("button", { name: "Globe", exact: true }).filter({ visible: true }).click();
    const map = page.locator('[data-projection="globe"]');
    await map.waitFor({ timeout: 30000 });
    await page.locator(".globe-controls").waitFor();
    await page.waitForFunction(() => document.querySelector('[data-projection="globe"]')?.dataset.waterColor);
    await page.waitForFunction(() => document.querySelector('[data-projection="globe"]')?.dataset.dotRingColor);
    assert.ok(styleUrls.every(url => url.includes("voyager")), `inactive dark style fetched: ${styleUrls}`);
    const canvas = page.locator(".maplibregl-canvas");
    await canvas.evaluate(node => { window.__initialCanvas = node; });
    const inspectControls = () => page.locator(".globe-controls button").evaluateAll(buttons => buttons.map(button => {
      const box = button.getBoundingClientRect(), icon = button.querySelector("svg")?.getBoundingClientRect();
      const style = getComputedStyle(button);
      const rgb = color => { const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
        const ctx = canvas.getContext("2d"); ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1); return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3); };
      const luminance = color => rgb(color).map(value => { const c = value / 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
      const foreground = luminance(style.color), background = luminance(getComputedStyle(button.closest(".globe-controls")).backgroundColor);
      return { name: button.getAttribute("aria-label"), width: box.width, height: box.height,
        dx: icon ? Math.abs(icon.x + icon.width / 2 - box.x - box.width / 2) : 99,
        dy: icon ? Math.abs(icon.y + icon.height / 2 - box.y - box.height / 2) : 99,
        contrast: (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05) };
    }));
    const controls = await inspectControls();
    assert.deepEqual(controls.map(control => control.name), ["Zoom in", "Zoom out", "Use my location", "Full screen"]);
    assert.ok(controls.every(control => control.width >= 40 && control.height >= 40 && control.dx < 1 && control.dy < 1 && control.contrast >= 4.5), JSON.stringify(controls));
    const paint = async () => map.evaluate(node => ({ space: getComputedStyle(node.closest(".job-globe")).backgroundColor,
      ocean: node.dataset.waterColor, land: node.dataset.landColor, border: node.dataset.borderColor,
      label: node.dataset.labelColor, sky: node.dataset.skyColor, theme: node.dataset.styleTheme }));
    assert.deepEqual(await paint(), { ...expected.light, theme: "light" });
    assert.equal(await map.getAttribute("data-dot-ring-color"), "255,255,255,255", "light Deck sticker ring is white");
    assert.equal(await page.locator('[data-globe-legend] i').nth(3).evaluate(node => getComputedStyle(node).backgroundColor), "rgba(0, 0, 0, 0)");
    assert.equal(await page.locator('[data-globe-legend] i').nth(3).evaluate(node => getComputedStyle(node).borderTopColor), "rgb(100, 116, 139)");
    assert.equal(await page.locator('[aria-label="Not scored"]').first().evaluate(node => getComputedStyle(node).borderTopColor), "rgb(100, 116, 139)");
    assert.equal(await page.locator('[data-globe-legend] i').nth(1).evaluate(node => getComputedStyle(node).backgroundColor), "rgb(245, 158, 11)");
    assert.equal(await page.locator('[aria-label="Fit score 85 out of 100"]').first().evaluate(node => getComputedStyle(node).backgroundColor), "rgb(16, 185, 129)");
    const bubble = await page.locator(".globe-cluster").first().evaluate(node => ({ size: getComputedStyle(node, "::before").width,
      color: getComputedStyle(node, "::before").backgroundColor, target: node.getBoundingClientRect().width,
      ring: getComputedStyle(node, "::before").boxShadow }));
    assert.equal(bubble.size, "32px");
    assert.equal(bubble.color, "rgb(16, 185, 129)");
    assert.ok(bubble.target >= 44 && bubble.ring.includes("2px"), JSON.stringify(bubble));
    await page.getByRole("button", { name: "Zoom in" }).click();
    await page.waitForTimeout(400);
    const before = await map.evaluate(node => ({ center: node.dataset.center, zoom: node.dataset.zoom }));
    await page.getByRole("button", { name: "Use dark theme" }).click();
    await page.waitForFunction(() => document.querySelector('[data-projection="globe"]')?.dataset.styleTheme === "dark");
    assert.deepEqual(await paint(), { ...expected.dark, theme: "dark" });
    assert.equal(await map.getAttribute("data-dot-ring-color"), "5,10,20,255", "dark Deck sticker ring matches dark paper");
    assert.equal(await page.locator(".job-globe .maplibregl-ctrl-attrib").evaluate(node => getComputedStyle(node).backgroundColor),
      await page.locator(".globe-controls").evaluate(node => getComputedStyle(node).backgroundColor), "dark attribution uses the card surface");
    const darkControls = await inspectControls();
    assert.ok(darkControls.every(control => control.dx < 1 && control.dy < 1 && control.contrast >= 4.5), JSON.stringify(darkControls));
    assert.ok(styleUrls.some(url => url.includes("dark-matter")), "dark style fetched on demand");
    assert.equal(await canvas.evaluate(node => node === window.__initialCanvas), true, "theme change keeps the map canvas");
    assert.deepEqual(await map.evaluate(node => ({ center: node.dataset.center, zoom: node.dataset.zoom })), before, "theme change keeps the camera");
    await page.evaluate(() => Object.defineProperty(navigator, "geolocation", { configurable: true,
      value: { getCurrentPosition(_success, error) { error({ code: 1 }); } } }));
    await page.getByRole("button", { name: "Use my location" }).click();
    await page.getByText("Location unavailable · you can still explore", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Retry location" }).count(), 1);
    await page.getByRole("button", { name: "Full screen" }).click();
    await page.waitForFunction(() => document.fullscreenElement?.classList.contains("job-globe"));
    assert.equal(await page.locator(".job-globe").evaluate(node => document.fullscreenElement === node), true);
    assert.equal(await page.locator(".globe-rail").evaluate(node => document.fullscreenElement?.contains(node)), false);
    await page.getByRole("button", { name: "Exit full screen" }).click();
    await page.waitForFunction(() => !document.fullscreenElement);
    await page.evaluate(() => { Element.prototype.requestFullscreen = () => Promise.reject(new Error("fixture denied")); });
    await page.getByRole("button", { name: "Full screen" }).click();
    await page.waitForTimeout(100);
    assert.equal(errors.length, 0, JSON.stringify(errors));
    console.log(JSON.stringify({ result: "PASS", controls, darkControls, bubble, styleUrls, before, after: await paint() }));
  } finally { await context.close(); }
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, reducedMotion: "reduce" });
  try {
    await mobile.addInitScript(() => {
      delete Element.prototype.requestFullscreen;
      Object.defineProperty(Document.prototype, "fullscreenEnabled", { get: () => false });
      localStorage.setItem("job-radar-theme", "dark");
      window.EventSource = class { addEventListener() {} close() {} };
    });
    const page = await mobile.newPage();
    const mobileStyleUrls = [];
    const mobileErrors = [];
    page.on("pageerror", error => mobileErrors.push(error.message));
    await page.route("**/*", route => {
      const url = new URL(route.request().url());
      if (url.hostname.endsWith("cartocdn.com")) { if (url.pathname.endsWith("style.json")) mobileStyleUrls.push(url.pathname); return route.continue(); }
      if (url.pathname === "/api/jobs/globe") return route.fulfill({ json: payload });
      if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs } });
      if (url.pathname.startsWith("/api/")) return route.fulfill({ status: 404, json: { error: "Fixture only" } });
      return route.continue();
    });
    await page.goto(base);
    await page.getByRole("button", { name: "Globe", exact: true }).filter({ visible: true }).click();
    await page.locator(".globe-controls").waitFor({ timeout: 30000 });
    assert.equal(await page.getByRole("button", { name: "Full screen" }).count(), 0, "unsupported Fullscreen API hides the control");
    const sizes = await page.locator(".globe-controls button").evaluateAll(buttons => buttons.map(button => button.getBoundingClientRect().width));
    assert.deepEqual(sizes, [44, 44, 44]);
    assert.ok(mobileStyleUrls.length && mobileStyleUrls.every(url => url.includes("dark-matter")), JSON.stringify(mobileStyleUrls));
    assert.deepEqual(mobileErrors, []);
    console.log(JSON.stringify({ mobileControlSizes: sizes, mobileStyleUrls }));
  } finally { await mobile.close(); }
} finally { await browser.close(); }
