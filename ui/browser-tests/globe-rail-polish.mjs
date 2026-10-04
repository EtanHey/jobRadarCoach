// Synthetic, read-only browser proof for globe R3 PR2b: D13 rail states, D14 hover sync, R3-13 flights, N4 slow data.
// Motion is ON unless a phase says otherwise. API writes are refused; only loopback and CARTO tiles are reachable.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";

const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4360";
assert.equal(new URL(base).hostname, "127.0.0.1");
const only = process.env.GLOBE_QA_ONLY;
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const places = [...Array(12).fill(["Rehovot, Israel", 34.8113, 31.8928]), ["Berlin, Germany", 13.405, 52.52], ["Moscow, Russia", 37.6173, 55.7558], ["New York, United States", -74.006, 40.7128]];
const jobs = places.map(([location], n) => ({ id: id(n), title: `Fixture role ${n}`, company: "Fixture", source: "fixture",
  last_seen_at: "2026-09-22T00:00:00Z", experience: null, description_available: false, seniority_origin: "unknown",
  extraction_state: "not-extracted", location, remote: false, seniority: null, stack: [], salary: null, url: "https://example.test",
  apply_url: null, posted_at: null, first_seen_at: "2026-09-22T00:00:00Z", status: "new", status_reason: null, score: 80, fit_line: null, recommendation: null }));
const payload = { jobs, points: places.map(([, lng, lat], n) => ({ posting_id: id(n), lng, lat, precision: "city", source: "Synthetic fixture", resolved_at: "2026-09-22T00:00:00Z" })),
  total_count: jobs.length, resolved_count: jobs.length, unresolved_count: 0, attribution: "© OpenStreetMap contributors" };
const BERLIN = id(12);

const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const failures = [], passed = [];
async function phase(name, options, body) {
  if (only && only !== name) return;
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "no-preference", ...options.context });
  try {
    await context.addInitScript(location => {
      localStorage.setItem("job-radar.board-preferences", JSON.stringify({ version: 3, filter: "all",
        view: { search: "", source: "", location, seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" } }));
      localStorage.setItem("job-globe-dragged", "1");
      class FixtureEvents extends EventTarget { constructor() { super(); setTimeout(() => this.dispatchEvent(new Event("ready")), 20); } close() {} }
      window.EventSource = FixtureEvents;
      window.__commits = 0;
      window.__REACT_DEVTOOLS_GLOBAL_HOOK__ = { renderers: new Map(), supportsFiber: true, isDisabled: false, inject() { return 1; }, checkDCE() {},
        onScheduleFiberRoot() {}, onCommitFiberRoot() { window.__commits++; }, onCommitFiberUnmount() {}, onPostCommitFiberRoot() {} };
    }, options.location ?? "");
    const page = await context.newPage(), errors = [];
    page.on("pageerror", error => errors.push(error.message));
    let release = () => {};
    const held = options.holdGlobeMs === undefined ? null : new Promise(resolve => { release = resolve; setTimeout(resolve, options.holdGlobeMs); });
    await page.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.hostname !== "127.0.0.1") return url.hostname.endsWith(".cartocdn.com") ? route.continue() : route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (request.method() !== "GET") return route.fulfill({ status: 405, json: { error: "Read-only fixture" } });
      if (url.pathname === "/api/jobs/globe") { if (held) await held; return route.fulfill({ json: payload }).catch(() => {}); }
      if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs } });
      return route.fulfill({ status: 404, json: { error: "Fixture only" } });
    });
    await page.goto(base);
    await page.getByRole("button", { name: "Globe", exact: true }).click();
    await body(page, { release });
    assert.deepEqual(errors, []);
    passed.push(name);
  } catch (error) { failures.push(`${name}: ${error.message.split("\n")[0]} @${error.stack.match(/globe-rail-polish\.mjs:(\d+)/)?.[1]}`); }
  finally { await context.close(); }
}
const map = page => page.locator('[data-projection="globe"]');
const camera = page => map(page).evaluate(el => ({ center: el.dataset.center.split(",").map(Number), zoom: Number(el.dataset.zoom), starts: Number(el.dataset.cameraStarts || 0), min: Number(el.dataset.flightMinZoom) }));
// Resolves with the movestart→moveend time of the next camera move, read from the dev-only camera datasets.
const timeNextMove = page => map(page).evaluate(el => new Promise(resolve => {
  let start = null;
  const observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.attributeName === "data-camera-starts" && start === null) start = performance.now();
      if (record.attributeName === "data-center" && start !== null) { observer.disconnect(); resolve(performance.now() - start); }
    }
  });
  observer.observe(el, { attributes: true, attributeFilter: ["data-camera-starts", "data-center"] });
}));
const settle = page => page.waitForFunction(() => { const el = document.querySelector('[data-projection="globe"]'); return el && el.dataset.center; }, null, { timeout: 30000 });
async function chooseLocation(page, name) {
  await page.getByRole("combobox", { name: "Location", exact: true }).filter({ visible: true }).click();
  await page.getByRole("option", { name, exact: true }).click();
}

// Saved Other gates the map on globe data; data landing at 17 s must keep a visible loading rail, then recover.
await phase("n4-slow-other", { location: "other", holdGlobeMs: 17000 }, async page => {
  await page.getByText("Counting roles on screen…", { exact: true }).waitFor({ timeout: 5000 });
  assert.equal(await page.locator(".globe-loading-card").count(), 4, "four skeleton cards while globe data loads");
  await page.getByText("Loading map…", { exact: true }).waitFor();
  await page.waitForTimeout(14000);
  assert.equal(await page.locator(".globe-loading-card").count(), 4, "loading stays visible while data is slow");
  await page.locator('[data-globe-section="visible"] [data-posting-id]').first().waitFor({ timeout: 25000 });
  await page.waitForTimeout(4000);
  assert.equal(await page.getByText("The globe could not load", { exact: false }).count(), 0, "slow saved Other data must not trip the map timeout");
  assert.equal(await page.getByRole("button", { name: "Globe", exact: true }).getAttribute("aria-pressed"), "true");
});

await phase("layout-empty", {}, async page => {
  await settle(page);
  await page.locator('[data-globe-section="visible"] [data-posting-id]').first().waitFor({ timeout: 30000 });
  const live = page.locator("header").getByText("Live", { exact: true });
  await live.waitFor({ timeout: 5000 });
  assert.equal(await page.locator("header [title='Live updates connected']").count(), 1, "Live dot carries the full status as a tooltip");
  assert.equal(await page.locator("main").getByText("Live updates connected").count(), 0, "footer status moved into the header");
  const layout = await page.evaluate(() => {
    const rail = document.querySelector(".globe-rail"), slot = document.querySelector(".globe-slot");
    const scrollers = [...document.querySelectorAll("body *")].filter(el => /auto|scroll/.test(getComputedStyle(el).overflowY) && el.scrollHeight > el.clientHeight + 1);
    return { page: document.scrollingElement.scrollHeight - document.scrollingElement.clientHeight, railBottom: rail.getBoundingClientRect().bottom,
      slotBottom: slot.getBoundingClientRect().bottom, target: innerHeight - 16, scrollers: scrollers.map(el => el.className) };
  });
  assert.equal(layout.page, 0, `page must not scroll: ${JSON.stringify(layout)}`);
  assert.ok(Math.abs(layout.railBottom - layout.target) <= 2 && Math.abs(layout.slotBottom - layout.target) <= 2, JSON.stringify(layout));
  assert.deepEqual(layout.scrollers.length, 1, JSON.stringify(layout.scrollers));
  assert.match(layout.scrollers[0], /globe-rail-list/, "only the card list scrolls, so its scrollbar sits beside the list");
  // Whatever scrolls inside the rail, the header must stay outside it and no card may paint inside the header box.
  const railScroller = () => page.locator(".globe-rail").evaluateHandle(rail => [rail, ...rail.querySelectorAll("*")]
    .find(el => /auto|scroll/.test(getComputedStyle(el).overflowY) && el.scrollHeight > el.clientHeight + 1));
  const headerAtTop = async () => page.evaluate(scroller => {
    const rail = document.querySelector(".globe-rail"), header = rail.querySelector(".globe-rail-header");
    const railBox = rail.getBoundingClientRect(), headerBox = header.getBoundingClientRect(), listBox = scroller.getBoundingClientRect();
    const topPixel = document.elementFromPoint(headerBox.left + headerBox.width / 2, railBox.top + 1);
    let cardPixels = 0;
    for (let x = headerBox.left + 2; x < headerBox.right - 2; x += 6) for (let y = headerBox.top; y < headerBox.bottom; y += 2) if (document.elementFromPoint(x, y)?.closest("[data-globe-card]")) cardPixels++;
    return { gap: headerBox.top - railBox.top, coversTop: header.contains(topPixel), headerScrolls: scroller.contains(header), listBelowHeader: listBox.top - headerBox.bottom, cardPixels };
  }, await railScroller());
  const scrollRail = async top => (await railScroller()).evaluate((scroller, top) => { scroller.scrollTop = top; }, top);
  for (const scrollTop of [0, 75, 400]) {
    await scrollRail(scrollTop);
    const top = await headerAtTop();
    assert.ok(Math.abs(top.gap) <= .5 && top.coversTop, `rail header covers top edge at ${scrollTop}: ${JSON.stringify(top)}`);
    assert.ok(!top.headerScrolls && top.listBelowHeader >= -.5, `header sits outside the scrolling list at ${scrollTop}: ${JSON.stringify(top)}`);
    assert.equal(top.cardPixels, 0, `no card paints inside the header at ${scrollTop}: ${JSON.stringify(top)}`);
  }
  // Focus scrolling brings a card into the list's own viewport, never under the header.
  await page.locator('[data-globe-card] > article > button').first().focus();
  const focused = await page.evaluate(() => {
    const header = document.querySelector(".globe-rail-header").getBoundingClientRect(), card = document.activeElement.closest("article").getBoundingClientRect();
    return { cardTop: card.top, headerBottom: header.bottom };
  });
  assert.ok(focused.cardTop >= focused.headerBottom - .5, `focused card clears the header: ${JSON.stringify(focused)}`);
  await page.evaluate(() => document.activeElement?.blur());
  // Clicking a card cut off at the list's top scrolls it fully into the list, clear of the header (mouse at absolute coordinates, so Playwright cannot pre-scroll).
  const cutCard = await page.locator('[data-globe-card]').nth(2).elementHandle();
  const clickAt = await (await railScroller()).evaluate((list, card) => {
    list.scrollTop += card.getBoundingClientRect().top - list.getBoundingClientRect().top + 60;
    const box = card.getBoundingClientRect(), listBox = list.getBoundingClientRect();
    return { x: box.left + 30, y: Math.max(box.top, listBox.top) + 30 };
  }, cutCard);
  await page.mouse.click(clickAt.x, clickAt.y);
  await page.waitForFunction(card => card.closest("[data-globe-card]").dataset.globeSelected === "true", cutCard);
  await page.waitForTimeout(700);
  const revealed = await cutCard.evaluate(card => {
    const box = card.getBoundingClientRect(), header = document.querySelector(".globe-rail-header").getBoundingClientRect(), list = document.querySelector(".globe-rail-list")?.getBoundingClientRect();
    return { cardTop: box.top, headerBottom: header.bottom, listTop: list?.top };
  });
  assert.ok(revealed.cardTop >= revealed.headerBottom - .5 && revealed.cardTop >= revealed.listTop - .5, `selected card scrolls fully into the list: ${JSON.stringify(revealed)}`);
  await page.keyboard.press("Escape");
  await scrollRail(400);
  const canvas = await page.locator(".maplibregl-canvas").boundingBox();
  // One drag turns the globe to the empty Pacific; the fixture has no roles there.
  await page.mouse.move(canvas.x + canvas.width * .85, canvas.y + canvas.height * .5);
  await page.mouse.down();
  await page.mouse.move(canvas.x + canvas.width * .25, canvas.y + canvas.height * .5, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(1500);
  await page.getByText("Nothing on screen here.", { exact: true }).waitFor({ timeout: 10000 }).catch(async error => { throw new Error(`${error.message.split("\n")[0]} camera=${JSON.stringify(await camera(page))}`); });
  await page.getByText("Zoom out or drag to another region.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Show whole world", exact: true }).click();
  await page.locator('[data-globe-section="visible"] [data-posting-id]').first().waitFor({ timeout: 10000 });
  await page.waitForFunction(() => { const [lng, lat] = document.querySelector('[data-projection="globe"]').dataset.center.split(",").map(Number); return Math.abs(lng - 34.8113) < .01 && Math.abs(lat - 31.8928) < .01; }, null, { timeout: 5000 });
});

// Show whole world must reveal the roles the current Location allows, not just the Rehovot home camera.
await phase("whole-world-filtered", { location: "united-states" }, async page => {
  await settle(page);
  await page.locator('[data-globe-section="visible"] [data-posting-id]').first().waitFor({ timeout: 30000 });
  for (let n = 0; n < 3; n++) { await page.getByRole("button", { name: "Zoom in", exact: true }).click(); await page.waitForTimeout(500); }
  await page.getByText("Nothing on screen here.", { exact: true }).waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: "Show whole world", exact: true }).click();
  await page.locator(`[data-globe-section="visible"] [data-posting-id="${id(14)}"]`).waitFor({ timeout: 5000 })
    .catch(async error => { throw new Error(`${error.message.split("\n")[0]} camera=${JSON.stringify(await camera(page))}`); });
  assert.equal(await page.getByText("Nothing on screen here.", { exact: true }).count(), 0);
});

await phase("hover-sync", {}, async page => {
  await settle(page);
  await page.locator(".globe-cluster").first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(1200);
  // Etan's cluster hover bug: the hover grow must not move the bubble out from under a still pointer.
  const bubbleBox = await page.locator(".globe-cluster").first().boundingBox();
  await page.mouse.move(bubbleBox.x + bubbleBox.width / 2, bubbleBox.y + bubbleBox.height / 2);
  await page.evaluate(() => { window.__commits = 0; });
  const hoverStates = [];
  for (let n = 0; n < 12; n++) {
    await page.mouse.move(bubbleBox.x + bubbleBox.width / 2 + (n % 4) - 2, bubbleBox.y + bubbleBox.height / 2 + (n % 3) - 1);
    hoverStates.push(await page.locator(".globe-cluster").first().evaluate(node => `${node.matches(":hover")}@${node.getBoundingClientRect().x.toFixed(1)}`));
  }
  assert.equal(new Set(hoverStates).size, 1, `hovered bubble must hold still under a moving pointer: ${hoverStates}`);
  assert.ok(await page.evaluate(() => window.__commits) <= 1, `hovered bubble must not flicker React state: ${await page.evaluate(() => window.__commits)}`);
  const before = await camera(page);
  const rail = page.locator(".globe-rail-list");
  const railTop = await rail.evaluate(el => el.scrollTop);
  const berlinCard = page.locator(`[data-globe-card="${BERLIN}"]`);
  await berlinCard.hover();
  await page.waitForFunction(berlin => document.querySelector('[data-projection="globe"]').dataset.hoverId === berlin, BERLIN, { timeout: 2000 });
  const box = await berlinCard.boundingBox();
  await page.evaluate(() => { window.__commits = 0; });
  for (let n = 0; n < 20; n++) await page.mouse.move(box.x + 20 + n * 4, box.y + 20 + (n % 3));
  assert.ok(await page.evaluate(() => window.__commits) <= 1, `card hover commits: ${await page.evaluate(() => window.__commits)}`);
  await page.locator(`[data-globe-card="${id(0)}"]`).hover();
  await page.waitForFunction(() => document.querySelector(".globe-cluster")?.classList.contains("globe-cluster-hovered"), null, { timeout: 2000 });
  await page.waitForTimeout(700);
  const after = await camera(page);
  assert.equal(after.starts, before.starts, "hovering cards never moves the map");
  assert.equal(await rail.evaluate(el => el.scrollTop), railTop, "hovering cards never scrolls the rail");
  await page.mouse.move(10, 10);
  await page.waitForFunction(() => !document.querySelector('[data-projection="globe"]').dataset.hoverId && !document.querySelector(".globe-cluster-hovered"), null, { timeout: 2000 });
  // Rail click is intent: the map centres the Berlin dot, then pointer hover over that dot highlights its card without scrolling.
  await berlinCard.locator("button").first().click();
  await page.waitForFunction(berlin => document.querySelector('[data-projection="globe"]').dataset.selectedId === berlin, BERLIN, { timeout: 2000 });
  await page.waitForTimeout(1500);
  const mapBox = await map(page).boundingBox();
  await rail.evaluate(el => { el.scrollTop = 0; });
  const cx = mapBox.x + mapBox.width / 2, cy = mapBox.y + mapBox.height / 2;
  await page.mouse.move(cx - 40, cy);
  await page.mouse.move(cx, cy, { steps: 4 });
  await page.waitForFunction(berlin => document.querySelector(`[data-globe-card="${berlin}"]`)?.hasAttribute("data-hovered"), BERLIN, { timeout: 2000 });
  await page.evaluate(() => { window.__commits = 0; });
  for (let n = 0; n < 20; n++) await page.mouse.move(cx + (n % 5) - 2, cy + (n % 3) - 1);
  const dotCommits = await page.evaluate(() => window.__commits);
  assert.ok(dotCommits <= 1, `dot hover must not commit per mousemove: ${dotCommits}`);
  assert.equal(await rail.evaluate(el => el.scrollTop), 0, "dot hover never scrolls the rail");
  await page.mouse.move(cx - 60, cy + 60);
  await page.waitForFunction(berlin => !document.querySelector(`[data-globe-card="${berlin}"]`)?.hasAttribute("data-hovered"), BERLIN, { timeout: 2000 });
});

await phase("flight-motion", {}, async page => {
  await settle(page);
  await page.waitForTimeout(1200);
  await chooseLocation(page, "Israel");
  await page.waitForFunction(() => Number(document.querySelector('[data-projection="globe"]').dataset.zoom) >= 5, null, { timeout: 5000 });
  await page.waitForTimeout(300);
  const israel = await camera(page);
  const farMove = timeNextMove(page);
  await chooseLocation(page, "United States");
  const farMs = await farMove;
  const us = await camera(page);
  assert.ok(us.center[0] < -90, JSON.stringify(us));
  assert.ok(us.min < Math.min(israel.zoom, us.zoom) - .5, `far move must zoom out first: ${JSON.stringify({ israel, us })}`);
  assert.ok(farMs >= 1200 && farMs <= 2600, `far move duration ${farMs}`);
  const back = timeNextMove(page);
  await chooseLocation(page, "All locations");
  await back;
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await page.waitForTimeout(800);
  const near = await camera(page);
  const gentle = timeNextMove(page);
  await page.getByRole("button", { name: "Reset view", exact: true }).filter({ visible: true }).click();
  const gentleMs = await gentle;
  const home = await camera(page);
  assert.ok(home.min >= home.zoom - .05, `near reset must not dip: ${JSON.stringify({ near, home })}`);
  assert.ok(gentleMs <= 1000, `near reset duration ${gentleMs}`);
  // #361 hidden-camera queue: a Location picked while the globe is hidden is flown to on re-show.
  await page.getByRole("button", { name: "Globe", exact: true }).click();
  await chooseLocation(page, "United States");
  await page.getByRole("button", { name: "Globe", exact: true }).click();
  await page.waitForFunction(() => Number(document.querySelector('[data-projection="globe"]').dataset.center?.split(",")[0]) < -90, null, { timeout: 8000 });
});

await phase("flight-reduced", { context: { reducedMotion: "reduce" } }, async page => {
  await settle(page);
  const start = await camera(page);
  const move = timeNextMove(page);
  await chooseLocation(page, "United States");
  const ms = await move;
  const us = await camera(page);
  assert.ok(ms <= 100, `reduced motion location move must be instant: ${ms}`);
  assert.ok(us.min >= Math.min(start.zoom, us.zoom) - 1e-6, JSON.stringify({ start, us }));
});

await browser.close();
console.log(JSON.stringify({ passed, failures }, null, 1));
if (failures.length) process.exit(1);
