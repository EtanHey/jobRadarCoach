import assert from "node:assert/strict";
import { test } from "node:test";
import { globePoints } from "../lib/globe-model";
import { JobSummarySchema, type JobSummary } from "../lib/contracts";
import { earlierListingCount, groupDuplicateJobs, relatedDuplicateJobs, shortListingId } from "../lib/job-dedup";
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

test("only demonstrably earlier alternates count as earlier listings", () => {
  const at = "2026-10-02T12:00:00Z";
  const simultaneous = groupDuplicateJobs([job(20, { posted_at: at, first_seen_at: at }), job(21, { posted_at: at, first_seen_at: at })])[0];
  assert.equal(simultaneous.alternates.length, 1);
  assert.equal(earlierListingCount(simultaneous.job, simultaneous.alternates), 0);

  const current = job(22, { posted_at: "2026-09-28T12:00:00Z", first_seen_at: "2026-09-28T13:00:00Z" });
  const older = job(23, { posted_at: "2026-08-20T12:00:00Z", first_seen_at: "2026-08-20T13:00:00Z" });
  const samePostedLaterSeen = job(24, { posted_at: "2026-09-28T12:00:00Z", first_seen_at: "2026-09-27T13:00:00Z" });
  const unknownPosted = job(25, { posted_at: null, first_seen_at: "2026-08-01T00:00:00Z" });
  assert.equal(earlierListingCount(current, [older]), 1);
  assert.equal(earlierListingCount(current, [samePostedLaterSeen]), 0);
  assert.equal(earlierListingCount(current, [unknownPosted]), 0);
  assert.equal(earlierListingCount(current, [older, samePostedLaterSeen, unknownPosted]), 1);

  const seenOnly = job(26, { posted_at: null, first_seen_at: "2026-09-10T00:00:00Z" });
  const seenEarlier = job(27, { posted_at: null, first_seen_at: "2026-09-01T00:00:00Z" });
  assert.equal(earlierListingCount(seenOnly, [seenEarlier]), 1);
  assert.equal(earlierListingCount(seenOnly, [job(28, { posted_at: null, first_seen_at: "2026-09-10T00:00:00Z" })]), 0);
  assert.equal(earlierListingCount(job(29, { posted_at: "invalid", first_seen_at: "invalid" }), [older]), 0);
});

test("linked groups mark reposts by republished date; earlier-listing counts only without publication dates", () => {
  const marker = ({ job: row, alternates }: ReturnType<typeof groupDuplicateJobs>[number]) =>
    repostNote(row.posted_at, row.last_published_at, earlierListingCount(row, alternates), "UTC");
  const dated = groupDuplicateJobs([
    job(30, { posted_at: "2026-09-28T12:00:00Z", last_published_at: "2026-09-28T12:00:00Z", first_seen_at: "2026-09-28T13:00:00Z" }),
    job(31, { posted_at: "2026-08-20T12:00:00Z", last_published_at: "2026-08-20T12:00:00Z", first_seen_at: "2026-08-20T13:00:00Z" }),
  ]);
  assert.equal(dated.length, 1);
  assert.equal(dated[0].job.posted_at, "2026-08-20T12:00:00Z");
  assert.equal(earlierListingCount(dated[0].job, dated[0].alternates), 0);
  assert.equal(marker(dated[0]), "Reposted: republished 2026-09-28");

  const mixed = groupDuplicateJobs([
    job(32, { posted_at: "2026-09-28T12:00:00Z", first_seen_at: "2026-09-28T13:00:00Z" }),
    job(33, { posted_at: null, first_seen_at: "2026-08-01T00:00:00Z" }),
  ]);
  assert.equal(mixed.length, 1);
  assert.equal(earlierListingCount(mixed[0].job, mixed[0].alternates), 0);

  const undated = groupDuplicateJobs([
    job(34, { posted_at: null, last_published_at: null, first_seen_at: "2026-09-10T00:00:00Z" }),
    job(35, { posted_at: null, last_published_at: null, first_seen_at: "2026-09-01T00:00:00Z" }),
  ]);
  assert.equal(undated.length, 1);
  assert.equal(marker(undated[0]), "Reposted: 1 earlier listing of this role");
});

test("a known latest publication blocks the discovery fallback even without original dates", () => {
  const marker = ({ job: row, alternates }: ReturnType<typeof groupDuplicateJobs>[number]) =>
    repostNote(row.posted_at, row.last_published_at, earlierListingCount(row, alternates), "UTC");
  // R13 scratch case: schema-valid twins share one known latest publication but were found weeks apart.
  const latestOnly = groupDuplicateJobs([
    job(40, { posted_at: null, last_published_at: "2026-09-28T12:00:00Z", first_seen_at: "2026-09-28T13:00:00Z" }),
    job(41, { posted_at: null, last_published_at: "2026-09-28T12:00:00Z", first_seen_at: "2026-09-01T13:00:00Z" }),
  ].map(row => JobSummarySchema.parse(row)));
  assert.equal(latestOnly.length, 1);
  assert.equal(latestOnly[0].job.posted_at, null);
  assert.equal(latestOnly[0].job.last_published_at, "2026-09-28T12:00:00Z");
  assert.equal(earlierListingCount(latestOnly[0].job, latestOnly[0].alternates), 0);
  assert.equal(marker(latestOnly[0]), null);

  // Differing latest dates without a known original are still not "later than the original".
  const latestDiffers = groupDuplicateJobs([
    job(42, { posted_at: null, last_published_at: "2026-09-28T12:00:00Z", first_seen_at: "2026-09-28T13:00:00Z" }),
    job(43, { posted_at: null, last_published_at: "2026-09-01T12:00:00Z", first_seen_at: "2026-09-01T13:00:00Z" }),
  ]);
  assert.equal(latestDiffers.length, 1);
  assert.equal(earlierListingCount(latestDiffers[0].job, latestDiffers[0].alternates), 0);
  assert.equal(marker(latestDiffers[0]), null);

  // One member's latest publication dates the whole group.
  const partlyDated = groupDuplicateJobs([
    job(44, { posted_at: null, last_published_at: null, first_seen_at: "2026-09-28T13:00:00Z" }),
    job(45, { posted_at: null, last_published_at: "2026-09-01T12:00:00Z", first_seen_at: "2026-09-01T13:00:00Z" }),
  ]);
  assert.equal(partlyDated.length, 1);
  assert.equal(earlierListingCount(partlyDated[0].job, partlyDated[0].alternates), 0);
  assert.equal(marker(partlyDated[0]), null);
});
