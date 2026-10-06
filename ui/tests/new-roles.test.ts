import assert from "node:assert/strict";
import { test } from "node:test";

import type { JobSummary } from "../lib/contracts";
import { reconcileStatusMutations } from "../lib/job-board-state";
import { defaultBoardPreferences } from "../lib/job-board-preferences";
import { countNewRoleCards, createNewRolesPollGate, NEW_ROLES_LIMIT, NEW_ROLES_MIN_GAP_MS, NEW_ROLES_POLL_MS, newRolesLabel, newRolesRequestPath, newRolesSince } from "../lib/new-roles";

test("the cutoff is the newest loaded first_seen_at, verbatim, so the newest loaded role is never counted as new", () => {
  const jobs = [
    { first_seen_at: "2026-10-05T09:00:00.000001+00:00" },
    { first_seen_at: "2026-10-05T10:00:00.123456+00:00" },
    { first_seen_at: "2026-10-05T10:00:00.123455+00:00" },
    { first_seen_at: "2026-10-04T23:00:00Z" },
  ];
  assert.equal(newRolesSince(jobs), "2026-10-05T10:00:00.123456+00:00");
});

test("an empty view counts every matching role, since nothing of it is loaded", () => {
  assert.equal(newRolesSince([]), "1970-01-01T00:00:00.000Z");
});

test("the poll asks the list endpoint for a bounded page of roles newer than the cutoff", () => {
  const path = newRolesRequestPath({ filter: "new-for-me", availability: "active", since: "2026-10-05T10:00:00.123456+00:00" });
  const url = new URL(path, "http://localhost");
  assert.equal(url.pathname, "/api/jobs");
  assert.deepEqual(Object.fromEntries(url.searchParams), { filter: "new-for-me", availability: "active", limit: String(NEW_ROLES_LIMIT + 1), since: "2026-10-05T10:00:00.123456+00:00" });
});

test("the poll is cheap: every 90s, and focus or visibility polls only after a quiet gap", () => {
  assert.equal(NEW_ROLES_POLL_MS, 90_000);
  const gate = createNewRolesPollGate();
  gate.reset(1_000);
  assert.equal(gate.shouldPoll(1_000 + NEW_ROLES_MIN_GAP_MS - 1, false), false, "a list that just loaded is fresh");
  assert.equal(gate.shouldPoll(1_000 + NEW_ROLES_MIN_GAP_MS, false), true);
  assert.equal(gate.shouldPoll(1_000 + NEW_ROLES_MIN_GAP_MS + 1, false), false, "focus right after a poll does not poll again");
  assert.equal(gate.shouldPoll(1_000 + NEW_ROLES_POLL_MS, true), false, "a hidden tab never polls");
  assert.equal(gate.shouldPoll(1_000 + NEW_ROLES_POLL_MS, false), true);
});

test("the pill label is singular for one role and marks a truncated page", () => {
  assert.equal(newRolesLabel(1, false), "1 new role");
  assert.equal(newRolesLabel(20, false), "20 new roles");
  assert.equal(newRolesLabel(100, true), "100+ new roles");
});

const role = (n: number, overrides: Partial<JobSummary> = {}): JobSummary => ({
  id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, title: `Engineer ${n}`, company: `Company ${n}`, source: "linkedin",
  last_seen_at: "2026-10-05T10:00:00Z", first_seen_at: "2026-10-05T10:00:00Z", experience: null, description_available: false,
  seniority_origin: "unknown", extraction_state: "not-extracted", location: "Tel Aviv, Israel", remote: null, seniority: null,
  stack: [], salary: null, url: "https://example.test/job", apply_url: null, posted_at: null, status: "new", status_reason: null,
  score: 90, fit_line: null, recommendation: "apply", alive: true, ...overrides,
});

test("the pill counts cards Show will add under the current view, not raw postings", () => {
  const view = { ...defaultBoardPreferences().view, fit: "recommended" };
  const current = [role(0)];
  assert.equal(countNewRoleCards(current, [role(1, { score: 20, recommendation: "skip" })], view), 0, "a role the view hides is not new to the reader");
  assert.equal(countNewRoleCards(current, [role(2), role(3, { title: "Engineer 2", company: "Company 2" })], view), 1, "two postings of one role are one card");
  assert.equal(countNewRoleCards(current, [role(4, { title: "Engineer 0", company: "Company 0" })], view), 0, "a newer listing of a visible card adds no card");
  assert.equal(countNewRoleCards(current, [role(5, { title: "Searchable" })], { ...view, search: "nothing matches" }), 0, "search applies");
  assert.equal(countNewRoleCards(current, [role(6), role(7, { score: 20, recommendation: "skip" })], { ...view, fit: "" }), 2);
});

test("a confirmed status PATCH is reconciled into a list read that may predate it", () => {
  const read = [role(0), role(1), role(2)];
  const mutations = new Map([
    [role(0).id, { status: "seen" as const, reason: null, remove: false }],
    [role(1).id, { status: "applied" as const, reason: null, remove: true }],
  ]);
  const settled = reconcileStatusMutations(read, mutations);
  assert.deepEqual(settled.map(job => [job.id, job.status]), [[role(0).id, "seen"], [role(2).id, "new"]]);
  assert.equal(reconcileStatusMutations(read, new Map()), read, "no mutations keeps the snapshot identity");
});
