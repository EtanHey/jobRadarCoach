import { retainVisitCohort } from "./job-board-state";
import type { GlobeResponse } from "./globe-contract";
export function retainGlobeCohort(previous: GlobeResponse | null, incoming: GlobeResponse, latest?: GlobeResponse): GlobeResponse {
  if (!previous) return incoming;
  const retainedIds = new Set(previous.jobs.map(job => job.id));
  const updates = latest?.jobs.filter(job => retainedIds.has(job.id)) ?? [];
  const jobs = retainVisitCohort(previous.jobs, incoming.jobs, updates);
  const updatedIds = new Set(updates.map(job => job.id));
  const incomingIds = new Set([...incoming.jobs.map(job => job.id), ...updatedIds]);
  const points = [...incoming.points.filter(point => !updatedIds.has(point.posting_id)),
    ...(latest?.points.filter(point => updatedIds.has(point.posting_id)) ?? []),
    ...previous.points.filter(point => !incomingIds.has(point.posting_id))];
  return { ...incoming, jobs, points, total_count: jobs.length, resolved_count: points.length, unresolved_count: jobs.length - points.length };
}
