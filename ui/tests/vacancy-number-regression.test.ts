import { test } from "node:test";
import assert from "node:assert/strict";
import { vacancyIdentity } from "../lib/vacancy-identity";
import { groupDuplicateJobs } from "../lib/job-dedup";
import type { GlobeJob } from "../lib/globe-contract";

const base = {company: "Acme", title: "Engineer", location: "Tel Aviv", apply_url: null,
  posted_at: null, first_seen_at: "2026-01-01T00:00:00Z", source: "greenhouse",
  remote: null, seniority: null, stack: [], status: "new", status_reason: null,
  score: null, recommendation: null, alive: null} satisfies Omit<GlobeJob, "id" | "url">;
const tracking = {...base, id: "1", url: "https://boards.greenhouse.io/acme/jobs/90001?utm_campaign=12345", raw_jd: "Req ID: 12345"};
const other = {...base, id: "2", url: "https://boards.greenhouse.io/acme/jobs/90002", raw_jd: "Req ID: 67890"};
const unpunctuated = {...tracking, url: "https://boards.greenhouse.io/acme/jobs/90001", raw_jd: "Job Req 12345"};
const otherUnpunctuated = {...other, raw_jd: "Job Req 67890"};

test("an unrelated tracking number preserves an explicit requisition", () => {
  assert.deepEqual(vacancyIdentity(tracking).requisitions, ["12345"]);
});
test("distinct requisitions stay separate when a URL has numeric tracking", () => {
  for (const rows of [[tracking, other], [other, tracking]]) assert.equal(groupDuplicateJobs(rows).length, 2);
});
test("the explicit Job Req label allows an omitted colon", () => {
  assert.deepEqual(vacancyIdentity(unpunctuated).requisitions, ["12345"]);
});
test("distinct unpunctuated Job Req labels prevent merging", () => {
  for (const rows of [[unpunctuated, otherUnpunctuated], [otherUnpunctuated, unpunctuated]]) assert.equal(groupDuplicateJobs(rows).length, 2);
});
