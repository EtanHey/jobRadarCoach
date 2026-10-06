import assert from "node:assert/strict";
import { test } from "node:test";
import { QueryClient } from "@tanstack/react-query";
import { boardListKey } from "../../lib/job-board-query";

test("list queries isolate filter and availability and reuse their cached response", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  let reads = 0;
  const queryFn = async () => ++reads;
  const all = boardListKey("all", "active"), inactive = boardListKey("all", "inactive");
  assert.equal(await client.fetchQuery({ queryKey: all, queryFn }), 1);
  assert.equal(await client.fetchQuery({ queryKey: all, queryFn }), 1);
  assert.equal(await client.fetchQuery({ queryKey: inactive, queryFn }), 2);
  client.clear();
});

test("an abandoned list read cannot publish into the next view", async () => {
  const client = new QueryClient();
  const old = boardListKey("all", "active"), next = boardListKey("seen", "active");
  let release!: (value: string) => void;
  const read = client.fetchQuery({ queryKey: old, queryFn: () => new Promise<string>(resolve => { release = resolve; }) }).catch(() => undefined);
  await client.cancelQueries({ queryKey: old });
  client.setQueryData(next, "current view");
  release("stale view");
  await read;
  assert.equal(client.getQueryData(old), undefined);
  assert.equal(client.getQueryData(next), "current view");
  client.clear();
});
