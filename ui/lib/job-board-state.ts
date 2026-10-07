import type { ViewOptions } from "./job-filters";
type ListRequest = { filter: string; availability: string; limit: number } & Partial<Pick<ViewOptions, "fit" | "statuses" | "sort">>;
export function jobListCacheKey(input: ListRequest): string {
  const params = new URLSearchParams({ filter: input.filter, availability: input.availability, limit: String(input.limit) });
  if (input.fit !== undefined) params.set("fit", input.fit);
  if (input.statuses !== undefined) params.set("statuses", [...new Set(input.statuses)].sort().join(","));
  if (input.sort !== undefined) params.set("sort", input.sort);
  return params.toString();
}

export function jobListRequestPath(input: ListRequest): string {
  return `/api/jobs?${jobListCacheKey(input)}`;
}

export function updateJobStatus<T extends { id: string; status: string; status_reason: string | null }>(
  jobs: T[], id: string, status: T["status"], statusReason: string | null,
): T[] {
  return jobs.map((job) => job.id === id ? { ...job, status, status_reason: statusReason } : job);
}

export type StatusMutation<S extends string = string> = { status: S; reason: string | null; remove: boolean };

// Applies PATCH replies that landed while this snapshot was being read, so a read that
// started before them cannot undo them (and nothing needs to be read again).
export function reconcileStatusMutations<T extends { id: string; status: string; status_reason: string | null }>(
  jobs: T[], mutations: ReadonlyMap<string, StatusMutation<T["status"]>>,
): T[] {
  if (mutations.size === 0) return jobs;
  return jobs.flatMap((job) => {
    const mutation = mutations.get(job.id);
    if (!mutation) return [job];
    return mutation.remove ? [] : [{ ...job, status: mutation.status, status_reason: mutation.reason }];
  });
}

export function uniqueJobsById<T extends { id: string }>(jobs: T[]): T[] {
  const indexes = new Map<string, number>();
  const unique: T[] = [];
  for (const job of jobs) {
    const index = indexes.get(job.id);
    if (index === undefined) {
      indexes.set(job.id, unique.length);
      unique.push(job);
    } else {
      unique[index] = job;
    }
  }
  return unique.length === jobs.length ? jobs : unique;
}

export function retainVisitCohort<T extends { id: string }>(current: T[] | null, incoming: T[], latest: T[] = []): T[] {
  const uniqueIncoming = uniqueJobsById(incoming);
  if (current === null) return uniqueIncoming;
  const uniqueCurrent = uniqueJobsById(current);
  const incomingById = new Map([...uniqueIncoming, ...latest].map((job) => [job.id, job]));
  const retainedIds = new Set(uniqueCurrent.map((job) => job.id));
  return uniqueCurrent
    .map((job) => incomingById.get(job.id) ?? job)
    .concat(uniqueIncoming.filter((job) => !retainedIds.has(job.id)));
}

// Hydrate excluded retained IDs independently of status/availability and list limits.
// Errors propagate so the UI reports previous results rather than caching stale truth.
export async function refreshVisitCohort<T extends { id: string }>(
  current: T[] | null, incoming: T[], readByIds: (ids: string[]) => Promise<T[]>,
): Promise<T[]> {
  const incomingIds = new Set(incoming.map(job => job.id));
  const missing = [...new Set(current?.filter(job => !incomingIds.has(job.id)).map(job => job.id))];
  const latest: T[] = [];
  for (let offset = 0; offset < missing.length; offset += 100) {
    latest.push(...await readByIds(missing.slice(offset, offset + 100)));
  }
  return retainVisitCohort(current, incoming, latest);
}
