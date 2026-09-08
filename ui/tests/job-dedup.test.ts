import assert from "node:assert/strict";
import { test } from "node:test";
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
    apply_url: null,
    posted_at: "2026-09-08T00:00:00Z",
    first_seen_at: "2026-09-08T00:00:00Z",
    status: "new",
    status_reason: null,
    score: null,
    fit_line: null,
    recommendation: null,
    ...overrides,
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
  const differentTitle = job(4, { title: "Senior C Engineer" });
  const differentSource = job(5, { source: "workable" });
  const input = [
    repeatedOld, differentCompany, repeatedMiddle, differentTitle,
    repeatedLatest, genuinePair, differentSource,
  ];
  const before = structuredClone(input);

  const groups = groupDuplicateJobs(input);

  assert.deepEqual(groups.map((group) => group.job.id), [
    repeatedLatest.id, differentCompany.id, differentTitle.id, differentSource.id,
  ]);
  assert.equal(groups[0].job, repeatedLatest);
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

  assert.equal(group.job, lowerId);
  assert.deepEqual(group.alternates, [higherId]);
});

test("falls back to first-seen and uses it to break equal published dates", () => {
  const olderFallback = job(10, { posted_at: null, first_seen_at: "2026-09-08T06:00:00Z" });
  const newerFallback = job(11, { posted_at: null, first_seen_at: "2026-09-08T07:00:00Z" });
  const olderTie = job(12, { posted_at: "2026-09-09", first_seen_at: "2026-09-08T08:00:00Z" });
  const newerTie = job(13, { posted_at: "2026-09-09", first_seen_at: "2026-09-08T09:00:00Z" });

  assert.equal(groupDuplicateJobs([olderFallback, newerFallback])[0].job, newerFallback);
  assert.equal(groupDuplicateJobs([olderTie, newerTie])[0].job, newerTie);
});

test("keeps loaded peers reachable after the selected listing leaves the view", () => {
  const selected = job(20, { status: "saved" });
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
