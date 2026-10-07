// Run from ui under e2e/cap.sh against the credential-free Next fixture app.
import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";

const output = process.env.GLOBE_QA_OUTPUT;
assert.ok(output, "Set GLOBE_QA_OUTPUT for evidence");
await mkdir(output, { recursive: true });
const port = "55471", base = `http://127.0.0.1:${port}`;
const app = spawn(process.execPath, ["e2e/start-app.mjs", port], { stdio: ["ignore", "pipe", "pipe"] });
let appLog = "", browser;
app.stdout.on("data", chunk => appLog += chunk);
app.stderr.on("data", chunk => appLog += chunk);
const receipts = [];
try {
  await expect.poll(async () => {
    try { return (await fetch(base)).ok; } catch { return false; }
  }, { timeout: 60_000 }).toBe(true);
  browser = await chromium.launch({ headless: true });
  // Reset both after leaving New-for-me and while staying on a nondefault facet.
  for (const leave of [true, false]) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
    const errors = [], reads = [];
    page.on("pageerror", error => errors.push(error.message));
    const job = { id: "00000000-0000-4000-8000-000000000001", title: "Reset engineer",
      company: "Example", source: "fixture", last_seen_at: "2026-10-06T00:00:00Z",
      first_seen_at: new Date(Date.now() - 3600000).toISOString(), posted_at: null, experience: null,
      description_available: false, seniority_origin: "unknown", extraction_state: "not-extracted",
      location: null, remote: null, seniority: null, stack: [], salary: null,
      url: "https://example.test", apply_url: null, status: "new", status_reason: null,
      score: 90, recommendation: "apply", fit_line: null, alive: true };
    await page.addInitScript(() => localStorage.setItem("job-radar.board-preferences", JSON.stringify({
      version: 3, filter: "new-for-me", view: { search: "", source: "", location: "", seniority: "",
        fit: "good", statuses: [], availability: "active", sort: "found", found_within: "7d" },
    })));
    await page.route("**/api/**", route => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/jobs") {
        reads.push(Object.fromEntries(url.searchParams));
        const ids = url.searchParams.get("ids")?.split(",");
        const jobs = url.searchParams.has("since") ? [] : ids
          ? ids.includes(job.id) ? [{ ...job }] : []
          : url.searchParams.get("filter") === "new-for-me" && job.status !== "new" ? [] : [{ ...job }];
        return route.fulfill({ json: { jobs } });
      }
      if (url.pathname === `/api/jobs/${job.id}/status`) {
        job.status = "seen";
        return route.fulfill({ json: { status: "seen", reason: null } });
      }
      if (url.pathname === `/api/jobs/${job.id}`) return route.fulfill({ json: { job: {
        ...job, raw_jd: "Synthetic description", reasons: [], score_payload: null, brain: null, scored_at: null,
      } } });
      return route.fulfill({ status: 404, json: { error: "fixture only" } });
    });
    await page.goto(base);
    await expect(page.locator("article[data-posting-id]")).toHaveCount(1);
    assert.equal(reads[0].sort, "found");
    assert.equal(reads[0].fit, "good");
    assert.equal(reads[0].found_within, "7d");
    await page.getByRole("button", { name: "Open Reset engineer at Example", exact: true }).click();
    await expect.poll(() => job.status).toBe("seen");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(page.locator("article[data-posting-id]")).toHaveCount(1);
    if (leave) await page.getByRole("button", { name: "All roles", exact: true }).click();
    const before = reads.length;
    await page.getByRole("button", { name: "Reset view", exact: true }).click();
    await expect.poll(() => reads.slice(before).some(read =>
      read.filter === "new-for-me" && read.sort === "fit" && read.fit === "recommended" && !read.found_within)).toBe(true);
    await expect(page.getByRole("heading", { name: "No roles in this view yet.", exact: true })).toBeVisible();
    await expect(page.locator("article[data-posting-id]")).toHaveCount(0);
    assert.equal(reads.slice(before).some(read => read.ids), false, "Reset must not hydrate the old Seen cohort");
    assert.deepEqual(errors, []);
    await page.screenshot({ path: `${output}/reset-${leave ? "after-all" : "same-cohort"}.png` });
    receipts.push({ leave, reads, errors });
    await page.close();
  }
  await writeFile(`${output}/receipt.json`, JSON.stringify(receipts, null, 2));
  console.log("PASS: Reset clears nondefault sort/fit/found-within visit snapshots after All and within New-for-me");
} finally {
  if (browser) await browser.close();
  app.kill("SIGTERM");
  if (app.exitCode === null) await new Promise(resolve => app.once("exit", resolve));
  await writeFile(`${output}/app.log`, appLog);
}
