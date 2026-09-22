import assert from "node:assert/strict";
import { test } from "node:test";
import { JobSummarySchema } from "../lib/contracts";
import { countGlobeRoles, partitionGlobeGroups, viewportPostingIds } from "../lib/globe-viewport";
import type { GlobePoint } from "../lib/globe-model";
const job = (n: number) => JobSummarySchema.parse({ id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, title: "Engineer", company: "Example", source: "test", last_seen_at: "2026-09-22", experience: null, description_available: false, seniority_origin: "unknown", extraction_state: "not-extracted", location: null, remote: null, seniority: null, stack: [], salary: null, url: "https://example.test", apply_url: null, posted_at: null, first_seen_at: "2026-09-22", status: "new", status_reason: null, score: null, fit_line: null, recommendation: null });
const point = (n: number): GlobePoint => ({ posting_id: job(n).id, job: job(n), rowId: job(n).id, lng: 35, lat: 32, precision: "city", source: "test", resolved_at: "2026-09-22" });
test("viewport uses actual pixel bounds, front-face round trip and current availability", () => {
  const points = Array.from({length:9}, (_,n) => point(n));
  points[7].job.alive = false;
  const screens = [{x:50,y:40},{x:-1,y:40},{x:101,y:40},{x:50,y:-1},{x:50,y:81},{x:NaN,y:40},{x:1,y:1},{x:50,y:40},{x:100,y:80}];
  assert.deepEqual(viewportPostingIds(points, 100, 80, p => screens[points.indexOf(p)], p => p.x === 1 ? {lng:-145,lat:-32} : {lng:35,lat:32}), [points[0].posting_id,points[8].posting_id]);
  assert.deepEqual(viewportPostingIds(points, 0, 80, () => {throw new Error("hidden canvas cannot project");}, () => ({lng:35,lat:32})), []);
});
test("round trip handles antimeridian wrapping, nonfinite and mismatched latitude", () => {
  const p={...point(1),lng:180};
  assert.deepEqual(viewportPostingIds([p],100,80,()=>({x:50,y:40}),()=>({lng:-180,lat:32})),[p.posting_id]);
  for (const back of [{lng:NaN,lat:32},{lng:180,lat:NaN},{lng:180,lat:33}]) assert.deepEqual(viewportPostingIds([p],100,80,()=>({x:50,y:40}),()=>back),[]);
});
test("partition preserves sorted group identities, counts, alternates and unavailable/unresolved rows", () => {
  const groups=Array.from({length:5},(_,n)=>({job:job(n),alternates:n===3?[job(9)]:[]}));
  groups[1].job.alive=false;
  const result=partitionGlobeGroups(groups,[job(3).id,job(1).id,job(9).id,job(0).id,job(99).id]);
  assert.deepEqual(result.visible,[groups[0],groups[3]]);assert.deepEqual(result.outside,[groups[1],groups[2],groups[4]]);
  assert.equal(new Set([...result.visible,...result.outside]).size,groups.length);
  assert.deepEqual(partitionGlobeGroups(groups,[job(9).id]).visible,[groups[3]],"visible alternate lifts its single existing group");
  assert.deepEqual(partitionGlobeGroups(groups,[]).outside,groups);
  assert.deepEqual(partitionGlobeGroups(groups.slice(0,2),[job(9).id]).visible,[],"stale viewport IDs cannot restore filtered roles");
});
test("globe counts use deduplicated roles across mapped, unmapped and visible sections", () => {
  const groups=[{job:job(1),alternates:[job(2)]},{job:job(3),alternates:[]},{job:job(4),alternates:[]}];
  groups[1].job.alive=false;
  const counts=countGlobeRoles(groups,[point(2),point(3)]);
  assert.deepEqual(counts,{total:3,mapped:2,unmapped:1});
  assert.equal(counts.mapped+counts.unmapped,counts.total);
  assert.deepEqual(partitionGlobeGroups(groups,[job(2).id]).visible,[groups[0]]);
});
