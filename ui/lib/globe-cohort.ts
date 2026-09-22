import { retainVisitCohort } from "./job-board-state";
import type { GlobeResponse } from "./globe-contract";
export function retainGlobeCohort(previous: GlobeResponse | null, incoming: GlobeResponse): GlobeResponse {
  if (!previous) return incoming;
  const jobs = retainVisitCohort(previous.jobs, incoming.jobs);
  const incomingIds = new Set(incoming.jobs.map(job => job.id));
  const points = [...incoming.points, ...previous.points.filter(point => !incomingIds.has(point.posting_id))];
  return { ...incoming, jobs, points, total_count: jobs.length, resolved_count: points.length, unresolved_count: jobs.length - points.length };
}
