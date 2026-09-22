import { GlobeQuerySchema, GlobeResponseSchema } from "../../../../lib/globe-contract";
import { getGlobeStore, globeResponse, type GlobeStore } from "../../../../lib/globe-server";
import { HttpError, output, safely } from "../../../../lib/http";

export function makeGetGlobe(store: GlobeStore) {
  return (request: Request) => safely(async () => {
    const parsed = GlobeQuerySchema.safeParse(Object.fromEntries(new URL(request.url).searchParams));
    if (!parsed.success) throw new HttpError(400, "Invalid globe filters.");
    return output(GlobeResponseSchema, await globeResponse(store, parsed.data));
  }, "job_globe");
}
export function GET(request: Request): Promise<Response> {
  return makeGetGlobe(getGlobeStore())(request);
}
