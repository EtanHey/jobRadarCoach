import "server-only";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { z } from "zod";

import {
  JobDetailSchema, JobIdSchema, JobSummarySchema, ProfileEntriesSchema, ProfileSchema,
  ProfilePatchSchema, ScoreReasonSchema, StatusResultSchema, type JobDetail, type JobListQuery,
  type JobSummary, type Profile, type ProfileEntry, type StatusPatch, type StatusResult,
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
const scoreSchema = z.object({
  score: z.number().nullable(), reasons: z.array(ScoreReasonSchema), labels: z.record(z.string(), z.unknown()),
  brain: z.string(), model: z.string().nullable(), scorer_version: z.string().nullable(),
  score_payload: z.unknown().nullable(), scored_at: z.string(),
});
const rawSummarySchema = z.object({
  source: z.string(), last_seen_at: z.string(), raw_jd: z.string().nullable(),
  posting_extractions: z.object({ posting_id: JobIdSchema }).nullable(),
  id: JobIdSchema, title: z.string(), company: z.string(), location: z.string().nullable(),
  remote: z.boolean().nullable(), seniority: z.string().nullable(), stack: z.array(z.string()),
  salary: z.string().nullable(), url: z.string(), apply_url: z.string().nullable(),
  posted_at: z.string().nullable(), first_seen_at: z.string(),
  posting_status: z.object({ status: z.string(), reason: z.string().nullable() }).nullable(),
  posting_scores: scoreSchema.nullable(),
});
const rawDetailSchema = rawSummarySchema.extend({ raw_jd: z.string().nullable() });
const statusRowSchema = StatusResultSchema.passthrough();
const profileRowSchema = z.object({ field: z.string(), value: z.unknown() });
const SUMMARY = "source,last_seen_at,raw_jd,posting_extractions(posting_id),id,title,company,location,remote,seniority,stack,salary,url,apply_url,posted_at,first_seen_at,posting_status(status,reason),posting_scores(score,reasons,labels,brain,model,scorer_version,score_payload,scored_at)";
const STATUS_SUMMARY = SUMMARY.replace("posting_status(", "posting_status!inner(");
const DETAIL = SUMMARY;

function client(): SupabaseClient {
  const env = envSchema.safeParse(process.env);
  if (!env.success) throw new HttpError(503, "Server database configuration is unavailable.");
  return createClient(env.data.SUPABASE_URL, env.data.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

async function data(result: PromiseLike<{ data: unknown; error: unknown }>): Promise<unknown> {
  const response = await result;
  if (response.error) throw new HttpError(503, "Database request failed.");
  return response.data;
}

function checked<T>(schema: z.ZodType<T>, value: unknown): T {
  const parsed = schema.safeParse(value);
  if (!parsed.success) throw new HttpError(500, "Database returned an invalid response.");
  return parsed.data;
}

function summary(row: z.infer<typeof rawSummarySchema>): JobSummary {
  const base = checked(rawSummarySchema, row);
  const { posting_scores: score, posting_status: status, posting_extractions: extraction, raw_jd, ...posting } = base;
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
  });
}

async function selectSummaries(db: SupabaseClient, input: JobListQuery): Promise<JobSummary[]> {
  if (input.filter === "new-for-me") {
    const visit = checked(z.object({ last_visit_at: z.string().nullable() }).nullable(), await data(
      db.from("visits").select("last_visit_at").eq("singleton", true).maybeSingle(),
    ));
    let fresh = db.from("postings").select(STATUS_SUMMARY)
      .eq("posting_status.status", "new").order("first_seen_at", { ascending: false }).order("id").limit(input.limit);
    if (visit?.last_visit_at) {
      const cutoff = z.iso.datetime({ offset: true }).parse(visit.last_visit_at);
      fresh = fresh.or(`posted_at.gt.${cutoff},and(posted_at.is.null,first_seen_at.gt.${cutoff})`);
    }
    return checked(z.array(rawSummarySchema), await data(fresh)).map(summary);
  }
  let query = db.from("postings").select(input.filter === "all" ? SUMMARY : STATUS_SUMMARY)
    .order("first_seen_at", { ascending: false }).order("id").limit(input.limit);
  if (input.filter !== "all") query = query.eq("posting_status.status", input.filter);
  return checked(z.array(rawSummarySchema), await data(query)).map(summary);
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
        if (seeded.error) throw new HttpError(503, "Database request failed.");
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
