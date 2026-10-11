import assert from "node:assert/strict";
import { test } from "node:test";
import { FoundWithinSchema, JobListQuerySchema } from "../lib/contracts";
import { foundWithinCutoff } from "../lib/job-filters";
import { foundWithinOptions, fitOptions, sortOptions } from "../lib/view-options";
import { usesBoardRpc } from "../lib/server";

test("every offered window round-trips and uses its inclusive day cutoff", () => {
  const now = Date.parse("2026-10-11T00:00:00Z");
  for (const { value, days } of foundWithinOptions) {
    assert.equal(FoundWithinSchema.parse(value), value);
    assert.equal(foundWithinCutoff(value, now), days === null ? null : now - days * 86400000);
  }
  assert.equal(FoundWithinSchema.safeParse("2d").success, false);
  for (const { value } of fitOptions) assert.equal(JobListQuerySchema.parse({ filter: "all", fit: value }).fit, value);
  for (const { value } of sortOptions) assert.equal(JobListQuerySchema.parse({ filter: "all", sort: value }).sort, value);
});

test("RPC routing keeps neutral facets explicit and poll windows on the cursor path", () => {
  const base = { filter: "all" as const, availability: "active" as const, limit: 50 };
  assert.equal(usesBoardRpc(base), false);
  assert.equal(usesBoardRpc({ ...base, found_within: "" }), false);
  assert.equal(usesBoardRpc({ ...base, found_within: "7d" }), true);
  assert.equal(usesBoardRpc({ ...base, since: "2026-10-11T00:00:00Z", found_within: "7d" }), false);
  for (const facets of [{ fit: "" as const }, { sort: "fit" as const }, { statuses: [] }]) assert.equal(usesBoardRpc({ ...base, ...facets }), true);
});
