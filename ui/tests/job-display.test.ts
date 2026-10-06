import assert from "node:assert/strict";
import { test } from "node:test";
import { postingDates, relativeAge, repostNote, workMode, workModeOf } from "../lib/job-display";
const now = Date.parse("2026-09-08T12:00:00Z");
test("relative observation ages clamp future and recent dates", () => {
  assert.equal(relativeAge("2026-09-09T12:00:00Z", now), "just now");
  assert.equal(relativeAge("2026-09-08T11:59:59Z", now), "just now");
});
test("unknown work mode stays unknown", () => {
  assert.equal(workMode(null), "Work mode unspecified");
  assert.equal(workMode(true), "Remote");
  assert.equal(workMode(false), "On-site");
});

test("each date kind gets its icon kind, compact age and full accessible wording", () => {
  const found = "2026-09-08T10:00:00Z";
  const posted = "2026-09-07T12:00:00Z";
  assert.deepEqual(postingDates(posted, found, now, null, "UTC"), [
    { kind: "posted", short: "1d", tooltip: "Posted 2026-09-07", label: "Posted 2026-09-07, 1 day ago", dateTime: posted },
    { kind: "found", short: "2h", tooltip: "Found by JRC 2026-09-08 10:00", label: "Found by JRC 2026-09-08 10:00, 2 hours ago", dateTime: found },
  ]);
  assert.deepEqual(postingDates(null, found, now, null, "UTC").map(date => date.kind), ["found"]);
  assert.deepEqual(postingDates("invalid", found, now, null, "UTC").map(date => date.kind), ["found"]);
  assert.deepEqual(postingDates(posted, null, now, null, "UTC").map(date => date.kind), ["posted"]);
  assert.deepEqual(postingDates(null, null, now), []);
  assert.equal(postingDates(null, "2026-09-08T11:30:00Z", now, null, "UTC")[0].short, "now");
  assert.equal(postingDates(null, "2026-09-08T11:30:00Z", now, null, "UTC")[0].label, "Found by JRC 2026-09-08 11:30, just now");
});

test("discovery time is shown in the viewer's time zone", () => {
  assert.equal(postingDates(null, "2026-10-03T11:10:00Z", now, null, "Asia/Jerusalem")[0].tooltip, "Found by JRC 2026-10-03 14:10");
  assert.equal(postingDates("2026-09-01T22:30:00Z", null, now, null, "Asia/Jerusalem")[0].tooltip, "Posted 2026-09-02");
});

test("a later publication is a Republished date; equal or invalid instants are not reposts", () => {
  const original = "2026-09-01T12:00:00Z", latest = "2026-09-07T12:00:00Z", found = "2026-09-08T10:00:00Z";
  assert.deepEqual(postingDates(original, found, now, latest, "UTC").map(({ kind, short, tooltip }) => ({ kind, short, tooltip })), [
    { kind: "posted", short: "7d", tooltip: "Posted 2026-09-01" },
    { kind: "republished", short: "1d", tooltip: "Republished 2026-09-07" },
    { kind: "found", short: "2h", tooltip: "Found by JRC 2026-09-08 10:00" },
  ]);
  assert.deepEqual(postingDates(original, found, now, "2026-09-01T14:00:00+02:00").map(date => date.kind), ["posted", "found"]);
  assert.deepEqual(postingDates(original, found, now, "invalid").map(date => date.kind), ["posted", "found"]);
  assert.deepEqual(postingDates(null, found, now, latest, "UTC").map(({ kind, tooltip }) => ({ kind, tooltip })), [
    { kind: "published", tooltip: "Published 2026-09-07" },
    { kind: "found", tooltip: "Found by JRC 2026-09-08 10:00" },
  ]);
});

test("repost note covers a later republish and linked past listings, and nothing else", () => {
  const original = "2026-09-01T12:00:00Z", latest = "2026-09-07T12:00:00Z";
  assert.equal(repostNote(original, latest, 0, "UTC"), "Reposted: republished 2026-09-07");
  assert.equal(repostNote(original, original, 0, "UTC"), null);
  assert.equal(repostNote(original, null, 0, "UTC"), null);
  assert.equal(repostNote(original, null, 1, "UTC"), "Reposted: 1 earlier listing of this role");
  assert.equal(repostNote(original, latest, 2, "UTC"), "Reposted: republished 2026-09-07 · 2 earlier listings of this role");
});

test("work mode reads a structured mode first and falls back to the remote flag", () => {
  assert.deepEqual(workModeOf({ remote: true }), { kind: "remote", label: "Remote" });
  assert.deepEqual(workModeOf({ remote: false }), { kind: "on-site", label: "On-site" });
  assert.deepEqual(workModeOf({ remote: null }), { kind: "unknown", label: "Work mode unspecified" });
  assert.deepEqual(workModeOf({ remote: null, work_mode: "hybrid" }), { kind: "hybrid", label: "Hybrid" });
  assert.deepEqual(workModeOf({ remote: false, work_mode: "Hybrid" }), { kind: "hybrid", label: "Hybrid" });
  for (const value of ["onsite", "on_site", "on-site", "On-site"]) assert.equal(workModeOf({ remote: null, work_mode: value }).kind, "on-site", value);
  assert.equal(workModeOf({ remote: null, work_mode: "remote" }).kind, "remote");
  assert.equal(workModeOf({ remote: true, work_mode: "flexible" }).kind, "remote", "an unknown structured value falls back to the flag");
  assert.equal(workModeOf({ remote: null, work_mode: "flexible" }).kind, "unknown");
  for (const value of ["constructor", "__proto__", "toString"]) assert.equal(workModeOf({ remote: false, work_mode: value }).kind, "on-site", `inherited key ${value} falls back to the flag`);
});
