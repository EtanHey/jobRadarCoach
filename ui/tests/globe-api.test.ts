import assert from "node:assert/strict";
import { test } from "node:test";
import { makeGetGlobe } from "../app/api/jobs/globe/route";
import { GlobeQuerySchema } from "../lib/globe-contract";
import { globeResponse, type GlobeStore } from "../lib/globe-server";
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
const point = (id: string) => ({ posting_id: id, lat: 32, lng: 34, precision: "hq", source: "https://example.test/hq", resolved_at: "2026-09-22T00:00:00Z" });
const store: GlobeStore = {
  page: async (_, offset) => jobs.slice(offset, offset + 137), // Lower provider row cap, >1000 total.
  geo: async (ids) => ids.filter((id) => Number(id.slice(-12)) % 3).map(point),
};
test("complete filtered counts cross page and provider caps; exact dashboard predicates", async () => {
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
  const response = await globeResponse({ page: async (_, offset) => offset ? [] : [jobs[0]], geo: async () => [
    {...point(jobs[0].id), lat:91}, {...point(jobs[0].id), lng:Infinity}, point(jobs[1].id), point(jobs[0].id), point(jobs[0].id),
  ] }, GlobeQuerySchema.parse({}));
  assert.equal(response.points.length, 1); assert.equal(response.unresolved_count, 0);
});
test("route is private, rejects pagination/invalid filters, preserves no-store, fails on changing pages", async () => {
  assert.equal(classifyAuthPath("/api/jobs/globe"), "private");
  const get = makeGetGlobe(store);
  for (const query of ["limit=10", "remote=maybe", "min_score=101", "statuses=new"]) {
    assert.equal((await get(new Request(`https://example.test/api/jobs/globe?${query}`))).status, 400);
  }
  const response = await get(new Request("https://example.test/api/jobs/globe?location=israel"));
  assert.equal(response.status, 200); assert.match(response.headers.get("cache-control")!, /no-store/);
  const bad = makeGetGlobe({ ...store, page: async () => [jobs[0]] });
  assert.equal((await bad(new Request("https://example.test/api/jobs/globe"))).status, 503);
});
