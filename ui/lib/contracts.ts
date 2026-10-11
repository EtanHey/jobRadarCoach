import { z } from "zod";
import { pipelineStatusValues } from "./pipeline-status-values";

const text = z.string();
const nullableText = text.nullable();
const nonblank = text.trim().min(1).max(2_000);
const stringList = z.array(text.trim().min(1).max(200)).max(100);
const publicUrl = z.url().refine((value) => ["http:", "https:"].includes(new URL(value).protocol));

export const JobStatusSchema = z.enum(["new", "seen", "worth_checking", "skipped", "applied", "screen", "interview_technical", "interview_final", "offer", "contract", "rejected", "archived", "not_relevant"]);
export const RecommendationSchema = z.enum(["apply", "referral", "review", "skip"]);
export const WorkModeSchema = z.enum(["hybrid", "remote", "on-site"]);
export const AvailabilitySchema = z.enum(["active", "inactive", "all"]);
// PostgreSQL's uuid type accepts the canonical 8-4-4-4-12 hexadecimal form
// without restricting RFC version or variant bits. Match that database domain.
export const JobIdSchema = z.guid();

export const ScoreReasonSchema = z.object({
  factor: z.enum([
    "product_role_match", "stack_domain_evidence", "seniority_gap", "employer_type", "preferences",
  ]),
  basis: z.enum(["posting", "comparison"]),
  assessment: z.enum(["positive", "mixed", "negative", "unknown"]),
  evidence_ids: z.array(text.min(1)).min(1),
  detail: text.min(1),
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

export const LinkedInClosedSignalSchema = z.object({
  phrase: z.enum(["no longer accepting applications", "not currently accepting applications"]),
  checked_at: z.iso.datetime({ offset: true }),
  url: publicUrl.refine(value => {
    const url = new URL(value);
    return url.protocol === "https:" && (url.hostname === "linkedin.com" || url.hostname.endsWith(".linkedin.com"))
      && !url.username && !url.password && (!url.port || url.port === "443");
  }),
}).strict();

export const JobSummarySchema = z.object({
  id: JobIdSchema,
  title: text,
  company: text,
  source: text,
  last_seen_at: text,
  experience: nullableText,
  // Optional for legacy cached summaries; list responses omit drawer metadata.
  description_available: z.boolean().optional(),
  seniority_origin: z.enum(["extracted", "title", "unknown"]).optional(),
  extraction_state: z.enum(["not-extracted", "extracted"]).optional(),
  location: nullableText,
  remote: z.boolean().nullable(),
  work_mode: WorkModeSchema.nullable().optional(),
  seniority: nullableText,
  stack: z.array(text),
  salary: nullableText.optional(),
  url: publicUrl,
  apply_url: publicUrl.nullable(),
  posted_at: nullableText,
  last_published_at: nullableText.optional(),
  first_seen_at: text,
  status: JobStatusSchema,
  status_reason: nullableText,
  relevance_filtered: z.boolean().optional(),
  relevance_rule: nullableText.optional(),
  score: z.number().int().min(0).max(100).nullable(),
  fit_line: nullableText,
  recommendation: RecommendationSchema.nullable(),
  alive: z.boolean().nullable().default(null),
  linkedin_closed_signal: LinkedInClosedSignalSchema.nullable().optional(),
}).strict();

export const JobDetailSchema = JobSummarySchema.extend({
  description_available: z.boolean(),
  seniority_origin: z.enum(["extracted", "title", "unknown"]),
  extraction_state: z.enum(["not-extracted", "extracted"]),
  salary: nullableText,
  raw_jd: nullableText,
  reasons: z.array(ScoreReasonSchema),
  score_payload: ScorePayloadSchema.nullable(),
  brain: nullableText,
  scored_at: nullableText,
}).strict();

export const FoundWithinSchema = z.enum(["", "24h", "3d", "7d", "30d"]);
export type FoundWithin = z.infer<typeof FoundWithinSchema>;

const limit = z.coerce.number().int().min(1).max(1000).default(50);
const filterStatus = JobStatusSchema.exclude(["skipped"]);
export const JobSourcesQuerySchema = z.object({
  filter: z.enum(["all", "new-for-me", "not-scored", ...filterStatus.options]).default("all"),
  availability: AvailabilitySchema.default("active"),
}).strict();
export const JobSourcesResponseSchema = z.object({ sources: z.array(text) });

export const JobListQuerySchema = z.object({
  filter: z.enum(["all", "new-for-me", "not-scored", ...filterStatus.options]),
  availability: AvailabilitySchema.default("active"),
  limit,
  ids: z.string().transform(value => value.split(",")).pipe(z.array(JobIdSchema).min(1).max(100)).optional(),
  // Strictly-newer cursor for the board's new-roles poll.
  found_within: FoundWithinSchema.optional(),
  since: z.iso.datetime({ offset: true }).optional(),
  fit: z.enum(["", "recommended", "skip", "good", "scored", "unscored"]).optional(),
  statuses: z.string().transform(value => value === "" ? [] : value.split(","))
    .pipe(z.array(z.enum(pipelineStatusValues)).max(pipelineStatusValues.length)).optional(),
  sort: z.enum(["found", "posted", "fit", "seniority"]).optional(),
  source: z.string().max(200).optional(),
  work_mode: WorkModeSchema.optional(),
  remote: z.enum(["true", "false"]).transform(value => value === "true").optional(),
  location: z.enum(["", "israel", "united-states", "other"]).optional(),
  seniority: z.enum(["", "non-senior", "Intern", "Junior", "Mid-level", "Senior", "Lead / Manager", "Staff / Principal", "Unknown"]).optional(),
}).strict().refine(query => !query.ids || (query.filter === "all" && query.availability === "all" && !query.since && !query.found_within), {
  message: "ID lookup requires all statuses and availability, without a cursor.",
}).refine(query => !(query.ids || query.since) || (query.fit === undefined && query.statuses === undefined && query.sort === undefined && query.source === undefined && query.work_mode === undefined && query.remote === undefined && query.location === undefined && query.seniority === undefined), {
  message: "ID and poll reads do not accept board facets.",
});

const ordinaryStatus = JobStatusSchema.exclude(["seen", "skipped", "rejected", "not_relevant"]);
const verbatimReason = z.string().max(2_000).refine((value) => value.trim().length > 0);
export const StatusPatchSchema = z.discriminatedUnion("status", [
  z.object({ status: ordinaryStatus }).strict(),
  z.object({ status: z.literal("seen"), automatic: z.literal(true).optional() }).strict(),
  z.object({ status: z.literal("rejected"), reason: verbatimReason }).strict(),
  z.object({ status: z.literal("not_relevant"), reason: verbatimReason.optional() }).strict(),
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

export const JobListItemSchema = JobSummarySchema.omit({
  salary: true, description_available: true, seniority_origin: true, extraction_state: true,
}).strip();
export const JobListResponseSchema = z.object({ jobs: z.array(JobListItemSchema).max(1000) }).strict();
export const JobDetailResponseSchema = z.object({ job: JobDetailSchema }).strict();
export const StatusResultSchema = z.object({
  status: JobStatusSchema,
  reason: nullableText,
}).strict();
export const ProfileResponseSchema = z.object({ profile: ProfileSchema }).strict();

export type JobSummary = z.infer<typeof JobSummarySchema>;
export type JobDetail = z.infer<typeof JobDetailSchema>;
export type JobListQuery = z.infer<typeof JobListQuerySchema>;
export type Availability = z.infer<typeof AvailabilitySchema>;
export type StatusPatch = z.infer<typeof StatusPatchSchema>;
export type StatusResult = z.infer<typeof StatusResultSchema>;
export type ProfileEntry = z.infer<typeof ProfilePatchSchema>;
export type Profile = z.infer<typeof ProfileSchema>;
