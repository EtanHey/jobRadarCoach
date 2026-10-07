import { queryOptions, type QueryClient } from "@tanstack/react-query";
import type { Availability, JobDetail, JobSummary, StatusResult } from "./contracts";
import { statusMutationRemovesCard } from "./job-status";
import { uniqueJobsById, updateJobStatus } from "./job-board-state";
import type { BoardFilter } from "./job-board-preferences";
import { loadJobDetail } from "./job-detail-request";
import type { ViewOptions } from "./job-filters";

export type CachedList = { jobs: JobSummary[]; loadedUpdatedAt: string | null };
export const boardListKey = (filter: BoardFilter, availability: Availability, view?: Pick<ViewOptions, "fit" | "statuses" | "sort" | "found_within">) =>
  ["board-list", filter, availability, view?.fit ?? "", [...new Set(view?.statuses ?? [])].sort().join(","), view?.sort ?? "fit", view?.found_within ?? ""] as const;
// Facet-specific snapshots still belong to one New-for-me visit. Keep settled
// cards when a sort/fit change creates a new query, and hydrate them by ID.
export function cachedVisitCohort(client: QueryClient, availability: Availability, foundWithin: ViewOptions["found_within"] = ""): JobSummary[] | null {
  const snapshots = client.getQueriesData<CachedList>({ queryKey: ["board-list", "new-for-me", availability] })
    .flatMap(([key, data]) => data && (key[6] ?? "") === (foundWithin ?? "") ? [data.jobs] : []);
  return snapshots.length ? uniqueJobsById(snapshots.flat()) : null;
}
type Confirmation = { id: string; result: StatusResult; automatic: boolean; revision: number };
export const confirmedStatusRevision = (client: QueryClient) => client.getQueryData<number>(["board-status-revision"]) ?? 0;

// A held Show read must still contribute its arrivals. Replay only PATCH confirmations
// committed after that read began; later reads use server truth, even in the same clock tick.
export function confirmListRead(client: QueryClient, jobs: JobSummary[], filter: BoardFilter, started: number) {
  for (const [, confirmation] of client.getQueriesData<Confirmation>({ queryKey: ["board-status"] })) {
    if (!confirmation || confirmation.revision <= started) continue;
    const { id, result, automatic } = confirmation;
    jobs = updateJobStatus(jobs, id, result.status, result.reason);
    if (!automatic && statusMutationRemovesCard(filter, result.status)) jobs = jobs.filter(job => job.id !== id);
  }
  const rescued = client.getQueryData<Record<string, number>>(["board-score-anyway"]) ?? {};
  jobs = jobs.map(job => (rescued[job.id] ?? 0) > started ? { ...job, relevance_filtered: false } : job);
  return jobs.filter(job => Boolean(job.relevance_filtered) === (filter === "not-scored"));
}

export function confirmDetailRead(client: QueryClient, job: JobDetail, started: number) {
  if ((client.getQueryData<Record<string, number>>(["board-score-anyway"]) ?? {})[job.id] > started) job = { ...job, relevance_filtered: false };
  const confirmation = client.getQueryData<Confirmation>(["board-status", job.id]);
  return confirmation && confirmation.revision > started ? { ...job, status: confirmation.result.status, status_reason: confirmation.result.reason } : job;
}

// Hover prefetch and the drawer share this query, so opening a warmed card renders from cache.
// Fresh for 30 s: re-hovering never refetches; an older entry still renders while one read refreshes it.
export const DETAIL_STALE_MS = 30_000;
export const jobDetailQueryOptions = (client: QueryClient, id: string | null) => queryOptions({
  queryKey: ["board-detail", id] as const,
  queryFn: async ({ signal }) => {
    if (id === null) throw new Error("Select a role to load its details.");
    const started = confirmedStatusRevision(client);
    return confirmDetailRead(client, await loadJobDetail(id, signal), started);
  },
  staleTime: DETAIL_STALE_MS,
  gcTime: 60_000,
});

// A status reply is not a detail read: keep the read's timestamp, so score and body still
// refresh 30 s after the last GET however often the role is reopened or re-saved.
export function patchCachedDetailStatus(client: QueryClient, id: string, result: StatusResult) {
  for (const query of client.getQueryCache().findAll({ queryKey: ["board-detail", id] })) {
    client.setQueryData<JobDetail>(query.queryKey, job => job ? { ...job, status: result.status, status_reason: result.reason } : job,
      { updatedAt: query.state.dataUpdatedAt });
  }
}

export function applyConfirmedStatus(client: QueryClient, id: string, result: StatusResult, automatic: boolean) {
  // Confirmations belong to this board client. GC must not reset their ordering
  // while a read is running; list/detail queries keep their own GC settings.
  client.setQueryDefaults(["board-status"], { gcTime: Infinity });
  client.setQueryDefaults(["board-status-revision"], { gcTime: Infinity });
  const revision = confirmedStatusRevision(client) + 1;
  client.setQueryData(["board-status-revision"], revision);
  client.setQueryData<Confirmation>(["board-status", id], { id, result, automatic, revision });
  client.removeQueries({ queryKey: ["board-list"], type: "inactive" });
  for (const [key] of client.getQueriesData<CachedList>({ queryKey: ["board-list"], type: "active" })) {
    client.setQueryData<CachedList>(key, current => {
      if (!current) return current;
      const jobs = updateJobStatus(current.jobs, id, result.status, result.reason);
      const remove = !automatic && statusMutationRemovesCard(key[1] as BoardFilter, result.status);
      return { ...current, jobs: remove ? jobs.filter(job => job.id !== id) : jobs };
    });
  }
}


export function applyScoreAnyway(client: QueryClient, job: JobDetail) {
  client.setQueryDefaults(["board-score-anyway"], { gcTime: Infinity });
  const revision = confirmedStatusRevision(client) + 1;
  client.setQueryData(["board-status-revision"], revision);
  client.setQueryData<Record<string, number>>(["board-score-anyway"], ids => ({ ...ids, [job.id]: revision }));
  client.setQueryData(["board-detail", job.id], job);
  client.removeQueries({ queryKey: ["board-list"], type: "inactive" });
  for (const [key] of client.getQueriesData<CachedList>({ queryKey: ["board-list"], type: "active" })) {
    client.setQueryData<CachedList>(key, current => current ? { ...current,
      jobs: key[1] === "not-scored" ? current.jobs.filter(row => row.id !== job.id) : current.jobs,
    } : current);
  }
}
