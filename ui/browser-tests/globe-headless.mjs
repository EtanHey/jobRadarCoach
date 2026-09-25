// Run against an isolated fixture copy (no proxy.ts), never a logged-in browser.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
const repo = fileURLToPath(new URL("../..", import.meta.url));
const sourceHead = execFileSync("git", ["rev-parse", "HEAD"], {cwd:repo,encoding:"utf8"}).trim();
const sourceDirty = !!execFileSync("git", ["status", "--porcelain"], {cwd:repo,encoding:"utf8"}).trim();
const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4318";
assert.equal(new URL(base).hostname, "127.0.0.1");
const output = process.env.GLOBE_QA_OUTPUT;
assert.ok(output, "Set GLOBE_QA_OUTPUT to a durable evidence directory");
await mkdir(output, { recursive: true });
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const jobs = Array.from({ length: 6 }, (_, n) => ({ id: id(n), title: ["Frontend Engineer", "Design Engineer", "Product Engineer", "UI Engineer", "Software Engineer", "Platform Engineer"][n], company: ["Atlas", "Meridian", "Orbit", "Northstar", "Signal", "Remote Studio"][n], source: "fixture", last_seen_at: "2026-09-22T00:00:00Z", experience: "3+ years", description_available: false, seniority_origin: "title", extraction_state: "not-extracted", location: ["Rehovot, Israel", "Berlin, Germany", "New York, United States", "London, UK", "Tel Aviv, Israel", "Remote"][n], remote: n % 2 === 0, seniority: "Junior", stack: ["React", "TypeScript"], salary: null, url: "https://example.test", apply_url: null, posted_at: null, first_seen_at: "2026-09-22T00:00:00Z", status: "new", status_reason: null, score: [91, 85, 78, 65, 44, null][n], fit_line: null, recommendation: "apply" }));
const points = [[31.8928,34.8113], [52.52,13.405], [40.7128,-74.006], [51.507,-0.127], [32.085,34.782]].map(([lat,lng],n) => ({posting_id:id(n),lat,lng,precision:n===4?"hq":"city",source:n===4?"https://example.test/company | nominatim:osm:node:1":"Development fixture",resolved_at:"2026-09-22T00:00:00Z"}));
const payload = {jobs,points,total_count:6,resolved_count:5,unresolved_count:1,attribution:"© OpenStreetMap contributors"};
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, reducedMotion: "reduce" });
await context.grantPermissions(["geolocation"], { origin: new URL(base).origin });
await context.setGeolocation({latitude:37.7749,longitude:-122.4194});
const page = await context.newPage();
await page.addInitScript(() => {
  window.locationRequests = 0;
  window.locationMode = "success";
  window.highZoomCartoTiles = [];
  navigator.geolocation.getCurrentPosition = (success, error) => {
    window.locationRequests++;
    if (window.locationMode === "success") success?.({coords:{latitude:37.7749,longitude:-122.4194,accuracy:30},timestamp:Date.now()});
    else error?.({code:1,message:"Fixture permission denied"});
  };
});
const errors = [];
page.on("pageerror", error => errors.push(error.message));
page.on("console", message => { if (message.type() === "error") console.error(message.text()); });
const highZoomCartoTiles = [];
page.on("request", request => {
  const url = new URL(request.url());
  const tile = url.pathname.match(/\/(\d+)\/\d+\/\d+\.mvt$/);
  if (url.hostname.endsWith(".basemaps.cartocdn.com") && tile && Number(tile[1]) >= 10) highZoomCartoTiles.push(Number(tile[1]));
});
let failApi = false;
const globeRequests = [];
page.on("requestfailed", request => console.error("FAILED",request.url(),request.failure()));
await page.route("**/api/**", route => {
  const url = new URL(route.request().url());
  if (url.pathname === "/api/jobs/globe") { globeRequests.push(url.search); return route.fulfill({status:failApi?503:200,json:failApi?{error:"fixture outage"}:payload}); }
  if (url.pathname === "/api/jobs") return route.fulfill({json:{jobs}});
  if (url.pathname === "/api/events") return route.fulfill({contentType:"text/event-stream",body:"event: ready\ndata: {}\n\n"});
  const job = jobs.find(job => url.pathname === `/api/jobs/${job.id}`);
  if (job) return route.fulfill({json:{job:{...job,raw_jd:null,reasons:[],score_payload:null,brain:null,scored_at:null}}});
  return route.fulfill({status:404,json:{error:"fixture only"}});
});
// Idle prefetch can request the style before the first click; hold it until OFF.
const styleUrl = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
let releaseStyle;
const styleGate = new Promise(resolve => { releaseStyle = resolve; });
await page.route(styleUrl, async route => { await styleGate; await route.continue(); });
const styleRequest = page.waitForRequest(styleUrl);
try {
  await page.goto(base);
  await page.getByRole("button", {name:"Globe",exact:true}).waitFor();
  await page.getByRole("button",{name:"All roles",exact:true}).click();
  await page.waitForFunction(() => document.querySelectorAll("[data-posting-id]").length === 6);
  await page.screenshot({path:`${output}/list.png`,fullPage:true});
  // The style remains pending so an immediate OFF leaves the map uninitialized.
  await page.clock.install();
  await page.getByRole("button",{name:"Globe",exact:true}).click();
  await styleRequest;
  await page.getByRole("button",{name:"Globe",exact:true}).click();
  await page.clock.fastForward(21000);
  assert.equal(await page.getByText("The globe could not load. Your list is still here.",{exact:false}).count(),0,"a hidden globe must not report a late load failure");
  assert.equal(await page.locator(".job-globe").count(),1,"the hidden globe stays mounted");
  await page.clock.resume();
  releaseStyle();
  // Clock fast-forward can leave Base UI transitions unstable for pointer clicks.
  await page.addStyleTag({content:"*,*::before,*::after { transition-duration: 0s !important; animation-duration: 0s !important; }"});
  await page.waitForTimeout(2200);
  await page.unroute(styleUrl);
  await page.emulateMedia({reducedMotion:"no-preference"});
  const sampleToggle = async () => {
    const oldMapBox = await page.locator(".job-globe").boundingBox();
    await page.getByRole("button",{name:"Globe",exact:true}).click();
    const frames = [];
    for (let i = 0; i < 32; i++) {
      await page.evaluate(() => new Promise(requestAnimationFrame));
      const mapBox = await page.locator(".maplibregl-canvas-container").boundingBox();
      const target = mapBox ?? oldMapBox;
      if (target) await page.mouse.move(target.x + target.width * (0.3 + (i % 10) * 0.04), target.y + target.height * (0.4 + (i % 5) * 0.03));
      frames.push(await page.evaluate(() => {
        const layout = document.querySelector(".globe-layout"), rail = document.querySelector(".globe-rail");
        const card = rail.querySelector("article"), badge = card?.querySelector("[aria-label^='Fit score']");
        const canvas = document.querySelector(".maplibregl-canvas");
        const chip = [...document.querySelectorAll("button")].find(button => button.getAttribute("aria-label") === "Globe");
        return {open:layout.classList.contains("globe-layout-open"),rail:rail.getBoundingClientRect().width,layout:layout.getBoundingClientRect().width,
          partitionReady:!!document.querySelector("#globe-visible-heading"),
          slot:document.querySelector(".globe-slot").getBoundingClientRect().width,
          badgeInside:!card||!badge||badge.getBoundingClientRect().right<=card.getBoundingClientRect().right+1,
          chipLegible:!!chip&&chip.getBoundingClientRect().width>=40&&getComputedStyle(chip).visibility==="visible"&&getComputedStyle(chip).opacity!=="0",
          canvasUsable:!canvas||!layout.classList.contains("globe-layout-open")||(canvas.clientWidth>0&&canvas.clientHeight>0),
          projection:canvas?document.querySelector("[data-projection]")?.getAttribute("data-projection"):null};
      }));
    }
    return frames;
  };
  const onFrames = await sampleToggle();
  assert.ok(onFrames.every(frame => frame.open && frame.rail/frame.layout < .43 && frame.rail/frame.layout > .2 && frame.slot > 0 && frame.badgeInside && frame.chipLegible && frame.canvasUsable && (!frame.projection||frame.projection==="globe")), "ON keeps a stable two-column layout, globe projection, chip and badges in every frame");
  await page.emulateMedia({reducedMotion:"reduce"});
  await page.getByText("Drag to spin",{exact:false}).waitFor({timeout:30000});
  await page.waitForTimeout(2200);
  await page.screenshot({path:`${output}/globe.png`,fullPage:true});
  const firstCanvas = await page.locator(".maplibregl-canvas").elementHandle();
  assert.equal(await page.locator(".maplibregl-canvas").count(),1);
  assert.equal(await page.getByText("5 on the globe · 1 without a location",{exact:true}).filter({visible:true}).count(),1);
  assert.ok(globeRequests.every(query => !query.includes("limit=")));
  const map = page.locator("[data-projection]");
  const grantedPermission = await page.evaluate(async () => (await navigator.permissions.query({name:"geolocation"})).state);
  assert.equal(grantedPermission,"granted","fixture starts with browser location permission granted");
  await page.waitForTimeout(350);
  const geolocationCallsOnLoad = await page.evaluate(() => window.locationRequests);
  const atRestZoomBeforeLocationClick = Number(await map.getAttribute("data-zoom"));
  const highZoomCartoTilesBeforeLocationClick = [...highZoomCartoTiles];
  assert.equal(geolocationCallsOnLoad,0,"granted permission must not request location on Globe load");
  assert.ok(atRestZoomBeforeLocationClick <= 1.9,"granted permission keeps the world-level landing zoom until an explicit click");
  assert.deepEqual(highZoomCartoTilesBeforeLocationClick,[],"opening Globe with granted permission must not request city-level CARTO tiles");
  const locationControl = page.locator(".maplibregl-ctrl-top-right").getByRole("button",{name:"Use my location",exact:true});
  await locationControl.waitFor();
  assert.ok(await locationControl.evaluate(button => button.getBoundingClientRect().width >= 44 && button.getBoundingClientRect().height >= 44), "location control meets the 44px target");
  assert.equal(await locationControl.locator("svg").count(),1,"location control has a visible SVG crosshair, not a font-dependent glyph");
  const desktopLocationControl = await locationControl.evaluate(button => ({width:button.getBoundingClientRect().width,height:button.getBoundingClientRect().height}));
  const cameraBeforeDenied = await map.evaluate(element => ({center:element.dataset.center,zoom:element.dataset.zoom,bearing:element.dataset.bearing,pitch:element.dataset.pitch}));
  await page.evaluate(() => { window.locationMode = "denied"; });
  await locationControl.click();
  assert.equal(await page.evaluate(() => window.locationRequests),1);
  await page.getByText("Location unavailable · you can still explore",{exact:true}).waitFor();
  assert.deepEqual(await map.evaluate(element => ({center:element.dataset.center,zoom:element.dataset.zoom,bearing:element.dataset.bearing,pitch:element.dataset.pitch})),cameraBeforeDenied,"denied location leaves the camera unchanged");
  const desktopStatus = await page.locator(".maplibregl-ctrl-location-status").boundingBox();
  const desktopLocationBox = await page.locator(".maplibregl-ctrl-location").boundingBox();
  const desktopStatusAligned = Math.abs(desktopStatus.y - desktopLocationBox.y) < 8;
  assert.ok(desktopStatusAligned,"desktop location status is aligned with the location button row");
  await page.clock.fastForward(5500);
  await page.getByText("Location unavailable · you can still explore",{exact:true}).waitFor();
  const denialStatusRemainsAfter5500Ms = await page.getByText("Location unavailable · you can still explore",{exact:true}).count() === 1;
  await page.screenshot({path:`${output}/denied-location.png`,fullPage:true});
  assert.equal(await map.getAttribute("data-projection"),"globe");
  await page.getByRole("button",{name:"Zoom in",exact:true}).click();
  await page.waitForTimeout(400);
  assert.equal(await map.getAttribute("data-projection"),"globe");
  await page.getByRole("button",{name:"Zoom out",exact:true}).click();
  await page.waitForTimeout(400);
  const count = page.getByRole("button",{name:"2 roles near Rehovot",exact:true});
  const clusterZoomBefore = Number(await map.getAttribute("data-zoom"));
  await count.focus();
  await page.keyboard.press("Enter");
  await page.waitForFunction(before => Number(document.querySelector("[data-projection]")?.getAttribute("data-zoom")) > before + 1, clusterZoomBefore);
  assert.equal(await map.getAttribute("data-projection"), "globe");
  const chip = page.getByRole("button",{name:/Clear bubble filter/});
  await chip.waitFor();
  assert.match(await chip.innerText(),/Near Rehovot · 2 roles/);
  assert.equal(await page.locator('[data-globe-section="visible"] [data-posting-id]').count(),2);
  assert.equal(await page.locator('[data-globe-section="outside"]').count(),0);
  await page.getByRole("button",{name:"Open Frontend Engineer at Atlas",exact:true}).focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.getByRole("button",{name:"Open Frontend Engineer at Atlas",exact:true}).getAttribute("aria-pressed"),"true");
  await page.getByRole("button",{name:"Open Software Engineer at Signal",exact:true}).focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.getByRole("button",{name:"Open Software Engineer at Signal",exact:true}).getAttribute("aria-pressed"),"true");
  const desktopChip = await chip.boundingBox();
  const desktopRail = await page.locator('.globe-rail').boundingBox();
  assert.ok(desktopChip && desktopRail && desktopChip.y >= desktopRail.y && desktopChip.y < desktopRail.y + desktopRail.height,"bubble chip stays in the desktop rail");
  await chip.focus();
  await page.keyboard.press("Enter");
  await chip.waitFor({state:"detached"});
  assert.equal(await page.locator('[data-globe-posting]').getAttribute('data-globe-posting'),id(4));
  assert.equal(await page.locator('[data-globe-selected="true"] button[aria-pressed="true"]').count(),1);
  await page.getByRole("button",{name:"Open Product Engineer at Orbit",exact:true}).click();
  await page.waitForTimeout(300);
  assert.equal(await page.locator('[data-globe-posting]').getAttribute('data-globe-posting'),id(2));
  await page.getByRole("button",{name:"View job details",exact:true}).click();
  await page.getByRole('dialog').getByRole('heading',{name:'Product Engineer',exact:true}).waitFor();
  await page.keyboard.press("Escape");
  await page.getByRole('dialog').waitFor({state:'hidden'});
  const mapTop = (await page.locator(".job-globe").boundingBox()).y;
  await page.getByRole("button",{name:"Open Design Engineer at Meridian",exact:true}).click();
  await page.waitForTimeout(400);
  assert.equal(await page.locator('[data-globe-selected="true"]').count(),1);
  assert.equal(await page.locator(".job-globe-shell").getByText("Design Engineer",{exact:true}).count(),1);
  assert.equal(await page.locator(".job-globe-shell").getByText("Software Engineer",{exact:true}).count(),0);
  assert.equal(await page.locator('[data-globe-posting]').getAttribute('data-globe-posting'),id(1));
  assert.equal((await page.locator(".job-globe").boundingBox()).y,mapTop);
  assert.match(await page.locator('[data-globe-posting]').innerText(), /Meridian · 85 fit/);
  assert.equal(await map.getAttribute("data-projection"),"globe");
  assert.ok(Number(await map.getAttribute("data-zoom")) >= 5, "selection keeps or raises camera zoom");
  const cameraBeforeToggle = await map.evaluate(element => ({center:element.dataset.center,zoom:element.dataset.zoom,bearing:element.dataset.bearing,pitch:element.dataset.pitch}));
  await page.evaluate(() => {
    window.mapMouseEvents = 0;
    document.querySelector(".maplibregl-canvas-container").addEventListener("mousemove", event => {
      if (event.isTrusted) window.mapMouseEvents++;
    }, {capture:true});
  });
  const offFrames = await sampleToggle();
  assert.ok(offFrames.every(frame => !frame.open && frame.rail/frame.layout > .95 && frame.badgeInside && frame.chipLegible), "OFF keeps the full-width grid, chip and badges in every frame");
  await page.screenshot({path:`${output}/toggle-off.png`,fullPage:true});
  await page.waitForTimeout(150); // Beyond MapLibre's throttled hidden resize observer.
  const onAgainFrames = await sampleToggle();
  assert.ok(onAgainFrames.every(frame => frame.open && frame.rail/frame.layout < .43 && frame.rail/frame.layout > .2 && frame.badgeInside));
  assert.ok(onAgainFrames.every(frame => frame.partitionReady),"reopening a valid partition never flashes the loading shell");
  assert.equal(await page.locator(".maplibregl-canvas").count(),1);
  assert.ok(await firstCanvas.evaluate((canvas,other) => canvas === other, await page.locator(".maplibregl-canvas").elementHandle()), "canvas identity survives OFF/ON");
  assert.deepEqual(await map.evaluate(element => ({center:element.dataset.center,zoom:element.dataset.zoom,bearing:element.dataset.bearing,pitch:element.dataset.pitch})),cameraBeforeToggle);
  const trustedCanvasMouseEvents = await page.evaluate(() => window.mapMouseEvents);
  assert.ok(trustedCanvasMouseEvents > 0,"real pointer events must reach MapLibre's canvas container after re-opening");
  await page.screenshot({path:`${output}/toggle-on-again.png`,fullPage:true});
  await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({path:`${output}/selected.png`,fullPage:true});
  await page.getByRole("combobox",{name:"Location",exact:true}).click();
  await page.getByRole("option",{name:"Israel",exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-posting-id]').length===2);
  assert.equal(await page.locator("[data-posting-id]").count(),2);
  assert.equal(await page.getByText("2 on the globe · 0 without a location",{exact:true}).filter({visible:true}).count(),1);
  await page.getByRole("combobox",{name:"Work mode",exact:true}).click();
  await page.getByRole("option",{name:"On-site / hybrid",exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-posting-id]').length===0);
  assert.equal(await page.locator("[data-posting-id]").count(),0);
  await page.getByRole("combobox",{name:"Work mode",exact:true}).click();
  await page.getByRole("option",{name:"Any work mode",exact:true}).click();
  await page.getByRole("combobox",{name:"Location",exact:true}).click();
  await page.getByRole("option",{name:"All locations",exact:true}).click();
  const search = page.getByPlaceholder("Search title, company, or stack");
  await search.fill("Remote Studio");
  await page.waitForFunction(()=>document.querySelectorAll('[data-posting-id]').length===1);
  assert.equal(await page.locator("[data-posting-id]").count(),1);
  assert.equal(await page.getByText("0 on the globe · 1 without a location",{exact:true}).filter({visible:true}).count(),1);
  assert.equal(await page.locator('[data-globe-selected="true"]').count(),0);
  await search.fill("no results anywhere");
  assert.equal(await page.getByText("0 on the globe · 0 without a location",{exact:true}).filter({visible:true}).count(),1);
  await search.fill("");
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(300);
  const mobileLocationControl = page.locator(".maplibregl-ctrl-top-right").getByRole("button",{name:"Retry location",exact:true});
  await mobileLocationControl.waitFor();
  assert.ok(await mobileLocationControl.evaluate(button => button.getBoundingClientRect().width >= 44 && button.getBoundingClientRect().height >= 44), "mobile location control meets the 44px target");
  const mobileLocationControlSize = await mobileLocationControl.evaluate(button => ({width:button.getBoundingClientRect().width,height:button.getBoundingClientRect().height}));
  assert.ok(Number(await map.getAttribute("data-zoom")) > 0, "resizing to mobile preserves a usable camera");
  await page.screenshot({path:`${output}/mobile.png`,fullPage:true});
  const mobileCamera = await map.evaluate(element => ({center:element.dataset.center,zoom:element.dataset.zoom,bearing:element.dataset.bearing,pitch:element.dataset.pitch}));
  const mobileOffFrames = await sampleToggle();
  assert.ok(mobileOffFrames.every(frame => !frame.open && frame.rail/frame.layout > .95 && frame.badgeInside));
  await page.screenshot({path:`${output}/mobile-toggle-off.png`,fullPage:true});
  const mobileOnFrames = await sampleToggle();
  assert.ok(mobileOnFrames.every(frame => frame.open && frame.rail/frame.layout > .95 && frame.slot > 0 && frame.badgeInside));
  assert.deepEqual(await map.evaluate(element => ({center:element.dataset.center,zoom:element.dataset.zoom,bearing:element.dataset.bearing,pitch:element.dataset.pitch})),mobileCamera);
  assert.ok(await firstCanvas.evaluate((canvas,other) => canvas === other, await page.locator(".maplibregl-canvas").elementHandle()));
  await page.screenshot({path:`${output}/mobile-toggle-on.png`,fullPage:true});
  const zoomBeforeLocation = Number(await map.getAttribute("data-zoom"));
  await page.evaluate(() => { window.locationMode = "success"; });
  await mobileLocationControl.click();
  assert.equal(await page.evaluate(() => window.locationRequests),2);
  await page.getByText("Centered near you · not saved by Job Radar",{exact:true}).waitFor();
  await page.waitForFunction(() => {
    const center = document.querySelector("[data-projection]")?.getAttribute("data-center")?.split(",").map(Number);
    return center && Math.abs(center[0] + 122.4194) < 0.02 && Math.abs(center[1] - 37.7749) < 0.02;
  });
  assert.ok(Number(await map.getAttribute("data-zoom")) >= 10, "location moves the camera to city-level zoom");
  assert.ok(Number(await map.getAttribute("data-zoom")) >= zoomBeforeLocation, "location never zooms out");
  const locationCamera = await map.evaluate(element => ({center:element.dataset.center,zoom:Number(element.dataset.zoom)}));
  assert.equal(await page.locator("[data-globe-posting]").count(),0,"location centering hides the unrelated focused-posting card");
  const mobileStatusAvoidsHint = await page.evaluate(() => {
    const status = document.querySelector(".maplibregl-ctrl-location-status").getBoundingClientRect();
    const hint = document.querySelector(".job-globe > p")?.getBoundingClientRect();
    if (!hint) return true;
    return status.right <= hint.left || status.left >= hint.right || status.bottom <= hint.top || status.top >= hint.bottom;
  });
  assert.equal(mobileStatusAvoidsHint,true,"mobile location status does not cover the map hint");
  await page.screenshot({path:`${output}/location-success.png`,fullPage:true});
  assert.ok(globeRequests.every(query => !/37\.7749|-122\.4194/.test(query)), "user coordinates are never sent with globe requests");
  await page.clock.fastForward(4500);
  const successStatusClearedAfter4500Ms = await page.getByText("Centered near you · not saved by Job Radar",{exact:true}).count() === 0;
  assert.equal(successStatusClearedAfter4500Ms,true,"successful location status clears after a few seconds");
  await page.evaluate(() => { navigator.geolocation.getCurrentPosition = success => success({coords:{latitude:52.52,longitude:13.405,accuracy:30},timestamp:Date.now()}); });
  await page.getByRole("button",{name:"Use my location",exact:true}).click();
  await page.waitForFunction(() => {
    const center = document.querySelector("[data-projection]")?.getAttribute("data-center")?.split(",").map(Number);
    return center && Math.abs(center[0] - 13.405) < .0001 && Math.abs(center[1] - 52.52) < .0001;
  });
  assert.equal(await page.locator("[data-globe-posting]").count(),0,"location move hides the previously focused card");
  const mapBox = await page.locator(".job-globe").boundingBox();
  let pointPixel = null;
  for (let dy = -20; dy <= 20 && !pointPixel; dy += 4) for (let dx = -12; dx <= 12 && !pointPixel; dx += 4) {
    const x = mapBox.x + mapBox.width / 2 + dx, y = mapBox.y + mapBox.height / 2 + dy;
    await page.mouse.move(x, y); await page.waitForTimeout(25);
    if (await page.locator(`[data-globe-hover="${id(1)}"]`).count()) pointPixel = {x, y};
  }
  assert.ok(pointPixel,"Berlin point is hoverable after location move");
  await page.mouse.click(pointPixel.x,pointPixel.y);
  await page.locator(`[data-globe-posting="${id(1)}"]`).waitFor();
  const pointDrawer = page.getByRole("dialog");
  if (await pointDrawer.isVisible()) { await pointDrawer.getByRole("button", { name: "Close", exact: true }).click(); await pointDrawer.waitFor({ state: "hidden" }); }
  await page.getByRole("button",{name:"Use my location",exact:true}).click();
  await page.waitForFunction(() => document.querySelectorAll("[data-globe-posting]").length === 0);
  await page.getByRole("button",{name:"Open Design Engineer at Meridian",exact:true}).click();
  await page.locator(`[data-globe-posting="${id(1)}"]`).waitFor();
  for (const button of await page.locator(".job-globe button, .globe-footer button").all()) {
    const bounds = await button.boundingBox();
    if (bounds) assert.ok(bounds.width >= 44 && bounds.height >= 44, "map controls meet 44px target");
  }
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.getByRole("button",{name:"Globe",exact:true}).click();
  assert.equal(await page.locator(".job-globe").count(),1);
  assert.equal(await page.locator(".job-globe").isVisible(),false);
  await page.locator(".maplibregl-canvas").evaluate(canvas => canvas.dispatchEvent(new Event("webglcontextlost",{cancelable:true})));
  assert.equal(await page.getByText("The globe could not load. Your list is still here.",{exact:false}).count(),0,"hidden context loss waits for show");
  await page.getByRole("button",{name:"Globe",exact:true}).click();
  await page.getByText("The globe could not load. Your list is still here.",{exact:false}).waitFor();
  assert.equal(await page.locator(".job-globe").count(),0,"deferred context loss returns to the list");
  failApi = true;
  await page.getByRole("button",{name:"Globe",exact:true}).click();
  await page.getByText("The globe is unavailable. Your list is still here.",{exact:false}).waitFor();
  await page.screenshot({path:`${output}/api-error.png`,fullPage:true});
  assert.equal(await page.locator("[data-posting-id]").count(),6);
  assert.equal(await page.locator(".job-globe").isVisible(),false);
  assert.deepEqual(errors,[]);
  failApi = false;
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type,...args) { return /webgl/.test(type) ? null : original.call(this,type,...args); };
  });
  await page.reload();
  await page.getByRole("button",{name:"Globe",exact:true}).click();
  await page.getByText("The globe could not load. Your list is still here.",{exact:false}).waitFor();
  await page.screenshot({path:`${output}/webgl-error.png`,fullPage:true});
  assert.equal(await page.locator("[data-posting-id]").count(),6);
  const screenshots = {};
  for (const name of ["list", "globe", "toggle-off", "toggle-on-again", "selected", "mobile", "mobile-toggle-off", "mobile-toggle-on", "denied-location", "location-success", "api-error", "webgl-error"]) screenshots[`${name}.png`] = createHash("sha256").update(await readFile(`${output}/${name}.png`)).digest("hex");
  await writeFile(`${output}/receipt.json`,JSON.stringify({sourceHead,sourceDirty,screenshots,kind:"headless development fixtures, not live data",onFrames,offFrames,onAgainFrames,mobileOffFrames,mobileOnFrames,grantedPermission,geolocationCallsOnLoad,atRestZoomBeforeLocationClick,highZoomCartoTilesBeforeLocationClick,desktopChip,mobileLocationControlSize,desktopLocationControl,desktopStatusAligned,denialStatusRemainsAfter5500Ms,deniedCameraUnchanged:true,locationCamera,mobileStatusAvoidsHint,successStatusClearedAfter4500Ms,globeRequests,highZoomCartoTiles,trustedCanvasMouseEvents,errors,checks:["hidden delayed-load timeout does not fail after 21 s","stable width on every toggle frame","one canvas and preserved camera across OFF/ON on desktop and mobile","valid partition survives re-show without loading shell","desktop chip filters the rail","same rail role restores focused card after location move","hidden context loss replays on show and falls back to list","contained badges","trusted canvas pointer movement during toggles, including after 150 ms hidden","globe render","no limit","cluster keyboard activation zooms in and filters exact roles", "rail selection then different row exact title/company/ID", "globe projection at initial/zoom/selection and fly zoom cap", "granted browser permission verified with no geolocation call, no zoom change, and no high-zoom CARTO tile request before click", "44px desktop and mobile location controls in MapLibre control stack", "SVG crosshair control icon", "denied geolocation leaves camera unchanged and announces non-blocking status", "denial status remains for 5.5 seconds and desktop status aligns with its control row", "successful geolocation centers within 0.02 degrees at zoom >= 10 without zooming out", "success status clears after 4.5 seconds", "focused role card clears after location centering", "mobile location status does not cover the map hint", "user coordinates never sent with globe requests", "distinct denied/API/WebGL frames","permission denial fallback","location and remote filters","WebGL fallback","shared query and unresolved counts","empty filter","mobile overflow","close","API fallback"]},null,2));
} catch (error) { await page.screenshot({path:`${output}/failure.png`,fullPage:true,timeout:5000}).catch(()=>{}); console.error(errors); throw error; } finally { releaseStyle?.(); await browser.close(); }
