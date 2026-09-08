import assert from "node:assert/strict";
import { test } from "node:test";
import { postingDate, publishedAge, relativeAge, workMode } from "../lib/job-display";
const now = Date.parse("2026-09-08T12:00:00Z");
test("published dates never substitute observation dates", () => {
  assert.equal(publishedAge(null, now), "Posted date unavailable");
  assert.equal(publishedAge("invalid", now), "Posted date unavailable");
  assert.equal(publishedAge("2026-09-08T10:00:00Z", now), "Posted 2h ago");
  assert.equal(publishedAge("2026-09-07T12:00:00Z", now), "Posted 1d ago");
  assert.equal(relativeAge("2026-09-09T12:00:00Z", now), "just now");
  assert.equal(relativeAge("2026-09-08T11:59:59Z", now), "just now");
});
test("unknown work mode stays unknown", () => {
  assert.equal(workMode(null), "Work mode unspecified");
  assert.equal(workMode(true), "Remote");
  assert.equal(workMode(false), "On-site");
});

test("cards distinguish published dates from first discovery", () => {
  const found = "2026-09-08T10:00:00Z";
  assert.deepEqual(postingDate(null, found, now), { label: "Found 2h ago", dateTime: found });
  assert.deepEqual(postingDate("invalid", found, now), { label: "Found 2h ago", dateTime: found });
  const posted = "2026-09-07T12:00:00Z";
  assert.deepEqual(postingDate(posted, found, now), { label: "Posted 1d ago", dateTime: posted });
  assert.deepEqual(postingDate(null, null, now), { label: "Found date unavailable", dateTime: undefined });
});
