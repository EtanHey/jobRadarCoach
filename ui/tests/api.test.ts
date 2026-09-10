import assert from "node:assert/strict";
import { test } from "node:test";

import { makeGetJob } from "../app/api/jobs/[id]/route";
import { makePatchStatus } from "../app/api/jobs/[id]/status/route";
import { GET as getJobs, makeGetJobs } from "../app/api/jobs/route";
import { makeGetProfile, makePatchProfile } from "../app/api/profile/route";
import { JobIdSchema, JobStatusSchema, type JobDetail, type JobSummary } from "../lib/contracts";
import { HttpError } from "../lib/http";
import type { ApiStore } from "../lib/server";
import { parseSummaryRows } from "../lib/server";

const ID = "0199d9c3-a742-7000-8000-000000000001";
const summary: JobSummary = {
  id: ID,
  title: "Backend Engineer",
  company: "Public Example",
  source: "linkedin",
  last_seen_at: "2026-09-08T10:00:00Z",
  experience: null, description_available: true,
  seniority_origin: "unknown",
  extraction_state: "not-extracted",
  location: null,
  remote: null,
  seniority: null,
  stack: [],
  salary: null,
  url: "https://example.test/job",
  apply_url: null,
  posted_at: null,
  first_seen_at: "2026-09-08T10:00:00Z",
  status: "new",
  status_reason: null,
  score: null,
  fit_line: null,
  recommendation: null,
};
const detail: JobDetail = {
  ...summary,
  raw_jd: "Full public description",
  reasons: [],
  score_payload: null,
  brain: null,
  scored_at: null,
};

const profile = {
  "candidate.roles_wanted": ["Engineer"],
  "candidate.stacks": ["TypeScript"],
  "candidate.seniority": ["Senior"],
  "candidate.open_to.geographies": ["Israel"],
  "candidate.remote": null,
  "candidate.salary_floor": null,
  "candidate.red_flag_words": [],
  "candidate.preferences.free_text": null,
  "runtime.brain": "codex" as const,
};

function store(overrides: Partial<ApiStore> = {}): ApiStore {
  return {
    listJobs: () => Promise.resolve([summary]),
    getJob: () => Promise.resolve(detail),
    setStatus: (input) => Promise.resolve({
      status: input.status,
      reason: input.status === "rejected" || input.status === "not_relevant" ? input.reason ?? null : null,
    }),
    getProfile: () => Promise.resolve(profile),
    updateProfile: () => Promise.resolve(profile),
    ...overrides,
  };
}


function mutation(path: string, body: unknown, headers: HeadersInit = {}): Request {
  return new Request(`http://localhost${path}`, {
    method: "PATCH",
    headers: { "content-type": "application/json", "x-job-radar-status-version": "2", ...headers },
    body: JSON.stringify(body),
  });
}

test("job list exposes a bounded nullable unscored contract without raw JD", async () => {
  let received: unknown;
  const response = await makeGetJobs(
    store({
      listJobs: (query) => {
        received = query;
        return Promise.resolve([summary]);
      },
    }),
  )(new Request("http://localhost/api/jobs?filter=all&limit=250"));

  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(received, { filter: "all", limit: 250 });
  assert.deepEqual(body, { jobs: [summary] });
  assert.equal("raw_jd" in body.jobs[0], false);
  assert.match(response.headers.get("x-request-id") ?? "", /^[0-9a-f-]{36}$/);
  assert.match(response.headers.get("server-timing") ?? "", /^app;dur=\d+$/);
});

test("PostgreSQL UUID forms are not rejected by stricter RFC version and variant rules", () => {
  const postgresUuid = "123e4567-e89b-02d3-0456-426614174000";
  assert.equal(JobIdSchema.safeParse(postgresUuid).success, true);

  const raw = {
    source: "fixture", last_seen_at: summary.last_seen_at, raw_jd: null,
    posting_extractions: null, id: postgresUuid, title: "Engineer", company: "Acme",
    location: null, remote: null, seniority: null, stack: [], salary: null,
    url: "https://example.com/job", apply_url: null, posted_at: null, first_seen_at: summary.first_seen_at,
    posting_status: null, posting_scores: null,
  };
  const result = parseSummaryRows([raw]);
  assert.equal(result.invalidRowCount, 0);
  assert.equal(result.jobs.length, 1);
});

test("a non-GUID row fails visibly instead of being silently omitted", () => {
  const raw = {
    source: summary.source, last_seen_at: summary.last_seen_at, raw_jd: "3+ years of backend engineering experience",
    posting_extractions: null, id: summary.id, title: summary.title, company: summary.company,
    location: summary.location, remote: summary.remote, seniority: summary.seniority, stack: summary.stack,
    salary: summary.salary, url: summary.url, apply_url: summary.apply_url, posted_at: summary.posted_at,
    first_seen_at: summary.first_seen_at, posting_status: null, posting_scores: null,
  };
  assert.throws(
    () => parseSummaryRows([{ ...raw, id: "synthetic-non-uuid" }, raw]),
    (error: unknown) => error instanceof HttpError && error.category === "invalid_response",
  );
});

test("frozen status filters are direct values rather than a second status parameter", async () => {
  let received: unknown;
  const handler = makeGetJobs(store({ listJobs: (query) => { received = query; return Promise.resolve([]); } }));
  assert.equal((await handler(new Request("http://localhost/api/jobs?filter=seen"))).status, 200);
  assert.deepEqual(received, { filter: "seen", limit: 50 });
  assert.equal(
    (await handler(new Request("http://localhost/api/jobs?filter=status&status=seen"))).status,
    400,
  );
});

test("invalid and reasonless rejected statuses fail before the store", async () => {
  let calls = 0;
  const handler = makePatchStatus(store({ setStatus: () => { calls += 1; return Promise.reject(new Error()); } }));
  for (const body of [{ status: "deleted" }, { status: "rejected", reason: "  " }]) {
    const response = await handler(mutation(`/api/jobs/${ID}/status`, body), {
      params: Promise.resolve({ id: ID }),
    });
    assert.equal(response.status, 400);
  }
  assert.equal(calls, 0);
});

test("mutations require JSON and reject a supplied foreign Origin", async () => {
  const handler = makePatchStatus(store());
  const wrongType = new Request(`http://localhost/api/jobs/${ID}/status`, {
    method: "PATCH",
    body: "{}",
  });
  assert.equal((await handler(wrongType, { params: Promise.resolve({ id: ID }) })).status, 415);
  const foreign = mutation(`/api/jobs/${ID}/status`, { status: "worth_checking" }, {
    origin: "https://foreign.example",
  });
  assert.equal((await handler(foreign, { params: Promise.resolve({ id: ID }) })).status, 403);
});

test("malformed job UUIDs are rejected for reads and writes", async () => {
  const context = { params: Promise.resolve({ id: "not-a-uuid" }) };
  assert.equal(
    (await makeGetJob(store())(new Request("http://localhost/api/jobs/not-a-uuid"), context)).status,
    400,
  );
  assert.equal(
    (await makePatchStatus(store())(mutation("/api/jobs/not-a-uuid/status", { status: "worth_checking" }), context)).status,
    400,
  );
});

test("profile input rejects unsupported brains and private fields", async () => {
  const handler = makePatchProfile(store());
  assert.equal(
    (await handler(mutation("/api/profile", { field: "runtime.brain", value: "claude" }))).status,
    400,
  );
  assert.equal(
    (await handler(mutation("/api/profile", { field: "candidate.connectors", value: ["private"] }))).status,
    400,
  );
});

test("successful detail/status/profile responses honor their public shapes", async () => {
  const detailResponse = await makeGetJob(store())(
    new Request(`http://localhost/api/jobs/${ID}`),
    { params: Promise.resolve({ id: ID }) },
  );
  assert.deepEqual(await detailResponse.json(), { job: detail });
  const statusResponse = await makePatchStatus(store())(
    mutation(`/api/jobs/${ID}/status`, { status: "rejected", reason: "  Not aligned  " }),
    { params: Promise.resolve({ id: ID }) },
  );
  assert.deepEqual(await statusResponse.json(), { status: "rejected", reason: "  Not aligned  " });
  const profileResponse = await makeGetProfile(store())();
  assert.deepEqual(await profileResponse.json(), {
    profile,
  });
});

test("detail GET is read-only and seen is an explicit status mutation", async () => {
  let statusCalls = 0;
  const readonly = store({ setStatus: () => { statusCalls += 1; return Promise.resolve({ status: "seen", reason: null }); } });
  await makeGetJob(readonly)(new Request(`http://localhost/api/jobs/${ID}`), {
    params: Promise.resolve({ id: ID }),
  });
  assert.equal(statusCalls, 0);

  let received: unknown;
  const response = await makePatchStatus(store({
    setStatus: (input) => { received = input; return Promise.resolve({ status: "worth_checking", reason: null }); },
  }))(mutation(`/api/jobs/${ID}/status`, { status: "seen" }), {
    params: Promise.resolve({ id: ID }),
  });
  assert.deepEqual(received, { posting_id: ID, status: "seen" });
  assert.deepEqual(await response.json(), { status: "worth_checking", reason: null });
});

test("non-http external URLs fail the output boundary", async () => {
  const response = await makeGetJobs(store({
    listJobs: () => Promise.resolve([{ ...summary, url: "data:text/plain,not-http" }]),
  }))(new Request("http://localhost/api/jobs"));
  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { error: "Database returned an invalid response." });
});

test("unexpected failures never expose database internals", async () => {
  const response = await makeGetJobs(
    store({ listJobs: () => Promise.reject(new Error("password=secret relation posting_scores")) }),
  )(new Request("http://localhost/api/jobs"));
  assert.equal(response.status, 500);
  const text = await response.text();
  assert.match(text, /Unexpected server error/);
  assert.doesNotMatch(text, /secret|posting_scores/);
});

test("missing server configuration is returned as a safe unavailable response", async () => {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  delete process.env.SUPABASE_URL;
  delete process.env.SUPABASE_SERVICE_ROLE_KEY;
  try {
    const response = await getJobs(new Request("http://localhost/api/jobs"));
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), { error: "Server database configuration is unavailable." });
  } finally {
    if (url === undefined) delete process.env.SUPABASE_URL;
    else process.env.SUPABASE_URL = url;
    if (key === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY;
    else process.env.SUPABASE_SERVICE_ROLE_KEY = key;
  }
});


test("every pipeline state filters and saves, preserving rejection wording", async () => {
  for (const status of JobStatusSchema.options) {
    const reason = status === "rejected" || status === "not_relevant" ? "  Exact owner wording  " : undefined;
    const response = await makePatchStatus(store())(mutation(`/api/jobs/${ID}/status`, {status, ...(reason ? {reason} : {})}), {params:Promise.resolve({id:ID})});
    assert.equal(response.status, 200, status);
    assert.deepEqual(await response.json(), {status,reason:reason ?? null});
    const list = await makeGetJobs(store())(new Request(`http://localhost/api/jobs?filter=${status}`));
    assert.equal(list.status, 200, status);
  }
});
test("stale clients cannot reinterpret their old rejection action", async () => {
  let calls = 0;
  const handler = makePatchStatus(store({setStatus: async () => {calls++; return {status:"rejected",reason:"old"};}}));
  const response = await handler(mutation(`/api/jobs/${ID}/status`, {status:"rejected",reason:"old"}, {"x-job-radar-status-version":"1"}), {params:Promise.resolve({id:ID})});
  assert.equal(response.status,409);
  assert.equal(calls,0);
});
test("automatic seen intent is distinct from explicit backward edits", async () => {
  const inputs: unknown[] = [];
  const handler = makePatchStatus(store({setStatus: async input => {inputs.push(input); return {status:"seen",reason:null};}}));
  for (const body of [{status:"seen",automatic:true},{status:"seen"}]) {
    assert.equal((await handler(mutation(`/api/jobs/${ID}/status`,body),{params:Promise.resolve({id:ID})})).status,200);
  }
  assert.deepEqual(inputs,[{posting_id:ID,status:"seen",automatic:true},{posting_id:ID,status:"seen"}]);
});
