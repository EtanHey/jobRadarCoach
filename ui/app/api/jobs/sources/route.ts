import { JobSourcesQuerySchema, JobSourcesResponseSchema } from "../../../../lib/contracts";
import { HttpError, output, safely } from "../../../../lib/http";
import { getApiStore, type ApiStore } from "../../../../lib/server";

export function makeGetSources(store: Pick<ApiStore, "listSources">) {
  return (request: Request) => safely(async () => {
    const parsed = JobSourcesQuerySchema.safeParse(Object.fromEntries(new URL(request.url).searchParams));
    if (!parsed.success) throw new HttpError(400, "Invalid source filters.");
    return output(JobSourcesResponseSchema, { sources: await store.listSources(parsed.data) });
  });
}

export function GET(request: Request): Promise<Response> {
  return makeGetSources(getApiStore())(request);
}
