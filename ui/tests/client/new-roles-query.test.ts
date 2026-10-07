import assert from "node:assert/strict";
import { test } from "node:test";
import { QueryClient } from "@tanstack/react-query";
import { newRolesQueryOptions } from "../../components/use-new-roles";

test("new-role queries poll every 90s, pause while hidden and focus only after a 15s quiet gap", t => {
  const options = newRolesQueryOptions("/api/jobs/new-roles?since=fixture");
  assert.equal(options.refetchInterval, 90_000);
  assert.equal(options.refetchIntervalInBackground, false);
  assert.equal(options.staleTime, 15_000);
  const client = new QueryClient();
  t.after(() => client.clear());
  const query = client.getQueryCache().build(client, { ...options, queryKey: [...options.queryKey] });
  assert.equal(typeof options.refetchOnWindowFocus, "function");
  if (typeof options.refetchOnWindowFocus !== "function") throw new Error("Focus must respect the quiet gap");
  query.setState({ dataUpdatedAt: 1_000, errorUpdatedAt: 0 });
  const clock = t.mock.method(Date, "now", () => 15_999);
  assert.equal(options.refetchOnWindowFocus(query), false);
  clock.mock.mockImplementation(() => 16_000);
  assert.equal(options.refetchOnWindowFocus(query), true);
  query.setState({ errorUpdatedAt: 10_000 });
  clock.mock.mockImplementation(() => 24_999);
  assert.equal(options.refetchOnWindowFocus(query), false);
  clock.mock.mockImplementation(() => 25_000);
  assert.equal(options.refetchOnWindowFocus(query), true);
});
test("the poll posts only loaded ids and view and consumes a count response", async t => {
  const view = {search:"",source:"",location:"" as const,seniority:"",fit:"",statuses:[],availability:"all" as const,sort:"fit" as const};
  let arrivals=7;
  t.mock.method(globalThis, "fetch", async (path: string, options: RequestInit) => {
    if (options.method !== "POST") return Response.json({count:arrivals,truncated:arrivals>0,companies:["synthetic"]});
    assert.equal(path,"/api/jobs/new-roles"); assert.equal(options.method,"POST"); assert.ok(arrivals,"quiet polls must not upload ids");
    assert.deepEqual(JSON.parse(String(options.body)),{filter:"all",availability:"all",since:"2026-10-07T00:00:00Z",ids:["fixture"],view});
    return Response.json({count:7,truncated:true});
  });
  const client = new QueryClient(); t.after(() => client.clear());
  const options = newRolesQueryOptions("/api/jobs/new-roles?filter=all&availability=all&since=2026-10-07T00%3A00%3A00Z",["fixture","unrelated"],view,[{id:"fixture",company:" Ｓｙｎｔｈｅｔｉｃ "},{id:"unrelated",company:"Other"}]);
  assert.deepEqual(await client.fetchQuery({...options,initialData:undefined,staleTime:0}),{count:7,truncated:true});
  arrivals=0;
  assert.deepEqual(await client.fetchQuery({...options,initialData:undefined,staleTime:0}),{count:0,truncated:false});
});
