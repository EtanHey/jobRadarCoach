import assert from "node:assert/strict";
import { test } from "node:test";
import { timestamp } from "../lib/job-time";

test("timestamp distinguishes missing chronology from epoch and pre-epoch dates", () => {
  for (const value of [null, undefined, "", "invalid"]) assert.equal(timestamp(value), null);
  assert.equal(timestamp("1970-01-01T00:00:00Z"), 0);
  assert.equal(timestamp("1969-12-31T23:59:59Z"), -1000);
  assert.equal(timestamp("2026-10-06T12:00:00Z"), Date.parse("2026-10-06T12:00:00Z"));
});
