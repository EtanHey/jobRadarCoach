import { NewRolesQuerySchema, NewRolesResponseSchema, NewRolesProbeSchema } from "../../../../lib/new-roles-contract";
import { getNewRolesStore } from "../../../../lib/new-roles-server";
import { HttpError, output, parse, safely } from "../../../../lib/http";
export function makePostNewRoles(store: ReturnType<typeof getNewRolesStore>) {
  return (request: Request) => safely(async () => {
    if (request.headers.get("content-type")?.split(";")[0] !== "application/json") throw new HttpError(415, "Content-Type must be application/json.");
    const body = await request.text();
    if (body.length > 400000) throw new HttpError(413, "Request body is too large.");
    let value: unknown;
    try { value = JSON.parse(body); } catch { throw new HttpError(400, "Malformed JSON."); }
    return output(NewRolesResponseSchema, await store.count(parse(NewRolesQuerySchema, value)));
  }, "job_list");
}
export function POST(request: Request): Promise<Response> { return makePostNewRoles(getNewRolesStore())(request); }
// Quiet polls send no loaded ids. A nonempty probe is reconciled with the loaded cohort by POST.
export function makeGetNewRoles(store: ReturnType<typeof getNewRolesStore>) {
  return (request: Request) => safely(async () => output(NewRolesProbeSchema, await store.probe(
    parse(NewRolesQuerySchema.omit({ids:true,view:true,incoming_ids:true}),Object.fromEntries(new URL(request.url).searchParams)),
  )), "job_list");
}
export function GET(request: Request): Promise<Response> { return makeGetNewRoles(getNewRolesStore())(request); }
