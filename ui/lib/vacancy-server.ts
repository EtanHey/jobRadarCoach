import "server-only";
import { z } from "zod";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { GlobeJob } from "./globe-contract";
import { JobIdSchema } from "./contracts";
import { data } from "./server";
import { uniqueJobsById } from "./job-board-state";
import { vacancyIdentity } from "./vacancy-identity";

// The marker RPC intentionally omits JD bodies. Fetch evidence only for its captured IDs.
export async function withVacancyIdentity(db: SupabaseClient, jobs: GlobeJob[]): Promise<GlobeJob[]> {
  const identities = new Map<string, ReturnType<typeof vacancyIdentity>>();
  const schema = z.array(z.object({ id: JobIdSchema, url: z.string(), apply_url: z.string().nullable(), raw_jd: z.string().nullable() }));
  const unique = uniqueJobsById(jobs);
  for (let offset = 0; offset < unique.length; offset += 100) {
    const rows = schema.parse(await data(db.from("postings").select("id,url,apply_url,raw_jd").in("id", unique.slice(offset, offset + 100).map(job => job.id))));
    for (const row of rows) identities.set(row.id, vacancyIdentity(row));
  }
  return jobs.map(job => ({ ...job, vacancy_identity: identities.get(job.id) ?? vacancyIdentity(job) }));
}
