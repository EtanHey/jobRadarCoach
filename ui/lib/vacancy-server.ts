import "server-only";
import { z } from "zod";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { GlobeJob } from "./globe-contract";
import { JobIdSchema } from "./contracts";
import { uniqueJobsById } from "./job-board-state";
import { normalizedIdentity } from "./job-dedup";
import { vacancyIdentity } from "./vacancy-identity";

export function vacancyBodyCandidates<T extends GlobeJob>(jobs: T[]): T[] {
  const unique = uniqueJobsById(jobs);
  const employers = new Map<string, number>();
  for (const job of unique) {
    const employer = normalizedIdentity(job.company);
    employers.set(employer, (employers.get(employer) ?? 0) + 1);
  }
  return unique.filter(job => (employers.get(normalizedIdentity(job.company)) ?? 0) >= 2
    && vacancyIdentity(job).requisitions.length === 0);
}

// Membership projections stay body-free; only unresolved repeated employers need JD evidence.
export async function withVacancyIdentity<T extends GlobeJob>(db: SupabaseClient, jobs: T[]): Promise<T[]> {
  const identities = new Map(jobs.map(job => [job.id, vacancyIdentity(job)]));
  const candidates = vacancyBodyCandidates(jobs);
  const selected = candidates.slice(0, 300);
  if (candidates.length > selected.length) {
    console.warn("Vacancy identity body fetch capped", {
      candidates: candidates.length, fetched: selected.length, skipped: candidates.length - selected.length,
    });
  }
  const schema = z.array(z.object({ id: JobIdSchema, identity_evidence: z.string().nullable() }));
  for (let offset = 0; offset < selected.length; offset += 100) {
    const batch = selected.slice(offset, offset + 100);
    try {
      const response = await db.from("postings").select("id,identity_evidence:raw_jd").in("id", batch.map(job => job.id));
      if (response.error) throw response.error;
      const bodies = new Map(schema.parse(response.data).map(row => [row.id, row.identity_evidence]));
      for (const job of batch) identities.set(job.id, vacancyIdentity({ ...job, raw_jd: bodies.get(job.id) }));
    } catch {
      // Error payloads can contain JD content or credentials; log bounded context only.
      console.error("Vacancy identity body fetch failed; using URL-only identity", { offset, count: batch.length });
    }
  }
  return jobs.map(job => ({ ...job, vacancy_identity: identities.get(job.id) ?? vacancyIdentity(job) }));
}
