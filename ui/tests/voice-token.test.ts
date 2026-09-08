import { test } from "node:test";
import assert from "node:assert/strict";
import { TokenVerifier } from "livekit-server-sdk";

import { makePost } from "../app/api/livekit/token/route";
import { mintVoiceToken, VOICE_TOKEN_TTL_SECONDS } from "../lib/voice/token-server";

const API_KEY = "synthetic-api-key";
const API_SECRET = "synthetic-secret-used-only-by-voice-token-tests";
const CLIENT_ID = "c50222b1-f6d3-4d31-924a-81fdfc3f93da";
const SESSION_ID = "43aa8d96-b981-4059-baf0-f0651bf1f18f";
const environment = {
  LIVEKIT_API_KEY: API_KEY,
  LIVEKIT_API_SECRET: API_SECRET,
  LIVEKIT_PUBLIC_URL: "wss://voice.example.test",
};

function request(body: string, headers: Record<string, string> = {}) {
  return new Request("https://radar.example.test/api/livekit/token", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body,
  });
}

test("mints a short-lived signed token with only room, microphone, subscription, and data grants", async () => {
  const result = await mintVoiceToken(CLIENT_ID, environment, () => SESSION_ID);
  const claims = await new TokenVerifier(API_KEY, API_SECRET).verify(result.token);

  assert.deepEqual({ ...result, token: "<signed>" }, {
    server_url: "wss://voice.example.test",
    token: "<signed>",
    room_name: `job-radar-voice-${CLIENT_ID}-${SESSION_ID}`,
    participant_identity: `web:${CLIENT_ID}:${SESSION_ID}`,
    dispatch_mode: "automatic",
  });
  assert.equal(claims.iss, API_KEY);
  assert.equal(claims.sub, result.participant_identity);
  assert.deepEqual(claims.video, {
    roomJoin: true,
    room: result.room_name,
    canPublish: true,
    canPublishSources: ["microphone"],
    canSubscribe: true,
    canPublishData: true,
    canUpdateOwnMetadata: false,
  });
  assert.equal(claims.exp! - claims.nbf!, VOICE_TOKEN_TTL_SECONDS);
  assert.equal(claims.roomConfig, undefined);
  assert.equal(claims.sip, undefined);
  assert.equal(claims.inference, undefined);
  assert.equal(claims.observability, undefined);
});

test("creates a fresh server session UUID for each token without accepting room or identity overrides", async () => {
  const post = makePost(environment);
  const first = await post(request(JSON.stringify({ client_id: CLIENT_ID })));
  const second = await post(request(JSON.stringify({ client_id: CLIENT_ID })));
  const firstBody = await first.json();
  const secondBody = await second.json();

  assert.equal(first.status, 200);
  assert.equal(second.status, 200);
  assert.notEqual(firstBody.room_name, secondBody.room_name);
  assert.match(firstBody.room_name, new RegExp(`^job-radar-voice-${CLIENT_ID}-[0-9a-f-]{36}$`));
  assert.match(firstBody.participant_identity, new RegExp(`^web:${CLIENT_ID}:[0-9a-f-]{36}$`));

  const override = await post(request(JSON.stringify({
    client_id: CLIENT_ID, room_name: "admin-room", grants: { roomAdmin: true }, agent_name: "riki",
  })));
  assert.equal(override.status, 400);
  assert.deepEqual(await override.json(), { error: "Invalid request." });
});

test("rejects foreign origins, invalid UUIDs, and oversized bodies before minting", async () => {
  const post = makePost(environment);
  const foreign = await post(request(JSON.stringify({ client_id: CLIENT_ID }), {
    origin: "https://foreign.example",
  }));
  assert.equal(foreign.status, 403);
  assert.deepEqual(await foreign.json(), { error: "Foreign origin rejected." });

  const invalid = await post(request(JSON.stringify({ client_id: "not-a-uuid" })));
  assert.equal(invalid.status, 400);
  assert.deepEqual(await invalid.json(), { error: "Invalid request." });

  const oversized = await post(request(`{"client_id":"${CLIENT_ID}","padding":"${"x".repeat(16_384)}"}`));
  assert.equal(oversized.status, 413);
  assert.deepEqual(await oversized.json(), { error: "Request body is too large." });
});

test("fails closed for missing or unsafe environment without exposing credential values", async () => {
  const secret = "must-never-appear-in-an-error";
  for (const unsafeEnvironment of [
    {},
    { ...environment, LIVEKIT_API_SECRET: secret, LIVEKIT_PUBLIC_URL: "https://voice.example.test" },
    { ...environment, LIVEKIT_API_SECRET: secret, LIVEKIT_PUBLIC_URL: "wss://user:password@voice.example.test" },
    { ...environment, LIVEKIT_API_SECRET: secret, LIVEKIT_PUBLIC_URL: "not a url" },
  ]) {
    const response = await makePost(unsafeEnvironment)(request(JSON.stringify({ client_id: CLIENT_ID })));
    const text = await response.text();
    assert.equal(response.status, 503);
    assert.equal(text.includes(secret), false);
    assert.equal(text.includes("password"), false);
    assert.deepEqual(JSON.parse(text), { error: "Voice service configuration is unavailable." });
  }
});
