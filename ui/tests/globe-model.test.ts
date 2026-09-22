import assert from "node:assert/strict";
import { test } from "node:test";
import { clusterPoints, clusterScore, globePoints, pointLabel, scoreColor, thinPoints, type PostingPoint } from "../lib/globe-model";
import { JobSummarySchema } from "../lib/contracts";
const job = (n: number) => JobSummarySchema.parse({ id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, title: "Engineer", company: "Example", source: "test", last_seen_at: "2026-09-22", experience: null, description_available: false, seniority_origin: "unknown", extraction_state: "not-extracted", location: null, remote: null, seniority: null, stack: [], salary: null, url: "https://example.test", apply_url: null, posted_at: null, first_seen_at: "2026-09-22", status: "new", status_reason: null, score: null, fit_line: null, recommendation: null });
const geo = (n: number): PostingPoint => ({ posting_id: job(n).id, lat: 32, lng: 35, precision: "city", source: "test fixture", resolved_at: "2026-09-22T00:00:00Z" });
test("only filtered jobs become dots; duplicate postings target their representative row", () => {
  const points = globePoints([{ job: job(1), alternates: [job(2)] }], [geo(1), geo(2), geo(3)]);
  assert.equal(points.length, 2);
  assert.deepEqual(points.map(p => p.rowId), [job(1).id, job(1).id]);
  assert.equal(globePoints([{ job: job(1), alternates: [] }], [{ ...geo(1), lat: NaN }]).length, 0);
  assert.equal(globePoints([{ job: job(1), alternates: [] }], [{ ...geo(1), lng: 181 }]).length, 0);
});
test("large datasets stay bounded, preserving selection and actual coordinates", () => {
  const points = Array.from({ length: 10001 }, (_, i) => ({ ...geo(i), job: job(i), rowId: job(i).id }));
  const sampled = thinPoints(points, job(9999).id);
  assert.ok(sampled.length <= 5000);
  assert.ok(sampled.includes(points[9999]));
  assert.ok(sampled.every(p => points.includes(p)));
});
test("HQ and approximate centroids never claim an office; null is not score zero", () => {
  const point = { ...geo(1), job: job(1), rowId: job(1).id };
  assert.match(pointLabel({ ...point, precision: "hq" }), /not the job location/);
  assert.match(pointLabel(point), /Approximate city/);
  assert.notDeepEqual(scoreColor(0), scoreColor(null));
});

test("colliding real coordinates expose every member including duplicate alternates", () => {
  const points = globePoints([{job: job(1), alternates: [job(2)]}, {job: job(3), alternates: []}, {job: job(4), alternates: []}], [geo(1), geo(2), {...geo(3), lng: 35.01}, {...geo(4), lng: 80}]);
  const groups = clusterPoints(points, point => ({x: point.lng * 10, y: point.lat * 10}));
  assert.deepEqual(groups.map(group => group.members.map(point => point.posting_id)), [[job(1).id, job(2).id, job(3).id], [job(4).id]]);
  assert.ok(groups.every(group => points.includes(group.anchor)));
  assert.equal(clusterPoints(points, () => null).length, 0);
  assert.equal(clusterScore(groups[0]), null);
  points[1].job.score = 85;
  assert.equal(clusterScore(groups[0]), 85);
  assert.equal(thinPoints(points, job(2).id, 2)[0].posting_id, job(2).id);
});
