import assert from "node:assert/strict";
import { test } from "node:test";
import { postingDates, publishedAge, relativeAge, workMode } from "../lib/job-display";
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

test("cards keep published and first-discovery dates distinct", () => {
  const found = "2026-09-08T10:00:00Z";
  const posted = "2026-09-07T12:00:00Z";
  assert.deepEqual(postingDates(posted, found, now), [
    { label: "Posted 1d ago", dateTime: posted },
    { label: "Found 2h ago", dateTime: found },
  ]);
  assert.deepEqual(postingDates(null, found, now), [{ label: "Found 2h ago", dateTime: found }]);
  assert.deepEqual(postingDates("invalid", found, now), [{ label: "Found 2h ago", dateTime: found }]);
  assert.deepEqual(postingDates(posted, null, now), [{ label: "Posted 1d ago", dateTime: posted }]);
  assert.deepEqual(postingDates(null, null, now), [{ label: "Date unavailable", dateTime: undefined }]);
});
