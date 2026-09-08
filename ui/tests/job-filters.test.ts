import assert from "node:assert/strict";
import { test } from "node:test";
import { filterJobGroups, filterJobs, levelGroup, locationGroup, sourceFilterValues, type ViewOptions } from "../lib/job-filters";
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
  const rows=[job(1,null,null,"Tel Aviv, Israel"),job(2,null,null,"Remote, United States"),job(3,null,null,"London, UK"),job(4,null,null,"Remote"),job(5,null,null,"San Francisco, CA"),job(6,null,null,"Denver, CO"),job(7,null,null,"Bastrop, TX"),job(8,null,null,"San Francisco Bay Area"),job(9,null,null,"Remote / Anywhere"),job(10,null,null,"Remote - Worldwide")];
  assert.deepEqual(rows.map((row)=>locationGroup(row.location)),["israel","united-states","other","unknown","united-states","united-states","united-states","united-states","unknown","unknown"]);
  assert.deepEqual(filterJobs(rows,{...options,location:"israel"}).map((row)=>row.id),[rows[0].id]);
  assert.deepEqual(filterJobs(rows,{...options,location:"united-states"}).map((row)=>row.id),[rows[1].id,rows[4].id,rows[5].id,rows[6].id,rows[7].id]);
  assert.deepEqual(filterJobs(rows,{...options,location:"other"}).map((row)=>row.id),[rows[2].id]);
});

test("recommendation filtering composes with location without hiding stretch reviews",()=>{
  const rows=[{...job(1,44,null,"Israel"),recommendation:"review" as const},{...job(2,80,null,"Israel"),recommendation:"skip" as const},{...job(3,92,null,"United States"),recommendation:"apply" as const},job(4,null,null,"Israel")];
  assert.deepEqual(filterJobs(rows,{...options,fit:"recommended",location:"israel"}).map(x=>x.id),[rows[0].id]);
  assert.deepEqual(filterJobs(rows,{...options,fit:"skip"}).map(x=>x.id),[rows[1].id]);
  assert.equal(filterJobs(rows,options).length,4);
});

test("country codes alone cannot masquerade as US states",()=>{
  for (const location of ["Toronto, CA", "Hyderabad, IN", "Unknown City, CA", "Bremen, DE"]) assert.equal(locationGroup(location),"other",location);
  for (const location of ["San Francisco, CA", "Fortville, IN", "Chicago, IL", "Washington, DC", "Austin, Texas Metropolitan Area"]) assert.equal(locationGroup(location),"united-states",location);
});

test("a restored source absent from current jobs remains a visible selected option", () => {
  assert.deepEqual(
    sourceFilterValues([{ source: "linkedin" }, { source: "workable" }], "greenhouse"),
    ["greenhouse", "linkedin", "workable"],
  );
});

test("filtered best-fit groups sort by the displayed newest representative", () => {
  const unique78 = { ...job(20, 78, null, "Israel"), title: "Frontend Developer" };
  const duplicateHigh = { ...job(21, 76, null, "Israel"), title: "Fullstack Engineer", company: "Academy", posted_at: "2026-09-01T00:00:00Z" };
  const unique74 = { ...job(22, 74, null, "Israel"), title: "Data Product Engineer" };
  const duplicateNewest = { ...job(23, 68, null, "Israel"), title: "Fullstack Engineer", company: "Academy", posted_at: "2026-09-08T00:00:00Z" };

  const displayed = filterJobGroups(
    [unique78, duplicateHigh, unique74, duplicateNewest],
    { ...options, location: "israel" },
  );

  assert.deepEqual(displayed.map(({ job: row }) => row.score), [78, 74, 68]);
});

test("every sort mode orders duplicate groups by the displayed representative", () => {
  const duplicateOld = { ...job(30, 99, "Senior", "Israel"), title: "Grouped role", company: "Grouped Co", posted_at: "2026-09-01T00:00:00Z", first_seen_at: "2026-09-01T00:00:00Z" };
  const duplicateNewest = { ...job(31, 50, "Senior", "Israel"), title: "Grouped role", company: "Grouped Co", posted_at: "2026-09-04T00:00:00Z", first_seen_at: "2026-09-04T00:00:00Z" };
  const junior = { ...job(32, 74, "Junior", "Israel"), title: "Junior unique", posted_at: "2026-09-03T00:00:00Z", first_seen_at: "2026-09-03T00:00:00Z" };
  const mid = { ...job(33, 78, "Mid-level", "Israel"), title: "Mid unique", posted_at: "2026-09-02T00:00:00Z", first_seen_at: "2026-09-02T00:00:00Z" };
  const rows = [duplicateOld, junior, mid, duplicateNewest];

  const ids = (sort: ViewOptions["sort"]) => filterJobGroups(rows, { ...options, location: "israel", sort }).map(({ job: row }) => row.id);
  assert.deepEqual(ids("fit"), [mid.id, junior.id, duplicateNewest.id]);
  assert.deepEqual(ids("found"), [duplicateNewest.id, junior.id, mid.id]);
  assert.deepEqual(ids("posted"), [duplicateNewest.id, junior.id, mid.id]);
  assert.deepEqual(ids("seniority"), [junior.id, mid.id, duplicateNewest.id]);
});
