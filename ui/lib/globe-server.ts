import "server-only";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { JobSummary } from "./contracts";
import { filterJobs } from "./job-filters";
import { GlobePointSchema, type GlobePoint, type GlobeQuery, type GlobeResponse } from "./globe-contract";
import { client, data, selectSummaries } from "./server";
import { HttpError } from "./http";

export interface GlobeStore {
  page(input: GlobeQuery, offset: number): Promise<JobSummary[]>;
  geo(ids: string[]): Promise<unknown>;
}
export function getGlobeStore(db: SupabaseClient = client()): GlobeStore {
  return {
    page: (input, offset) => selectSummaries(db, { filter: input.filter, availability: input.availability, limit: 500 }, offset),
    geo: (ids) => data(db.rpc("get_job_geo", { posting_ids: ids })),
  };
}
export async function globeResponse(store: GlobeStore, input: GlobeQuery): Promise<GlobeResponse> {
  const all: JobSummary[] = [];
  const seen = new Set<string>();
  for (let offset = 0; ; ) {
    const page = await store.page(input, offset);
    for (const job of page) {
      // Concurrent changes during paging must fail explicitly rather than publish wrong counts.
      if (seen.has(job.id)) throw new HttpError(503, "Jobs changed while loading. Please retry.");
      seen.add(job.id); all.push(job);
    }
    if (!page.length) break;
    offset += page.length; // Handles a server row cap lower than our requested batch size.
  }
  const jobs = filterJobs(all, input).filter((job) =>
    (input.remote === undefined || job.remote === input.remote) &&
    (input.min_score === undefined || (job.score !== null && job.score >= input.min_score)));
  const points: GlobePoint[] = [];
  for (let offset = 0; offset < jobs.length; offset += 500) {
    const ids = new Set(jobs.slice(offset, offset + 500).map((job) => job.id));
    const raw = await store.geo([...ids]);
    if (!Array.isArray(raw)) throw new HttpError(503, "Geographic data unavailable.");
    for (const row of raw) {
      const parsed = GlobePointSchema.safeParse(row);
      if (parsed.success && ids.delete(parsed.data.posting_id)) points.push(parsed.data);
    }
  }
  return { jobs, points, total_count: jobs.length, resolved_count: points.length,
    unresolved_count: jobs.length - points.length, attribution: "© OpenStreetMap contributors" };
}
