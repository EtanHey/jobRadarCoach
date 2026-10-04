import assert from "node:assert/strict";
import { test } from "node:test";
import { loadJobDetail } from "../lib/job-detail-request";
import { safely, HttpError } from "../lib/http";

const fixture = {
  id: "0199d9c3-a742-7000-8000-000000000001", title: "Engineer", company: "Example",
  source: "linkedin", last_seen_at: "2026-09-08T10:00:00Z", first_seen_at: "2026-09-08T10:00:00Z",
  experience: null, description_available: true, seniority_origin: "unknown", extraction_state: "not-extracted",
  location: null, remote: null, seniority: null, stack: [], salary: null, url: "https://example.test/job",
  apply_url: null, posted_at: null, status: "new", status_reason: null, score: null, fit_line: null,
  recommendation: null, raw_jd: "Public description", reasons: [], score_payload: null, brain: null, scored_at: null,
};

test("detail read recovers from gateway failure without issuing a mutation", async () => {
  const calls: RequestInit[] = [], waits: number[] = [];
  const result = await loadJobDetail(fixture.id, new AbortController().signal, async (_url, options) => {
    calls.push(options!);
    return calls.length === 1 ? new Response("Bad Gateway", { status: 502 }) : Response.json({ job: fixture });
  }, async (ms) => { waits.push(ms); });
  assert.equal(result.id, fixture.id);
  assert.equal(calls.length, 2);
  assert(calls.every((call) => !call.method || call.method === "GET"));
  assert.deepEqual(waits, [750]);
});

test("persistent unavailable service stops after three reads and offers recovery", async () => {
  let calls = 0;
  await assert.rejects(loadJobDetail(fixture.id, new AbortController().signal, async () => {
    calls++; return new Response(null, { status: 503 });
  }, async () => {}), /Retry.*original posting/);
  assert.equal(calls, 3);
});

test("not found and malformed payloads do not retry", async () => {
  for (const response of [new Response(null, { status: 404 }), Response.json({ job: {} })]) {
    let calls = 0;
    await assert.rejects(loadJobDetail(fixture.id, new AbortController().signal, async () => { calls++; return response; }, async () => { assert.fail("unexpected retry"); }));
    assert.equal(calls, 1);
  }
});

test("closing selection cancels the retry before another read", async () => {
  const controller = new AbortController(); let calls = 0;
  await assert.rejects(loadJobDetail(fixture.id, controller.signal, async () => {
    calls++; return new Response(null, { status: 502 });
  }, async () => { controller.abort(); }), { name: "AbortError" });
  assert.equal(calls, 1);
});

test("job detail failure log correlates response without including private error contents", async (t) => {
  const log = t.mock.method(console, "error", () => {});
  const response = await safely(async () => { throw new Error("PRIVATE_SQL_TOKEN_SENTINEL"); }, "job_detail");
  const entry = JSON.parse(log.mock.calls[0].arguments[0]);
  assert.equal(response.status, 500);
  assert.equal(entry.requestId, response.headers.get("x-request-id"));
  assert.equal(entry.operation, "job_detail");
  assert.equal(entry.category, "unexpected");
  assert(!JSON.stringify(entry).includes("SENTINEL"));
  assert(!(await response.text()).includes("SENTINEL"));
  const unavailable = await safely(async () => { throw new HttpError(503, "Database request failed.", "database"); }, "job_detail");
  assert.equal(unavailable.status, 503);
  assert.equal(JSON.parse(log.mock.calls[1].arguments[0]).category, "database");
});

test("a queued detail fetch reaches a bounded error and aborts its transport", async () => {
  let transportSignal: AbortSignal | undefined;
  const read = loadJobDetail(fixture.id, new AbortController().signal, async (_url, options) => {
    transportSignal = options!.signal!;
    return new Promise<Response>(() => {});
  }, async () => {}, 20);
  await assert.rejects(Promise.race([read, new Promise((_, reject) => setTimeout(() => reject(new Error("TEST: detail still pending past deadline")), 100))]), /took too long.*Retry/);
  assert.equal(transportSignal?.aborted, true);
});

test("a stalled response body is covered by the same detail deadline", async () => {
  const response = new Response();
  response.json = () => new Promise(() => {});
  const read = loadJobDetail(fixture.id, new AbortController().signal, async () => response, async () => {}, 20);
  await assert.rejects(Promise.race([read, new Promise((_, reject) => setTimeout(() => reject(new Error("TEST: detail body still pending past deadline")), 100))]), /took too long.*Retry/);
});

test("closing a queued read preserves caller cancellation without retrying", async () => {
  const controller = new AbortController();
  let calls = 0;
  const read = loadJobDetail(fixture.id, controller.signal, async () => {
    calls++; return new Promise<Response>(() => {});
  }, async () => assert.fail("unexpected retry"), 50);
  const reason = new DOMException("Selection closed", "AbortError");
  controller.abort(reason);
  await assert.rejects(Promise.race([read, new Promise((_, reject) => setTimeout(() => reject(new Error("TEST: cancelled read still pending")), 100))]), error => error === reason);
  assert.equal(calls, 1);
});

test("the detail deadline includes time spent waiting between retries", async () => {
  let calls = 0;
  const read = loadJobDetail(fixture.id, new AbortController().signal, async () => {
    calls++; return new Response(null, {status: 503});
  }, async () => new Promise(() => {}), 20);
  await assert.rejects(Promise.race([read, new Promise((_, reject) => setTimeout(() => reject(new Error("TEST: retry wait still pending past deadline")), 100))]), /took too long.*Retry/);
  assert.equal(calls, 1);
});
