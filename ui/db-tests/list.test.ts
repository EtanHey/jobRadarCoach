import assert from "node:assert/strict";
import { test } from "node:test";
import { createClient } from "@supabase/supabase-js";
import corpus from "./fixtures/metadata-corpus.json";
import { experiencePhrase, technologyMentions } from "../lib/job-metadata";
import { getApiStore, selectSummaries } from "../lib/server";

const ids = [1, 2, 3].map(n => `00000000-0000-0000-0000-00000002400${n}`);
const responses: Record<string, unknown>[][] = [];
const nativeFetch = globalThis.fetch;
const fixtureFetch: typeof fetch = (input, init) => {
    const url = new URL(String(input));
    url.pathname = url.pathname.replace(/^\/rest\/v1/, "");
    const headers = new Headers(init?.headers);
    headers.delete("authorization");
    return nativeFetch(`${process.env.JOBRADAR_TEST_REST_URL}${url.pathname}${url.search}`, {...init, headers}).then(async response => {
      if (!response.ok) console.error(response.status, await response.clone().text());
      if (url.pathname === "/postings") responses.push(await response.clone().json());
      return response;
    });
};
const rest = createClient("http://fixture.invalid", "synthetic-test-key", {
  auth: {persistSession: false}, global: {fetch: fixtureFetch},
});

test("DB-backed default/status/IDs lists preserve metadata and omit descriptions", async () => {
  const query = {filter: "new-for-me", availability: "active", limit: 50} as const;
  const rows = await selectSummaries(rest, query);
  assert.deepEqual(rows.map(row => row.id), [ids[0], ids[2]]);
  assert.equal(rows[0].experience, "3+ years of backend engineering experience");
  assert.deepEqual(rows[0].stack, ["Python", "Docker"]);
  assert.equal(rows[0].description_available, true);
  assert.equal(rows[1].description_available, false);
  assert.deepEqual(rows[1].stack, ["Extracted"]);
  assert.deepEqual((await selectSummaries(rest, {...query, filter: "seen", availability: "all"})).map(row => row.id), [ids[1]]);
  assert.deepEqual((await selectSummaries(rest, {filter: "all", availability: "all", limit: 50, ids: [ids[1]]})).map(row => row.id), [ids[1]]);
  assert.deepEqual((await selectSummaries(rest, {...query, filter: "all", availability: "all", limit: 1})).map(row => row.id), [ids[1]]);
  assert.ok(responses.length >= 4);
  for (const rows of responses) for (const row of rows) assert.equal("raw_jd" in row, false);
});


test("SQL metadata matches the current UI heuristics for the synthetic corpus", async () => {
  for (const description of corpus) {
    const {data, error} = await rest.rpc("posting_list_metadata", {description});
    assert.equal(error, null);
    assert.deepEqual(data, {stack: technologyMentions(description), experience: experiencePhrase(description), description_available: Boolean(description?.trim())}, JSON.stringify(description));
  }
});

test("globe summaries also omit descriptions", async () => {
  const {data, error} = await rest.rpc("get_globe_snapshot", {filter: "all", availability: "all"});
  assert.equal(error, null);
  assert.equal(data.jobs.length, 3);
  for (const row of data.jobs) assert.equal("raw_jd" in row, false);
});


test("the real detail store retains the full description and identical summary metadata", async () => {
  const previousUrl = process.env.SUPABASE_URL, previousKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  process.env.SUPABASE_URL = "http://fixture.invalid";
  process.env.SUPABASE_SERVICE_ROLE_KEY = "synthetic-test-key";
  globalThis.fetch = fixtureFetch;
  try {
    const detail = await getApiStore().getJob(ids[0]);
    assert.equal(detail?.raw_jd, "Requirements: 3+ years of backend engineering experience with Python and Docker.");
    assert.equal(detail?.experience, "3+ years of backend engineering experience");
    assert.deepEqual(detail?.stack, ["Python", "Docker"]);
  } finally {
    globalThis.fetch = nativeFetch;
    if (previousUrl === undefined) delete process.env.SUPABASE_URL; else process.env.SUPABASE_URL = previousUrl;
    if (previousKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY; else process.env.SUPABASE_SERVICE_ROLE_KEY = previousKey;
  }
});
