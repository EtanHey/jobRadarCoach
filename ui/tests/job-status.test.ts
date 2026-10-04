import assert from "node:assert/strict";
import { test } from "node:test";
import { isStatusPatchNoop, statusMutationRemovesCard } from "../lib/job-status";

test("same status is a no-op, while a different status is a mutation", () => {
  assert.equal(isStatusPatchNoop({ status: "new", status_reason: null }, { status: "new" }), true);
  assert.equal(isStatusPatchNoop({ status: "seen", status_reason: null }, { status: "seen" }), true);
  assert.equal(isStatusPatchNoop({ status: "seen", status_reason: null }, { status: "new" }), false);
});

test("a same-status rejection still saves a changed verbatim reason", () => {
  const rejected = { status: "rejected" as const, status_reason: "Role filled" };
  assert.equal(isStatusPatchNoop(rejected, { status: "rejected", reason: "Role filled" }), true);
  assert.equal(isStatusPatchNoop(rejected, { status: "rejected", reason: " Role filled " }), false);
  assert.equal(isStatusPatchNoop(rejected, { status: "rejected", reason: "Team paused hiring" }), false);
  assert.equal(isStatusPatchNoop({ status: "not_relevant", status_reason: "Wrong stack" }, { status: "not_relevant" }), true);
  assert.equal(isStatusPatchNoop({ status: "not_relevant", status_reason: "Wrong stack" }, { status: "not_relevant", reason: "Location" }), false);
});

test("New transitions retain the card, while explicit non-New edits may remove it", () => {
  assert.equal(statusMutationRemovesCard("new-for-me", "new"), false);
  for (const status of ["seen", "applied", "worth_checking", "rejected"] as const) {
    assert.equal(statusMutationRemovesCard("new-for-me", status), true);
    assert.equal(statusMutationRemovesCard("all", status), false);
  }
});
