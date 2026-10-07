// Synthetic loopback proof that grid card, drawer and globe rail share one CompanyLogo: catalog, Logo.dev
// (routed to a synthetic image, never the network), 404 → initials, placeholder → initials, no overflow at 390 px.
// The server must run with NEXT_PUBLIC_LOGO_DEV_KEY=pk_synthetic_fixture. No API call reaches the server: the drawer's
// automatic mark-seen PATCH is answered in-browser so the drawer renders clean; every other write is refused.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";

const base = process.env.LOGO_QA_URL ?? "http://127.0.0.1:4370";
const output = process.env.LOGO_QA_OUTPUT;
assert.equal(new URL(base).hostname, "127.0.0.1");
if (output) await mkdir(output, { recursive: true });

const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const companies = [
  { company: "Wix", expect: { source: "catalog", state: "loaded" } },
  { company: "Acme Robotics", apply_url: "https://careers.acmerobotics.com/jobs/1", expect: { source: "logo-dev", state: "loaded" } },
  { company: "Nowhere Widgets", apply_url: "https://nowherewidgets.test/jobs/1", expect: { source: "logo-dev", state: "load-failed", initials: "NW" } },
  { company: "Confidential", expect: { state: "unmapped", initials: "C" } },
  { company: "Jeen.ai", expect: { source: "logo-dev", state: "loaded" } },
  { company: "TalentHop", expect: { state: "unmapped", initials: "T" } },
  { company: "Doit", apply_url: "https://doit.app/jobs/1", expect: { source: "logo-dev", state: "load-failed", initials: "D" } },
  { company: "DoiT", apply_url: "https://doit.com/jobs/1", expect: { source: "catalog", state: "loaded" } },
];
const places = [["Rehovot, Israel", 34.8113, 31.8928], ["Berlin, Germany", 13.405, 52.52], ["Tel Aviv, Israel", 34.7818, 32.0853], ["London, United Kingdom", -0.1276, 51.5072], ["Paris, France", 2.3522, 48.8566], ["Rome, Italy", 12.4964, 41.9028]];
const jobs = companies.map(({ company, apply_url = null }, n) => ({ id: id(n), title: `Fixture engineer ${n}`, company, source: "fixture",
  last_seen_at: "2026-10-04T00:00:00Z", experience: "3+ years", description_available: true, seniority_origin: "title",
  extraction_state: "not-extracted", location: places[n % places.length][0], remote: false, seniority: "Junior", stack: ["React", "TypeScript"], salary: null,
  url: "https://www.linkedin.com/jobs/view/1", apply_url, posted_at: null, first_seen_at: "2026-10-04T00:00:00Z", status: "new", status_reason: null,
  score: 70 + n * 3, fit_line: null, recommendation: null }));
const detail = job => ({ ...job, raw_jd: `Synthetic description for the logo fixture.${job.company === "DoiT" ? " Our employer site is https://doit.app." : ""}`, reasons: [], score_payload: null, brain: null, scored_at: null });
const globe = { jobs, points: jobs.map((_, n) => ({ posting_id: id(n), lng: places[n % places.length][1], lat: places[n % places.length][2], precision: "city", source: "Synthetic fixture", resolved_at: "2026-10-04T00:00:00Z" })),
  total_count: jobs.length, resolved_count: jobs.length, unresolved_count: 0, attribution: "© OpenStreetMap contributors" };
const syntheticLogo = '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"><rect width="128" height="128" fill="#fff"/><circle cx="64" cy="64" r="44" fill="#7c3aed"/><text x="64" y="78" font-family="sans-serif" font-size="40" font-weight="700" fill="#fff" text-anchor="middle">AR</text></svg>';

const browser = await chromium.launch({ headless: true, channel: "chromium-headless-shell", args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const failures = [], passed = [], logoRequests = new Set(), logoRequestCounts = new Map();
// Lookup paths whose requests fail at the network layer (route.abort), to prove a transport error is never cached as a miss.
const abortedLogoPaths = new Set();
// Logo.dev's CDN answers with access-control-allow-origin: * (probed 2026-10-04); the fixture mirrors it so a CORS confirm can read the status.
const cors = { "access-control-allow-origin": "*" };

async function open(viewport, colorScheme, body) {
  const context = await browser.newContext({ viewport, colorScheme, reducedMotion: "reduce" });
  try {
    await context.addInitScript(() => {
      localStorage.setItem("job-radar.board-preferences", JSON.stringify({ version: 3, filter: "all",
        view: { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" } }));
      localStorage.setItem("job-globe-dragged", "1");
      class FixtureEvents extends EventTarget { constructor() { super(); setTimeout(() => this.dispatchEvent(new Event("ready")), 20); } close() { this.closed = true; } }
      window.EventSource = FixtureEvents;
    });
    const page = await context.newPage(), errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => {
      const request = route.request(), url = new URL(request.url());
      if (url.hostname === "img.logo.dev") {
        logoRequests.add(`${url.pathname}?${url.searchParams.get("fallback")}`);
        logoRequestCounts.set(url.pathname, (logoRequestCounts.get(url.pathname) ?? 0) + 1);
        if (abortedLogoPaths.has(url.pathname)) return route.abort("failed");
        return ["/acmerobotics.com", "/jeen.ai"].includes(url.pathname) ? route.fulfill({ contentType: "image/svg+xml", headers: cors, body: syntheticLogo }) : route.fulfill({ status: 404, headers: cors, body: "" });
      }
      if (url.hostname !== "127.0.0.1") return url.hostname.endsWith(".cartocdn.com") ? route.continue() : route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (request.method() === "PATCH" && /^\/api\/jobs\/[^/]+\/status$/.test(url.pathname)) return route.fulfill({ json: { status: "seen", reason: null } });
      if (request.method() !== "GET") return route.fulfill({ status: 405, json: { error: "Read-only fixture" } });
      if (url.pathname === "/api/jobs/globe") return route.fulfill({ json: globe });
      if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs } });
      const job = jobs.find(item => url.pathname === `/api/jobs/${item.id}`);
      return job ? route.fulfill({ json: { job: detail(job) } }) : route.fulfill({ status: 404, json: { error: "Fixture only" } });
    });
    await page.goto(base);
    await page.locator("[data-posting-id]").first().waitFor();
    try { await body(page); } catch (error) { if (output) await page.screenshot({ path: `${output}/FAIL-${viewport.width}-${colorScheme}.png` }); throw error; }
    assert.deepEqual(errors, []);
  } finally { await context.close(); }
}

const settled = (page, scope) => page.waitForFunction(selector => [...document.querySelectorAll(`${selector} [data-company-logo]`)]
  .every(logo => logo.dataset.logoState !== "loading"), scope, { timeout: 15000 });
async function logosIn(page, scope) {
  await settled(page, scope);
  return page.locator(`${scope} [data-company-logo]`).evaluateAll(logos => logos.map(logo => {
    const image = logo.querySelector("img"), box = logo.getBoundingClientRect();
    return { label: logo.getAttribute("aria-label"), source: logo.dataset.logoSource ?? null, state: logo.dataset.logoState, size: logo.dataset.logoSize,
      text: logo.textContent, width: Math.round(box.width), height: Math.round(box.height), image: image ? { src: image.getAttribute("src"), natural: image.naturalWidth, opacity: getComputedStyle(image).opacity } : null,
      frame: [...logo.classList].filter(name => !/^(?:sm:)?size-|^text-|^bg-/.test(name)).sort().join(" ") };
  }));
}
const order = new Map(companies.map(({ company }, n) => [company, n]));
const companyOf = logo => logo.label.replace(/ logo(?: unavailable)?$/, "");
const byCompany = logos => logos.slice().sort((a, b) => order.get(companyOf(a)) - order.get(companyOf(b)));
function checkLogos(logos, where) {
  assert.equal(logos.length, companies.length, `${where}: one logo per card`);
  logos.forEach((logo, n) => {
    const want = companies[n].expect;
    // After the first 404 on a page, later renders of the same company use the remembered miss.
    const states = want.state === "load-failed" ? ["load-failed", "cached-miss"] : [want.state];
    assert.ok(states.includes(logo.state), `${where} ${companies[n].company} state ${logo.state}`);
    if (want.source) assert.equal(logo.source, want.source, `${where} ${companies[n].company} source`);
    if (want.initials) { assert.equal(logo.text, want.initials, `${where} ${companies[n].company} initials`); assert.equal(logo.image, null, `${where}: no broken image left behind`); }
    if (want.state === "loaded") { assert.ok(logo.image.natural > 0, `${where}: loaded image has pixels`); assert.equal(logo.image.opacity, "1"); }
    assert.equal(logo.width, logo.height, `${where}: square box`);
  });
  assert.equal(new Set(logos.map(logo => logo.frame)).size, 1, `${where}: one frame recipe`);
}
const noHorizontalOverflow = page => page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth);
const shot = async (page, name) => { if (output) await page.screenshot({ path: `${output}/${name}.png` }); };

const onlyRun = process.env.LOGO_QA_ONLY;
for (const [vpName, viewport] of [["desktop", { width: 1440, height: 900 }], ["390", { width: 390, height: 844 }]]) {
  for (const scheme of ["light", "dark"]) {
    if (onlyRun && onlyRun !== `${vpName}-${scheme}`) continue;
    const name = `${vpName}-${scheme}`;
    try {
      await open(viewport, scheme, async page => {
        const grid = byCompany(await logosIn(page, "main"));
        checkLogos(grid, `${name} grid`);
        assert.ok(grid.every(logo => logo.size === "md"), `${name}: grid cards use the md tile`);
        assert.ok(await noHorizontalOverflow(page), `${name}: grid has no horizontal overflow`);
        await page.getByText("Logos provided by Logo.dev").waitFor();
        await shot(page, `${name}-card`);

        await page.getByRole("button", { name: "Open Fixture engineer 1 at Acme Robotics" }).click();
        const drawer = page.getByRole("dialog");
        await drawer.getByText("Synthetic description for the logo fixture.").waitFor();
        const [drawerLogo] = await logosIn(page, '[role="dialog"]');
        assert.deepEqual([drawerLogo.source, drawerLogo.state, drawerLogo.size, drawerLogo.frame], ["logo-dev", "loaded", "md", grid[1].frame], `${name}: drawer shares the card logo`);
        assert.equal(drawerLogo.image.src, grid[1].image.src, `${name}: drawer reuses the card's logo URL`);
        assert.ok(await noHorizontalOverflow(page), `${name}: drawer has no horizontal overflow`);
        await shot(page, `${name}-drawer`);
        await page.keyboard.press("Escape");
        await drawer.waitFor({ state: "hidden" });

        await page.getByRole("button", { name: "Open Fixture engineer 6 at Doit", exact: true }).click();
        await drawer.getByText("Synthetic description for the logo fixture.").waitFor();
        const [appLogo] = await logosIn(page, '[role="dialog"]');
        assert.equal(appLogo.text, "D", `${name}: Doit app drawer uses initials`);
        assert.equal(appLogo.image, null, `${name}: Doit app drawer never inherits the cloud logo`);
        await shot(page, `${name}-doit-drawer`);
        await page.keyboard.press("Escape");
        await drawer.waitFor({ state: "hidden" });

        await page.getByRole("button", { name: "Open Fixture engineer 7 at DoiT", exact: true }).click();
        await drawer.getByText("Our employer site is https://doit.app.", { exact: false }).waitFor();
        const [conflictLogo] = await logosIn(page, '[role="dialog"]');
        assert.equal(conflictLogo.state, "unmapped", `${name}: loaded conflicting JD vetoes the catalog`);
        assert.equal(conflictLogo.image, null, `${name}: conflicting drawer has no image`);
        await shot(page, `${name}-conflict-drawer`);
        await page.keyboard.press("Escape");
        await drawer.waitFor({ state: "hidden" });

        await page.getByRole("button", { name: "Globe", exact: true }).click();
        await page.locator('[data-globe-section="visible"]').waitFor({ timeout: 30000 });
        await page.waitForFunction(count => document.querySelectorAll("#globe-rail [data-company-logo]").length === count, companies.length, { timeout: 30000 });
        const rail = byCompany(await logosIn(page, "#globe-rail"));
        checkLogos(rail, `${name} rail`);
        assert.ok(rail.every(logo => logo.size === "sm" && logo.width === 40), `${name}: rail cards use the compact 40 px tile`);
        assert.equal(rail[0].frame, grid[0].frame, `${name}: rail shares the card frame`);
        assert.ok(await noHorizontalOverflow(page), `${name}: globe view has no horizontal overflow`);
        if (vpName === "390") await page.locator("#globe-rail").scrollIntoViewIfNeeded();
        await shot(page, `${name}-rail`);
      });
      passed.push(name);
    } catch (error) { failures.push(`${name}: ${error.message.split("\n")[0]}`); }
  }
}
// A Logo.dev miss is billed like a hit and has no cache headers: after one 404 a reload must not ask again.
try {
  await open({ width: 1440, height: 900 }, "light", async page => {
    await settled(page, "main");
    // The miss is recorded after its 404 is confirmed, so wait for the entry before counting.
    await page.waitForFunction(() => (localStorage.getItem("job-radar.logo-misses.v1") ?? "").includes("nowherewidgets.test"));
    const before = logoRequestCounts.get("/nowherewidgets.test") ?? 0;
    assert.ok(before > 0, "the first visit asked Logo.dev once");
    await page.reload();
    await page.locator("[data-posting-id]").first().waitFor();
    await settled(page, "main");
    const nowhere = page.locator('[data-company-logo][aria-label="Nowhere Widgets logo unavailable"]');
    await nowhere.waitFor();
    assert.equal(await nowhere.getAttribute("data-logo-state"), "cached-miss", "the known miss renders initials at once");
    assert.equal(logoRequestCounts.get("/nowherewidgets.test") ?? 0, before, "no second request for a known miss");
    const stored = await page.evaluate(() => localStorage.getItem("job-radar.logo-misses.v1") ?? "");
    assert.match(stored, /nowherewidgets.test/);
    assert.doesNotMatch(stored, /pk_|token/, "the key never reaches storage");
    assert.equal(await page.locator('[data-company-logo][aria-label="Acme Robotics logo"]').getAttribute("data-logo-state"), "loaded", "hits are unaffected");
  });
  passed.push("miss-cache");
} catch (error) { failures.push(`miss-cache: ${error.message.split("\n")[0]}`); }
// B1: an <img> error cannot tell a provider 404 from a network failure. A transport failure must never be cached.
try {
  abortedLogoPaths.add("/acmerobotics.com");
  await open({ width: 1440, height: 900 }, "light", async page => {
    assert.equal(await page.evaluate(() => navigator.onLine), true, "the browser believes it is online");
    await settled(page, "main");
    const acme = page.locator('[data-company-logo][aria-label^="Acme Robotics logo"]');
    const failedState = await acme.getAttribute("data-logo-state");
    assert.equal(failedState, "load-failed", `the failed load shows initials (got ${failedState})`);
    await page.waitForTimeout(800);
    assert.doesNotMatch(await page.evaluate(() => localStorage.getItem("job-radar.logo-misses.v1") ?? ""), /acmerobotics/, "a network failure is not cached as a miss");
    abortedLogoPaths.delete("/acmerobotics.com");
    await page.reload();
    await page.locator("[data-posting-id]").first().waitFor();
    await settled(page, "main");
    assert.equal(await acme.getAttribute("data-logo-state"), "loaded", "the real logo shows once the network recovers");
  });
  passed.push("abort-not-cached");
} catch (error) { abortedLogoPaths.clear(); failures.push(`abort-not-cached: ${error.message.split("\n")[0]}`); }
try {
  assert.ok(logoRequests.has("/acmerobotics.com?404"), "trusted company domain went to Logo.dev with fallback=404");
  assert.ok(logoRequests.has("/jeen.ai?404"), "mapped company uses domain lookup");
  assert.ok(![...logoRequests].some(request => /name\/Jeen|TalentHop/i.test(request)), "mapped names and map-null companies never use name lookup");
  assert.ok(logoRequests.has("/nowherewidgets.test?404"), "company-site posting used its own domain");
  assert.ok(![...logoRequests].some(request => /greenhouse|confidential|wix/i.test(request)), "no ATS host, placeholder or catalog name reached Logo.dev");
  assert.ok(![...logoRequests].some(request => request.startsWith("/name/")), "no company name alone reaches Logo.dev");
  passed.push("requests");
} catch (error) { failures.push(`requests: ${error.message.split("\n")[0]}`); }
finally { await browser.close(); }
console.log(JSON.stringify({ passed, failures, logoRequests: [...logoRequests] }, null, 1));
if (failures.length) process.exitCode = 1;
