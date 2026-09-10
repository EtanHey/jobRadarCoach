import assert from "node:assert/strict";
import { test } from "node:test";

import {
  authenticateWithPasskey,
  startPasskeyAttempt,
  type PasskeyCeremony,
  type SerializedPasskeyCredential,
} from "../lib/auth/passkey-attempt";

type TimerHandle = ReturnType<typeof globalThis.setTimeout>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function fakeTimer() {
  let callback: (() => void) | undefined;
  let cleared = false;
  const handle = 1 as unknown as TimerHandle;
  return {
    setTimer(next: () => void) {
      callback = next;
      return handle;
    },
    clearTimer(received: TimerHandle) {
      assert.equal(received, handle);
      cleared = true;
    },
    fire() {
      assert.ok(callback);
      callback();
    },
    get cleared() { return cleared; },
  };
}

test("manual cancellation settles and aborts when the credential provider never returns", async () => {
  const provider = deferred<{ error: unknown }>();
  const timer = fakeTimer();
  let signal: AbortSignal | undefined;
  const attempt = startPasskeyAttempt(
    (received) => {
      signal = received;
      return provider.promise;
    },
    { setTimer: timer.setTimer, clearTimer: timer.clearTimer },
  );

  await Promise.resolve();
  attempt.cancel();

  assert.deepEqual(await attempt.result, { kind: "cancelled" });
  assert.equal(signal?.aborted, true);
  assert.equal(timer.cleared, true);

  provider.resolve({ error: null });
  assert.deepEqual(await attempt.result, { kind: "cancelled" });
});

test("the deadline settles, aborts, and ignores a late provider completion", async () => {
  const provider = deferred<{ error: unknown }>();
  const timer = fakeTimer();
  let signal: AbortSignal | undefined;
  const attempt = startPasskeyAttempt(
    (received) => {
      signal = received;
      return provider.promise;
    },
    { setTimer: timer.setTimer, clearTimer: timer.clearTimer },
  );

  await Promise.resolve();
  timer.fire();

  assert.deepEqual(await attempt.result, { kind: "timed_out" });
  assert.equal(signal?.aborted, true);
  provider.resolve({ error: null });
  assert.deepEqual(await attempt.result, { kind: "timed_out" });
});

test("SDK success and error both settle and clear the deadline", async () => {
  const successTimer = fakeTimer();
  const success = startPasskeyAttempt(
    async () => ({ error: null }),
    { setTimer: successTimer.setTimer, clearTimer: successTimer.clearTimer },
  );
  assert.deepEqual(await success.result, { kind: "success" });
  assert.equal(successTimer.cleared, true);

  const failureTimer = fakeTimer();
  const error = new Error("credential rejected");
  const failure = startPasskeyAttempt(
    async () => ({ error }),
    { setTimer: failureTimer.setTimer, clearTimer: failureTimer.clearTimer },
  );
  assert.deepEqual(await failure.result, { kind: "error", error });
  assert.equal(failureTimer.cleared, true);
});

const requestOptions = {
  challenge: "Y2hhbGxlbmdl",
};
const serializedCredential: SerializedPasskeyCredential = {
  id: "credential",
  rawId: "credential",
  response: {
    authenticatorData: "authenticator-data",
    clientDataJSON: "client-data",
    signature: "signature",
  },
  clientExtensionResults: {},
  type: "public-key",
};

test("cancelling a stuck browser ceremony prevents late verification and session creation", async () => {
  const provider = deferred<SerializedPasskeyCredential>();
  const timer = fakeTimer();
  let verifyCalls = 0;
  const client = {
    async startAuthentication() {
      return {
        data: { challenge_id: "challenge-id", options: requestOptions, expires_at: 1 },
        error: null,
      };
    },
    async verifyAuthentication() {
      verifyCalls += 1;
      return { error: null };
    },
  };
  const ceremony: PasskeyCeremony = { get: () => provider.promise };
  const attempt = startPasskeyAttempt(
    (signal, commit) => authenticateWithPasskey(client, ceremony, signal, commit),
    { setTimer: timer.setTimer, clearTimer: timer.clearTimer },
  );

  await Promise.resolve();
  await Promise.resolve();
  assert.equal(attempt.cancel(), true);
  assert.deepEqual(await attempt.result, { kind: "cancelled" });

  provider.resolve(serializedCredential);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(verifyCalls, 0);
});

test("verification is the non-cancellable commit point", async () => {
  const verification = deferred<{ error: unknown }>();
  const timer = fakeTimer();
  let committed = false;
  let verifyCalls = 0;
  const client = {
    async startAuthentication() {
      return {
        data: { challenge_id: "challenge-id", options: requestOptions, expires_at: 1 },
        error: null,
      };
    },
    verifyAuthentication(input: { challengeId: string; credential: SerializedPasskeyCredential }) {
      assert.deepEqual(input, {
        challengeId: "challenge-id",
        credential: serializedCredential,
      });
      verifyCalls += 1;
      return verification.promise;
    },
  };
  const ceremony: PasskeyCeremony = { get: async () => serializedCredential };
  const attempt = startPasskeyAttempt(
    (signal, commit) => authenticateWithPasskey(client, ceremony, signal, commit),
    {
      onCommit: () => { committed = true; },
      setTimer: timer.setTimer,
      clearTimer: timer.clearTimer,
    },
  );

  for (let index = 0; index < 5 && verifyCalls === 0; index += 1) await Promise.resolve();
  assert.equal(committed, true);
  assert.equal(verifyCalls, 1);
  assert.equal(attempt.cancel(), false);

  verification.resolve({ error: null });
  assert.deepEqual(await attempt.result, { kind: "success" });
});

test("a verification deadline requires navigation instead of allowing a stale retry", async () => {
  const verification = deferred<{ error: unknown }>();
  const timer = fakeTimer();
  let verifyCalls = 0;
  const client = {
    async startAuthentication() {
      return {
        data: { challenge_id: "challenge-id", options: requestOptions, expires_at: 1 },
        error: null,
      };
    },
    verifyAuthentication() {
      verifyCalls += 1;
      return verification.promise;
    },
  };
  const attempt = startPasskeyAttempt(
    (signal, commit) => authenticateWithPasskey(
      client,
      { get: async () => serializedCredential },
      signal,
      commit,
    ),
    { setTimer: timer.setTimer, clearTimer: timer.clearTimer },
  );

  for (let index = 0; index < 5 && verifyCalls === 0; index += 1) await Promise.resolve();
  assert.equal(verifyCalls, 1);
  assert.equal(attempt.cancel(), false);
  timer.fire();
  assert.deepEqual(await attempt.result, { kind: "verification_timed_out" });

  verification.resolve({ error: null });
  assert.deepEqual(await attempt.result, { kind: "verification_timed_out" });
});
