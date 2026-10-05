import { NewJobCountQuerySchema, NewJobCountResponseSchema } from "../../../../lib/contracts";
import { HttpError, output, safely } from "../../../../lib/http";
import { getApiStore, type ApiStore } from "../../../../lib/server";

export function makeGetNewJobCount(store: ApiStore) {
  return (request: Request) => safely(async () => {
    const raw = Object.fromEntries(new URL(request.url).searchParams);
    const parsed = NewJobCountQuerySchema.safeParse(raw);
    if (!parsed.success) throw new HttpError(400, "Invalid new-roles query.");
    return output(NewJobCountResponseSchema, { count: await store.countJobsSince(parsed.data) });
  }, "job_new_count");
}

export function GET(request: Request): Promise<Response> {
  return makeGetNewJobCount(getApiStore())(request);
}
