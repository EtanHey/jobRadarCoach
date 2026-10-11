import assert from "node:assert/strict";
import { test } from "node:test";
import type { JobDetail, JobSummary } from "../../lib/contracts";
import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { applyScoreAnyway, applyConfirmedStatus, boardListKey, cachedVisitCohort, confirmedStatusRevision, confirmDetailRead, confirmListRead, DETAIL_STALE_MS, jobDetailQueryOptions, patchCachedDetailStatus } from "../../lib/job-board-query";

test("server facet changes retain the New-for-me visit cohort across query keys", () => {
  const client = new QueryClient();
  const view = { fit: "recommended", statuses: [], sort: "fit" as const };
  const kept = { id: "kept", status: "seen" } as JobSummary;
  client.setQueryData(boardListKey("new-for-me", "active", view), { jobs: [kept], loadedUpdatedAt: null });
  client.setQueryData(boardListKey("new-for-me", "active", { ...view, sort: "found" }), { jobs: [kept, row], loadedUpdatedAt: null });
  assert.deepEqual(cachedVisitCohort(client, "active"), [kept, row]);
  assert.equal(cachedVisitCohort(client, "inactive"), null);
  client.clear();
});

test("list cache isolates every server facet, canonicalizing OR status order", () => {
  const view = { fit: "recommended", statuses: ["applied", "worth_checking"] as const, sort: "fit" as const };
  const key = boardListKey("all", "active", { ...view, statuses: [...view.statuses] });
  assert.deepEqual(key, boardListKey("all", "active", { ...view, statuses: ["worth_checking", "applied", "applied"] }));
  assert.notDeepEqual(key, boardListKey("all", "active", { ...view, statuses: [], fit: "recommended" }));
  assert.notDeepEqual(key, boardListKey("all", "active", { ...view, statuses: [...view.statuses], fit: "good" }));
  assert.notDeepEqual(key, boardListKey("all", "active", { ...view, statuses: [...view.statuses], sort: "found" }));
});

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

function observeList(client: QueryClient, key: ReturnType<typeof boardListKey>) {
  return new QueryObserver(client, { queryKey: key, staleTime: Infinity, queryFn: () => Promise.reject(new Error("Unexpected list read")) }).subscribe(() => {});
}

const row = { id: "fixture", status: "new", status_reason: null } as JobSummary;
test("a confirmed PATCH survives an older Show read without losing arrivals or a replacement GET", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const key = boardListKey("new-for-me", "active");
  client.setQueryData(key, { jobs: [row], loadedUpdatedAt: null });
  const stop = observeList(client, key);
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
  stop(); client.clear();
});
test("automatic Seen retains the active New-for-me cohort and drops inactive views", () => {
  const client = new QueryClient();
  const fresh = boardListKey("new-for-me", "active"), all = boardListKey("all", "active");
  for (const key of [fresh, all]) client.setQueryData(key, { jobs: [row], loadedUpdatedAt: null });
  const stop = observeList(client, fresh);
  applyConfirmedStatus(client, row.id, { status: "seen", reason: null }, true);
  assert.equal(client.getQueryData<{ jobs: JobSummary[] }>(fresh)?.jobs[0].status, "seen");
  assert.equal(client.getQueryData(all), undefined);
  stop(); client.clear();
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

test("a status confirmation drops inactive Seen results without refetching the active list", () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  const all = boardListKey("all", "active"), seen = boardListKey("seen", "active");
  client.setQueryData(all, { jobs: [row], loadedUpdatedAt: null });
  client.setQueryData(seen, { jobs: [], loadedUpdatedAt: null });
  let reads = 0;
  const stop = new QueryObserver(client, { queryKey: all, queryFn: () => { reads++; return Promise.resolve({ jobs: [row], loadedUpdatedAt: null }); } }).subscribe(() => {});
  applyConfirmedStatus(client, row.id, { status: "seen", reason: null }, true);
  assert.equal(client.getQueryData(seen), undefined);
  assert.equal(client.getQueryData<{ jobs: JobSummary[] }>(all)?.jobs[0].status, "seen");
  assert.equal(reads, 0);
  stop(); client.clear();
});

test("a held detail read keeps an overlapping confirmed status; a later opening uses server truth", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const job = { ...row, raw_jd: "Synthetic description" } as JobDetail;
  const started = confirmedStatusRevision(client);
  let release!: (job: JobDetail) => void;
  const read = client.fetchQuery({ queryKey: ["board-detail", row.id, 1], queryFn: async () => {
    const read = await new Promise<JobDetail>(resolve => { release = resolve; });
    return confirmDetailRead(client, read, started);
  } });
  applyConfirmedStatus(client, row.id, { status: "applied", reason: null }, false);
  release(job);
  assert.equal((await read).status, "applied");
  assert.equal(confirmDetailRead(client, job, confirmedStatusRevision(client)), job);
  client.clear();
});

test("closing a detail observer aborts its read and cannot publish into the next selected role", async () => {
  const client = new QueryClient();
  let signal!: AbortSignal, release!: (value: string) => void;
  const oldKey = ["board-detail", "old-role", 1];
  const old = new QueryObserver(client, { queryKey: oldKey, gcTime: 0, queryFn: ({ signal: current }) => {
    signal = current;
    return new Promise<string>(resolve => { release = resolve; });
  } });
  const close = old.subscribe(() => {});
  close();
  assert.equal(signal.aborted, true);
  const nextKey = ["board-detail", "next-role", 2];
  await client.fetchQuery({ queryKey: nextKey, queryFn: () => Promise.resolve("next role body") });
  release("old role body");
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(client.getQueryData(oldKey), undefined);
  assert.equal(client.getQueryData(nextKey), "next role body");
  client.clear();
});

const detailFixture = {
  id: "0199d9c3-a742-7000-8000-000000000001", title: "Engineer", company: "Example", source: "fixture", last_seen_at: "2026-09-08T10:00:00Z", first_seen_at: "2026-09-08T10:00:00Z",
  experience: null, description_available: true, seniority_origin: "unknown", extraction_state: "not-extracted", location: null, remote: null,
  seniority: null, stack: [], salary: null, url: "https://example.test/job", apply_url: null, posted_at: null, status: "new", status_reason: null,
  score: null, fit_line: null, recommendation: null, raw_jd: "Synthetic description", reasons: [], score_payload: null, brain: null, scored_at: null,
};

test("hover prefetch and the drawer share one detail query: open reads from cache, staleTime bounds refetches", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  const reads: string[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    reads.push(String(input));
    return Response.json({ job: detailFixture });
  }) as typeof fetch;
  try {
    const options = jobDetailQueryOptions(client, detailFixture.id);
    assert.deepEqual(options.queryKey, ["board-detail", detailFixture.id]);
    assert.ok(Number.isFinite(options.staleTime) && (options.staleTime as number) > 0, "finite detail staleTime");
    assert.ok((options.gcTime as number) >= (options.staleTime as number), "prefetched data outlives its freshness window");
    await Promise.all([client.prefetchQuery(options), client.prefetchQuery(jobDetailQueryOptions(client, detailFixture.id))]);
    assert.equal(reads.length, 1, "one in-flight prefetch per card");
    await client.prefetchQuery(jobDetailQueryOptions(client, detailFixture.id));
    assert.equal(reads.length, 1, "fresh data is not refetched");
    const observer = new QueryObserver(client, { ...jobDetailQueryOptions(client, detailFixture.id), enabled: true });
    const stop = observer.subscribe(() => {});
    assert.equal(observer.getCurrentResult().data?.raw_jd, "Synthetic description", "the drawer renders the prefetched body at once");
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(reads.length, 1, "opening adds zero detail reads");
    stop();
  } finally {
    globalThis.fetch = original;
    client.clear();
  }
});

test("a status-only cache write keeps the detail read's age, so score and body still refresh after staleTime", () => {
  const client = new QueryClient();
  const key = jobDetailQueryOptions(client, row.id).queryKey;
  const readAt = Date.now() - DETAIL_STALE_MS - 1_000;
  client.setQueryData(key, { ...row, raw_jd: "Synthetic description" } as JobDetail, { updatedAt: readAt });
  for (const result of [{ status: "seen", reason: null }, { status: "applied", reason: null }] as const) {
    patchCachedDetailStatus(client, row.id, result);
    const state = client.getQueryState(key);
    assert.equal(client.getQueryData<JobDetail>(key)?.status, result.status);
    assert.equal(state?.dataUpdatedAt, readAt, "a status write is not a detail read");
  }
  assert.equal(client.getQueryCache().find({ queryKey: key })?.isStaleByTime(DETAIL_STALE_MS), true, "the next opening refetches score and body");
  patchCachedDetailStatus(client, "never-read", { status: "seen", reason: null });
  assert.equal(client.getQueryCache().find({ queryKey: ["board-detail", "never-read"] }), undefined, "no entry is created for an unread role");
  client.clear();
});

test("found windows isolate list caches and retained New-for-me cohorts", () => {
  const client = new QueryClient();
  const view = { fit: "recommended", statuses: [], sort: "fit" as const, found_within: "24h" as const };
  const recent = boardListKey("new-for-me", "active", view);
  const older = boardListKey("new-for-me", "active", { ...view, found_within: "30d" });
  assert.notDeepEqual(recent, older);
  client.setQueryData(recent, { jobs: [row], loadedUpdatedAt: null });
  client.setQueryData(older, { jobs: [{ ...row, id: "old" }], loadedUpdatedAt: null });
  assert.deepEqual(cachedVisitCohort(client, "active", "24h"), [row]);
  assert.equal(cachedVisitCohort(client, "active", "7d"), null);
  client.clear();
});

test("filtered postings leave retained normal tabs and remain only in the archive", () => {
  const client = new QueryClient();
  const filtered = { ...row, relevance_filtered: true, relevance_rule: "leadership-title-strict" };
  for (const filter of ["all", "new-for-me", "seen"] as const) assert.deepEqual(confirmListRead(client, [filtered], filter, 0), []);
  assert.deepEqual(confirmListRead(client, [filtered], "not-scored", 0), [filtered]);
  client.clear();
});


test("an override defeats a held archive read but a later JD verdict stays authoritative", () => {
  const client = new QueryClient();
  const filtered = { ...row, relevance_filtered: true };
  applyScoreAnyway(client, { ...filtered, relevance_filtered: false } as JobDetail);
  assert.deepEqual(confirmListRead(client, [filtered], "not-scored", 0), []);
  assert.deepEqual(confirmListRead(client, [filtered], "not-scored", confirmedStatusRevision(client)), [filtered]);
  client.clear();
});


test("server facets partition snapshots, including legacy remote", () => {
  const base = { fit: "", statuses: [], sort: "fit" as const, found_within: "" as const };
  for (const [name, value] of Object.entries({ source: "synthetic", work_mode: "hybrid", location: "israel", seniority: "Junior", remote: false })) {
    assert.notDeepEqual(boardListKey("all", "all", base), boardListKey("all", "all", { ...base, [name]: value }));
  }
});
