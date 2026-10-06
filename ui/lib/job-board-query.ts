import type { QueryClient } from "@tanstack/react-query";
import type { Availability, JobDetail, JobSummary, StatusResult } from "./contracts";
import { statusMutationRemovesCard } from "./job-status";
import { updateJobStatus } from "./job-board-state";
import type { BoardFilter } from "./job-board-preferences";

export type CachedList = { jobs: JobSummary[]; loadedUpdatedAt: string | null };
export const boardListKey = (filter: BoardFilter, availability: Availability) => ["board-list", filter, availability] as const;
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
  return jobs;
}

export function confirmDetailRead(client: QueryClient, job: JobDetail, started: number) {
  const confirmation = client.getQueryData<Confirmation>(["board-status", job.id]);
  return confirmation && confirmation.revision > started ? { ...job, status: confirmation.result.status, status_reason: confirmation.result.reason } : job;
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
