import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createGuardedCaptureAdapter, type VoiceCaptureSession, type VoiceCaptureTrack,
} from "../components/voice/capture-adapter";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function harness() {
  const created = deferred<VoiceCaptureTrack>();
  const published = deferred<unknown>();
  let stops = 0;
  let publishes = 0;
  let unpublishes = 0;
  const track = { mediaStreamTrack: { stop: () => { stops += 1; } } };
  const session: VoiceCaptureSession = {
    createTrack: () => created.promise,
    publish: () => { publishes += 1; return published.promise; },
    unpublish: async () => { unpublishes += 1; },
  };
  let current: VoiceCaptureSession | null = session;
  const adapter = createGuardedCaptureAdapter(() => current);
  return {
    adapter, track, created, published,
    replaceSession: () => { current = null; },
    counts: () => ({ stops, publishes, unpublishes }),
  };
}

test("a capture that resolves after stop cannot publish", async () => {
  const h = harness();
  const enabling = h.adapter.enable();
  h.adapter.stop();
  h.created.resolve(h.track);
  await assert.rejects(enabling, /session changed/);
  assert.deepEqual(h.counts(), { stops: 1, publishes: 0, unpublishes: 1 });
});

test("a session change during publication stops and unpublishes immediately", async () => {
  const h = harness();
  const enabling = h.adapter.enable();
  h.created.resolve(h.track);
  await Promise.resolve();
  assert.equal(h.counts().publishes, 1);
  h.replaceSession();
  h.adapter.stop();
  assert.equal(h.counts().stops, 1);
  h.published.resolve(undefined);
  await assert.rejects(enabling, /session changed/);
  assert.equal(h.counts().unpublishes, 2);
});

test("the returned handle is idempotent and stops the media track before cleanup", async () => {
  const h = harness();
  const enabling = h.adapter.enable();
  h.created.resolve(h.track);
  h.published.resolve(undefined);
  const handle = await enabling;
  handle.stop();
  handle.stop();
  assert.deepEqual(h.counts(), { stops: 1, publishes: 1, unpublishes: 1 });
});
