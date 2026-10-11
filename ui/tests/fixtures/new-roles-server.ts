// Separate react-server process so the client query exercises real API handlers.
import { readFileSync } from "node:fs";
import { createClient } from "@supabase/supabase-js";
import { getNewRolesStore } from "../../lib/new-roles-server";
import { makeGetNewRoles, makePostNewRoles } from "../../app/api/jobs/new-roles/route";
async function main() {
  const fixture = JSON.parse(readFileSync(0, "utf8"));
  const db = createClient("https://database.example.test", "synthetic", { global: { fetch: async (_url, init) => {
    const args = JSON.parse(String(init?.body));
    return Response.json({ incoming: fixture.incoming.filter((row: {id: string}) =>
      !args.incoming_ids || args.incoming_ids.includes(row.id)),
      current: args.ids.includes(fixture.loaded.id) ? [fixture.loaded] : [] });
  } } });
  const store = getNewRolesStore(db);
  const request = new Request("https://example.test" + fixture.path, fixture.body ? {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(fixture.body),
  } : undefined);
  const response = await (fixture.body ? makePostNewRoles(store) : makeGetNewRoles(store))(request);
  if (!response.ok) throw new Error(await response.text());
  console.log(await response.text());
}
void main();
