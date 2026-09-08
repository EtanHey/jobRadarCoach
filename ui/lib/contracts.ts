import { z } from "zod";

const text = z.string();
const nullableText = text.nullable();
const nonblank = text.trim().min(1).max(2_000);
const stringList = z.array(text.trim().min(1).max(200)).max(100);
const publicUrl = z.url().refine((value) => ["http:", "https:"].includes(new URL(value).protocol));

export const JobStatusSchema = z.enum(["new", "seen", "saved", "applied", "rejected"]);
export const RecommendationSchema = z.enum(["apply", "referral", "review", "skip"]);
export const JobIdSchema = z.uuid();

export const ScoreReasonSchema = z.object({
  factor: z.enum([
    "product_role_match", "stack_domain_evidence", "seniority_gap", "employer_type", "preferences",
  ]),
  basis: z.enum(["posting", "comparison"]),
  assessment: z.enum(["positive", "mixed", "negative", "unknown"]),
  evidence_ids: z.array(text.min(1)).min(1),
  detail: text.min(1).max(200),
}).strict();

export const ScorePayloadSchema = z.object({
  employer_type: z.enum(["direct", "agency", "unknown"]),
  seniority_real: z.boolean().nullable(),
  fit_score: z.number().int().min(0).max(100),
  fit_tier: z.enum(["strong", "good", "stretch", "weak"]),
  recommendation: RecommendationSchema,
  reasons: z.array(ScoreReasonSchema),
  fit_line: text,
  fit_line_evidence_ids: z.array(text),
  luna_status: z.literal("ok"),
}).strict();

export const JobSummarySchema = z.object({
  id: JobIdSchema,
  title: text,
  company: text,
  source: text,
  last_seen_at: text,
  experience: nullableText,
  seniority_origin: z.enum(["extracted", "title", "unknown"]),
  extraction_state: z.enum(["not-extracted", "extracted"]),
  location: nullableText,
  remote: z.boolean().nullable(),
  seniority: nullableText,
  stack: z.array(text),
  salary: nullableText,
  url: publicUrl,
  apply_url: publicUrl.nullable(),
  posted_at: nullableText,
  first_seen_at: text,
  status: JobStatusSchema,
  status_reason: nullableText,
  score: z.number().int().min(0).max(100).nullable(),
  fit_line: nullableText,
  recommendation: RecommendationSchema.nullable(),
}).strict();

export const JobDetailSchema = JobSummarySchema.extend({
  raw_jd: nullableText,
  reasons: z.array(ScoreReasonSchema),
  score_payload: ScorePayloadSchema.nullable(),
  brain: nullableText,
  scored_at: nullableText,
}).strict();

const limit = z.coerce.number().int().min(1).max(1000).default(50);
export const JobListQuerySchema = z.object({
  filter: z.enum(["all", "new-for-me", "seen", "saved", "applied", "rejected"]),
  limit,
}).strict();

const ordinaryStatus = z.enum(["new", "seen", "saved", "applied"]);
export const StatusPatchSchema = z.discriminatedUnion("status", [
  z.object({ status: ordinaryStatus }).strict(),
  z.object({ status: z.literal("rejected"), reason: nonblank }).strict(),
]);

const profileVariants = [
  z.object({ field: z.literal("candidate.roles_wanted"), value: stringList }).strict(),
  z.object({ field: z.literal("candidate.stacks"), value: stringList }).strict(),
  z.object({ field: z.literal("candidate.seniority"), value: stringList }).strict(),
  z.object({ field: z.literal("candidate.open_to.geographies"), value: stringList }).strict(),
  z.object({ field: z.literal("candidate.remote"), value: z.boolean().nullable() }).strict(),
  z.object({ field: z.literal("candidate.salary_floor"), value: z.number().min(0).nullable() }).strict(),
  z.object({ field: z.literal("candidate.red_flag_words"), value: stringList }).strict(),
  z.object({ field: z.literal("candidate.preferences.free_text"), value: nonblank.nullable() }).strict(),
  z.object({ field: z.literal("runtime.brain"), value: z.enum(["ollama", "codex"]) }).strict(),
] as const;
export const ProfilePatchSchema = z.discriminatedUnion("field", profileVariants);
export const ProfileEntriesSchema = z.array(ProfilePatchSchema).max(profileVariants.length);
export const ProfileSchema = z.object({
  "candidate.roles_wanted": stringList,
  "candidate.stacks": stringList,
  "candidate.seniority": stringList,
  "candidate.open_to.geographies": stringList,
  "candidate.remote": z.boolean().nullable(),
  "candidate.salary_floor": z.number().min(0).nullable(),
  "candidate.red_flag_words": stringList,
  "candidate.preferences.free_text": nonblank.nullable(),
  "runtime.brain": z.enum(["ollama", "codex"]),
}).strict();

export const JobListResponseSchema = z.object({ jobs: z.array(JobSummarySchema).max(1000) }).strict();
export const JobDetailResponseSchema = z.object({ job: JobDetailSchema }).strict();
export const StatusResultSchema = z.object({
  status: JobStatusSchema,
  reason: nullableText,
}).strict();
export const StatusResponseSchema = z.object({ status: JobStatusSchema, reason: nullableText }).strict();
export const ProfileResponseSchema = z.object({ profile: ProfileSchema }).strict();

export type JobSummary = z.infer<typeof JobSummarySchema>;
export type JobDetail = z.infer<typeof JobDetailSchema>;
export type JobListQuery = z.infer<typeof JobListQuerySchema>;
export type StatusPatch = z.infer<typeof StatusPatchSchema>;
export type StatusResult = z.infer<typeof StatusResultSchema>;
export type ProfileEntry = z.infer<typeof ProfilePatchSchema>;
export type Profile = z.infer<typeof ProfileSchema>;
