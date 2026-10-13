import assert from "node:assert/strict";
import { test } from "node:test";
import { jobListCacheKey, jobListRequestPath, retainVisitCohort, refreshVisitCohort, uniqueJobsById, updateJobStatus } from "../lib/job-board-state";

test("list requests key the complete server query", () => {
  assert.equal(jobListCacheKey({ filter: "all", availability: "active", limit: 1000 }), "filter=all&availability=active&limit=1000");
  assert.equal(jobListRequestPath({ filter: "seen", availability: "inactive", limit: 1000 }), "/api/jobs?filter=seen&availability=inactive&limit=1000");
});

test("board requests send fit, pipeline statuses and sort to the server", () => {
  const path = jobListRequestPath({ filter: "all", availability: "active", limit: 1000,
    fit: "recommended", statuses: ["applied", "worth_checking"], sort: "fit" });
  const params = new URL(path, "https://example.test").searchParams;
  assert.equal(params.get("fit"), "recommended");
  assert.equal(params.get("statuses"), "applied,worth_checking");
  assert.equal(params.get("sort"), "fit");
});

test("a status mutation updates the active list without resetting unrelated rows", () => {
  const current = [
    { id: "job-1", status: "new", status_reason: null },
    { id: "job-2", status: "seen", status_reason: null },
  ];
  const updated = updateJobStatus(current, "job-1", "worth_checking", null);

  assert.deepEqual(updated[0], { id: "job-1", status: "worth_checking", status_reason: null });
  assert.equal(updated[1], current[1]);
});

test("new-for-me visit cohort keeps existing order while updating and appending jobs", () => {
  const first = [{ id: "job-1", status: "new" }, { id: "job-2", status: "new" }];
  const refreshed = retainVisitCohort(first, [{ id: "job-3", status: "new" }, { id: "job-1", status: "seen" }]);

  assert.deepEqual(refreshed.map((row) => row.id), ["job-1", "job-2", "job-3"]);
  assert.deepEqual(refreshed.map((row) => row.status), ["seen", "new", "new"]);
  assert.equal(refreshed[1], first[1]);
});

test("a cleared visit cohort starts from the current server result", () => {
  const refreshed = [{ id: "job-3" }, { id: "job-1" }];
  assert.equal(retainVisitCohort(null, refreshed), refreshed);
});

test("an initial snapshot collapses repeated IDs using the latest payload", () => {
  const first = { id: "job-1", status: "new" };
  const second = { id: "job-2", status: "new" };
  const latest = { id: "job-1", status: "seen" };

  const cohort = retainVisitCohort(null, [first, second, latest]);

  assert.deepEqual(cohort.map((row) => row.id), ["job-1", "job-2"]);
  assert.equal(cohort[0], latest);
  assert.equal(cohort[1], second);
});

test("refresh collapses repeated incoming and preexisting IDs without changing first appearance order", () => {
  const staleCurrent = { id: "job-1", revision: "current-old" };
  const retained = { id: "job-2", revision: "current-only" };
  const latestCurrent = { id: "job-1", revision: "current-latest" };
  const firstNew = { id: "job-3", revision: "incoming-old" };
  const staleIncoming = { id: "job-1", revision: "incoming-old" };
  const latestNew = { id: "job-3", revision: "incoming-latest" };
  const latestIncoming = { id: "job-1", revision: "incoming-latest" };

  const cohort = retainVisitCohort(
    [staleCurrent, retained, latestCurrent],
    [firstNew, staleIncoming, latestNew, latestIncoming],
  );

  assert.deepEqual(cohort.map((row) => row.id), ["job-1", "job-2", "job-3"]);
  assert.equal(cohort[0], latestIncoming);
  assert.equal(cohort[1], retained);
  assert.equal(cohort[2], latestNew);
});

test("unique IDs preserve their input array reference", () => {
  const jobs = [{ id: "job-1" }, { id: "job-2" }];
  assert.equal(uniqueJobsById(jobs), jobs);
});


test("retained card absent from incoming refreshes all fields without moving or admitting unrelated rows", () => {
  const current = [{ id: "a", status: "new", title: "old" }, { id: "b", status: "new", title: "B" }];
  const latest = [{ id: "a", status: "applied", title: "updated" }, { id: "unrelated", status: "seen", title: "other" }];
  const next = retainVisitCohort(current, [{ id: "c", status: "new", title: "C" }, current[1]], latest);
  assert.deepEqual(next.map(job => job.id), ["a", "b", "c"]);
  assert.deepEqual(next[0], latest[0]);
});


test("refresh hydrates only absent retained IDs in bounded batches, including an empty new cohort", async () => {
  const current = Array.from({ length: 205 }, (_, n) => ({ id: String(n), status: "new" }));
  const calls: string[][] = [];
  const refreshed = await refreshVisitCohort(current, [], ids => {
    calls.push(ids);
    return Promise.resolve(ids.map(id => ({ id, status: "applied" })));
  });
  assert.deepEqual(calls.map(ids => ids.length), [100, 100, 5]);
  assert.deepEqual(refreshed.map(job => job.id), current.map(job => job.id));
  assert.ok(refreshed.every(job => job.status === "applied"));
  await refreshVisitCohort(null, current, () => { throw new Error("unnecessary fetch"); });
  await refreshVisitCohort(current, current, () => { throw new Error("unnecessary fetch"); });
  await assert.rejects(refreshVisitCohort(current, [], () => { throw new Error("offline"); }), /offline/);
});
