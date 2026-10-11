import "server-only";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { z } from "zod";

import {
  LinkedInClosedSignalSchema, WorkModeSchema, JobDetailSchema, JobIdSchema, JobSummarySchema, JobSourcesQuerySchema, JobSourcesResponseSchema, ProfileEntriesSchema, ProfileSchema,
  ProfilePatchSchema, ScoreReasonSchema, StatusResultSchema, type JobDetail, type JobListQuery,
  type Availability, type JobSummary, type Profile, type ProfileEntry, type StatusPatch, type StatusResult,
} from "./contracts";
import { postingUrl, titleSeniority } from "./job-metadata";
import { foundWithinCutoff } from "./job-filters";
import { HttpError } from "./http";

export interface ApiStore {
  listJobs(input: JobListQuery): Promise<JobSummary[]>;
  listSources(input: z.infer<typeof JobSourcesQuerySchema>): Promise<string[]>;
  getJob(id: string): Promise<JobDetail | null>;
  scoreAnyway?(id: string): Promise<JobDetail | null>;
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
  relevance_filtered: z.boolean().optional(),
  relevance_gate: z.object({ rule: z.string().nullable().optional() }).passthrough().optional(),
  source: z.string(), last_seen_at: z.string(),
  list_metadata: z.object({ stack: z.array(z.string()), experience: z.string().nullable(), description_available: z.boolean() }),
  liveness: z.object({ alive: z.unknown().optional() }).passthrough().nullable(),
  posting_extractions: z.object({ posting_id: JobIdSchema }).nullable(),
  id: JobIdSchema, title: z.string(), company: z.string(), location: z.string().nullable(),
  work_mode: WorkModeSchema.nullable().optional(), remote: z.boolean().nullable(), seniority: z.string().nullable(), stack: z.array(z.string()),
  salary: z.string().nullable(), url: z.string(), apply_url: z.string().nullable(),
  posted_at: z.string().nullable(), last_published_at: z.string().nullable().default(null), first_seen_at: z.string(),
  posting_status: z.object({ status: z.string(), reason: z.string().nullable() }).nullable(),
});
const rawSummarySchema = rawBaseSchema.extend({ posting_scores: summaryScoreSchema.nullable() });
const rawListSchema = rawBaseSchema.omit({
  salary: true, list_metadata: true, liveness: true, relevance_gate: true, posting_extractions: true,
}).extend({
  list_stack: z.array(z.string()), experience: z.string().nullable(),
  relevance_rule: z.string().nullable(), alive: z.unknown().nullable(), linkedin_closed_signal: z.unknown().nullable(),
  posting_scores: z.object({ score: z.number().nullable(), recommendation: z.unknown().nullable(), fit_line: z.unknown().nullable() }).nullable(),
});
const rawDetailSchema = rawBaseSchema.extend({ posting_scores: scoreSchema.nullable(), raw_jd: z.string().nullable() });
const statusRowSchema = StatusResultSchema.passthrough();
const profileRowSchema = z.object({ field: z.string(), value: z.unknown() });
const SUMMARY = "relevance_filtered,relevance_rule:relevance_gate->rule,source,last_seen_at,list_stack:list_metadata->stack,experience:list_metadata->experience,alive:liveness->alive,linkedin_closed_signal:liveness->linkedin_closed_signal,id,title,company,location,remote,work_mode,seniority,stack,url,apply_url,posted_at,last_published_at,first_seen_at,posting_status(status,reason),posting_scores(score,recommendation:score_payload->recommendation,fit_line:score_payload->fit_line)";
const STATUS_SUMMARY = SUMMARY.replace("posting_status(", "posting_status!inner(");
const DETAIL = "relevance_filtered,relevance_gate,source,last_seen_at,raw_jd,list_metadata,liveness,posting_extractions(posting_id),id,title,company,location,remote,work_mode,seniority,stack,salary,url,apply_url,posted_at,last_published_at,first_seen_at,posting_status(status,reason),posting_scores(score,reasons,labels,brain,model,scorer_version,score_payload,scored_at)";

export function client(): SupabaseClient {
  const env = envSchema.safeParse(process.env);
  if (!env.success) throw new HttpError(503, "Server database configuration is unavailable.");
  return createClient(env.data.SUPABASE_URL, env.data.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

export async function data(result: PromiseLike<{ data: unknown; error: unknown }>): Promise<unknown> {
  const response = await result;
  if (response.error) throw new HttpError(503, "Database request failed.", "database");
  return response.data;
}

function checked<T>(schema: z.ZodType<T>, value: unknown): T {
  const parsed = schema.safeParse(value);
  if (!parsed.success) throw new HttpError(500, "Database returned an invalid response.", "invalid_response");
  return parsed.data;
}

function listSummary(base: z.infer<typeof rawListSchema>): JobSummary {
  const { posting_scores: score, posting_status: status, list_stack, alive, linkedin_closed_signal, ...posting } = base;
  const level = posting.seniority ?? titleSeniority(posting.title);
  return checked(JobSummarySchema, {
    ...posting, url: postingUrl(posting.url),
    apply_url: posting.apply_url ? postingUrl(posting.apply_url) : null,
    stack: posting.stack.length ? posting.stack : list_stack,
    seniority: level,
    status: status?.status ?? "new", status_reason: status?.reason ?? null,
    score: base.relevance_filtered ? null : score?.score ?? null,
    fit_line: base.relevance_filtered ? null : score?.fit_line ?? null,
    recommendation: base.relevance_filtered ? null : score?.recommendation ?? null,
    alive: typeof alive === "boolean" ? alive : null,
    linkedin_closed_signal: LinkedInClosedSignalSchema.safeParse(linkedin_closed_signal).data ?? null,
  });
}

function summary(row: z.infer<typeof rawSummarySchema>): JobSummary {
  const { salary, posting_extractions, liveness, list_metadata, relevance_gate, posting_scores, ...posting } = checked(rawSummarySchema, row);
  const payload = posting_scores?.score_payload;
  const fit = payload && typeof payload === "object" ? payload : null;
  const job = listSummary({ ...posting, list_stack: list_metadata.stack, experience: list_metadata.experience,
    relevance_rule: relevance_gate?.rule ?? null, alive: liveness?.alive ?? null,
    linkedin_closed_signal: liveness?.linkedin_closed_signal ?? null,
    posting_scores: posting_scores ? { score: posting_scores.score,
      fit_line: fit && "fit_line" in fit ? fit.fit_line : null,
      recommendation: fit && "recommendation" in fit ? fit.recommendation : null } : null });
  return { ...job, salary, description_available: list_metadata.description_available,
    seniority_origin: row.seniority ? "extracted" : titleSeniority(row.title) ? "title" : "unknown",
    extraction_state: posting_extractions ? "extracted" : "not-extracted" };
}

function parseListRows(value: unknown): { jobs: JobSummary[] } {
  return { jobs: checked(z.array(rawListSchema), value).map(listSummary) };
}

export function availabilityPredicate(availability: Availability) {
  if (availability === "inactive") return { method: "eq", column: "liveness->alive", value: false } as const;
  if (availability === "active") return { method: "or", filter: "liveness->alive.neq.false,liveness->alive.is.null" } as const;
  return null;
}

export function parseSummaryRows(value: unknown): { jobs: JobSummary[] } {
  const rows = checked(z.array(rawSummarySchema), value);
  return { jobs: rows.map(summary) };
}

export async function selectSummaries(db: SupabaseClient, input: JobListQuery): Promise<JobSummary[]> {
  if (input.ids) {
    return parseListRows(await data(db.from("postings").select(SUMMARY).in("id", input.ids).limit(input.limit))).jobs;
  }
  if ((!input.since && input.found_within) || input.sort !== undefined || input.fit !== undefined || input.statuses !== undefined || input.source !== undefined || input.work_mode !== undefined || input.remote !== undefined || input.location !== undefined || input.seniority !== undefined) {
    return parseListRows(await data(db.rpc("board_postings", {
      filter: input.filter, availability: input.availability, fit: input.fit ?? "",
      statuses: input.statuses ?? [], sort: input.sort ?? "fit", max: input.limit,
      ...(input.source !== undefined ? { source: input.source } : {}),
      ...(input.work_mode !== undefined ? { work_mode: input.work_mode } : {}),
      ...(input.remote !== undefined ? { remote: input.remote } : {}),
      ...(input.location !== undefined ? { location: input.location } : {}),
      ...(input.seniority !== undefined ? { seniority: input.seniority } : {}),
      ...(input.found_within ? { found_within: input.found_within } : {}),
    }).select(SUMMARY))).jobs;
  }
  let query = db.from("postings").select(["all", "not-scored"].includes(input.filter) ? SUMMARY : STATUS_SUMMARY);
  query = query.eq("relevance_filtered", input.filter === "not-scored");
  if (!["all", "not-scored"].includes(input.filter)) query = query.eq("posting_status.status", input.filter === "new-for-me" ? "new" : input.filter);
  const availability = availabilityPredicate(input.availability);
  if (availability?.method === "eq") query = query.eq(availability.column, availability.value);
  else if (availability?.method === "or") query = query.or(availability.filter);
  const cutoff = foundWithinCutoff(input.found_within);
  if (cutoff !== null) query = query.gte("first_seen_at", new Date(cutoff).toISOString());
  if (input.since) query = query.gt("first_seen_at", input.since);
  query = query.order("first_seen_at", { ascending: false }).order("id").limit(input.limit);
  return parseListRows(await data(query)).jobs;
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

export async function selectSources(db: SupabaseClient, input: z.infer<typeof JobSourcesQuerySchema>): Promise<string[]> {
  return checked(JobSourcesResponseSchema.shape.sources, await data(db.rpc("board_sources", input)));
}

export function getApiStore(): ApiStore {
  return {
    listJobs: (input) => selectSummaries(client(), input),
    listSources: (input) => selectSources(client(), input),
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
    async scoreAnyway(id) {
      const exists = await data(client().rpc("score_anyway", { posting_id: id }));
      if (exists !== true) return null;
      return this.getJob(id);
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
