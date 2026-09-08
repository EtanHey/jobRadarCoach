import { JobDetailResponseSchema, JobIdSchema } from "../../../../lib/contracts";
import { HttpError, output, parse, safely } from "../../../../lib/http";
import { getApiStore, type ApiStore } from "../../../../lib/server";

type Context = { params: Promise<{ id: string }> };

export function makeGetJob(store: ApiStore) {
  return (_request: Request, context: Context) => safely(async () => {
    const id = parse(JobIdSchema, (await context.params).id);
    const job = await store.getJob(id);
    if (!job) throw new HttpError(404, "Job not found.");
    return output(JobDetailResponseSchema, { job });
  }, "job_detail");
}

export function GET(request: Request, context: Context): Promise<Response> {
  return makeGetJob(getApiStore())(request, context);
}
