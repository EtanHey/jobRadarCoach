import assert from "node:assert/strict";
import { test } from "node:test";

import { makeGetJob } from "../app/api/jobs/[id]/route";
import { makePatchStatus } from "../app/api/jobs/[id]/status/route";
import { GET as getJobs, makeGetJobs } from "../app/api/jobs/route";
import { makeGetProfile, makePatchProfile } from "../app/api/profile/route";
import { type JobDetail, type JobSummary } from "../lib/contracts";
import type { ApiStore } from "../lib/server";

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
      reason: input.status === "rejected" ? input.reason : null,
    }),
    getProfile: () => Promise.resolve(profile),
    updateProfile: () => Promise.resolve(profile),
    ...overrides,
  };
}


function mutation(path: string, body: unknown, headers: HeadersInit = {}): Request {
  return new Request(`http://localhost${path}`, {
    method: "PATCH",
    headers: { "content-type": "application/json", ...headers },
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
  const foreign = mutation(`/api/jobs/${ID}/status`, { status: "saved" }, {
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
    (await makePatchStatus(store())(mutation("/api/jobs/not-a-uuid/status", { status: "saved" }), context)).status,
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
  assert.deepEqual(await statusResponse.json(), { status: "rejected", reason: "Not aligned" });
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
    setStatus: (input) => { received = input; return Promise.resolve({ status: "saved", reason: null }); },
  }))(mutation(`/api/jobs/${ID}/status`, { status: "seen" }), {
    params: Promise.resolve({ id: ID }),
  });
  assert.deepEqual(received, { posting_id: ID, status: "seen" });
  assert.deepEqual(await response.json(), { status: "saved", reason: null });
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
