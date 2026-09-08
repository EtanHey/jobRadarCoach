import assert from "node:assert/strict";
import { test } from "node:test";
import { filterJobs, levelGroup, locationGroup, type ViewOptions } from "../lib/job-filters";
import { JobSummarySchema } from "../lib/contracts";
import { technologyMentions } from "../lib/job-metadata";
const options: ViewOptions = {search:"",source:"",location:"",seniority:"",fit:"",sort:"fit"};
function job(id: number, score: number | null, seniority: string | null = null, location: string | null = null) {
  return JobSummarySchema.parse({id:`00000000-0000-4000-8000-${String(id).padStart(12,"0")}`,title:"Engineer",company:"Example",location,remote:null,seniority,stack:[],salary:null,url:"https://example.test/",apply_url:null,posted_at:null,first_seen_at:"2026-09-08T00:00:00Z",last_seen_at:"2026-09-08T00:00:00Z",source:"linkedin",experience:null,description_available:true,seniority_origin:"unknown",extraction_state:"not-extracted",status:"new",status_reason:null,score,fit_line:null,recommendation:null});
}
test("best fit keeps zero above unscored and never drops unknown roles by default",()=>{
  const rows=[job(1,null),job(2,0),job(3,75)];
  assert.deepEqual(filterJobs(rows,options).map(x=>x.score),[75,0,null]);
  assert.equal(filterJobs(rows,{...options,fit:"scored"}).length,2);
  assert.equal(filterJobs(rows,{...options,fit:"unscored"}).length,1);
});
test("source and level filters compose; unknown levels are explicit",()=>{
  const rows=[job(1,60,"Senior"),{...job(2,null,"Junior"),source:"workable"},job(3,null)];
  assert.equal(filterJobs(rows,{...options,source:"workable",seniority:"Junior"}).length,1);
  assert.equal(filterJobs(rows,{...options,seniority:"Unknown"}).length,1);
  assert.equal(filterJobs(rows,{...options,seniority:"non-senior"}).length,2);
  assert.equal(levelGroup("Staff"),"Staff / Principal");
});
test("technology badges quote explicit words, not Go prose or Java inside JavaScript",()=>{
  assert.deepEqual(technologyMentions("Go to our website. JavaScript and React experience."),["React","JavaScript"]);
  assert.deepEqual(technologyMentions(null),[]);
});
test("location filters keep countryless remote roles unknown",()=>{
  const rows=[job(1,null,null,"Tel Aviv, Israel"),job(2,null,null,"Remote, United States"),job(3,null,null,"London, UK"),job(4,null,null,"Remote"),job(5,null,null,"San Francisco, CA"),job(6,null,null,"Denver, CO"),job(7,null,null,"Bastrop, TX"),job(8,null,null,"San Francisco Bay Area")];
  assert.deepEqual(rows.map((row)=>locationGroup(row.location)),["israel","united-states","other","unknown","united-states","united-states","united-states","united-states"]);
  assert.deepEqual(filterJobs(rows,{...options,location:"israel"}).map((row)=>row.id),[rows[0].id]);
  assert.deepEqual(filterJobs(rows,{...options,location:"united-states"}).map((row)=>row.id),[rows[1].id,rows[4].id,rows[5].id,rows[6].id,rows[7].id]);
  assert.deepEqual(filterJobs(rows,{...options,location:"other"}).map((row)=>row.id),[rows[2].id]);
});
