import type { JobSummary } from "./contracts";
import { uniqueJobsById } from "./job-board-state";

export type DuplicateJobGroup = { job: JobSummary; alternates: JobSummary[] };

function normalizedIdentity(value: string): string {
  return value.normalize("NFKC").trim().replace(/\s+/gu, " ").toLowerCase();
}

function duplicateJobKey(job: Pick<JobSummary, "title" | "company" | "source">): string {
  return JSON.stringify([
    normalizedIdentity(job.title),
    normalizedIdentity(job.company),
    normalizedIdentity(job.source),
  ]);
}

function timestamp(value: string | null): number | null {
  if (value === null) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function descending(a: number, b: number): number {
  if (a === b) return 0;
  return a > b ? -1 : 1;
}

function representativeTime(job: JobSummary): number {
  return timestamp(job.posted_at) ?? timestamp(job.first_seen_at) ?? -Infinity;
}

function newestFirst(a: JobSummary, b: JobSummary): number {
  return descending(representativeTime(a), representativeTime(b))
    || descending(timestamp(a.first_seen_at) ?? -Infinity, timestamp(b.first_seen_at) ?? -Infinity)
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

export function groupDuplicateJobs(jobs: JobSummary[]): DuplicateJobGroup[] {
  const groups = new Map<string, JobSummary[]>();
  for (const job of uniqueJobsById(jobs)) {
    const key = duplicateJobKey(job);
    const group = groups.get(key);
    if (group) group.push(job);
    else groups.set(key, [job]);
  }
  return [...groups.values()].map((members) => {
    const [job, ...alternates] = [...members].sort(newestFirst);
    return { job, alternates };
  });
}

export function relatedDuplicateJobs(
  jobs: JobSummary[], selectedId: string, loadedDetail: JobSummary | null,
): JobSummary[] {
  const selectedJob = loadedDetail?.id === selectedId
    ? loadedDetail
    : jobs.find((job) => job.id === selectedId);
  if (!selectedJob) return [];
  const key = duplicateJobKey(selectedJob);
  return uniqueJobsById(jobs)
    .filter((job) => job.id !== selectedId && duplicateJobKey(job) === key)
    .sort(newestFirst);
}

export function shortListingId(id: string): string {
  return id.slice(-8);
}
