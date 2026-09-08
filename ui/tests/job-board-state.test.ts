import assert from "node:assert/strict";
import { test } from "node:test";
import { createDetailCoordinator, retainVisitCohort, uniqueJobsById } from "../lib/job-board-state";

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
