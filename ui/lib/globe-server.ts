import "server-only";
import type { SupabaseClient } from "@supabase/supabase-js";
import { GlobeJobSchema, type GlobeJob, GlobePointSchema, type GlobePoint, type GlobeQuery, type GlobeResponse } from "./globe-contract";
import { client, data } from "./server";
import { HttpError } from "./http";

export interface GlobeStore {
  snapshot(input: GlobeQuery): Promise<{ jobs: GlobeJob[]; geo: unknown[] }>;
}
export function getGlobeStore(db: SupabaseClient = client()): GlobeStore {
  return { async snapshot(input) {
    // Jobs, visit cutoff and geo share one SQL statement snapshot, even for empty results.
    const raw = await data(db.rpc("get_globe_markers", { filter: input.filter, availability: input.availability, found_within: input.found_within ?? "" }));
    if (!raw || typeof raw !== "object" || !("jobs" in raw) || !("geo" in raw) || !Array.isArray(raw.geo)) {
      throw new HttpError(503, "Geographic data unavailable.");
    }
    return { jobs: GlobeJobSchema.array().parse(raw.jobs), geo: raw.geo };
  } };
}
export async function globeResponse(store: GlobeStore, input: GlobeQuery): Promise<GlobeResponse> {
  const snapshot = await store.snapshot(input);
  const jobs = snapshot.jobs.map(row => GlobeJobSchema.parse(row));
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
