import type { Availability, FoundWithin } from "./contracts";
import type { GlobeJob } from "./globe-contract";
import { uniqueJobsById } from "./job-board-state";
import { filterJobGroups, type ViewOptions } from "./job-filters";

export const NEW_ROLES_POLL_MS = 90_000;
// Focus and visibility polls wait this long after the last poll or list load.
export const NEW_ROLES_MIN_GAP_MS = 15_000;
// The poll reads at most this many newer postings; one extra row marks the page as truncated.
export const NEW_ROLES_LIMIT = 100;
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

export function newRolesRequestPath(input: { filter: string; availability: Availability; since: string; found_within?: FoundWithin }): string {
  const params = new URLSearchParams({ filter: input.filter, availability: input.availability, since: input.since });
  if (input.found_within) params.set("found_within", input.found_within);
  return `/api/jobs/new-roles?${params}`;
}

// The pill's number is the cards Show would add: the board's own view filters and
// duplicate grouping run over the loaded list with and without the newer postings.
export function countNewRoleCards(current: GlobeJob[], incoming: GlobeJob[], view: ViewOptions): number {
  if (incoming.length === 0) return 0;
  const visible = new Set(filterJobGroups(current, view).flatMap(group => [group.job, ...group.alternates].map(job => job.id)));
  return filterJobGroups(uniqueJobsById([...current, ...incoming]), view)
    .filter(group => ![group.job, ...group.alternates].some(job => visible.has(job.id))).length;
}

// A truncated page only samples the newest postings, so zero visible matches there is not
// zero arrivals: offer Show without claiming a number.
export function newRolesNotice(count: number, truncated: boolean): string | null {
  if (count === 0) return truncated ? "New roles may be available" : null;
  return `${count}${truncated ? "+" : ""} new ${count === 1 && !truncated ? "role" : "roles"}`;
}
