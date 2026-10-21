import assert from "node:assert/strict";
import { test } from "node:test";
import { createClient } from "@supabase/supabase-js";
import { withVacancyIdentity } from "../lib/vacancy-server";
import { GlobeJobSchema } from "../lib/globe-contract";
import { getNewRolesStore } from "../lib/new-roles-server";
import { NewRolesQuerySchema } from "../lib/new-roles-contract";
import { defaultBoardPreferences } from "../lib/job-board-preferences";
const job = (n: number) => GlobeJobSchema.parse({id:`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`,
  title:"Engineer",company:"Fixture",source:"fixture",location:null,remote:null,seniority:null,stack:[],
  url:"https://example.test",apply_url:null,posted_at:null,first_seen_at:"2026-10-07T00:00:00Z",status:"new",status_reason:null,score:90,recommendation:"apply",alive:true});

test("snapshot identity hydration batches captured IDs, preserves deleted rows and never emits JD", async () => {
  const jobs = Array.from({length:205}, (_, n) => job(n));
  let reads = 0;
  const db = createClient("https://database.example.test", "synthetic", {global:{fetch:async input => {
    const url = new URL(String(input));
    assert.equal(url.searchParams.get("select"), "id,url,apply_url,raw_jd");
    const batch = jobs.slice(reads++ * 100, reads * 100);
    assert.equal(url.searchParams.get("id"), `in.(${batch.map(job=>job.id).join(",")})`);
    return Response.json(batch.filter(job=>job.id !== jobs[0].id).map(job=>({...job,raw_jd:"Build services."})));
  }}});
  const result = await withVacancyIdentity(db, [...jobs,jobs[0]]);
  assert.equal(reads,3); assert.equal(result.length,206);
  assert.deepEqual(result.map(job=>job.id), [...jobs,jobs[0]].map(job=>job.id));
  assert.ok(result[1].vacancy_identity?.jd_fingerprint);
  assert.equal(result[0].vacancy_identity?.jd_fingerprint,null);
  assert.equal("raw_jd" in result[1],false);
});
test("identity read errors propagate and empty snapshots perform no extra read", async () => {
  const db = createClient("https://database.example.test", "synthetic", {global:{fetch:async () => Response.json({message:"unavailable"},{status:503})}});
  assert.deepEqual(await withVacancyIdentity(db,[]),[]);
  await assert.rejects(withVacancyIdentity(db,[job(1)]));
});
test("new-role count uses the same JD identity as board and globe", async () => {
  const current=job(1), incoming={...job(2),title:"Updated title"};
  const db = createClient("https://database.example.test", "synthetic", {global:{fetch:async input => {
    if(String(input).includes("/postings?")) return Response.json([current,incoming].map(job=>({...job,raw_jd:"Build services."})));
    return Response.json({current:[current],incoming:[incoming]});
  }}});
  assert.equal((await getNewRolesStore(db).count(NewRolesQuerySchema.parse({filter:"all",availability:"all",since:"2026-10-06T00:00:00Z",ids:[current.id],incoming_ids:[incoming.id],view:defaultBoardPreferences().view}))).count,0);
});
