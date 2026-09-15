import assert from "node:assert/strict";
import test from "node:test";

import { JobListQuerySchema, JobStatusSchema, StatusPatchSchema } from "../lib/contracts";
import { pipelineStatusOptions, statusLabels, statusOptions } from "../lib/job-status";


test("skipped rows parse without exposing a hosted-unsafe selectable option", () => {
  assert.equal(JobStatusSchema.parse("skipped"), "skipped");
  assert.equal(statusLabels.skipped, "Skipped");
  assert.equal(statusOptions.map(({ value }) => String(value)).includes("skipped"), false);
  assert.equal(pipelineStatusOptions.map(({ value }) => String(value)).includes("skipped"), false);
  assert.equal(StatusPatchSchema.safeParse({ status: "skipped" }).success, false);
  assert.equal(JobListQuerySchema.safeParse({ filter: "skipped" }).success, false);
});
