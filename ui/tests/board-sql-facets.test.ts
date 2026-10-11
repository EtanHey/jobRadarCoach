import assert from "node:assert/strict";
import { test } from "node:test";
import { createClient } from "@supabase/supabase-js";
import { makeGetJobs } from "../app/api/jobs/route";
import { selectSummaries, type ApiStore } from "../lib/server";
import { jobListRequestPath } from "../lib/job-board-state";

test("SQL facets travel through request, schema and RPC", async () => {
  const calls: Record<string, unknown>[] = [];
  const db = createClient("https://database.example.test", "synthetic", { global: { fetch: async (_url, init) => {
    calls.push(init?.body ? JSON.parse(String(init.body)) : {});
    return Response.json([]);
  } } });
  const handler = makeGetJobs({ listJobs: input => selectSummaries(db, input) } as ApiStore);
  const facets = { source: "synthetic & board", work_mode: "hybrid" as const, location: "israel" as const, seniority: "non-senior" };
  const path = jobListRequestPath({ filter: "all", availability: "all", limit: 1000, ...facets });
  assert.equal((await handler(new Request(`https://example.test${path}`))).status, 200);
  for (const [name, value] of Object.entries(facets)) assert.equal(calls[0][name], value);
  // Explicit work mode overrides legacy remote, as in the shared TS filter.
  const legacy = jobListRequestPath({ filter: "all", availability: "all", limit: 1000, remote: false });
  assert.equal((await handler(new Request(`https://example.test${legacy}`))).status, 200);
  assert.equal(calls[1].remote, false);
  for (const query of ["work_mode=maybe", "location=unknown", "seniority=CEO", "remote=maybe", "since=2026-10-01T00:00:00Z&source=synthetic", "ids=00000000-0000-0000-0000-000000000001&availability=all&source=synthetic"]) {
    assert.equal((await handler(new Request(`https://example.test/api/jobs?filter=all&${query}`))).status, 400, query);
  }
});

test("source vocabulary request is independent of narrowing facets", async () => {
  const calls: { path: string; input: unknown }[] = [];
  const db = createClient("https://database.example.test", "synthetic", { global: { fetch: async (url, init) => {
    calls.push({ path: new URL(String(url)).pathname, input: JSON.parse(String(init?.body)) });
    return Response.json(["fixture-a", "fixture-b"]);
  } } });
  const { makeGetSources } = await import("../app/api/jobs/sources/route");
  const { selectSources } = await import("../lib/server");
  const handler = makeGetSources({ listSources: input => selectSources(db, input) });
  const reply = await handler(new Request("https://example.test/api/jobs/sources?filter=seen&availability=inactive"));
  assert.equal(reply.status, 200);
  assert.deepEqual(await reply.json(), { sources: ["fixture-a", "fixture-b"] });
  assert.deepEqual(calls, [{ path: "/rest/v1/rpc/board_sources", input: { filter: "seen", availability: "inactive" } }]);
  for (const query of ["source=fixture-a", "work_mode=remote", "location=israel", "seniority=Senior", "fit=good", "statuses=applied", "sort=fit", "found_within=24h", "limit=1000", "filter=invalid", "availability=invalid"]) {
    assert.equal((await handler(new Request(`https://example.test/api/jobs/sources?${query}`))).status, 400, query);
  }
  assert.equal(calls.length, 1);
  const unavailable = makeGetSources({ listSources: async () => { throw new Error("private database details"); } });
  assert.equal((await unavailable(new Request("https://example.test/api/jobs/sources"))).status, 500);
});
