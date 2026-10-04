// Synthetic, read-only browser proof for the globe rail chooser.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";

const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4331";
assert.equal(new URL(base).hostname, "127.0.0.1");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const jobs = Array.from({ length: 14 }, (_, n) => ({
  id: id(n), title: `Fixture role ${n === 12 ? 11 : n}`, company: "Fixture", source: "fixture",
  last_seen_at: "2026-09-22T00:00:00Z", experience: null, description_available: false,
  seniority_origin: "unknown", extraction_state: "not-extracted",
  location: n === 13 ? "Berlin, Germany" : "Rehovot, Israel", remote: false,
  seniority: null, stack: [], salary: null, url: "https://example.test", apply_url: null,
  posted_at: null, first_seen_at: "2026-09-22T00:00:00Z", status: "new",
  status_reason: null, score: 80, fit_line: null, recommendation: null,
}));
const points = jobs.map((job, n) => ({ posting_id: job.id, lng: n === 13 ? 13.405 : 34.8113,
  lat: n === 13 ? 52.52 : 31.8928, precision: "city", source: "Synthetic fixture",
  resolved_at: "2026-09-22T00:00:00Z" }));
const payload = { jobs, points, total_count: jobs.length, resolved_count: points.length,
  unresolved_count: 0, attribution: "© OpenStreetMap contributors" };
const spreadCoords = [[34.60, 31.70], [35.10, 32.30], [35.30, 31.60]];
const spreadJobs = jobs.slice(0, 3).map(job => ({ ...job, location: "Tel Aviv-Yafo, Israel" }));
const spreadPayload = { ...payload, jobs: spreadJobs, points: points.slice(0, 3).map((point, index) => ({ ...point, lng: spreadCoords[index][0], lat: spreadCoords[index][1] })), total_count: 3, resolved_count: 3 };
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  try {
    await context.addInitScript(() => {
      localStorage.setItem("job-radar.board-preferences", JSON.stringify({ version: 3, filter: "all",
        view: { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" } }));
      window.EventSource = class { addEventListener() {} close() {} };
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    // The chip header sits above the scrolling list (never inside it), and no card paints inside the header box.
    const headerMetrics = () => page.locator(".globe-rail").evaluate(rail => {
      const header = rail.querySelector(".globe-rail-header"), railBox = rail.getBoundingClientRect(), headerBox = header.getBoundingClientRect();
      const scroller = [rail, ...rail.querySelectorAll("*")].find(el => /auto|scroll/.test(getComputedStyle(el).overflowY) && el.scrollHeight > el.clientHeight + 1);
      let cardPixels = 0;
      for (let x = headerBox.left + 2; x < headerBox.right - 2; x += 6) for (let y = Math.max(0, headerBox.top); y < headerBox.bottom; y += 2) if (document.elementFromPoint(x, y)?.closest("[data-globe-card]")) cardPixels++;
      return { gap: headerBox.top - railBox.top, headerTop: headerBox.top, coversTop: header.contains(document.elementFromPoint(headerBox.left + headerBox.width / 2, railBox.top + 1)),
        headerScrolls: Boolean(scroller?.contains(header)), cardPixels };
    });
    const assertPinnedHeader = async () => {
      const metrics = await headerMetrics();
      assert.ok(Math.abs(metrics.gap) <= .5 && metrics.coversTop, `sticky chip covers rail top: ${JSON.stringify(metrics)}`);
      assert.ok(!metrics.headerScrolls && metrics.cardPixels === 0, `chip stays outside the scrolling list: ${JSON.stringify(metrics)}`);
    };
    const scrollRail = top => page.locator(".globe-rail").evaluate((rail, next) => {
      [rail, ...rail.querySelectorAll("*")].find(el => /auto|scroll/.test(getComputedStyle(el).overflowY) && el.scrollHeight > el.clientHeight + 1).scrollTop = next;
    }, top);
    let spread = false;
    await page.route("**/*", route => {
      const request = route.request(), url = new URL(request.url());
      if (url.hostname !== "127.0.0.1") return url.hostname.endsWith(".cartocdn.com") ? route.continue() : route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (request.method() !== "GET") return route.fulfill({ status: 405, json: { error: "Read-only fixture" } });
      if (url.pathname === "/api/jobs/globe") return route.fulfill({ json: spread ? spreadPayload : payload });
      if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs: spread ? spreadJobs : jobs } });
      return route.fulfill({ status: 404, json: { error: "Fixture only" } });
    });
    await page.goto(base);
    await page.getByRole("button", { name: "Globe", exact: true }).click();
    const bubble = page.locator(".globe-cluster");
    await bubble.waitFor({ timeout: 30000 });
    assert.equal(await bubble.count(), 1);
    assert.match(await bubble.getAttribute("aria-label"), /12 roles near Rehovot/);
    assert.equal(await page.locator("#globe-posting-choices").count(), 0);
    await page.waitForTimeout(850); // PR4's first-open globe arrival must finish before pointer targeting.
    const zoom = Number(await page.locator("[data-projection]").getAttribute("data-zoom"));
    await bubble.click();
    await page.getByRole("button", { name: "Clear bubble filter" }).waitFor({ timeout: 10000 });
    assert.match(await page.getByRole("button", { name: "Clear bubble filter" }).innerText(), /Rehovot · 12 roles/);
    assert.equal(await page.locator('[data-globe-section="visible"] [data-posting-id]').count(), 12);
    assert.equal(await page.locator('[data-globe-section="outside"]').count(), 0);
    assert.ok(Number(await page.locator("[data-projection]").getAttribute("data-zoom")) >= zoom);
    assert.equal(await page.locator('[aria-label="Job search"]').getByText(/posting/i).count(), 0);
    await assertPinnedHeader();
    const firstCard = await page.locator('[data-globe-card]').first().boundingBox();
    const chipHeader = await page.locator(".globe-rail-header").boundingBox();
    assert.ok(firstCard.y >= chipHeader.y + chipHeader.height, "first card is clear of the chip at list top");
    await scrollRail(75);
    await assertPinnedHeader();
    await page.keyboard.press("Escape");
    await page.getByRole("heading", { name: "On screen", exact: true }).waitFor();
    await assertPinnedHeader();
    await page.waitForTimeout(200);
    await bubble.click();
    await page.getByRole("button", { name: "Clear bubble filter" }).waitFor();
    await assertPinnedHeader();
    await scrollRail(0);
    await assertPinnedHeader();
    const canvas = await page.locator(".maplibregl-canvas").boundingBox();
    await page.mouse.move(canvas.x + canvas.width * .75, canvas.y + canvas.height * .4);
    await page.mouse.down();
    await page.mouse.move(canvas.x + canvas.width * .65, canvas.y + canvas.height * .4, { steps: 8 });
    await page.mouse.up();
    await page.getByRole("heading", { name: "On screen", exact: true }).waitFor();
    await bubble.click();
    await page.getByRole("button", { name: "Clear bubble filter" }).click();
    await page.getByRole("heading", { name: "On screen", exact: true }).waitFor();
    await assertPinnedHeader();
    await page.getByPlaceholder("Search title, company, or stack").fill("Fixture role 11");
    await page.locator('[data-globe-section="visible"] [data-posting-id]').first().waitFor({ timeout: 10000 });
    await page.waitForFunction(() => document.querySelectorAll('[data-globe-section="visible"] [data-posting-id]').length === 1);
    await page.locator(".globe-cluster").waitFor({ state: "detached", timeout: 10000 });
    assert.equal(await page.locator(".globe-cluster").count(), 0, "two listings for one role make a dot");
    await page.getByPlaceholder("Search title, company, or stack").fill("");
    spread = true;
    await page.reload();
    await page.getByRole("button", { name: "Globe", exact: true }).click();
    const spreadBubble = page.locator(".globe-cluster").first();
    await spreadBubble.waitFor({ timeout: 30000 });
    await page.waitForTimeout(850);
    await spreadBubble.click();
    await page.getByRole("button", { name: "Clear bubble filter" }).waitFor();
    await page.waitForFunction(() => document.querySelectorAll(".globe-cluster").length === 0);
    const camera = await page.locator("[data-projection]").evaluate(el => ({ center: el.dataset.center.split(",").map(Number), zoom: Number(el.dataset.zoom), rect: el.getBoundingClientRect().toJSON() }));
    const scale = 512 * 2 ** camera.zoom / 360;
    const x = camera.rect.x + camera.rect.width / 2 + (spreadCoords[0][0] - camera.center[0]) * scale;
    const y = camera.rect.y + camera.rect.height / 2 - (spreadCoords[0][1] - camera.center[1]) * scale / Math.cos(camera.center[1] * Math.PI / 180);
    for (const [dx, dy] of [[0,0],[3,0],[-3,0],[0,3],[0,-3]]) {
      await page.mouse.click(x + dx, y + dy);
      if (await page.getByRole("dialog").count()) break;
    }
    await page.getByRole("dialog").waitFor({ timeout: 5000 });
    assert.equal(await page.locator("#globe-visible-heading button").count(), 1, "dot click keeps its bubble chip behind the detail dialog");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Clear bubble filter" }).waitFor({ timeout: 5000 });
    await page.setViewportSize({ width: 390, height: 844 });
    const mobileHeader = await page.locator(".globe-rail-header").boundingBox();
    const mobileCard = await page.locator('[data-globe-card]').first().boundingBox();
    assert.ok(mobileCard.y >= mobileHeader.y + mobileHeader.height, "mobile card stays below the filter header");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, "mobile rail has no horizontal overflow");
    // 390px scrolls the page: the chip header stays pinned at the top and cards slide fully under it.
    await page.evaluate(() => window.scrollTo(0, document.querySelector(".globe-rail").getBoundingClientRect().top + scrollY + 120));
    const pinned = await headerMetrics();
    assert.ok(Math.abs(pinned.headerTop) <= .5 && pinned.cardPixels === 0, `mobile chip stays pinned over scrolled cards: ${JSON.stringify(pinned)}`);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.locator('[data-globe-card]').first().locator("button").first().click();
    assert.equal(await page.locator('[data-globe-card]').first().getAttribute("data-globe-selected"), "true", "mobile card click still selects its row");
    // The first card's keyboard ring paints above its top edge instead of hiding under the opaque sticky header.
    // Escape clears the bubble chip first, then the selection.
    for (let presses = 0; presses < 3 && await page.locator('[data-globe-selected="true"]').count(); presses++) { await page.keyboard.press("Escape"); await page.waitForTimeout(150); }
    assert.equal(await page.locator('[data-globe-selected="true"]').count(), 0, "Escape clears the mobile selection");
    await page.evaluate(() => { window.scrollTo(0, 0); document.activeElement?.blur(); });
    await page.mouse.move(2, 2);
    const firstArticle = page.locator("[data-globe-card] > article").first();
    const topRingPixel = async () => { await page.waitForTimeout(300); const box = await firstArticle.boundingBox(); return page.screenshot({ clip: { x: box.x + box.width / 2, y: box.y - 1, width: 1, height: 1 } }); };
    const restTop = await topRingPixel();
    await firstArticle.locator("button").first().focus(); await page.keyboard.press("Shift+Tab"); await page.keyboard.press("Tab");
    assert.equal(await firstArticle.evaluate(article => !!article.querySelector(":focus-visible")), true, "first mobile card has keyboard focus");
    assert.notDeepEqual(await topRingPixel(), restTop, "mobile first-card keyboard ring paints above its top edge");
    assert.deepEqual(errors, []);
    console.log("chooser removed; 12-role stack filters rail; Escape, drag, and chip clear; duplicate listings make one dot");
  } finally { await context.close(); }
} finally { await browser.close(); }
