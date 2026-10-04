// Synthetic, read-only browser proof that job cards give keyboard focus the same visible state as hover.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";

const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4362";
assert.equal(new URL(base).hostname, "127.0.0.1");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const places = [["Rehovot, Israel", 34.8113, 31.8928], ["Berlin, Germany", 13.405, 52.52], ["Moscow, Russia", 37.6173, 55.7558], ["New York, United States", -74.006, 40.7128]];
const jobs = places.map(([location], n) => ({ id: id(n), title: `Fixture role ${n}`, company: `Fixture ${n}`, source: "fixture",
  last_seen_at: "2026-09-22T00:00:00Z", experience: null, description_available: false, seniority_origin: "unknown",
  extraction_state: "not-extracted", location, remote: false, seniority: null, stack: ["React"], salary: null, url: "https://example.test",
  apply_url: null, posted_at: null, first_seen_at: "2026-09-22T00:00:00Z", status: "new", status_reason: null, score: 80, fit_line: null, recommendation: null }));
const payload = { jobs, points: places.map(([, lng, lat], n) => ({ posting_id: id(n), lng, lat, precision: "city", source: "Synthetic fixture", resolved_at: "2026-09-22T00:00:00Z" })),
  total_count: jobs.length, resolved_count: jobs.length, unresolved_count: 0, attribution: "© OpenStreetMap contributors" };
const CARD = id(1);
const card = page => page.locator(`article[data-posting-id="${CARD}"]`);
const look = page => card(page).evaluate(async article => {
  await Promise.all(article.getAnimations().map(animation => animation.finished.catch(() => {})));
  const style = getComputedStyle(article), shadows = style.boxShadow.split(/,(?![^(]*\))/).map(part => part.trim());
  return { border: style.borderColor, ring: shadows.some(part => / 0px 0px 0px 2px$/.test(part) && !part.startsWith("rgba(0, 0, 0, 0)")),
    lift: shadows.filter(part => !/ 0px 0px 0px /.test(part)).join(", "), duration: style.transitionDuration, properties: style.transitionProperty,
    hovered: article.closest("[data-globe-card]")?.hasAttribute("data-hovered") ?? false,
    globeHover: document.querySelector("[data-hover-id]")?.dataset.hoverId ?? null };
});
const settle = page => page.waitForTimeout(250);
// One pixel just outside the card's left edge: the focus ring must actually paint there, not only compute.
const edgePixel = async page => { const box = await card(page).boundingBox(); return page.screenshot({ clip: { x: box.x - 1, y: box.y + box.height / 2, width: 1, height: 1 } }); };
const rest = async page => { await page.mouse.move(2, 2); await page.evaluate(() => document.activeElement?.blur()); await settle(page); };
const keyboardFocus = async page => { await card(page).locator("button").first().focus(); await page.keyboard.press("Shift+Tab"); await page.keyboard.press("Tab"); await settle(page); };

const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
try {
  for (const [mode, reducedMotion] of [["board", "no-preference"], ["globe", "no-preference"], ["globe", "reduce"]]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion });
    try {
      await context.addInitScript(() => {
        localStorage.setItem("job-radar.board-preferences", JSON.stringify({ version: 3, filter: "all",
          view: { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" } }));
        localStorage.setItem("job-globe-dragged", "1");
        window.EventSource = class { addEventListener() {} close() {} };
      });
      const page = await context.newPage(), errors = [], label = `${mode}/${reducedMotion}`;
      page.on("pageerror", error => errors.push(error.message));
      await page.route("**/*", route => {
        const request = route.request(), url = new URL(request.url());
        if (url.hostname !== "127.0.0.1") return url.hostname.endsWith(".cartocdn.com") ? route.continue() : route.abort();
        if (!url.pathname.startsWith("/api/")) return route.continue();
        if (request.method() !== "GET") return route.fulfill({ status: 405, json: { error: "Read-only fixture" } });
        if (url.pathname === "/api/jobs/globe") return route.fulfill({ json: payload });
        if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs } });
        return route.fulfill({ status: 404, json: { error: "Fixture only" } });
      });
      await page.goto(base);
      if (mode === "globe") { await page.getByRole("button", { name: "Globe", exact: true }).click(); await page.locator("[data-globe-card]").nth(3).waitFor(); await page.waitForTimeout(800); }
      else await page.locator("[data-posting-id]").nth(3).waitFor();

      await rest(page);
      const atRest = await look(page), restEdge = await edgePixel(page);
      await card(page).hover({ position: { x: 40, y: 40 } }); await settle(page);
      const hovered = await look(page);
      await rest(page);
      await keyboardFocus(page);
      const focused = await look(page), focusEdge = await edgePixel(page);

      assert.notEqual(hovered.lift, atRest.lift, `${label}: hover lifts the card: ${JSON.stringify({ atRest, hovered })}`);
      assert.equal(focused.border, hovered.border, `${label}: keyboard focus shows the hover border: ${JSON.stringify({ hovered, focused })}`);
      assert.equal(focused.lift, hovered.lift, `${label}: keyboard focus shows the hover lift: ${JSON.stringify({ hovered, focused })}`);
      assert.ok(focused.ring && !hovered.ring && !atRest.ring, `${label}: only keyboard focus adds the focus ring: ${JSON.stringify({ atRest, hovered, focused })}`);
      assert.notDeepEqual(focusEdge, restEdge, `${label}: the focus ring paints outside the card edge, not clipped`);
      assert.match(atRest.properties, /box-shadow/, `${label}: the lift transitions with the border`);
      if (reducedMotion === "reduce") assert.ok(atRest.duration.split(",").every(value => parseFloat(value) === 0), `${label}: reduced motion snaps: ${atRest.duration}`);
      else assert.ok(parseFloat(atRest.duration) > 0, `${label}: card state changes ease in`);

      if (mode === "globe") {
        const rail = await page.locator(".globe-rail").evaluate(element => ({ scroll: element.scrollWidth, client: element.clientWidth }));
        assert.ok(rail.scroll <= rail.client, `${label}: card paint room adds no sideways rail scroll: ${JSON.stringify(rail)}`);
        assert.ok(hovered.hovered && hovered.globeHover === CARD, `${label}: pointer hover syncs to the globe: ${JSON.stringify(hovered)}`);
        assert.ok(focused.hovered && focused.globeHover === CARD, `${label}: keyboard focus syncs to the globe like hover: ${JSON.stringify(focused)}`);
        await rest(page);
        const blurred = await look(page);
        assert.ok(!blurred.hovered && blurred.globeHover === null, `${label}: blur clears the globe sync: ${JSON.stringify(blurred)}`);
      }

      // Focus moved by script after a mouse action (the drawer handing focus back to its opener) is not keyboard focus.
      await rest(page);
      await page.locator('[aria-label="Job filters"] button[aria-pressed="true"]').click();
      await card(page).locator("button").first().evaluate(button => button.focus());
      await settle(page);
      const scripted = await look(page);
      assert.ok(!scripted.ring, `${label}: script focus after a mouse action shows no keyboard ring: ${JSON.stringify(scripted)}`);
      assert.deepEqual(errors, []);
      console.log(`${label}: hover and keyboard focus match; ring only for keyboard`);
    } finally { await context.close(); }
  }
} finally { await browser.close(); }
