import assert from "node:assert/strict";
import { test } from "node:test";

import { settleForCurrentSession } from "../components/voice/use-voice-session";

function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

test("late startAudio completion cannot update a replacement session", async () => {
  for (const outcome of ["resolve", "reject"] as const) {
    const operation = deferred();
    let current = true;
    let enabled = 0;
    let blocked = 0;
    settleForCurrentSession(
      operation.promise,
      () => current,
      () => { enabled += 1; },
      () => { blocked += 1; },
    );

    current = false;
    if (outcome === "resolve") operation.resolve();
    else operation.reject(new Error("old room audio failed"));
    await operation.promise.catch(() => undefined);
    await Promise.resolve();

    assert.equal(enabled, 0);
    assert.equal(blocked, 0);
  }
});

test("current startAudio completion updates only its matching outcome", async () => {
  const success = deferred();
  const failure = deferred();
  let enabled = 0;
  let blocked = 0;
  settleForCurrentSession(success.promise, () => true,
    () => { enabled += 1; }, () => { blocked += 1; });
  settleForCurrentSession(failure.promise, () => true,
    () => { enabled += 1; }, () => { blocked += 1; });

  success.resolve();
  failure.reject(new Error("current room audio failed"));
  await Promise.all([success.promise, failure.promise.catch(() => undefined)]);
  await Promise.resolve();

  assert.equal(enabled, 1);
  assert.equal(blocked, 1);
});
