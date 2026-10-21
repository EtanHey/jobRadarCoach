import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { readFileSync } from "node:fs";
import { createClient } from "@supabase/supabase-js";
import { test } from "node:test";
import { parseSummaryRows, selectSummaries } from "../lib/server";
import { projectLiveness } from "../lib/liveness";
import { GlobeJobSchema } from "../lib/globe-contract";

const now = Date.parse("2026-10-22T10:00:00Z");
for (const fixture of JSON.parse(readFileSync(resolve(import.meta.dirname, "../../scraper/fixtures/liveness-projection.json"), "utf8"))) {
  test(`shared projection contract: ${fixture.name}`, () => {
    const projected = projectLiveness(fixture.evidence, now);
    assert.equal(projected.liveness.state, fixture.state);
    assert.equal(projected.alive, fixture.alive);
  });
}
const raw = {
  id: "00000000-0000-4000-8000-000000000001", title: "Engineer", company: "Synthetic Example",
  source: "workday", last_seen_at: "2026-10-22T09:30:00Z", first_seen_at: "2026-10-01T00:00:00Z",
  list_metadata: { stack: [], experience: null, description_available: true },
  posting_extractions: null, location: null, remote: null, seniority: null, stack: [], salary: null,
  url: "https://example.test/job", apply_url: null, posted_at: null, posting_status: null, posting_scores: null,
};

test("summary readers preserve stale history without returning fresh alive", () => {
  for (const evidence of [
    { liveness_checked_at: "2026-10-22T09:30:00Z", last_attempt_verdict: "unknown" },
    { liveness_checked_at: "2026-10-13T09:30:00Z" },
    { liveness_checked_at: "2026-10-22T09:30:00Z", application_deadline: "2026-10-18T23:59:59Z" },
  ]) {
    const [job] = parseSummaryRows([{ ...raw, liveness: { alive: true, ...evidence } }], now).jobs;
    assert.equal(job.alive, null);
    assert.equal(job.liveness?.state, "application_deadline" in evidence ? "deadline_passed" : "stale");
    assert.equal(job.liveness?.last_confirmed_at, evidence.liveness_checked_at);
  }
});

test("slim globe snapshots cannot assert fresh availability without confirmation evidence", () => {
  const job = parseSummaryRows([{ ...raw, liveness: null }], now).jobs[0];
  assert.equal(GlobeJobSchema.parse({ ...job, alive: true }).alive, null);
  assert.equal(GlobeJobSchema.parse({ ...job, alive: false }).alive, false);
});

test("all list paths fetch and project latest-attempt and deadline evidence", async () => {
  for (const evidence of [
    { last_attempt_verdict: "unknown" },
    { application_deadline: "2026-10-18T23:59:59Z" },
  ]) {
    const { list_metadata, posting_extractions, salary, ...posting } = raw;
    void posting_extractions; void salary;
    const db = createClient("https://database.example.test", "synthetic", { global: { fetch: async input => {
      const selected = new URL(String(input)).searchParams.get("select") ?? "";
      for (const key of ["liveness_checked_at", "last_attempt_verdict", "application_deadline"]) {
        assert.ok(selected.includes(`${key}:liveness->${key}`));
      }
      return Response.json([{ ...posting, alive: true, liveness_checked_at: new Date().toISOString(),
        list_stack: list_metadata.stack, experience: null, relevance_rule: null,
        linkedin_reposted_signal: null, linkedin_closed_signal: null, ...evidence }]);
    } } });
    const base = { filter: "all", availability: "all", limit: 50 } as const;
    for (const query of [base, { ...base, sort: "fit" as const }, { ...base, ids: [raw.id] }]) {
      const [job] = await selectSummaries(db, query);
      assert.equal(job.alive, null);
      assert.equal(job.liveness?.state, "application_deadline" in evidence ? "deadline_passed" : "stale");
    }
  }
});

test("liveness badge displays stale confirmation age and explicit deadline status", () => {
  const probe = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", `
    import { renderToStaticMarkup } from "react-dom/server";
    import * as module from "./components/liveness-badge.tsx";
    const LivenessBadge = module.LivenessBadge ?? module.default?.LivenessBadge;
    const states = [
      { state: "stale", last_confirmed_at: "2026-10-13T10:00:00Z", application_deadline: null },
      { state: "deadline_passed", last_confirmed_at: null, application_deadline: "2026-10-18T23:59:59Z" },
      { state: "closed", last_confirmed_at: null, application_deadline: null },
    ];
    process.stdout.write(JSON.stringify(states.map(liveness => renderToStaticMarkup(
      LivenessBadge({ job: { liveness }, now: ${now} })
    ))));
  `], { cwd: resolve(import.meta.dirname, ".."), encoding: "utf8" });
  assert.equal(probe.status, 0, probe.stderr);
  const [stale, deadline, closed] = JSON.parse(probe.stdout);
  assert.match(stale, /Last confirmed 9 days ago/);
  assert.match(stale, /latest availability unconfirmed/i);
  assert.match(deadline, /Application deadline passed/);
  assert.match(closed, /Closed/);
});
