import { JobIdSchema, StatusPatchSchema, StatusResponseSchema } from "../../../../../lib/contracts";
import { HttpError, mutationJson, output, parse, safely } from "../../../../../lib/http";
import { getApiStore, type ApiStore } from "../../../../../lib/server";

type Context = { params: Promise<{ id: string }> };

export function makePatchStatus(store: ApiStore) {
  return (request: Request, context: Context) => safely(async () => {
    const id = parse(JobIdSchema, (await context.params).id);
    const patch = await mutationJson(request, StatusPatchSchema);
    if (request.headers.get("x-job-radar-status-version") !== "2") throw new HttpError(409, "Refresh Job Radar before changing status.");
    return output(StatusResponseSchema, await store.setStatus({ posting_id: id, ...patch }));
  });
}

export function PATCH(request: Request, context: Context): Promise<Response> {
  return makePatchStatus(getApiStore())(request, context);
}
