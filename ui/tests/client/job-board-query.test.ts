import assert from "node:assert/strict";
import { test } from "node:test";
import type { JobSummary } from "../../lib/contracts";
import { QueryClient } from "@tanstack/react-query";
import { applyConfirmedStatus, boardListKey, confirmedStatusRevision, confirmListRead } from "../../lib/job-board-query";

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

const row = { id: "fixture", status: "new", status_reason: null } as JobSummary;
test("a confirmed PATCH survives an older Show read without losing arrivals or a replacement GET", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const key = boardListKey("new-for-me", "active");
  client.setQueryData(key, { jobs: [row], loadedUpdatedAt: null });
  let release!: (value: { jobs: JobSummary[]; loadedUpdatedAt: null }) => void;
  let reads = 0;
  const started = confirmedStatusRevision(client);
  const oldRead = client.fetchQuery({ queryKey: key, staleTime: 0, queryFn: async () => {
    reads++;
    const read = await new Promise<{ jobs: JobSummary[]; loadedUpdatedAt: null }>(resolve => { release = resolve; });
    return { ...read, jobs: confirmListRead(client, read.jobs, "new-for-me", started) };
  } }).catch(() => undefined);
  await applyConfirmedStatus(client, row.id, { status: "applied", reason: null }, false);
  const arrival = { ...row, id: "arrival" };
  release({ jobs: [row, arrival], loadedUpdatedAt: null });
  await oldRead;
  assert.deepEqual(client.getQueryData(key), { jobs: [arrival], loadedUpdatedAt: null });
  assert.equal(reads, 1);
  client.clear();
});
test("automatic Seen retains New-for-me cards and patches other cached views", async () => {
  const client = new QueryClient();
  const fresh = boardListKey("new-for-me", "active"), all = boardListKey("all", "active");
  for (const key of [fresh, all]) client.setQueryData(key, { jobs: [row], loadedUpdatedAt: null });
  await applyConfirmedStatus(client, row.id, { status: "seen", reason: null }, true);
  for (const key of [fresh, all]) assert.equal(client.getQueryData<{ jobs: JobSummary[] }>(key)?.jobs[0].status, "seen");
  client.clear();
});
test("an uncached read applies only overlapping confirmations and later reads use server truth", async () => {
  const client = new QueryClient();
  await applyConfirmedStatus(client, row.id, { status: "applied", reason: null }, false);
  assert.deepEqual(confirmListRead(client, [row], "new-for-me", 0), []);
  assert.equal(confirmListRead(client, [row], "all", 0)[0].status, "applied");
  assert.equal(confirmListRead(client, [row], "all", confirmedStatusRevision(client))[0].status, "new");
  client.clear();
});

test("confirmation ordering survives inactive-query GC without overriding subsequent server truth", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { gcTime: 0 } } });
  applyConfirmedStatus(client, row.id, { status: "applied", reason: null }, false);
  await new Promise(resolve => setTimeout(resolve, 5));
  const started = confirmedStatusRevision(client);
  assert.equal(started, 1);
  assert.equal(confirmListRead(client, [row], "all", started)[0].status, "new");
  client.clear();
});
