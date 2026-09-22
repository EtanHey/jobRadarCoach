import "server-only";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { JobSummary } from "./contracts";
import { filterJobs } from "./job-filters";
import { GlobePointSchema, type GlobePoint, type GlobeQuery, type GlobeResponse } from "./globe-contract";
import { client, data, parseSummaryRows } from "./server";
import { HttpError } from "./http";

export interface GlobeStore {
  snapshot(input: GlobeQuery): Promise<{ jobs: JobSummary[]; geo: unknown[] }>;
}
export function getGlobeStore(db: SupabaseClient = client()): GlobeStore {
  return { async snapshot(input) {
    // Jobs, visit cutoff and geo share one SQL statement snapshot, even for empty results.
    const raw = await data(db.rpc("get_globe_snapshot", { filter: input.filter, availability: input.availability }));
    if (!raw || typeof raw !== "object" || !("jobs" in raw) || !("geo" in raw) || !Array.isArray(raw.geo)) {
      throw new HttpError(503, "Geographic data unavailable.");
    }
    return { jobs: parseSummaryRows(raw.jobs).jobs, geo: raw.geo };
  } };
}
export async function globeResponse(store: GlobeStore, input: GlobeQuery): Promise<GlobeResponse> {
  const snapshot = await store.snapshot(input);
  const jobs = filterJobs(snapshot.jobs, input).filter((job) =>
    (input.remote === undefined || job.remote === input.remote) &&
    (input.min_score === undefined || (job.score !== null && job.score >= input.min_score)));
  const ids = new Set(jobs.map((job) => job.id));
  if (ids.size !== jobs.length) throw new HttpError(503, "Invalid geographic snapshot.");
  const points: GlobePoint[] = [];
  for (const row of snapshot.geo) {
    const parsed = GlobePointSchema.safeParse(row);
    if (parsed.success && ids.delete(parsed.data.posting_id)) points.push(parsed.data);
  }
  return { jobs, points, total_count: jobs.length, resolved_count: points.length,
    unresolved_count: jobs.length - points.length, attribution: "© OpenStreetMap contributors" };
}
