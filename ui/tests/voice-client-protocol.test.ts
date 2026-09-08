import { test } from "node:test";
import assert from "node:assert/strict";

import {
  createOpenJobRpcHandler, MAX_OPEN_JOB_PAYLOAD_BYTES, OpenJobProtocolError,
  reduceTranscript, TRANSCRIPTION_TOPIC,
} from "../lib/voice/client-protocol";

const AGENT = "agent:riki";
const POSTING = "00000000-0000-4000-8000-000000000001";
const APPLY = "https://jobs.example.test/apply?job=1";
const requestId = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const payload = (id = requestId(1), apply_url = APPLY) => JSON.stringify({
  version: 1, request_id: id, posting_id: POSTING, apply_url,
});
const job = (apply_url: string | null = APPLY, url = "https://jobs.example.test/job/1") =>
  Response.json({ job: { id: POSTING, apply_url, url } });
const invocation = (value = payload(), callerIdentity = AGENT) => ({ callerIdentity, payload: value });
const parsed = (value: string) => JSON.parse(value);

test("deduplicates concurrent and completed requests before one grounded noopener open", async () => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let fetches = 0;
  const opens: unknown[][] = [];
  const handler = createOpenJobRpcHandler({
    trustedAgentIdentity: AGENT,
    fetchJob: async (input, init) => {
      fetches += 1;
      assert.equal(input, `/api/jobs/${POSTING}`);
      assert.deepEqual({ ...init, signal: undefined }, {
        method: "GET", headers: { accept: "application/json" }, cache: "no-store", signal: undefined,
      });
      assert.ok(init?.signal instanceof AbortSignal);
      await gate;
      return job();
    },
    openWindow: (...args) => { opens.push(args); return {} as Window; },
    renderFallback: () => assert.fail("fallback was not expected"),
    maxRememberedRequests: 1,
  });
  const first = handler(invocation());
  const duplicate = handler(invocation());
  assert.equal(fetches, 1);
  release();
  const [firstAck, duplicateAck] = await Promise.all([first, duplicate]);
  assert.deepEqual(parsed(firstAck), { version: 1, request_id: requestId(1), status: "opened" });
  assert.equal(duplicateAck, firstAck);
  assert.equal(await handler(invocation(payload(requestId(1), "https://different.example/"))), firstAck);
  await assert.rejects(handler(invocation(payload(requestId(2)))), OpenJobProtocolError);
  assert.equal(await handler(invocation()), firstAck);
  assert.equal(fetches, 1);
  assert.deepEqual(opens, [[APPLY, "_blank", "noopener,noreferrer"]]);
});

test("rejects non-public URLs, untrusted senders, and oversized JSON without fetching", async () => {
  let fetches = 0;
  const handler = createOpenJobRpcHandler({
    trustedAgentIdentity: AGENT,
    fetchJob: async () => { fetches += 1; return job(); },
    openWindow: () => assert.fail("open was not expected"),
    renderFallback: () => assert.fail("fallback was not expected"),
  });
  const unsafe = [
    "http://jobs.example.test/a", "javascript:alert(1)", "data:text/plain,no",
    "https://localhost/a", "https://127.0.0.1/a", "https://10.0.0.1/a",
    "https://172.16.1.1/a", "https://192.168.1.1/a", "https://169.254.1.1/a",
    "https://intranet/a", "https://[::1]/a", "https://[fd00::1]/a", "https://[ff02::1]/a",
    "https://[2001:db8::1]/a", "https://user:password@jobs.example.test/a",
  ];
  for (const [index, url] of unsafe.entries()) {
    assert.equal(parsed(await handler(invocation(payload(requestId(index + 2), url)))).reason, "not_https");
  }
  await assert.rejects(handler(invocation(payload(requestId(20)), "participant:other")), OpenJobProtocolError);
  await assert.rejects(handler(invocation("x".repeat(MAX_OPEN_JOB_PAYLOAD_BYTES + 1))), OpenJobProtocolError);
  assert.equal(fetches, 0);
});

test("requires exact preferred canonical URL and renders fallback before a blocked acknowledgement", async () => {
  const order: string[] = [];
  const equivalentButDifferent = "https://jobs.example.test/~candidate";
  const mismatch = createOpenJobRpcHandler({
    trustedAgentIdentity: AGENT, fetchJob: async () => job("https://jobs.example.test/%7Ecandidate", equivalentButDifferent),
    openWindow: () => assert.fail("open was not expected"), renderFallback: () => assert.fail("fallback was not expected"),
  });
  assert.deepEqual(parsed(await mismatch(invocation(payload(requestId(1), equivalentButDifferent)))), {
    version: 1, request_id: requestId(1), status: "rejected", reason: "url_mismatch",
  });

  const blocked = createOpenJobRpcHandler({
    trustedAgentIdentity: AGENT, fetchJob: async () => job(null, APPLY),
    openWindow: () => { order.push("open"); return null; },
    renderFallback: ({ href, requestId: id }) => { assert.equal(href, APPLY); assert.equal(id, requestId(21)); order.push("fallback"); },
  });
  const ack = parsed(await blocked(invocation(payload(requestId(21)))));
  order.push("ack");
  assert.deepEqual(ack, {
    version: 1, request_id: requestId(21), status: "popup_blocked", fallback: "clickable_link_rendered",
  });
  assert.deepEqual(order, ["open", "fallback", "ack"]);
});

test("does not cache a transient GET failure or open from malformed API data", async () => {
  let attempts = 0;
  let opens = 0;
  const handler = createOpenJobRpcHandler({
    trustedAgentIdentity: AGENT,
    fetchJob: async () => { attempts += 1; if (attempts === 1) throw new Error("offline"); return job(); },
    openWindow: () => { opens += 1; return {} as Window; }, renderFallback: () => undefined,
  });
  await assert.rejects(handler(invocation()), OpenJobProtocolError);
  assert.equal(parsed(await handler(invocation())).status, "opened");
  assert.equal(attempts, 2);
  assert.equal(opens, 1);

  const malformed = createOpenJobRpcHandler({
    trustedAgentIdentity: AGENT, fetchJob: async () => Response.json({ job: { apply_url: APPLY } }),
    openWindow: () => assert.fail("open was not expected"), renderFallback: () => undefined,
  });
  await assert.rejects(malformed(invocation(payload(requestId(22)))), OpenJobProtocolError);

  const invalidPayload = JSON.stringify({
    version: 1, request_id: requestId(23), posting_id: POSTING, apply_url: APPLY, extra: true,
  });
  assert.equal(parsed(await malformed(invocation(invalidPayload))).reason, "invalid_payload");

  const missing = createOpenJobRpcHandler({
    trustedAgentIdentity: AGENT, fetchJob: async () => new Response(null, { status: 404 }),
    openWindow: () => assert.fail("open was not expected"), renderFallback: () => undefined,
  });
  assert.equal(parsed(await missing(invocation(payload(requestId(24))))).reason, "posting_not_found");
});

test("bounds response and JSON waits, aborts work, and never opens from late results", async () => {
  let resolveFetch!: (response: Response) => void;
  const lateFetch = new Promise<Response>((resolve) => { resolveFetch = resolve; });
  const signals: AbortSignal[] = [];
  let fetches = 0;
  let opens = 0;
  const handler = createOpenJobRpcHandler({
    trustedAgentIdentity: AGENT,
    fetchJob: (_input, init) => {
      signals.push(init!.signal!); fetches += 1;
      return fetches === 1 ? lateFetch : Promise.resolve(job());
    },
    openWindow: () => { opens += 1; return {} as Window; },
    renderFallback: () => assert.fail("fallback was not expected"),
    requestTimeoutMs: 10,
  });
  await assert.rejects(handler(invocation()), OpenJobProtocolError);
  assert.equal(signals[0].aborted, true);
  resolveFetch(job());
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
  assert.equal(opens, 0);
  assert.equal(parsed(await handler(invocation())).status, "opened");
  assert.equal(opens, 1);

  let resolveJson!: (value: unknown) => void;
  const lateJson = new Promise<unknown>((resolve) => { resolveJson = resolve; });
  let jsonSignal!: AbortSignal;
  const jsonHandler = createOpenJobRpcHandler({
    trustedAgentIdentity: AGENT,
    fetchJob: async (_input, init) => {
      jsonSignal = init!.signal!;
      return { status: 200, ok: true, json: () => lateJson } as Response;
    },
    openWindow: () => { opens += 1; return {} as Window; },
    renderFallback: () => assert.fail("fallback was not expected"),
    requestTimeoutMs: 10,
  });
  await assert.rejects(jsonHandler(invocation(payload(requestId(25)))), OpenJobProtocolError);
  assert.equal(jsonSignal.aborted, true);
  resolveJson({ job: { id: POSTING, apply_url: APPLY, url: APPLY } });
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
  assert.equal(opens, 1);
});

const chunk = (senderIdentity: string, segmentId: string, streamId: string, chunkIndex: number,
  text: string, final: boolean, role: "user" | "agent" = "user") => ({
  topic: TRANSCRIPTION_TOPIC, senderIdentity, role, streamId, chunkIndex, text,
  attributes: {
    "lk.segment_id": segmentId, "lk.transcribed_track_id": `track:${senderIdentity}`,
    "lk.transcription_final": String(final),
  },
});

test("appends stream chunks, replaces interim with final, and ignores replay or late interim", () => {
  let state = reduceTranscript([], chunk("web:1", "segment-1", "interim", 0, "I, ", false));
  state = reduceTranscript(state, chunk("web:1", "segment-1", "interim", 1, "I might", false));
  state = reduceTranscript(state, chunk("web:1", "segment-1", "interim", 1, "I might", false));
  state = reduceTranscript(state, chunk("web:1", "segment-1", "final", 0, "I, I-- ", true));
  state = reduceTranscript(state, chunk("web:1", "segment-1", "final", 1, "changed  it.", true));
  state = reduceTranscript(state, chunk("web:1", "segment-1", "interim", 2, " late", false));
  state = reduceTranscript(state, chunk("agent:1", "segment-1", "agent-final", 0, "Done.", true, "agent"));
  assert.deepEqual(state.map(({ senderIdentity, role, text, final }) => ({ senderIdentity, role, text, final })), [
    { senderIdentity: "web:1", role: "user", text: "I, I-- changed  it.", final: true },
    { senderIdentity: "agent:1", role: "agent", text: "Done.", final: true },
  ]);
});

test("ignores non-transcription/missing-track input and bounds retained segment rows", () => {
  const one = chunk("web:1", "one", "s1", 0, "one", true);
  assert.equal(reduceTranscript([], { ...one, topic: "other" }).length, 0);
  assert.equal(reduceTranscript([], { ...one, attributes: { ...one.attributes, "lk.transcribed_track_id": "" } }).length, 0);
  assert.equal(reduceTranscript([], { ...one, chunkIndex: -1 }).length, 0);
  assert.equal(reduceTranscript([], { ...one, extra: true } as never).length, 0);
  assert.equal(reduceTranscript([], {
    ...one, attributes: { ...one.attributes, "lk.transcription_final": "TRUE" },
  }).length, 0);
  let state = reduceTranscript([], one, 2);
  assert.throws(() => reduceTranscript(state, chunk("web:1", "one", "s1", 1, "late", true), 0));
  state = reduceTranscript(state, chunk("web:1", "two", "s2", 0, "two", true), 2);
  state = reduceTranscript(state, chunk("web:1", "three", "s3", 0, "three", true), 2);
  assert.deepEqual(state.map((item) => item.segmentId), ["two", "three"]);
});
