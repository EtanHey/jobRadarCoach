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
    assert.equal(url.searchParams.get("select"), "id,identity_evidence:raw_jd");
    const batch = jobs.slice(reads++ * 100, reads * 100);
    assert.equal(url.searchParams.get("id"), `in.(${batch.map(job=>job.id).join(",")})`);
    return Response.json(batch.filter(job=>job.id !== jobs[0].id).map(job=>({id:job.id,identity_evidence:"Build services."})));
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
  await assert.rejects(withVacancyIdentity(db,[job(1),job(2)]));
});
test("new-role count uses the same JD identity as board and globe", async () => {
  const current=job(1), incoming={...job(2),title:"Updated title"};
  const db = createClient("https://database.example.test", "synthetic", {global:{fetch:async input => {
    if(String(input).includes("/postings?")) return Response.json([current,incoming].map(job=>({id:job.id,identity_evidence:"Build services."})));
    return Response.json({current:[current],incoming:[incoming]});
  }}});
  assert.equal((await getNewRolesStore(db).count(NewRolesQuerySchema.parse({filter:"all",availability:"all",since:"2026-10-06T00:00:00Z",ids:[current.id],incoming_ids:[incoming.id],view:defaultBoardPreferences().view}))).count,0);
});

test("only repeated normalized employers without URL requisitions fetch bodies", async () => {
  const jobs = [
    {...job(1),company:"  ＡＣＭＥ  Labs "},
    {...job(2),company:"acme labs"},
    {...job(3),company:"Singleton"},
    {...job(4),company:"Workday",url:"https://acme.myworkdayjobs.com/jobs/job/Engineer_JR12345"},
    {...job(5),company:"Workday",apply_url:"https://acme.myworkdayjobs.com/jobs/job/Engineer_R12345/apply"},
    {...job(6),company:"Mixed",url:"https://acme.myworkdayjobs.com/jobs/job/Engineer_JR54321"},
    {...job(7),company:"Mixed"},
    {...job(8),company:"Duplicate singleton"},
  ];
  const candidates = [jobs[0],jobs[1],jobs[6]];
  let reads = 0;
  const db = createClient("https://database.example.test", "synthetic", {global:{fetch:async input => {
    reads++;
    const url = new URL(String(input));
    assert.equal(url.searchParams.get("select"), "id,identity_evidence:raw_jd");
    assert.equal(url.searchParams.get("id"), `in.(${candidates.map(job=>job.id).join(",")})`);
    return Response.json(candidates.map(job=>({id:job.id,identity_evidence:"Job Req: JR54321. Build services."})));
  }}});
  const result = await withVacancyIdentity(db,[...jobs,jobs[7]]);
  assert.equal(reads,1);
  assert.deepEqual(result[3].vacancy_identity?.requisitions,["JR12345"]);
  assert.deepEqual(result[4].vacancy_identity?.requisitions,["R12345"]);
  assert.deepEqual(result[6].vacancy_identity?.requisitions,["JR54321"]);
  assert.equal(result[2].vacancy_identity?.jd_fingerprint,null);
  assert.equal(result[7].vacancy_identity?.jd_fingerprint,null);
  assert.equal(result.length,9);
  assert.ok(result.every(job=>!("raw_jd" in job) && !("identity_evidence" in job)));
});

test("singleton and URL-identified responses perform no body read", async () => {
  const db = createClient("https://database.example.test", "synthetic", {global:{fetch:async () => {
    assert.fail("unexpected body query");
  }}});
  await withVacancyIdentity(db,[job(1)]);
  await withVacancyIdentity(db,[job(1),job(1)]);
  const known = {...job(1),url:"https://acme.myworkdayjobs.com/jobs/job/Engineer_JR12345"};
  const result = await withVacancyIdentity(db,[known,{...known,id:job(2).id}]);
  assert.ok(result.every(job=>job.vacancy_identity?.requisitions[0] === "JR12345"));
});

test("body enrichment caps unique candidates at 300 and warns once", async (t) => {
  const jobs = Array.from({length:405}, (_, n) => job(n));
  const warnings = t.mock.method(console,"warn",()=>{});
  const sizes: number[] = [];
  const db = createClient("https://database.example.test", "synthetic", {global:{fetch:async input => {
    const url = new URL(String(input));
    const ids = url.searchParams.get("id")?.slice(4,-1).split(",") ?? [];
    const offset = sizes.reduce((sum,size)=>sum+size,0);
    assert.deepEqual(ids,jobs.slice(offset,offset+100).map(job=>job.id));
    sizes.push(ids.length);
    return Response.json(ids.map(id=>({id,identity_evidence:"Build services."})));
  }}});
  const result = await withVacancyIdentity(db,[...jobs,jobs[0]]);
  assert.deepEqual(sizes,[100,100,100]);
  assert.equal(warnings.mock.callCount(),1);
  assert.deepEqual(warnings.mock.calls[0].arguments,["Vacancy identity body fetch capped",{candidates:405,fetched:300,skipped:105}]);
  assert.equal(result.length,406);
  assert.ok(result[299].vacancy_identity?.jd_fingerprint);
  assert.equal(result[300].vacancy_identity?.jd_fingerprint,null);
  assert.ok(result[405].vacancy_identity?.jd_fingerprint);
});
