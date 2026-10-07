import { postingUrl, titleSeniority } from "./job-metadata";
import { z } from "zod";
import { JobIdSchema, JobListQuerySchema, JobSummarySchema } from "./contracts";

export const GlobeQuerySchema = z.object({
  filter: JobListQuerySchema.shape.filter.default("all"),
  availability: JobListQuerySchema.shape.availability,
  found_within: JobListQuerySchema.shape.found_within,
}).strict();
const hqSource = /^https:\/\/[A-Za-z0-9.-]+(?::[0-9]+)?(?:\/[^\s|]*)? \| nominatim:osm:(node|way|relation):[1-9][0-9]*$/;
export const GlobePointSchema = z.object({
  posting_id: JobIdSchema, lat: z.number().min(-90).max(90), lng: z.number().min(-180).max(180),
  precision: z.enum(["city", "region", "country", "hq"]), source: z.string().trim().min(1),
  resolved_at: z.iso.datetime({ offset: true }),
}).strict().refine((point) => point.precision !== "hq" || hqSource.test(point.source), "HQ requires HTTPS evidence and a provider object");
// Marker labels, local view predicates and complete-linkage identity only. Cards hydrate by id.
export const GlobeJobSchema = JobSummarySchema.pick({
  id:true,title:true,company:true,source:true,location:true,remote:true,work_mode:true,
  seniority:true,stack:true,url:true,apply_url:true,posted_at:true,last_published_at:true,
  first_seen_at:true,status:true,status_reason:true,score:true,recommendation:true,
  alive:true,relevance_filtered:true,
}).strip().transform(job => ({...job, seniority: job.seniority ?? titleSeniority(job.title),
  url: postingUrl(job.url), apply_url: job.apply_url ? postingUrl(job.apply_url) : null}));
export type GlobeJob = z.infer<typeof GlobeJobSchema>;
export const GlobeResponseSchema = z.object({
  jobs: z.array(GlobeJobSchema), points: z.array(GlobePointSchema),
  total_count: z.number().int().nonnegative(), resolved_count: z.number().int().nonnegative(),
  unresolved_count: z.number().int().nonnegative(), attribution: z.string(),
}).strict();
export type GlobeQuery = z.infer<typeof GlobeQuerySchema>;
export type GlobePoint = z.infer<typeof GlobePointSchema>;
export type GlobeResponse = z.infer<typeof GlobeResponseSchema>;
