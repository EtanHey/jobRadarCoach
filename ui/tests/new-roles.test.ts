import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";

import { createNewRolesPollGate, NEW_ROLES_MIN_GAP_MS, NEW_ROLES_POLL_MS, newRolesCountPath, newRolesLabel, newRolesSince } from "../lib/new-roles";

const uiRoot = resolve(import.meta.dirname, "..");

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

test("the count path carries the view's filter, availability and cutoff", () => {
  const path = newRolesCountPath({ filter: "new-for-me", availability: "active", since: "2026-10-05T10:00:00.123456+00:00" });
  const url = new URL(path, "http://localhost");
  assert.equal(url.pathname, "/api/jobs/new-count");
  assert.deepEqual(Object.fromEntries(url.searchParams), { filter: "new-for-me", availability: "active", since: "2026-10-05T10:00:00.123456+00:00" });
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

test("the pill label is singular for one role", () => {
  assert.equal(newRolesLabel(1), "1 new role");
  assert.equal(newRolesLabel(20), "20 new roles");
});

test("the board opens no SSE connection and the events route is gone", () => {
  assert.equal(existsSync(resolve(uiRoot, "app/api/events/route.ts")), false);
  const board = readFileSync(resolve(uiRoot, "components/job-board.tsx"), "utf8");
  assert.doesNotMatch(board, /EventSource|\/api\/events/);
  assert.doesNotMatch(board, /Live updates/);
});

test("a successful status change, manual or automatic Seen, does not refetch the list", () => {
  const board = readFileSync(resolve(uiRoot, "components/job-board.tsx"), "utf8");
  const changeStatus = board.slice(board.indexOf("async function changeStatus"), board.indexOf("if (!preferencesReady) return <div"));
  assert.ok(changeStatus.length > 0);
  const autoSeen = board.slice(board.indexOf("patchStarted = true"), board.indexOf("open();"));
  assert.ok(autoSeen.length > 0);
  for (const [name, body] of [["changeStatus", changeStatus], ["automatic Seen", autoSeen]]) {
    const success = body.slice(0, body.indexOf("catch (cause)"));
    assert.doesNotMatch(success, /requestRefresh\(\)/, name);
  }
});
