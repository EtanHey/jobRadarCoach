import assert from "node:assert/strict";
import { test } from "node:test";
import { createClient } from "@supabase/supabase-js";
import {
  closeOwnedRealtimeClient, makeGetMicEvents, type MicEventDependencies,
} from "../app/api/livekit/events/route";
import type { MicState } from "../lib/voice/mic-server";

const CLIENT_A = "a15ce2ae-6ef8-4ce2-b1e4-9255bc08e61f";
const CLIENT_B = "b71c785c-8123-4ed3-9f8f-8d65750d6ee4";
const state = (revision = "1", client_id: string | null = CLIENT_A): MicState => ({
  client_id, revision, updated_at: "2026-09-08T18:00:00.000Z",
});
const row = (revision = "1", client_id: string | null = CLIENT_A) => ({
  singleton: true, ...state(revision, client_id),
});

interface StreamHarness {
  dependencies: MicEventDependencies;
  emitRow(row: unknown): void;
  emitStatus(status: string): void;
  cleanup: { subscriptions: number; heartbeats: number };
}

function streamHarness(snapshot: () => Promise<MicState>): StreamHarness {
  let onRow: (row: unknown) => void = () => { throw new Error("not subscribed"); };
  let onStatus: (status: string) => void = () => { throw new Error("not subscribed"); };
  const cleanup = { subscriptions: 0, heartbeats: 0 };
  return {
    cleanup,
    dependencies: {
      snapshot,
      subscribe(rowCallback, statusCallback) {
        onRow = rowCallback;
        onStatus = statusCallback;
        return { close: () => { cleanup.subscriptions += 1; } };
      },
      scheduleHeartbeat: () => Symbol("heartbeat"),
      clearHeartbeat: () => { cleanup.heartbeats += 1; },
    },
    emitRow: (value) => onRow(value),
    emitStatus: (status) => onStatus(status),
  };
}

async function readThrough(reader: ReadableStreamDefaultReader<Uint8Array>, marker: string): Promise<string> {
  const decoder = new TextDecoder();
  let text = "";
  while (!text.includes(marker)) {
    const next = await reader.read();
    if (next.done) break;
    text += decoder.decode(next.value, { stream: true });
  }
  return text;
}

test("stream subscribes before snapshot, preserves bigint precision, and ignores stale snapshot ordering", async () => {
  let resolveSnapshot!: (value: MicState) => void;
  let snapshotStarted = false;
  const snapshot = new Promise<MicState>((resolve) => { resolveSnapshot = resolve; });
  const harness = streamHarness(() => { snapshotStarted = true; return snapshot; });
  const aborter = new AbortController();
  const response = makeGetMicEvents(harness.dependencies)(new Request(
    "http://localhost/api/livekit/events", { signal: aborter.signal },
  ));
  const reader = response.body!.getReader();
  assert.match(response.headers.get("cache-control") ?? "", /no-store/);

  harness.emitStatus("SUBSCRIBED");
  await Promise.resolve();
  assert.equal(snapshotStarted, true);
  harness.emitRow(row("9007199254740993", CLIENT_B));
  resolveSnapshot(state("9007199254740992", CLIENT_A));
  const text = await readThrough(reader, "event: ready");
  assert.match(text, /"revision":"9007199254740993"/);
  assert.match(text, new RegExp(CLIENT_B));
  assert.doesNotMatch(text, new RegExp(CLIENT_A));
  assert.equal((text.match(/event: ownership/g) ?? []).length, 1);
  assert.match(text, /event: ready\ndata: \{\}/);

  aborter.abort();
  assert.equal((await reader.read()).done, true);
  await Promise.resolve();
  assert.deepEqual(harness.cleanup, { subscriptions: 1, heartbeats: 1 });
});

test("stream cancellation and channel failure each clean subscription and heartbeat", async () => {
  const cancelled = streamHarness(async () => state());
  const cancelledResponse = makeGetMicEvents(cancelled.dependencies)(
    new Request("http://localhost/api/livekit/events"),
  );
  await cancelledResponse.body!.cancel();
  await Promise.resolve();
  assert.deepEqual(cancelled.cleanup, { subscriptions: 1, heartbeats: 1 });

  const failed = streamHarness(async () => state());
  const failedResponse = makeGetMicEvents(failed.dependencies)(
    new Request("http://localhost/api/livekit/events"),
  );
  failed.emitStatus("CHANNEL_ERROR");
  const text = await failedResponse.text();
  assert.equal(text, "event: error\ndata: {\"code\":\"stream_lost\"}\n\n");
  assert.doesNotMatch(text, /database|active_mic|private/i);
  await Promise.resolve();
  assert.deepEqual(failed.cleanup, { subscriptions: 1, heartbeats: 1 });
});

test("owned Realtime cleanup tears down and disconnects when channel leave returns error", async () => {
  const db = createClient("http://127.0.0.1:54321", "synthetic-service-key", {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const channel = db.channel("synthetic-failed-leave");
  let teardownCalls = 0;
  let disconnectCalls = 0;
  const teardown = channel.teardown.bind(channel);

  channel.unsubscribe = async () => "error";
  channel.teardown = () => { teardownCalls += 1; teardown(); };
  db.realtime.disconnect = async () => { disconnectCalls += 1; return "ok"; };

  await closeOwnedRealtimeClient(db);

  assert.equal(teardownCalls, 1);
  assert.equal(disconnectCalls, 1);
});
