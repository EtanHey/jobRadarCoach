import assert from "node:assert/strict";
import { test } from "node:test";

import { makeGetMic, makePostMic } from "../app/api/livekit/mic/route";
import { createMicStore, type MicState, type MicStore } from "../lib/voice/mic-server";

const CLIENT_A = "a15ce2ae-6ef8-4ce2-b1e4-9255bc08e61f";
const CLIENT_B = "b71c785c-8123-4ed3-9f8f-8d65750d6ee4";
const TIME = "2026-09-08T18:00:00.000Z";
const state = (revision = "1", client_id: string | null = CLIENT_A): MicState => ({
  client_id, revision, updated_at: TIME,
});
const row = (revision = "1", client_id: string | null = CLIENT_A) => ({
  singleton: true, ...state(revision, client_id),
});

function store(overrides: Partial<MicStore> = {}): MicStore {
  return {
    getCurrent: () => Promise.resolve(state()),
    claim: (clientId) => Promise.resolve(state("2", clientId)),
    release: () => Promise.resolve(state("2", null)),
    ...overrides,
  };
}

function post(body: unknown, headers: HeadersInit = {}): Request {
  return new Request("http://localhost/api/livekit/mic", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

test("mic mutations reject foreign origins and invalid exact bodies before calling the store", async () => {
  let calls = 0;
  const handler = makePostMic(store({ claim: async () => { calls += 1; return state(); } }));
  assert.equal((await handler(post({ action: "claim", client_id: CLIENT_A }, {
    origin: "https://foreign.example",
  }))).status, 403);
  for (const body of [
    { action: "steal", client_id: CLIENT_A },
    { action: "claim", client_id: "not-a-uuid" },
    { action: "claim", client_id: CLIENT_A, extra: true },
  ]) assert.equal((await handler(post(body))).status, 400);
  assert.equal(calls, 0);
});

test("stale release is delegated to the CAS RPC and returns its unchanged owner", async () => {
  const calls: unknown[] = [];
  const adapter = createMicStore(async (name, args) => {
    calls.push({ name, args });
    return { data: [row("8", CLIENT_B)], error: null };
  });
  const response = await makePostMic(adapter)(post({ action: "release", client_id: CLIENT_A }));
  assert.equal(response.status, 200);
  assert.deepEqual(calls, [{ name: "release_active_mic", args: { client_id: CLIENT_A } }]);
  assert.deepEqual(await response.json(), { mic: state("8", CLIENT_B) });
});

test("GET is noncache and malformed, imprecise, or out-of-range RPC rows fail closed", async () => {
  const response = await makeGetMic(store())();
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(await response.json(), { mic: state() });

  for (const data of [
    [],
    [{ ...row(), private_message: "must not pass" }],
    [row(9_007_199_254_740_992 as unknown as string)],
    [row("9223372036854775808")],
  ]) {
    const invalid = createMicStore(async () => ({ data, error: null }));
    await assert.rejects(invalid.getCurrent(), (error: unknown) => (
      error instanceof Error && error.message === "Database returned an invalid response."
    ));
  }
});
