import { z } from "zod";
import { JobDetailSchema, JobIdSchema } from "../../../../../lib/contracts";
import { HttpError, mutationJson, output, parse, safely } from "../../../../../lib/http";
import { getApiStore, type ApiStore } from "../../../../../lib/server";
type Context = { params: Promise<{ id: string }> };
export function makeScoreAnyway(store: ApiStore) {
  return (request: Request, context: Context) => safely(async () => {
    const id = parse(JobIdSchema, (await context.params).id);
    await mutationJson(request, z.object({}).strict());
    if (!store.scoreAnyway) throw new HttpError(503, "Scoring override unavailable.");
    const job = await store.scoreAnyway(id);
    if (!job) throw new HttpError(404, "Job not found.");
    return output(JobDetailSchema, job);
  });
}
export function POST(request: Request, context: Context): Promise<Response> {
  return makeScoreAnyway(getApiStore())(request, context);
}
