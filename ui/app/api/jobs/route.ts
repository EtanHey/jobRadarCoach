import { JobListQuerySchema, JobListResponseSchema } from "../../../lib/contracts";
import { HttpError, output, safely } from "../../../lib/http";
import { getApiStore, type ApiStore } from "../../../lib/server";

export function makeGetJobs(store: ApiStore) {
  return (request: Request) => safely(async () => {
    const search = new URL(request.url).searchParams;
    const raw = Object.fromEntries(search);
    raw.filter ??= "all";
    const parsed = JobListQuerySchema.safeParse(raw);
    if (!parsed.success) throw new HttpError(400, "Invalid job filters.");
    return output(JobListResponseSchema, { jobs: await store.listJobs(parsed.data) });
  }, "job_list");
}

export function GET(request: Request): Promise<Response> {
  return makeGetJobs(getApiStore())(request);
}
