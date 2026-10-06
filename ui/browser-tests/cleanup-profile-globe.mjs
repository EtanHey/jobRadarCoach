// Synthetic-only check of the profile title and globe debug instrumentation boundary.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium, expect } from "@playwright/test";
const base = process.env.GLOBE_QA_URL;
assert.equal(new URL(base).hostname, "127.0.0.1");
const output = process.env.GLOBE_QA_OUTPUT;
assert.ok(output);
await mkdir(output, { recursive: true });
const production = process.env.GLOBE_QA_PRODUCTION === "1";
const job = { id: "00000000-0000-4000-8000-000000000001", title: "Synthetic engineer", company: "Fixture Robotics", source: "fixture",
  last_seen_at: "2026-10-06T00:00:00Z", first_seen_at: "2026-10-06T00:00:00Z", experience: null,
  description_available: false, seniority_origin: "unknown", extraction_state: "not-extracted", location: "Rehovot, Israel",
  remote: false, seniority: null, stack: [], salary: null, url: "https://example.test/job", apply_url: null,
  posted_at: null, status: "new", status_reason: null, score: null, fit_line: null, recommendation: null, alive: true };
const jobs = [job, { ...job, id: "00000000-0000-4000-8000-000000000002", title: "Synthetic designer", company: "Fixture Design" }];
const profile = { "candidate.roles_wanted": ["Engineer"], "candidate.stacks": ["React"], "candidate.seniority": ["Junior"],
  "candidate.open_to.geographies": ["Israel"], "candidate.remote": null, "candidate.salary_floor": null,
  "candidate.red_flag_words": [], "candidate.preferences.free_text": null, "runtime.brain": "codex" };
const debugKeys = ["projection", "zoom", "center", "bearing", "pitch", "hoverId", "selectedId", "styleTheme", "waterColor",
  "landColor", "borderColor", "labelColor", "skyColor", "locationCorners", "cameraStarts", "flightMinZoom", "dotRingColor", "focusDecision"];
const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  try {
    await context.addInitScript(() => {
      localStorage.setItem("job-radar.board-preferences", JSON.stringify({ version: 3, filter: "all", view: {
        search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "active", sort: "fit" } }));
    });
    const page = await context.newPage(), errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => {
      const url = new URL(route.request().url());
      if (url.hostname.endsWith("cartocdn.com")) return route.continue();
      if (url.hostname !== "127.0.0.1") return route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (url.pathname === "/api/profile") return route.fulfill({ json: { profile } });
      if (url.pathname === "/api/jobs") return route.fulfill({ json: { jobs } });
      if (url.pathname === "/api/jobs/globe") return route.fulfill({ json: { jobs, points: jobs.map(item => ({ posting_id: item.id,
        lat: 31.8928, lng: 34.8113, precision: "city", source: "fixture", resolved_at: "2026-10-06T00:00:00Z" })),
        total_count: 2, resolved_count: 2, unresolved_count: 0, attribution: "fixture" } });
      return route.fulfill({ status: 404, json: { error: "Fixture only" } });
    });
    await page.goto(base);
    await page.getByRole("button", { name: "Edit profile", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveAccessibleName("Job preferences");
    await expect(page.getByRole("heading", { name: "Analysis worker", exact: true })).toBeVisible();
    await page.screenshot({ path: `${output}/profile.png` });
    await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
    await page.getByRole("button", { name: "Globe", exact: true }).filter({ visible: true }).click();
    await expect(page.getByRole("group", { name: "Globe controls" })).toBeVisible({ timeout: 30000 });
    const map = page.locator(".job-globe > .maplibregl-map");
    await page.getByRole("button", { name: "Zoom in", exact: true }).click();
    if (!production) await expect(map).toHaveAttribute("data-projection", "globe");
    const hoverCard = page.locator(`[data-globe-card="${job.id}"]`);
    await hoverCard.hover();
    if (!production) await expect(map).toHaveAttribute("data-hover-id", job.id);
    await expect(page.locator('.globe-cluster[data-unscored="true"]')).toBeVisible();
    await hoverCard.getByRole("button").first().click();
    if (!production) await expect(map).toHaveAttribute("data-selected-id", job.id);
    if (production) assert.deepEqual(await map.evaluate((node, keys) => keys.filter(key => Object.hasOwn(node.dataset, key)), debugKeys), []);
    await page.screenshot({ path: `${output}/globe.png` });
    assert.deepEqual(errors, []);
    console.log(`PASS: Job preferences title; analysis note retained; globe controls and card hover work; debug datasets ${production ? "absent in production" : "present in development"}.`);
  } finally { await context.close(); }
} finally { await browser.close(); }
