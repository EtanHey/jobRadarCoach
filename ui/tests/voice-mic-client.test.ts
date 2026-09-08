import assert from "node:assert/strict";
import { test } from "node:test";
import {
  createMicClient, type CaptureHandle, type MicEventStream, type PageLifecycle,
} from "../lib/voice/mic-client";
const SELF = "a15ce2ae-6ef8-4ce2-b1e4-9255bc08e61f";
const OTHER = "b71c785c-8123-4ed3-9f8f-8d65750d6ee4";
const TIME = "2026-09-08T18:00:00.000Z";
const mic = (revision: string, client_id: string | null = SELF) => ({ client_id, revision, updated_at: TIME });
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
class FakeEvents implements MicEventStream {
  listeners = new Map<string, Array<(event: MessageEvent) => void>>();
  closed = 0;
  addEventListener(name: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
  }
  emit(name: string, data: unknown = {}) {
    for (const listener of this.listeners.get(name) ?? []) listener({ data: JSON.stringify(data) } as MessageEvent);
  }
  close() { this.closed += 1; }
}
function harness() {
  const events = new FakeEvents();
  const requests: Array<{ init: RequestInit; reply: ReturnType<typeof deferred<{ ok: boolean; json(): Promise<unknown> }>> }> = [];
  const enables: Array<ReturnType<typeof deferred<CaptureHandle>>> = [];
  let globalStops = 0;
  let handleStops = 0;
  let pagehide: (() => void) | null = null;
  const page: PageLifecycle = {
    addEventListener: (_name, listener) => { pagehide = listener; },
    removeEventListener: () => { pagehide = null; },
  };
  const controller = createMicClient({
    clientId: SELF,
    openEvents: (url) => { assert.equal(url, "/api/livekit/events"); return events; },
    fetch: async (url, init) => {
      assert.equal(url, "/api/livekit/mic");
      const reply = deferred<{ ok: boolean; json(): Promise<unknown> }>();
      requests.push({ init, reply });
      return reply.promise;
    },
    capture: {
      enable: () => { const attempt = deferred<CaptureHandle>(); enables.push(attempt); return attempt.promise; },
      stop: () => { globalStops += 1; },
    },
    page,
  });
  const respond = (index: number, value: unknown, ok = true) => requests[index].reply.resolve({
    ok, json: async () => value,
  });
  const resolveCapture = (index: number) => enables[index].resolve({ stop: () => { handleStops += 1; } });
  return {
    controller, events, requests, enables, respond, resolveCapture,
    counts: () => ({ globalStops, handleStops }),
    pagehide: () => pagehide?.(),
  };
}
test("claim uses the supplied tab UUID and waits for both ownership and stream readiness", async () => {
  const h = harness();
  const opening = h.controller.tap();
  assert.deepEqual(JSON.parse(String(h.requests[0].init.body)), { action: "claim", client_id: SELF });
  assert.deepEqual(h.requests[0].init.headers, { "content-type": "application/json" });
  h.respond(0, { mic: mic("9007199254740993") });
  await opening;
  assert.equal(h.enables.length, 0);
  h.events.emit("ready");
  assert.equal(h.enables.length, 1);
  h.resolveCapture(0);
  await Promise.resolve();
  h.events.emit("ready");
  assert.equal(h.enables.length, 1);
  assert.deepEqual(h.controller.getState(), {
    phase: "open", ready: true, owner: SELF, revision: "9007199254740993", error: null,
  });
});
test("a stale earlier claim cannot release or overwrite a newer reopened intent", async () => {
  const h = harness();
  h.events.emit("ready");
  const firstOpen = h.controller.tap();
  const firstClose = h.controller.tap();
  const secondOpen = h.controller.tap();
  h.respond(2, { mic: mic("3") });
  await secondOpen;
  h.respond(0, { mic: mic("1") });
  await firstOpen;
  assert.equal(h.requests.length, 3);
  h.respond(1, { error: "late close failure" }, false);
  await firstClose;
  assert.equal(h.controller.getState().phase, "opening");
  assert.equal(h.controller.getState().error, null);
});
test("newer takeover cancels a pending open and a stale claim response cannot reopen it", async () => {
  const h = harness();
  h.events.emit("ready");
  const opening = h.controller.tap();
  h.events.emit("ownership", mic("10", OTHER));
  assert.equal(h.controller.getState().error, "ownership_lost");
  h.respond(0, { mic: mic("9") });
  await opening;
  await Promise.resolve();
  assert.equal(h.enables.length, 0);
  assert.deepEqual(JSON.parse(String(h.requests[1].init.body)), { action: "release", client_id: SELF });
  assert.equal(h.controller.getState().owner, OTHER);
});

test("explicit close stops immediately; release failure stays closed; late enable stops its own handle", async () => {
  const h = harness();
  h.events.emit("ready");
  const opening = h.controller.tap();
  h.respond(0, { mic: mic("1") });
  await opening;
  assert.equal(h.enables.length, 1);
  const closing = h.controller.tap();
  assert.equal(h.counts().globalStops, 1);
  h.respond(1, { error: "unavailable" }, false);
  assert.equal((await closing).error, "release_failed");
  h.resolveCapture(0);
  await Promise.resolve();
  assert.deepEqual(h.counts(), { globalStops: 1, handleStops: 1 });
  assert.notEqual(h.controller.getState().phase, "open");
});

test("claim HTTP failure remains closed and attempts ownership cleanup", async () => {
  const h = harness();
  h.events.emit("ready");
  const opening = h.controller.tap();
  h.respond(0, { error: "unavailable" }, false);
  assert.equal((await opening).error, "claim_failed");
  assert.equal(h.enables.length, 0);
  assert.deepEqual(JSON.parse(String(h.requests[1].init.body)), { action: "release", client_id: SELF });
});

test("stream loss stops capture and reconnect cannot reopen without a fresh tap", async () => {
  const h = harness();
  h.events.emit("ready");
  const opening = h.controller.tap();
  h.respond(0, { mic: mic("1") });
  await opening;
  h.resolveCapture(0);
  await Promise.resolve();
  h.events.emit("error");
  assert.equal(h.controller.getState().error, "stream_lost");
  assert.deepEqual(h.counts(), { globalStops: 1, handleStops: 1 });
  h.events.emit("ownership", mic("2"));
  h.events.emit("ready");
  assert.equal(h.controller.getState().phase, "closed");
  assert.equal(h.enables.length, 1);
  void h.controller.tap();
  assert.deepEqual(JSON.parse(String(h.requests[1].init.body)), { action: "claim", client_id: SELF });
});

test("malformed ownership fails closed and pagehide disposes a pending capture with keepalive release", async () => {
  const h = harness();
  h.events.emit("ready");
  const opening = h.controller.tap();
  h.respond(0, { mic: mic("1") });
  await opening;
  h.events.emit("ownership", { ...mic("1"), private_message: "secret" });
  assert.equal(h.controller.getState().error, "stream_lost");
  h.pagehide();
  h.resolveCapture(0);
  await Promise.resolve();
  assert.equal(h.counts().handleStops, 1);
  assert.equal(h.events.closed, 1);
  assert.equal(h.requests.at(-1)?.init.keepalive, true);
  assert.deepEqual(JSON.parse(String(h.requests.at(-1)?.init.body)), { action: "release", client_id: SELF });
  assert.deepEqual(h.controller.getState(), {
    phase: "closed", ready: false, owner: SELF, revision: "1", error: null,
  });
  const requestCount = h.requests.length;
  await h.controller.tap();
  h.events.emit("ready");
  assert.equal(h.requests.length, requestCount);
  assert.equal(h.controller.getState().ready, false);
});

test("invalid caller identity is rejected before opening browser resources", () => {
  assert.throws(() => createMicClient({
    clientId: "shared-local-storage-value",
    capture: { enable: async () => ({ stop() {} }), stop() {} },
    openEvents: () => { throw new Error("must not open"); },
  }), /UUID/);
});
