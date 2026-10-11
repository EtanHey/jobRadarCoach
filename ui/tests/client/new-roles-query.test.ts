import assert from "node:assert/strict";
import { test } from "node:test";
import { QueryClient } from "@tanstack/react-query";
import { newRolesQueryOptions } from "../../components/use-new-roles";
import { execFileSync } from "node:child_process";
import { countNewRoleCards } from "../../lib/new-roles";
import { GlobeJobSchema } from "../../lib/globe-contract";
import { defaultBoardPreferences } from "../../lib/job-board-preferences";

test("a duplicate arriving between probe and reconcile cannot change the probed cohort", async t => {
  const row = (n: number, company: string) => GlobeJobSchema.parse({
    id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, company, title: "Engineer",
    source: "fixture", location: null, remote: null, seniority: null, stack: [],
    url: `https://example.test/${n}`, apply_url: null, posted_at: null,
    first_seen_at: "2026-10-07T01:00:00Z", status: "new", status_reason: null,
    score: 90, recommendation: "apply", alive: true,
  });
  const loaded = row(1, "Loaded Company"), initial = row(2, "New Company"), raced = row(3, "Loaded Company");
  const view = defaultBoardPreferences().view;
  let posted: { ids: string[]; incoming_ids: string[] } | undefined;
  t.mock.method(globalThis, "fetch", async (path: string, init?: RequestInit) => {
    const body = init?.method === "POST" ? JSON.parse(String(init.body)) : null;
    if (body) posted = body;
    const env = { ...process.env }; delete env.NODE_TEST_CONTEXT;
    const stdout = execFileSync(process.execPath, ["--conditions=react-server", "--import", "tsx",
      "tests/fixtures/new-roles-server.ts"], { encoding: "utf8", env, input: JSON.stringify({ path, body, loaded,
      incoming: body ? [initial, raced] : [initial] }) });
    return Response.json(JSON.parse(stdout.trim().split("\n").at(-1)!));
  });
  const client = new QueryClient(); t.after(() => client.clear());
  const options = newRolesQueryOptions("/api/jobs/new-roles?filter=all&availability=all&since=2026-10-07T00%3A00%3A00Z",
    [loaded.id], view, [{ id: loaded.id, company: loaded.company }]);
  const actual = await client.fetchQuery({ ...options, initialData: undefined, staleTime: 0 });
  assert.equal(actual.count, countNewRoleCards([loaded], [initial, raced], view));
  assert.deepEqual(posted?.incoming_ids, [initial.id], "reconciliation must carry the probe's cohort");
  assert.deepEqual(posted?.ids, [], "unrelated loaded companies stay out of the payload");
});

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
    if (options.method !== "POST") return Response.json({count:arrivals,truncated:arrivals>0,companies:["synthetic"],incoming_ids:["00000000-0000-4000-8000-000000000002"]});
    assert.equal(path,"/api/jobs/new-roles"); assert.equal(options.method,"POST"); assert.ok(arrivals,"quiet polls must not upload ids");
    assert.deepEqual(JSON.parse(String(options.body)),{filter:"all",availability:"all",since:"2026-10-07T00:00:00Z",ids:["fixture"],view,incoming_ids:["00000000-0000-4000-8000-000000000002"]});
    return Response.json({count:7,truncated:true});
  });
  const client = new QueryClient(); t.after(() => client.clear());
  const options = newRolesQueryOptions("/api/jobs/new-roles?filter=all&availability=all&since=2026-10-07T00%3A00%3A00Z",["fixture","unrelated"],view,[{id:"fixture",company:" Ｓｙｎｔｈｅｔｉｃ "},{id:"unrelated",company:"Other"}]);
  assert.deepEqual(await client.fetchQuery({...options,initialData:undefined,staleTime:0}),{count:7,truncated:true});
  arrivals=0;
  assert.deepEqual(await client.fetchQuery({...options,initialData:undefined,staleTime:0}),{count:0,truncated:false});
});
