import { z } from "zod";
import { JobListQuerySchema, JobIdSchema } from "./contracts"; import { storedPreferencesSchema } from "./job-board-preferences";
export const NewRolesQuerySchema = z.object({
  filter: JobListQuerySchema.shape.filter, availability: JobListQuerySchema.shape.availability,
  since: z.iso.datetime({ offset: true }), found_within: JobListQuerySchema.shape.found_within,
  ids: z.array(JobIdSchema).max(10000), view: storedPreferencesSchema.shape.view,
  incoming_ids: z.array(JobIdSchema).max(101),
}).strict();
export const NewRolesResponseSchema = z.object({ count: z.number().int().nonnegative(), truncated: z.boolean() }).strict();
export const NewRolesProbeSchema = NewRolesResponseSchema.extend({companies:z.array(z.string()).max(101), incoming_ids: NewRolesQuerySchema.shape.incoming_ids});
export type NewRolesQuery = z.infer<typeof NewRolesQuerySchema>;
