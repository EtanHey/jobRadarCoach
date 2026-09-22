import assert from "node:assert/strict";
import { test } from "node:test";
import { retainGlobeCohort } from "../lib/globe-cohort";
import { filterJobGroups } from "../lib/job-filters";
import { globePoints } from "../lib/globe-model";
import { JobSummarySchema } from "../lib/contracts";
import type { GlobeResponse } from "../lib/globe-contract";
import { defaultBoardPreferences } from "../lib/job-board-preferences";
const job = (n: number) => JobSummarySchema.parse({ id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, title: "Frontend Engineer", company: `Example ${n}`, source: "test", last_seen_at: "2026-09-22", experience: null, description_available: false, seniority_origin: "title", extraction_state: "not-extracted", location: "Tel Aviv, Israel", remote: n % 2 === 0, seniority: "Junior", stack: ["React"], salary: null, url: "https://example.test", apply_url: null, posted_at: null, first_seen_at: "2026-09-22", status: "new", status_reason: null, score: 80, fit_line: null, recommendation: "apply" });
const response = (ids: number[], mapped = ids): GlobeResponse => ({ jobs: ids.map(job), points: mapped.map(n => ({ posting_id: job(n).id, lat: 32, lng: 35, precision: "city", source: "fixture", resolved_at: "2026-09-22T00:00:00Z" })), total_count: ids.length, resolved_count: mapped.length, unresolved_count: ids.length - mapped.length, attribution: "fixture" });
test("new-for-me preserves seen cohort coordinates but respects explicit geo removal in incoming jobs", () => {
  const retained = retainGlobeCohort(response([1, 2]), response([2, 3], [3]));
  assert.deepEqual(retained.jobs.map(j => j.id), [1, 2, 3].map(n => job(n).id));
  assert.deepEqual(new Set(retained.points.map(p => p.posting_id)), new Set([1, 3].map(n => job(n).id)));
  assert.equal(retained.unresolved_count, 1);
});
test("counts cover a full set beyond 1000 and filters drive rail and dots together", () => {
  const data = response(Array.from({ length: 1200 }, (_, i) => i), Array.from({ length: 1100 }, (_, i) => i));
  const view = { ...defaultBoardPreferences().view, location: "israel" as const, seniority: "Junior", remote: true, search: "React" };
  const groups = filterJobGroups(data.jobs, view);
  const points = globePoints(groups, data.points);
  assert.equal(groups.length, 600); assert.equal(points.length, 550);
  assert.equal(groups.length - points.length, 50);
  assert.equal(filterJobGroups(data.jobs, { ...view, location: "united-states" }).length, 0);
  assert.equal(filterJobGroups(data.jobs, { ...view, remote: false }).length, 600);
});
