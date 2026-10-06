import { z } from "zod";
import { JobIdSchema, JobListQuerySchema, JobSummarySchema } from "./contracts";

export const GlobeQuerySchema = z.object({
  filter: JobListQuerySchema.shape.filter.default("all"),
  availability: JobListQuerySchema.shape.availability,
}).strict();
const hqSource = /^https:\/\/[A-Za-z0-9.-]+(?::[0-9]+)?(?:\/[^\s|]*)? \| nominatim:osm:(node|way|relation):[1-9][0-9]*$/;
export const GlobePointSchema = z.object({
  posting_id: JobIdSchema, lat: z.number().min(-90).max(90), lng: z.number().min(-180).max(180),
  precision: z.enum(["city", "region", "country", "hq"]), source: z.string().trim().min(1),
  resolved_at: z.iso.datetime({ offset: true }),
}).strict().refine((point) => point.precision !== "hq" || hqSource.test(point.source), "HQ requires HTTPS evidence and a provider object");
export const GlobeResponseSchema = z.object({
  jobs: z.array(JobSummarySchema), points: z.array(GlobePointSchema),
  total_count: z.number().int().nonnegative(), resolved_count: z.number().int().nonnegative(),
  unresolved_count: z.number().int().nonnegative(), attribution: z.string(),
}).strict();
export type GlobeQuery = z.infer<typeof GlobeQuerySchema>;
export type GlobePoint = z.infer<typeof GlobePointSchema>;
export type GlobeResponse = z.infer<typeof GlobeResponseSchema>;
