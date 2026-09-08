import assert from "node:assert/strict";
import { test } from "node:test";

import { handleMicStateForSession } from "../components/voice/use-voice-session";
import type { MicClientState } from "../lib/voice/mic-client";

const micState = (error: MicClientState["error"]): MicClientState => ({
  phase: error === null ? "closed" : "error",
  ready: error === null,
  owner: null,
  revision: "1",
  error,
});

test("QA boundary failures queue teardown and ignore the dispose callback", async () => {
  for (const error of ["claim_failed", "release_failed", "stream_lost"] as const) {
    let current = true;
    let closes = 0;
    let revocations = 0;
    const published: MicClientState[] = [];
    const effects = {
      qaMode: true,
      isCurrent: () => current,
      publish: (state: MicClientState) => published.push(state),
      closeSession: () => {
        closes += 1;
        current = false;
        handleMicStateForSession(micState(null), effects);
      },
      revokeQa: () => { revocations += 1; },
    };

    handleMicStateForSession(micState(error), effects);
    assert.deepEqual(published.map((state) => state.error), [error]);
    assert.equal(closes, 0);
    assert.equal(revocations, 0);

    await Promise.resolve();
    assert.equal(closes, 1);
    assert.equal(revocations, 1);
    assert.deepEqual(published.map((state) => state.error), [error]);
  }
});

test("takeover, capture failure, production errors, and stale queued work do not revoke QA", async () => {
  for (const [qaMode, error] of [
    [true, "ownership_lost"],
    [true, "capture_failed"],
    [false, "stream_lost"],
  ] as const) {
    let closes = 0;
    let revocations = 0;
    handleMicStateForSession(micState(error), {
      qaMode,
      isCurrent: () => true,
      publish: () => undefined,
      closeSession: () => { closes += 1; },
      revokeQa: () => { revocations += 1; },
    });
    await Promise.resolve();
    assert.equal(closes, 0);
    assert.equal(revocations, 0);
  }

  let current = true;
  let closes = 0;
  let revocations = 0;
  handleMicStateForSession(micState("stream_lost"), {
    qaMode: true,
    isCurrent: () => current,
    publish: () => undefined,
    closeSession: () => { closes += 1; },
    revokeQa: () => { revocations += 1; },
  });
  current = false;
  await Promise.resolve();
  assert.equal(closes, 0);
  assert.equal(revocations, 0);
});
