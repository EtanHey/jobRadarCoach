import assert from "node:assert/strict";
import { test } from "node:test";
import { spawnSync } from "node:child_process";
import { createClient } from "@supabase/supabase-js";
import { JobListItemSchema, JobListResponseSchema, type JobListQuery } from "../lib/contracts";
import { BOARD_FIELD_ALIASES, getApiStore, parseSummaryRows, selectSummaries } from "../lib/server";
import { filterJobGroups, type ViewOptions } from "../lib/job-filters";

const id = "00000000-0000-4000-8000-000000000001";
const signal = { phrase: "no longer accepting applications", checked_at: "2026-10-07T10:00:00Z", url: "https://www.linkedin.com/jobs/view/123" };
const raw = {
  id, title: "Junior Engineer", company: "Synthetic Example", source: "linkedin",
  first_seen_at: "2026-10-07T00:00:00Z", last_seen_at: "2026-10-07T10:00:00Z",
  posted_at: null, last_published_at: null, location: "Tel Aviv, Israel", remote: null,
  work_mode: "hybrid", seniority: null, stack: [], salary: "Unused salary",
  url: signal.url, apply_url: "https://example.test/job", relevance_filtered: false,
  relevance_gate: { rule: "synthetic", evidence: "unused".repeat(100) },
  list_metadata: { stack: ["React"], experience: "3 years", description_available: true },
  posting_extractions: { posting_id: id }, posting_status: { status: "applied", reason: "Owner wording" },
  posting_scores: { score: 82, score_payload: { recommendation: "apply", fit_line: "Synthetic fit", reasons: ["unused".repeat(100)] } },
  liveness: { alive: false, linkedin_closed_signal: signal, history: "unused".repeat(100) },
};
const slim = () => {
  const { relevance_gate, list_metadata, liveness, posting_scores, ...rest } = raw;
  const projected: Record<string, unknown> = { ...rest, relevance_rule: relevance_gate.rule, list_stack: list_metadata.stack,
    experience: list_metadata.experience, alive: liveness.alive, linkedin_reposted_signal: null, linkedin_closed_signal: signal,
    posting_scores: { score: posting_scores.score, recommendation: "apply", fit_line: "Synthetic fit" } };
  delete projected.salary;
  delete projected.posting_extractions;
  return projected;
};

test("all list paths select only JSON keys used by the board", async () => {
  const selections: string[] = [];
  const db = createClient("https://database.example.test", "synthetic", { auth: { persistSession: false }, global: {
    fetch: async input => {
      selections.push(new URL(String(input)).searchParams.get("select") ?? "");
      return new Response("[]", { headers: { "content-type": "application/json" } });
    },
  } });
  const base = { filter: "all", availability: "all", limit: 100 } as const;
  const queries: JobListQuery[] = [base, { ...base, sort: "fit" }, { ...base, ids: [id] }, { ...base, filter: "applied", since: "2026-10-01T00:00:00Z" }];
  for (const query of queries) await selectSummaries(db, query);
  for (const selected of selections) {
    assert.ok(selected.includes("recommendation:score_payload->recommendation"), selected);
    assert.ok(selected.includes("fit_line:score_payload->fit_line"), selected);
    assert.ok(selected.includes("alive:liveness->alive"), selected);
    assert.ok(selected.includes("linkedin_closed_signal:liveness->linkedin_closed_signal"), selected);
    assert.ok(selected.includes("relevance_rule:relevance_gate->rule"), selected);
    assert.doesNotMatch(selected, /(?:^|[,()])(?:score_payload|liveness|relevance_gate|salary|posting_extractions)(?:[,()]|$)/);
  }
});

test("projected rows preserve card, filter, dedup and archive data", async () => {
  for (const overrides of [ {}, { relevance_filtered: true }, { posting_scores: null, alive: null, linkedin_closed_signal: null } ]) {
    const row = { ...slim(), ...overrides };
    const alternate = { id: "00000000-0000-4000-8000-000000000002", source: "greenhouse", posted_at: "2026-10-01T00:00:00Z" };
    const db = createClient("https://database.example.test", "synthetic", { auth: { persistSession: false }, global: {
      fetch: async () => new Response(JSON.stringify([row, { ...row, ...alternate }]), { headers: { "content-type": "application/json" } }),
    } });
    const jobs = await selectSummaries(db, { filter: "all", availability: "all", sort: "fit", limit: 100 });
    const old = { ...raw, ...overrides, ...(overrides.posting_scores === null ? { liveness: null } : {}) };
    const legacy = parseSummaryRows([old, { ...old, ...alternate }]).jobs;
    assert.deepEqual(JobListResponseSchema.parse({ jobs }), JobListResponseSchema.parse({ jobs: legacy }));
    const base: ViewOptions = { search: "", source: "", location: "", seniority: "", fit: "", statuses: [], availability: "all", sort: "fit" };
    for (const options of [base, { ...base, work_mode: "hybrid" as const }, { ...base, fit: "recommended" }, { ...base, search: "React", location: "israel" as const, statuses: ["applied" as const] }]) {
      const normalize = (rows: typeof jobs) => filterJobGroups(rows, options).map(({ job, alternates }) => ({
        job: JobListItemSchema.parse(job), alternates: alternates.map(row => JobListItemSchema.parse(row)),
      }));
      assert.deepEqual(normalize(jobs), normalize(legacy));
    }
    assert.equal(jobs[0].seniority, "Junior");
    assert.deepEqual(jobs[0].stack, ["React"]);
    assert.equal(jobs[0].status_reason, "Owner wording");
    assert.equal(filterJobGroups(jobs, base)[0].alternates.length, 1);
  }
});

test("browser list strips drawer metadata while accepting cached legacy summaries", () => {
  const old = { ...parseSummaryRows([raw]).jobs[0], salary: "Unused", description_available: true, seniority_origin: "title", extraction_state: "extracted" };
  const wire = JobListResponseSchema.parse({ jobs: [old] }).jobs[0];
  for (const field of ["salary", "description_available", "seniority_origin", "extraction_state"]) assert.ok(!(field in wire), field);
  assert.equal(wire.apply_url, old.apply_url);
  assert.equal(wire.fit_line, old.fit_line);
  assert.deepEqual(wire.linkedin_closed_signal, signal);
});

test("card markup is identical for legacy and slim browser rows", () => {
  const legacy = { ...parseSummaryRows([raw]).jobs[0], salary: "Unused", description_available: true, seniority_origin: "title", extraction_state: "extracted" };
  const wire = JobListResponseSchema.parse({ jobs: [legacy] }).jobs[0];
  const result = spawnSync(process.execPath, ["--import", "tsx", "tests/fixtures/card-payload.tsx"], {
    cwd: process.cwd(), input: JSON.stringify([legacy, wire]), encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  const [before, after] = JSON.parse(result.stdout);
  assert.equal(before, after);
});

test("detail by ID retains full score and drawer metadata", async () => {
  const previous = { fetch: globalThis.fetch, url: process.env.SUPABASE_URL, key: process.env.SUPABASE_SERVICE_ROLE_KEY };
  const score_payload = { employer_type: "direct", seniority_real: null, fit_score: 82, fit_tier: "good",
    recommendation: "apply", reasons: [], fit_line: "Synthetic fit", fit_line_evidence_ids: [], luna_status: "ok" };
  let selected = "";
  process.env.SUPABASE_URL = "https://database.example.test";
  process.env.SUPABASE_SERVICE_ROLE_KEY = "synthetic";
  globalThis.fetch = async input => {
    selected = new URL(String(input)).searchParams.get("select") ?? "";
    return new Response(JSON.stringify({ ...raw, raw_jd: "Synthetic full description",
      posting_scores: { score: 82, score_payload, reasons: [], labels: {}, brain: "synthetic", model: null, scorer_version: null, scored_at: "2026-10-07T00:00:00Z" } }),
      { headers: { "content-type": "application/json" } });
  };
  try {
    const detail = await getApiStore().getJob(id);
    assert.ok(detail);
    assert.deepEqual(detail.score_payload, score_payload);
    assert.equal(detail.salary, raw.salary);
    assert.equal(detail.description_available, true);
    assert.equal(detail.seniority_origin, "title");
    assert.equal(detail.extraction_state, "extracted");
    assert.equal(detail.raw_jd, "Synthetic full description");
    assert.ok(selected.includes("score_payload,scored_at"));
  } finally {
    globalThis.fetch = previous.fetch;
    for (const [name, value] of [["SUPABASE_URL", previous.url], ["SUPABASE_SERVICE_ROLE_KEY", previous.key]]) {
      if (value === undefined) delete process.env[name!]; else process.env[name!] = value;
    }
  }
});

test("every optional and required list field has an explicit database alias", () => {
  assert.deepEqual(Object.keys(BOARD_FIELD_ALIASES).sort(), Object.keys(JobListItemSchema.shape).sort());
});
