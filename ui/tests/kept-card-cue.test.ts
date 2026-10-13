import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";
import { keptCardStatus } from "../lib/job-status";

const uiRoot = resolve(import.meta.dirname, "..");

test("only New for me cards that moved on from new get a kept status", () => {
  assert.equal(keptCardStatus("new-for-me", "new"), null);
  for (const status of ["seen", "applied", "worth_checking", "not_relevant"] as const) assert.equal(keptCardStatus("new-for-me", status), status);
  for (const filter of ["all", "seen", "applied", "worth_checking"]) assert.equal(keptCardStatus(filter, "applied"), null, filter);
});

function renderCard(keptStatus: string | null, status = "applied"): string {
  const cardUrl = pathToFileURL(resolve(uiRoot, "components/job-card.tsx")).href;
  const job = { id: "00000000-0000-4000-8000-000000000001", title: "Fixture engineer", company: "Fixture", source: "fixture",
    last_seen_at: "2026-10-04T00:00:00Z", experience: null, description_available: false, seniority_origin: "unknown", extraction_state: "not-extracted",
    location: "Rehovot, Israel", remote: false, seniority: null, stack: [], salary: null, url: "https://example.test", apply_url: null,
    posted_at: null, first_seen_at: "2026-10-04T00:00:00Z", status, status_reason: null, score: 80, fit_line: null, recommendation: null, alive: true };
  const probe = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", `
    import React from "react";
    import { renderToStaticMarkup } from "react-dom/server";
    const module = await import(${JSON.stringify(cardUrl)});
    const JobCard = module.JobCard ?? module.default?.JobCard;
    process.stdout.write(renderToStaticMarkup(React.createElement(JobCard, { job: ${JSON.stringify(job)}, keptStatus: ${JSON.stringify(keptStatus)}, openerRef: { current: null }, selectJob() {} })));
  `], { cwd: uiRoot, encoding: "utf8" });
  assert.equal(probe.status, 0, probe.stderr);
  return probe.stdout;
}

test("a qualifying card renders exactly as before", () => {
  const html = renderCard(null, "new");
  assert.doesNotMatch(html, /data-settled|data-kept-status|opacity-60|aria-describedby/);
});
