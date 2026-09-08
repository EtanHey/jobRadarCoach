import assert from "node:assert/strict";
import { test } from "node:test";
import { createDetailCoordinator, retainVisitCohort } from "../lib/job-board-state";

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
