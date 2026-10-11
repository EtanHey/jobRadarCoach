import assert from "node:assert/strict";
import { test } from "node:test";
import { spawnSync } from "node:child_process";
import { createClient } from "@supabase/supabase-js";
import { makeGetJobs } from "../app/api/jobs/route";
import { repostNote } from "../lib/job-display";
import { parseSummaryRows, selectSummaries, type ApiStore } from "../lib/server";

const url = "https://www.linkedin.com/jobs/view/1234567890";
const signal = { label: "Reposted 2 weeks ago", url, checked_at: "2026-10-07T00:00:00Z" };
const row = {
  id: "0199d9c3-a742-7000-8000-000000000001", title: "Engineer", company: "Fixture",
  source: "linkedin", last_seen_at: signal.checked_at, location: null, remote: null,
  seniority: null, stack: [], url, apply_url: null,
  posted_at: "2026-09-01T00:00:00Z", last_published_at: "2026-10-01T00:00:00Z",
  first_seen_at: "2026-10-02T00:00:00Z", relevance_filtered: false,
  relevance_rule: null, list_stack: [], experience: null, alive: true,
  linkedin_reposted_signal: signal, linkedin_closed_signal: null,
  posting_status: null, posting_scores: null,
};

test("repost evidence survives every slim list path and the HTTP response", async () => {
  let selected = "";
  let responseRow: Record<string, unknown> = row;
  const db = createClient("https://database.example.test", "synthetic-key", {
    auth: { persistSession: false }, global: { fetch: async request => {
      selected = new URL(String(request)).searchParams.get("select") ?? "";
      return new Response(JSON.stringify([responseRow]), { headers: { "content-type": "application/json" } });
    } },
  });
  const handler = makeGetJobs({ listJobs: input => selectSummaries(db, input) } as ApiStore);
  for (const query of ["filter=all", "filter=applied", "filter=all&sort=fit", `filter=all&availability=all&ids=${row.id}`]) {
    const response = await handler(new Request(`http://localhost/api/jobs?${query}`));
    assert.equal(response.status, 200, query);
    const job = (await response.json()).jobs[0];
    assert.match(selected, /(?:^|,)linkedin_reposted_signal:liveness->linkedin_reposted_signal(?:,|$)/);
    assert.match(selected, /,posted_at,last_published_at,/);
    assert.doesNotMatch(selected, /(?:^|,)(?:liveness|raw_jd|list_metadata|score_payload)(?:,|$)/);
    assert.deepEqual(job.linkedin_reposted_signal, signal);
    assert.equal(repostNote(job), signal.label);
    assert.equal(job.posted_at, row.posted_at);
    assert.equal(job.last_published_at, row.last_published_at);
    const card = spawnSync(process.execPath, ["--import", "tsx", "tests/fixtures/card-payload.tsx"], {
      cwd: process.cwd(), input: JSON.stringify([job]), encoding: "utf8",
    });
    assert.equal(card.status, 0, card.stderr);
    const [markup] = JSON.parse(card.stdout);
    assert.match(markup, /data-repost-marker/);
    assert.ok(markup.includes(signal.label));
  }
  for (const evidence of [null, { ...signal, label: "Not a repost" }, { ...signal, url: "https://www.linkedin.com/jobs/view/999" }]) {
    responseRow = { ...row, linkedin_reposted_signal: evidence };
    const job = (await (await handler(new Request("http://localhost/api/jobs?filter=all"))).json()).jobs[0];
    assert.equal(repostNote(job), null);
  }
  responseRow = { ...row, source: "greenhouse", linkedin_reposted_signal: null };
  const ats = (await (await handler(new Request("http://localhost/api/jobs?filter=all"))).json()).jobs[0];
  assert.equal(repostNote(ats, "UTC"), "Reposted: republished 2026-10-01");
});

test("detail summary retains validated LinkedIn repost evidence", () => {
  const job = parseSummaryRows([{ ...row, salary: null, posting_extractions: null,
    list_metadata: { stack: [], experience: null, description_available: false },
    liveness: { alive: true, linkedin_reposted_signal: signal },
  }]).jobs[0];
  assert.deepEqual(job.linkedin_reposted_signal, signal);
  assert.equal(repostNote(job), signal.label);
});
