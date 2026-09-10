import "server-only";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { z } from "zod";

import {
  JobDetailSchema, JobIdSchema, JobSummarySchema, ProfileEntriesSchema, ProfileSchema,
  ProfilePatchSchema, ScoreReasonSchema, StatusResultSchema, type JobDetail, type JobListQuery,
  type Availability, type JobSummary, type Profile, type ProfileEntry, type StatusPatch, type StatusResult,
} from "./contracts";
import { postingUrl, titleSeniority, experiencePhrase, technologyMentions } from "./job-metadata";
import { HttpError } from "./http";

export interface ApiStore {
  listJobs(input: JobListQuery): Promise<JobSummary[]>;
  getJob(id: string): Promise<JobDetail | null>;
  setStatus(input: StatusPatch & { posting_id: string }): Promise<StatusResult>;
  getProfile(): Promise<Profile>;
  updateProfile(input: ProfileEntry): Promise<Profile>;
}

const envSchema = z.object({
  SUPABASE_URL: z.url(),
  SUPABASE_SERVICE_ROLE_KEY: z.string().min(1),
});
const summaryScoreSchema = z.object({
  score: z.number().nullable(), score_payload: z.unknown().nullable(),
});
const scoreSchema = summaryScoreSchema.extend({
  score: z.number().nullable(), reasons: z.array(ScoreReasonSchema), labels: z.record(z.string(), z.unknown()),
  brain: z.string(), model: z.string().nullable(), scorer_version: z.string().nullable(),
  score_payload: z.unknown().nullable(), scored_at: z.string(),
});
const rawBaseSchema = z.object({
  source: z.string(), last_seen_at: z.string(), raw_jd: z.string().nullable(),
  liveness: z.object({ alive: z.unknown().optional() }).passthrough().nullable(),
  posting_extractions: z.object({ posting_id: JobIdSchema }).nullable(),
  id: JobIdSchema, title: z.string(), company: z.string(), location: z.string().nullable(),
  remote: z.boolean().nullable(), seniority: z.string().nullable(), stack: z.array(z.string()),
  salary: z.string().nullable(), url: z.string(), apply_url: z.string().nullable(),
  posted_at: z.string().nullable(), first_seen_at: z.string(),
  posting_status: z.object({ status: z.string(), reason: z.string().nullable() }).nullable(),
});
const rawSummarySchema = rawBaseSchema.extend({ posting_scores: summaryScoreSchema.nullable() });
const rawDetailSchema = rawBaseSchema.extend({ posting_scores: scoreSchema.nullable() });
const statusRowSchema = StatusResultSchema.passthrough();
const profileRowSchema = z.object({ field: z.string(), value: z.unknown() });
const SUMMARY = "source,last_seen_at,raw_jd,liveness,posting_extractions(posting_id),id,title,company,location,remote,seniority,stack,salary,url,apply_url,posted_at,first_seen_at,posting_status(status,reason),posting_scores(score,score_payload)";
const STATUS_SUMMARY = SUMMARY.replace("posting_status(", "posting_status!inner(");
const DETAIL = "source,last_seen_at,raw_jd,liveness,posting_extractions(posting_id),id,title,company,location,remote,seniority,stack,salary,url,apply_url,posted_at,first_seen_at,posting_status(status,reason),posting_scores(score,reasons,labels,brain,model,scorer_version,score_payload,scored_at)";

function client(): SupabaseClient {
  const env = envSchema.safeParse(process.env);
  if (!env.success) throw new HttpError(503, "Server database configuration is unavailable.");
  return createClient(env.data.SUPABASE_URL, env.data.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

async function data(result: PromiseLike<{ data: unknown; error: unknown }>): Promise<unknown> {
  const response = await result;
  if (response.error) throw new HttpError(503, "Database request failed.", "database");
  return response.data;
}

function checked<T>(schema: z.ZodType<T>, value: unknown): T {
  const parsed = schema.safeParse(value);
  if (!parsed.success) throw new HttpError(500, "Database returned an invalid response.", "invalid_response");
  return parsed.data;
}

function summary(row: z.infer<typeof rawSummarySchema>): JobSummary {
  const base = checked(rawSummarySchema, row);
  const { posting_scores: score, posting_status: status, posting_extractions: extraction, liveness, raw_jd, ...posting } = base;
  const level = posting.seniority ?? titleSeniority(posting.title);
  const payload = score?.score_payload;
  const fit = payload && typeof payload === "object" ? payload : null;
  return checked(JobSummarySchema, {
    ...posting, url: postingUrl(posting.url),
    apply_url: posting.apply_url ? postingUrl(posting.apply_url) : null,
    stack: posting.stack.length ? posting.stack : technologyMentions(raw_jd),
    seniority: level, seniority_origin: posting.seniority ? "extracted" : level ? "title" : "unknown",
    description_available: Boolean(raw_jd?.trim()),
    experience: experiencePhrase(raw_jd), extraction_state: extraction ? "extracted" : "not-extracted",
    status: status?.status ?? "new", status_reason: status?.reason ?? null,
    score: score?.score ?? null,
    fit_line: fit && "fit_line" in fit ? fit.fit_line : null,
    recommendation: fit && "recommendation" in fit ? fit.recommendation : null,
    alive: typeof liveness?.alive === "boolean" ? liveness.alive : null,
  });
}

export function availabilityPredicate(availability: Availability) {
  if (availability === "inactive") return { method: "eq", column: "liveness->alive", value: false } as const;
  if (availability === "active") return { method: "or", filter: "liveness->alive.neq.false,liveness->alive.is.null" } as const;
  return null;
}

export function parseSummaryRows(value: unknown): { jobs: JobSummary[]; invalidRowCount: 0 } {
  const rows = checked(z.array(rawSummarySchema), value);
  return { jobs: rows.map(summary), invalidRowCount: 0 };
}

async function selectSummaries(db: SupabaseClient, input: JobListQuery): Promise<JobSummary[]> {
  if (input.filter === "new-for-me") {
    const visit = checked(z.object({ last_visit_at: z.string().nullable() }).nullable(), await data(
      db.from("visits").select("last_visit_at").eq("singleton", true).maybeSingle(),
    ));
    let fresh = db.from("postings").select(STATUS_SUMMARY)
      .eq("posting_status.status", "new");
    const availability = availabilityPredicate(input.availability);
    if (availability?.method === "eq") fresh = fresh.eq(availability.column, availability.value);
    else if (availability?.method === "or") fresh = fresh.or(availability.filter);
    if (visit?.last_visit_at) {
      const cutoff = z.iso.datetime({ offset: true }).parse(visit.last_visit_at);
      fresh = fresh.or(`posted_at.gt.${cutoff},and(posted_at.is.null,first_seen_at.gt.${cutoff})`);
    }
    fresh = fresh.order("first_seen_at", { ascending: false }).order("id").limit(input.limit);
    return parseSummaryRows(await data(fresh)).jobs;
  }
  let query = db.from("postings").select(input.filter === "all" ? SUMMARY : STATUS_SUMMARY);
  if (input.filter !== "all") query = query.eq("posting_status.status", input.filter);
  const availability = availabilityPredicate(input.availability);
  if (availability?.method === "eq") query = query.eq(availability.column, availability.value);
  else if (availability?.method === "or") query = query.or(availability.filter);
  query = query.order("first_seen_at", { ascending: false }).order("id").limit(input.limit);
  return parseSummaryRows(await data(query)).jobs;
}

async function readDetail(db: SupabaseClient, id: string): Promise<z.infer<typeof rawDetailSchema> | null> {
  const value = await data(db.from("postings").select(DETAIL).eq("id", id).maybeSingle());
  return value === null ? null : checked(rawDetailSchema, value);
}

async function readProfile(db: SupabaseClient): Promise<Profile> {
  const fields = ProfilePatchSchema.options.map((option) => option.shape.field.value);
  const entries = checked(ProfileEntriesSchema, await data(
    db.from("profile").select("field,value").in("field", fields).order("field"),
  ));
  return checked(ProfileSchema, {
    "candidate.roles_wanted": [], "candidate.stacks": [], "candidate.seniority": [],
    "candidate.open_to.geographies": [], "candidate.remote": null, "candidate.salary_floor": null,
    "candidate.red_flag_words": [], "candidate.preferences.free_text": null, "runtime.brain": "ollama",
    ...Object.fromEntries(entries.map((entry) => [entry.field, entry.value])),
  });
}

export function getApiStore(): ApiStore {
  return {
    listJobs: (input) => selectSummaries(client(), input),
    async getJob(id) {
      const db = client();
      const row = await readDetail(db, id);
      if (!row) return null;
      const score = row.posting_scores;
      return checked(JobDetailSchema, {
        ...summary(row), raw_jd: row.raw_jd, reasons: score?.reasons ?? [],
        score_payload: score?.score_payload ?? null, brain: score?.brain ?? null,
        scored_at: score?.scored_at ?? null,
      });
    },
    async setStatus(input) {
      const db = client();
      if (input.status === "seen" && input.automatic) {
        const seeded = await db.from("posting_status").upsert(
          { posting_id: input.posting_id, status: "seen", reason: null },
          { onConflict: "posting_id", ignoreDuplicates: true },
        );
        if (seeded.error?.code === "23503") throw new HttpError(404, "Job not found.");
        if (seeded.error) throw new HttpError(503, "Database request failed.", "database");
        const changed = await data(db.from("posting_status").update({ status: "seen", reason: null })
          .eq("posting_id", input.posting_id).eq("status", "new").select("status,reason").maybeSingle());
        if (changed !== null) return checked(StatusResultSchema, changed);
        const current = await data(db.from("posting_status").select("status,reason")
          .eq("posting_id", input.posting_id).maybeSingle());
        if (current === null) throw new HttpError(404, "Job not found.");
        return checked(StatusResultSchema, current);
      }
      const value = await data(db.rpc("set_status", {
        posting_id: input.posting_id, status: input.status,
        reason: input.status === "rejected" || input.status === "not_relevant" ? input.reason ?? null : null,
      }).single());
      const row = checked(statusRowSchema, value);
      return { status: row.status, reason: row.reason };
    },
    getProfile() {
      return readProfile(client());
    },
    async updateProfile(input) {
      const db = client();
      const row = checked(profileRowSchema, await data(db.rpc("update_profile", input).single()));
      checked(ProfilePatchSchema, row);
      return readProfile(db);
    },
  };
}
