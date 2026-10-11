import "server-only";
import type { SupabaseClient } from "@supabase/supabase-js";
import { client, data } from "./server";
import { GlobeJobSchema } from "./globe-contract";
import { countNewRoleCards, NEW_ROLES_LIMIT } from "./new-roles";
import type { NewRolesQuery } from "./new-roles-contract";
import { normalizedIdentity } from "./job-dedup";
import { z } from "zod";
const snapshotSchema = z.object({current: GlobeJobSchema.array(), incoming: GlobeJobSchema.array()});
export function getNewRolesStore(db: SupabaseClient = client()) {
  const read = async (input: Omit<NewRolesQuery,"view"|"incoming_ids"> & {incoming_ids?: string[]}) => snapshotSchema.parse(await data(db.rpc("get_new_roles_snapshot", {
      filter: input.filter, availability: input.availability, since: input.since,
      found_within: input.found_within ?? "", ids: input.ids,
      incoming_ids: input.incoming_ids ?? null,
    })));
  return {
    async probe(input: Omit<NewRolesQuery,"view"|"ids"|"incoming_ids">) {
      const snapshot=await read({...input,ids:[]});
      return {count:snapshot.incoming.length,truncated:snapshot.incoming.length>NEW_ROLES_LIMIT,companies:[...new Set(snapshot.incoming.map(job=>normalizedIdentity(job.company)))],incoming_ids:snapshot.incoming.map(job=>job.id)};
    },
    async count(input: NewRolesQuery) {
    const snapshot=await read(input);
    return {count: countNewRoleCards(snapshot.current, snapshot.incoming.slice(0, NEW_ROLES_LIMIT),
      {...input.view, found_within: input.found_within}), truncated: input.incoming_ids.length > NEW_ROLES_LIMIT};
  }};
}
