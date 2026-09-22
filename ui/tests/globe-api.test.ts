import assert from "node:assert/strict";
import { test } from "node:test";
import { makeGetGlobe } from "../app/api/jobs/globe/route";
import { GlobeQuerySchema } from "../lib/globe-contract";
import { getGlobeStore, globeResponse, type GlobeStore } from "../lib/globe-server";
import { filterJobs } from "../lib/job-filters";
import { classifyAuthPath } from "../lib/auth/boundary";
import type { JobSummary } from "../lib/contracts";

const jobs: JobSummary[] = Array.from({ length: 1007 }, (_, n) => ({
  id: `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`,
  title: n % 2 ? "Engineer" : "Designer", company: "Example", source: "fixture",
  location: n % 2 ? "Tel Aviv, Israel" : "New York, NY", remote: n % 2 === 1,
  seniority: "Senior", stack: ["React"], salary: null, url: "https://example.test/job", apply_url: null,
  posted_at: null, first_seen_at: "2026-09-22T00:00:00Z", last_seen_at: "2026-09-22T00:00:00Z",
  status: "new", status_reason: null, score: n % 2 ? 80 : null,
  fit_line: null, recommendation: "review", alive: true, experience: null,
  description_available: true, seniority_origin: "title", extraction_state: "not-extracted",
}));
const point = (id: string) => ({ posting_id: id, lat: 32, lng: 34, precision: "hq", source: "https://example.test/hq | nominatim:osm:relation:1", resolved_at: "2026-09-22T00:00:00Z" });
const store: GlobeStore = {
  snapshot: async () => ({ jobs, geo: jobs.filter((j) => Number(j.id.slice(-12)) % 3).map(j => point(j.id)) }),
};
test("complete snapshot counts exceed provider row caps; exact dashboard predicates", async () => {
  for (const raw of [{}, {location:"israel"}, { search:"react", fit:"good", seniority:"Senior" }, { location:"other" }, { remote:"false", min_score:"70" }]) {
    const query = GlobeQuerySchema.parse(raw);
    const response = await globeResponse(store, query);
    const expected = filterJobs(jobs, query).filter(j => (query.remote === undefined || j.remote === query.remote) && (query.min_score === undefined || (j.score !== null && j.score >= query.min_score)));
    assert.deepEqual(response.jobs, expected);
    assert.equal(response.total_count, expected.length);
    assert.equal(response.resolved_count, expected.filter(j => Number(j.id.slice(-12)) % 3).length);
    assert.equal(response.unresolved_count + response.resolved_count, expected.length);
    assert.ok(response.points.every(p => p.precision === "hq"));
  }
});
test("invalid, unrelated and duplicate geo rows do not create dots or negative counts", async () => {
  const response = await globeResponse({ snapshot: async () => ({ jobs: [jobs[0]], geo: [
    {...point(jobs[0].id), lat:91}, {...point(jobs[0].id), lng:Infinity}, point(jobs[1].id), point(jobs[0].id), point(jobs[0].id),
  ] }) }, GlobeQuerySchema.parse({}));
  assert.equal(response.points.length, 1); assert.equal(response.unresolved_count, 0);
});
test("route is private, rejects pagination/invalid filters, preserves no-store, rejects duplicate snapshot rows", async () => {
  assert.equal(classifyAuthPath("/api/jobs/globe"), "private");
  const get = makeGetGlobe(store);
  for (const query of ["limit=10", "remote=maybe", "min_score=101", "statuses=new"]) {
    assert.equal((await get(new Request(`https://example.test/api/jobs/globe?${query}`))).status, 400);
  }
  const response = await get(new Request("https://example.test/api/jobs/globe?location=israel"));
  assert.equal(response.status, 200); assert.match(response.headers.get("cache-control")!, /no-store/);
  const bad = makeGetGlobe({ ...store, snapshot: async () => ({ jobs: [jobs[0], jobs[0]], geo: [] }) });
  assert.equal((await bad(new Request("https://example.test/api/jobs/globe"))).status, 503);
});

test("empty matching jobs still reject a missing geo migration", async () => {
  const db = { rpc: async () => ({ data: null, error: { code: "PGRST202" } }), from: () => { throw new Error("Must not bypass snapshot for empty jobs"); } };
  const get = makeGetGlobe(getGlobeStore(db as unknown as Parameters<typeof getGlobeStore>[0]));
  assert.equal((await get(new Request("https://example.test/api/jobs/globe"))).status, 503);
});

test("HQ source must carry HTTPS evidence and a provider object", async () => {
  const { GlobePointSchema } = await import("../lib/globe-contract");
  assert.equal(GlobePointSchema.safeParse({ ...point(jobs[0].id), source: "guess" }).success, false);
});


test("one RPC fixes deletion/reordering and new-for-me cutoff for the entire request", async () => {
  const raw = jobs.slice(0, 4).map(j => ({ ...j, raw_jd: null, liveness: null,
    posting_status: {status: "new", reason: null}, posting_scores: null, posting_extractions: null }));
  let calls = 0;
  const db = { rpc: async (name: string, args: unknown) => {
    assert.equal(++calls, 1); assert.equal(name, "get_globe_snapshot");
    assert.deepEqual(args, { filter: "new-for-me", availability: "active" });
    const captured = structuredClone(raw);
    raw.shift(); raw.reverse(); // Later deletion/reordering cannot shift a second page.
    return { data: {jobs: captured, geo: []}, error: null };
  }, from: () => { throw new Error("Must not reread visits or fetch offset pages"); } };
  const result = await globeResponse(getGlobeStore(db as unknown as Parameters<typeof getGlobeStore>[0]), GlobeQuerySchema.parse({filter:"new-for-me"}));
  assert.deepEqual(new Set(result.jobs.map(j => j.id)), new Set(jobs.slice(0,4).map(j => j.id)));
  assert.equal(result.total_count, 4); assert.equal(calls, 1);
});
