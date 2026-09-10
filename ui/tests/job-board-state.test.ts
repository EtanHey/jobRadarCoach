import assert from "node:assert/strict";
import { test } from "node:test";
import { createBoundedJobListCache, createDetailCoordinator, createListRefreshCoordinator, createRequestFence, jobListCacheKey, retainVisitCohort, uniqueJobsById, updateJobStatus } from "../lib/job-board-state";

test("private list cache keys the complete server query and evicts the least-recently-used view", () => {
  assert.throws(() => createBoundedJobListCache(0), RangeError);
  assert.throws(() => createBoundedJobListCache(-1), RangeError);
  const cache = createBoundedJobListCache<string>(2);
  const all = jobListCacheKey({ filter: "all", limit: 1000 });
  const fresh = jobListCacheKey({ filter: "new-for-me", limit: 1000 });
  const seen = jobListCacheKey({ filter: "seen", limit: 1000 });

  assert.equal(all, "filter=all&limit=1000");
  let repeatedFetches = 0;
  const load = () => cache.get(all) ?? (++repeatedFetches, cache.set(all, "network rows"), "network rows");
  assert.equal(load(), "network rows");
  assert.equal(load(), "network rows");
  assert.equal(repeatedFetches, 1);
  cache.set(all, "all rows");
  cache.set(fresh, "fresh rows");
  assert.equal(cache.get(all), "all rows");
  cache.set(seen, "seen rows");
  assert.equal(cache.get(fresh), undefined);
  assert.equal(cache.get(all), "all rows");
  assert.equal(cache.get(seen), "seen rows");
  cache.clear();
  assert.equal(cache.get(all), undefined);
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

test("status invalidation rejects an older list response before it can refill cache", () => {
  const fence = createRequestFence();
  const beforeMutation = fence.capture();
  assert.equal(fence.isCurrent(beforeMutation), true);
  fence.invalidate();
  assert.equal(fence.isCurrent(beforeMutation), false);
  assert.equal(fence.isCurrent(fence.capture()), true);
});

test("a realtime refresh arriving during a list request schedules one follow-up", () => {
  const coordinator = createListRefreshCoordinator();
  coordinator.beginRequest();

  assert.equal(coordinator.requestRefresh(), false);
  assert.equal(coordinator.requestRefresh(), false);
  assert.equal(coordinator.finishRequest(), true);
  assert.equal(coordinator.finishRequest(), false);
});

test("a reconnect-ready event refreshes loaded cached rows", () => {
  const coordinator = createListRefreshCoordinator();

  assert.equal(coordinator.markReady(), false);
  coordinator.markDisconnected();
  assert.equal(coordinator.markReady(), true);
  assert.equal(coordinator.markReady(), false);
});

test("a reconnect-ready refresh queues behind an in-flight list request", () => {
  const coordinator = createListRefreshCoordinator();
  coordinator.beginRequest();
  coordinator.markDisconnected();

  assert.equal(coordinator.markReady(), true);
  assert.equal(coordinator.requestRefresh(), false);
  assert.equal(coordinator.finishRequest(), true);
});

test("a successful mutation invalidates an older SSE detail read", () => {
  const coordinator = createDetailCoordinator();
  const selected = coordinator.select("job-a");
  const staleSseRead = coordinator.beginRead();

  assert.equal(coordinator.acceptRead(staleSseRead), true);
  assert.equal(coordinator.commitMutation(selected), true);
  assert.equal(coordinator.acceptRead(staleSseRead), false);
});

test("selection generations reject detail work from a previously opened job", () => {
  const coordinator = createDetailCoordinator();
  const firstSelection = coordinator.select("job-a");
  const firstRead = coordinator.beginRead();
  const secondSelection = coordinator.select("job-b");

  assert.equal(coordinator.acceptRead(firstRead), false);
  assert.equal(coordinator.commitMutation(firstSelection), false);
  assert.equal(coordinator.commitMutation(secondSelection), true);
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
