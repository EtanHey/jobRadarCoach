import assert from "node:assert/strict";
import { test } from "node:test";
import { globePoints } from "../lib/globe-model";
import type { JobSummary } from "../lib/contracts";
import { groupDuplicateJobs, relatedDuplicateJobs, shortListingId } from "../lib/job-dedup";

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
  const a = { ...job(40, { apply_url: null, url: "https://www.linkedin.com/jobs/view/400" }), external_id: "old" };
  const b = { ...job(41, { apply_url: null, url: "https://www.linkedin.com/jobs/view/401" }), external_id: "new" };
  assert.equal(groupDuplicateJobs([a, b]).length, 1);
  const ats = { ...job(42, { source: "greenhouse", apply_url: null, url: "https://boards.greenhouse.io/fixture/jobs/123" }), external_id: "123" };
  const groups = groupDuplicateJobs([a, ats]);
  assert.equal(groups.length, 1);
  assert.deepEqual(globePoints(groups, [a, ats].map(row => ({posting_id: row.id, lat: 32, lng: 34, precision: "city", source: "fixture", resolved_at: row.first_seen_at}))).map(point => point.rowId), [groups[0].job.id, groups[0].job.id]);
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
  const a = job(80, { location: "Tel Aviv, Israel" });
  const bridge = job(81, { location: null });
  const other = job(82, { location: "Haifa, Israel" });
  for (const rows of [[a, bridge, other], [other, bridge, a]]) {
    assert.deepEqual(groupDuplicateJobs(rows).map(group => [group.job.id, ...group.alternates.map(row => row.id)]), [[a.id, bridge.id], [other.id]]);
  }
});
