import type { Availability } from "./contracts";

export const NEW_ROLES_POLL_MS = 90_000;
// Focus and visibility polls wait this long after the last poll or list load.
export const NEW_ROLES_MIN_GAP_MS = 15_000;
const EVERYTHING = new Date(0).toISOString();

// Keeps the database's own spelling: re-serialising through Date drops microseconds,
// which would count the newest loaded role as new.
export function newRolesSince(jobs: readonly { first_seen_at: string }[]): string {
  let newest: string | null = null;
  for (const { first_seen_at: seen } of jobs) {
    if (newest === null) { newest = seen; continue; }
    const delta = Date.parse(seen) - Date.parse(newest);
    if (delta > 0 || (delta === 0 && seen > newest)) newest = seen;
  }
  return newest ?? EVERYTHING;
}

export function newRolesCountPath(input: { filter: string; availability: Availability; since: string }): string {
  return `/api/jobs/new-count?${new URLSearchParams({ filter: input.filter, availability: input.availability, since: input.since })}`;
}

export function createNewRolesPollGate(minGapMs = NEW_ROLES_MIN_GAP_MS) {
  let last = 0;
  return {
    reset(now: number) { last = now; },
    shouldPoll(now: number, hidden: boolean) {
      if (hidden || now - last < minGapMs) return false;
      last = now;
      return true;
    },
  };
}

export function newRolesLabel(count: number): string {
  return `${count} new ${count === 1 ? "role" : "roles"}`;
}
