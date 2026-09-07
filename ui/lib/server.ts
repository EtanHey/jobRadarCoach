import "server-only";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { z } from "zod";

import {
  JobDetailSchema, JobIdSchema, JobSummarySchema, ProfileEntriesSchema, ProfileSchema,
  ProfilePatchSchema, ScoreReasonSchema, StatusResultSchema, type JobDetail, type JobListQuery,
  type JobSummary, type Profile, type ProfileEntry, type StatusPatch, type StatusResult,
} from "./contracts";
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
const SUMMARY = "id,title,company,location,remote,seniority,stack,salary,url,apply_url,posted_at,first_seen_at,posting_status(status,reason),posting_scores(score,reasons,labels,brain,model,scorer_version,score_payload,scored_at)";
const STATUS_SUMMARY = SUMMARY.replace("posting_status(", "posting_status!inner(");
const DETAIL = `${SUMMARY},raw_jd`;

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
  const { posting_scores: score, posting_status: status, ...posting } = base;
  const payload = score?.score_payload;
  const fit = payload && typeof payload === "object" ? payload : null;
  return checked(JobSummarySchema, {
    ...posting, status: status?.status ?? "new", status_reason: status?.reason ?? null,
    score: score?.score ?? null,
    fit_line: fit && "fit_line" in fit ? fit.fit_line : null,
    recommendation: fit && "recommendation" in fit ? fit.recommendation : null,
  });
}

async function selectSummaries(db: SupabaseClient, input: JobListQuery): Promise<JobSummary[]> {
  if (input.filter === "new-for-me") {
    const ids = checked(z.array(z.object({ posting_id: JobIdSchema })), await data(
      db.rpc("list_new_for_me").limit(input.limit),
    )).map((row) => row.posting_id);
    if (!ids.length) return [];
    const rows = checked(z.array(rawSummarySchema), await data(db.from("postings").select(SUMMARY).in("id", ids)));
    const byId = new Map(rows.map((row) => [row.id, summary(row)]));
    return ids.map((id) => {
      const job = byId.get(id);
      if (!job) throw new HttpError(500, "Database returned an invalid response.");
      return job;
    });
  }
  let query = db.from("postings").select(input.filter === "all" ? SUMMARY : STATUS_SUMMARY)
    .order("posted_at", { ascending: false, nullsFirst: false }).order("id").limit(input.limit);
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
  return checked(ProfileSchema, Object.fromEntries(entries.map((entry) => [entry.field, entry.value])));
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
      if (input.status === "seen") {
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
        reason: input.status === "rejected" ? input.reason : null,
      }).single());
      const row = checked(statusRowSchema, value);
      return { status: row.status, reason: row.reason };
    },
    async getProfile() {
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
