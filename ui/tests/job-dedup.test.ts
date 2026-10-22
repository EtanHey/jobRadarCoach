import assert from "node:assert/strict";
import { test } from "node:test";
import { vacancyIdentity } from "../lib/vacancy-identity";
import { globePoints } from "../lib/globe-model";
import { JobSummarySchema, type JobSummary } from "../lib/contracts";
import { groupDuplicateJobs, relatedDuplicateJobs, shortListingId } from "../lib/job-dedup";
import { repostNote } from "../lib/job-display";

function job(id: number, overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: `00000000-0000-4000-8000-${String(id).padStart(12, "0")}`,
    title: "Senior C++ Engineer",
    company: "Café Labs",
    source: "linkedin",
    last_seen_at: "2026-09-08T10:00:00Z",
    experience: null,
    description_available: true,
    seniority_origin: "title",
    extraction_state: "extracted",
    location: "Tel Aviv, Israel",
    remote: true,
    seniority: "Senior",
    stack: ["C++"],
    salary: null,
    url: `https://example.test/jobs/${id}`,
    apply_url: "https://apply.workable.com/fixture/j/DEFAULT/",
    posted_at: "2026-09-08T00:00:00Z",
    first_seen_at: "2026-09-08T00:00:00Z",
    status: "new",
    status_reason: null,
    score: null,
    fit_line: null,
    recommendation: null,
    ...overrides,
    alive: overrides.alive ?? null,
  };
}

test("groups a genuine pair after ID uniqueness without mixing payload fields", () => {
  const repeatedOld = job(1, { title: "old payload", score: 10, first_seen_at: "2026-09-08T04:00:00Z" });
  const repeatedMiddle = job(1, { title: "middle payload", score: 20, first_seen_at: "2026-09-08T05:00:00Z" });
  const repeatedLatest = job(1, {
    title: "  Senior   C++ Engineer ", company: "Cafe\u0301 Labs", source: " LINKEDIN ",
    score: 31, fit_line: "latest duplicate payload", first_seen_at: "2026-09-08T06:00:00Z",
    posted_at: "2026-09-09T00:00:00Z",
  });
  const genuinePair = job(2, {
    title: "senior c++ engineer", company: "Café Labs", score: 92,
    fit_line: "genuine pair payload", first_seen_at: "2026-09-08T07:00:00Z",
    posted_at: "2026-09-07T00:00:00Z",
  });
  const differentCompany = job(3, { company: "Other Labs" });
  const differentTitle = job(4, { title: "Senior C Engineer", apply_url: "https://apply.workable.com/fixture/j/OTHER-TITLE/" });
  const differentSource = job(5, { title: "Unique ATS role", source: "workable", apply_url: "https://apply.workable.com/fixture/j/OTHER/" });
  const input = [
    repeatedOld, differentCompany, repeatedMiddle, differentTitle,
    repeatedLatest, genuinePair, differentSource,
  ];
  const before = structuredClone(input);

  const groups = groupDuplicateJobs(input);

  assert.deepEqual(groups.map((group) => group.job.id), [
    repeatedLatest.id, differentTitle.id, differentSource.id, differentCompany.id,
  ]);
  assert.equal(groups[0].job.id, repeatedLatest.id);
  assert.equal(groups[0].job.posted_at, genuinePair.posted_at);
  assert.deepEqual(groups[0].alternates, [genuinePair]);
  assert.equal(groups[0].job.score, 31);
  assert.equal(groups[0].alternates[0].score, 92);
  assert.deepEqual(input, before);
  assert.deepEqual(
    groups.flatMap((group) => [group.job, ...group.alternates]).map((row) => row.id).sort(),
    [repeatedLatest.id, genuinePair.id, differentCompany.id, differentTitle.id, differentSource.id].sort(),
  );
});

test("uses a stable ID tie-break and ignores last-seen refresh churn", () => {
  const higherId = job(9, {
    first_seen_at: "2026-09-08T08:00:00Z", last_seen_at: "2026-09-10T08:00:00Z",
  });
  const lowerId = job(8, {
    first_seen_at: "2026-09-08T08:00:00Z", last_seen_at: "2026-09-08T08:00:00Z",
  });

  const [group] = groupDuplicateJobs([higherId, lowerId]);

  assert.equal(group.job.id, lowerId.id);
  assert.deepEqual(group.alternates, [higherId]);
});

test("falls back to first-seen only when publication is missing", () => {
  const olderFallback = job(10, { posted_at: null, first_seen_at: "2026-09-08T06:00:00Z" });
  const newerFallback = job(11, { posted_at: null, first_seen_at: "2026-09-08T07:00:00Z" });
  const olderTie = job(12, { posted_at: "2026-09-09", first_seen_at: "2026-09-08T08:00:00Z" });
  const newerTie = job(13, { posted_at: "2026-09-09", first_seen_at: "2026-09-08T09:00:00Z" });

  assert.equal(groupDuplicateJobs([olderFallback, newerFallback])[0].job.id, newerFallback.id);
  assert.equal(groupDuplicateJobs([olderTie, newerTie])[0].job.id, olderTie.id);
});

test("keeps loaded peers reachable after the selected listing leaves the view", () => {
  const selected = job(20, { status: "worth_checking" });
  const peer = job(21, { status: "new" });
  const unrelated = job(22, { company: "Other Labs", status: "new" });

  const related = relatedDuplicateJobs(
    [peer, unrelated], selected.id, selected,
  );

  assert.deepEqual(related, [peer]);
  assert.equal(peer.status, "new");
  assert.equal(unrelated.status, "new");
});

test("short listing IDs remain stable and distinguish fixture postings", () => {
  assert.equal(shortListingId(job(20).id), "00000020");
  assert.equal(shortListingId(job(21).id), "00000021");
});


test("matching company/title and compatible location links new IDs across sources without JD", () => {
  const leftListing = { ...job(40, { apply_url: null, url: "https://www.linkedin.com/jobs/view/400" }), external_id: "old" };
  const rightListing = { ...job(41, { apply_url: null, url: "https://www.linkedin.com/jobs/view/401" }), external_id: "new" };
  assert.equal(groupDuplicateJobs([leftListing, rightListing]).length, 1);
  const ats = { ...job(42, { source: "greenhouse", apply_url: null, url: "https://boards.greenhouse.io/fixture/jobs/123" }), external_id: "123" };
  const groups = groupDuplicateJobs([leftListing, ats]);
  assert.equal(groups.length, 1);
  assert.deepEqual(globePoints(groups, [leftListing, ats].map(row => ({posting_id: row.id, lat: 32, lng: 34, precision: "city", source: "fixture", resolved_at: row.first_seen_at}))).map(point => point.rowId), [groups[0].job.id, groups[0].job.id]);
});

test("different known locations stay separate even with shared role URL", () => {
  for (const location of ["Haifa, Israel", "United States"]) {
    assert.equal(groupDuplicateJobs([job(50), job(51, { location })]).length, 2);
  }
});

test("unknown or remote-equivalent locations link; remote flags alone do not split", () => {
  for (const location of [null, "Remote", "Remote / Anywhere", "Remote - Worldwide", "anywhere in the world"]) {
    assert.equal(groupDuplicateJobs([job(60, { apply_url: null }), job(61, { apply_url: null, location, source: "greenhouse", remote: false })]).length, 1);
  }
});

test("strong canonical role links title drift and preserves original group date", () => {
  const older = job(70, { apply_url: "https://apply.workable.com/fixture/j/REQ123/?utm_source=fixture", posted_at: "2026-09-01" });
  const repost = job(71, { title: "Updated Engineer title", apply_url: "https://apply.workable.com/fixture/jobs/view/REQ123.md", posted_at: "2026-10-01" });
  const [group] = groupDuplicateJobs([older, repost]);
  assert.equal(group.alternates.length, 1);
  assert.equal(group.job.id, repost.id);
  assert.equal(group.job.posted_at, older.posted_at);
  assert.equal(group.job.last_published_at, repost.posted_at);
  assert.equal(repost.posted_at, "2026-10-01");
  const generic = "https://example.test/careers";
  assert.equal(groupDuplicateJobs([job(72, {apply_url: generic}), job(73, {title: "Other title", apply_url: generic})]).length, 2);
});

test("missing-location bridge cannot collapse different locations; membership is input-stable", () => {
  const leftListing = job(80, { location: "Tel Aviv, Israel" });
  const bridge = job(81, { location: null });
  const other = job(82, { location: "Haifa, Israel" });
  for (const rows of [[leftListing, bridge, other], [other, bridge, leftListing]]) {
    assert.deepEqual(groupDuplicateJobs(rows).map(group => [group.job.id, ...group.alternates.map(row => row.id)]), [[leftListing.id, bridge.id], [other.id]]);
  }
});

test("location aliases and city/region/country containment link", () => {
  for (const [location, other] of [
    ["Haifa, Israel", "Haifa District, Israel"], ["Haifa, Israel", "Israel"],
    ["Tel Aviv", "Tel Aviv-Yafo, Tel Aviv District, Israel"],
    ["Petah Tikva, Center District, Israel", "Center District, Israel"],
    ["New York, United States", "United States"], ["Seattle, WA", "USA"],
    ["U.S. or Canada", "US and Canada"], ["central Israel", "Bnei Brak, Tel Aviv District, Israel"],
    ["customer locations", "Center District, Israel"], ["Toronto, CA", "Canada"],
    ["United States", "GA, TX, PA, CA, MD, or MI"],
  ]) assert.equal(groupDuplicateJobs([job(90, {location}), job(91, {location: other})]).length, 1, `${location} / ${other}`);
});

test("exclusive cities, regions and countries stay separate under containment", () => {
  for (const [location, other] of [
    ["Petah Tikva, Center District, Israel", "Ramat Yishai, North District, Israel"],
    ["Kfar Monash, Israel (Hybrid)", "Sarid, Israel (Hybrid)"],
    ["Seattle, WA", "Chicago, IL"], ["Minnesota, United States", "Illinois, United States"],
    ["Israel", "Austin, Texas Metropolitan Area"], ["London, UK", "Paris, France"], ["India", "USA"],
  ]) assert.equal(groupDuplicateJobs([job(92, {location}), job(93, {location: other})]).length, 2, `${location} / ${other}`);
});


test("grouping prepares identity and location evidence once instead of per pair", (context) => {
  const locations = ["Tel Aviv, Israel", "Tel Aviv District, Israel", "Haifa, Israel", "Haifa District, Israel", "Israel"];
  const rows = Array.from({ length: 1319 }, (_, index) => job(1000 + index, {
    company: `Synthetic company ${Math.floor(index / 37)}`,
    location: locations[index % locations.length],
  }));
  const counts = { regex: 0, location: 0, url: 0 };
  const originalRegex = globalThis.RegExp, originalUrl = globalThis.URL;
  const originalNormalize = String.prototype.normalize;
  try {
    globalThis.RegExp = new Proxy(originalRegex, { construct(target, args, newTarget) {
      counts.regex += 1;
      return Reflect.construct(target, args, newTarget);
    } });
    globalThis.URL = new Proxy(originalUrl, { construct(target, args, newTarget) {
      counts.url += 1;
      return Reflect.construct(target, args, newTarget);
    } });
    context.mock.method(String.prototype, "normalize", function(this: string, form?: Parameters<string["normalize"]>[0]) {
      if (locations.includes(String(this))) counts.location += 1;
      return originalNormalize.call(this, form);
    });
    assert.ok(groupDuplicateJobs(rows).length > 0);
  } finally {
    globalThis.RegExp = originalRegex;
    globalThis.URL = originalUrl;
    context.mock.restoreAll();
  }
  context.diagnostic(JSON.stringify(counts));
  assert.equal(counts.regex, 0, "country/state regexes must be compiled before grouping");
  assert.ok(counts.location <= locations.length, "each location must be parsed at most once per grouping call");
  assert.ok(counts.url <= rows.length * 2, "each listing URL must be parsed at most once per grouping call");
});

test("LinkedIn grouping keeps dates and alternates without inferring a repost", () => {
  for (const posted_at of [null, "2026-09-28T12:00:00Z"]) {
    const groups = groupDuplicateJobs([
      job(30, {posted_at,first_seen_at:"2026-09-28T13:00:00Z"}),
      job(31, {posted_at:posted_at ? "2026-08-20T12:00:00Z" : null,first_seen_at:"2026-08-20T13:00:00Z"}),
    ].map(row => JobSummarySchema.parse(row)));
    assert.equal(groups.length, 1);
    assert.equal(groups[0].alternates.length, 1);
    assert.equal(repostNote(groups[0].job), null);
  }
});


test("ATS grouping preserves each listing's republish evidence separately from group dates", () => {
  const ats = job(200, { source: "greenhouse", posted_at: "2026-09-01T12:00:00Z", last_published_at: "2026-10-03T12:00:00Z" });
  const alternate = job(201, { posted_at: "2026-08-01T12:00:00Z", last_published_at: "2026-10-04T12:00:00Z" });
  const [group] = groupDuplicateJobs([ats, alternate]);
  assert.equal(group.job.id, ats.id);
  assert.equal(group.job.posted_at, alternate.posted_at);
  assert.equal(group.job.last_published_at, alternate.last_published_at);
  assert.equal(repostNote(group.job, "UTC"), "Reposted: republished 2026-10-03");
  const [ordinary] = groupDuplicateJobs([{ ...ats, last_published_at: ats.posted_at }, alternate]);
  assert.equal(repostNote(ordinary.job, "UTC"), null, "aggregate dates alone are not evidence");
});

const vacancy = (id: number, requisition: string | null, overrides: Partial<JobSummary> & { raw_jd?: string } = {}) => ({
  ...job(id, { apply_url: requisition ? `https://nvidia.wd5.myworkdayjobs.com/en-US/Careers/job/Israel/Engineer_${requisition}` : null }),
  ...overrides,
});
test("same_requisition_title_drift_has_one_group", () => {
  assert.equal(groupDuplicateJobs([vacancy(301, "JR123"), vacancy(302, "JR123", { title: "Updated Engineer" })]).length, 1);
});
test("same_requisition_location_variants_have_one_group", () => {
  assert.equal(groupDuplicateJobs([vacancy(301, "JR123"), vacancy(302, "JR123", { location: "Haifa, Israel" })]).length, 1);
});
test("distinct_requisitions_with_same_title_location_and_jd_stay_separate", () => {
  assert.equal(groupDuplicateJobs([vacancy(301, "JR123", {raw_jd: "Build reliable services."}), vacancy(302, "JR456", {raw_jd: "Build reliable services."})]).length, 2);
});
test("jd_only_title_variants_have_one_group", () => {
  assert.equal(groupDuplicateJobs([vacancy(301, null, {raw_jd: "Build reliable services. ".repeat(20)}), vacancy(302, null, {title: "Updated Engineer", raw_jd: "Build   reliable\nservices. ".repeat(20)})]).length, 1);
});
test("Unframe identical JD reposts with different Greenhouse post IDs stay grouped", () => {
  // Frozen pair 7c3ef744 / 97994440: identical bodies, distinct source post IDs.
  const rows = [5009573101, 5003023101].map((posting, index) => vacancy(401 + index, null, {
    company: "Unframe", title: "Full Stack Software Engineer", location: "Tel Aviv, Israel",
    url: `https://job-boards.greenhouse.io/unframe/jobs/${posting}`,
    raw_jd: "Build enterprise AI applications and own features across the stack.",
  }));
  for (const input of [rows, rows.toReversed()]) assert.equal(groupDuplicateJobs(input).length, 1);
});
test("Office Hours trivial JD edits preserve the title and location fallback", () => {
  // Frozen pair 6270b19b / 7cf0dfb5 differs only by the word 'either'.
  const rows = ["can either be", "can be"].map((wording, index) => vacancy(411 + index, null, {
    company: "Office Hours", title: "Senior Frontend Engineer", location: "Israel",
    raw_jd: `Build frontend applications. This role ${wording} fully remote or in our office.`,
  }));
  for (const input of [rows, rows.toReversed()]) assert.equal(groupDuplicateJobs(input).length, 1);
});
test("different JD fingerprints alone do not establish distinct headcount", () => {
  const rows = [vacancy(421, null, {raw_jd: "Build Rust backend services."}),
    vacancy(422, null, {raw_jd: "Build React frontend applications."})];
  assert.equal(groupDuplicateJobs(rows).length, 1, "same employer, title and location remain a grouping candidate");
});
test("substantively different roles stay separate without a matching title or posting URL", () => {
  const rows = [vacancy(431, null, {title: "Backend Engineer", raw_jd: "Build Rust backend services."}),
    vacancy(432, null, {title: "Product Designer", raw_jd: "Design user journeys and conduct user research."})];
  for (const input of [rows, rows.toReversed()]) assert.equal(groupDuplicateJobs(input).length, 2);
});
test("NVIDIA URL JR ids ignore location and Workday repost suffixes", () => {
  assert.equal(groupDuplicateJobs([vacancy(301, "JR2023247"), vacancy(302, "JR2023247-1", {title: "Title variant", location: "Yokneam"})]).length, 1);
});

test("unknown identity cannot bridge different requisitions or split a shared requisition", () => {
  const unknown = vacancy(300, null);
  const a = vacancy(301, "JR123"), b = vacancy(302, "JR456");
  for (const rows of [[unknown, a, b], [b, a, unknown]]) {
    assert.equal(groupDuplicateJobs(rows).length, 2);
    assert.equal(groupDuplicateJobs([unknown, a, {...a, id: b.id, location: "Haifa", title: "Changed"}]).length, 2);
  }
});
test("conflicting requisitions are isolated; employers and per-source evidence survive grouping", () => {
  const a = vacancy(301, "JR123", {raw_jd: "Requisition ID: JR456"});
  assert.equal(groupDuplicateJobs([a, vacancy(302, "JR123")]).length, 2);
  assert.equal(groupDuplicateJobs([vacancy(301, "JR123"), vacancy(302, "JR123", {company: "Other"})]).length, 2);
  const rows = [vacancy(301, "JR123", {alive: true, score: 90}), vacancy(302, "JR123", {alive: false, score: 10, source: "workday", location: "Haifa"})];
  const [group] = groupDuplicateJobs(rows);
  assert.deepEqual([group.job, ...group.alternates].map(({id, source, score, alive, location}) => ({id, source, score, alive, location})), rows.map(({id, source, score, alive, location}) => ({id, source, score, alive, location})));
});

for (const [company, text, titles, duties] of [
  ["Evolent", "We build healthcare products integrating FHIR R4.", ["Backend Engineer", "Frontend Engineer"], ["Implement Java APIs and healthcare integrations.", "Build React interfaces and patient-facing components."]],
  ["Latent AI", "Our platform stores customer files in Cloudflare R2.", ["Site Reliability Engineer", "Security Engineer"], ["Operate Kubernetes clusters and manage on-call rotations.", "Perform threat modeling and implement application security."]],
  ["Latent AI", "Data & Real-Time: Convex, PostgreSQL, object storage (s3/r2)", ["Software Engineer", "Product Designer"], ["Implement durable backend workflow services.", "Run user interviews and design product interaction flows."]],
] as const) {
  test(`${company}: distinct ${titles.join(" / ")} roles sharing technology stay split`, () => {
    const rows = titles.map((title, index) => vacancy(450 + index, null, {
      company, title, raw_jd: `${text}\n\n${duties[index]}`,
    }));
    const compact = rows.map(row => ({...row, raw_jd: undefined, vacancy_identity: vacancyIdentity(row)}));
    for (const input of [rows, rows.toReversed(), compact, compact.toReversed()]) {
      assert.equal(groupDuplicateJobs(input).length, 2);
    }
  });
}

test("short matching boilerplate cannot merge different roles", () => {
  const rows = [vacancy(501, null, {title:"Engineer", raw_jd:"Apply now"}),
    vacancy(502, null, {title:"Designer", raw_jd:"Apply now"})];
  for (const input of [rows, rows.toReversed()]) assert.equal(groupDuplicateJobs(input).length, 2);
});
test("multiple requisitions merge only when their full sets match", () => {
  const a = vacancy(501, null, {raw_jd:"Req: ENG-123. Requisition: ENG-456"});
  const b = vacancy(502, null, {title:"Changed title", location:"Elsewhere", raw_jd:"Req: ENG-456. Req: ENG-123. Req: ENG-123"});
  for (const input of [[a,b],[b,a]]) assert.equal(groupDuplicateJobs(input).length, 1);
  for (const raw_jd of ["Req: ENG-123", "Req: ENG-123. Req: ENG-789", ""]) {
    assert.equal(groupDuplicateJobs([a, vacancy(503, null, {raw_jd})]).length, 2);
  }
});
