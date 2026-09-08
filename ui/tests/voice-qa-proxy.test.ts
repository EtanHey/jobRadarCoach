import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { createServer, request } from "node:http";
import { test } from "node:test";
import { TokenVerifier } from "livekit-server-sdk";
import { startQaProxy } from "../lib/voice/qa-proxy.mjs";
const key = "test-key", secret = "test-signing-secret-only";
async function harness(extra: Partial<Parameters<typeof startQaProxy>[0]> = {}) {
  const requests: string[] = [];
  const upstream = createServer((req, res) => { requests.push(req.method!); res.end("borrowed asset"); });
  await new Promise<void>(resolve => upstream.listen(0, "127.0.0.1", resolve));
  let ready = false;
  const session = randomUUID(), client = randomUUID(), address = upstream.address();
  if (!address || typeof address === "string") throw new Error("Missing test address");
  const proxy = await startQaProxy({ upstream: `http://127.0.0.1:${address.port}`, key, secret,
    serverUrl: "wss://signal.example.test", qaSessionId: session, verifyAgent: async () => ready, ...extra });
  const post = (path: string, body: unknown, sessionId: string = session) => fetch(proxy.origin + path, {
    method: "POST", headers: { "Content-Type": "application/json", Origin: proxy.origin, "X-Voice-QA-Session": sessionId },
    body: JSON.stringify(body),
  });
  return { proxy, post, session, client, requests, ready: () => { ready = true; },
    close: async () => { await proxy.close(); upstream.closeAllConnections(); await new Promise<void>(resolve => upstream.close(() => resolve())); } };
}
test("unknown, wrong-session and revoked gates cannot mint or forward", async () => {
  const h = await harness();
  try {
    assert.equal((await fetch(h.proxy.origin + "/api/livekit/qa")).status, 503);
    assert.equal((await h.post("/api/livekit/token", { client_id: h.client })).status, 503);
    assert.equal((await h.post("/api/livekit/mic", { client_id: h.client, action: "claim" })).status, 503);
    h.ready();
    assert.equal((await h.post("/api/livekit/token", { client_id: h.client }, "wrong-session")).status, 503);
    assert.equal(h.proxy.receipt().rooms.length, 0);
    h.proxy.invalidateQa();
    assert.equal((await h.post("/api/livekit/token", { client_id: h.client })).status, 503);
    assert.deepEqual(h.requests, []);
  } finally { await h.close(); }
});
test("signed QA metadata binds fresh automatic rooms to the verified run", async () => {
  const h = await harness();
  try {
    h.ready();
    assert.deepEqual(await (await fetch(h.proxy.origin + "/api/livekit/qa")).json(), {
      version: 1, qa_mode: true, session_id: h.session, browser_mutations_blocked: true,
      mic_isolated: true, agent_qa_verified: true, dispatch_mode: "automatic" });
    const one = await (await h.post("/api/livekit/token", { client_id: h.client })).json();
    const two = await (await h.post("/api/livekit/token", { client_id: h.client })).json();
    assert.notEqual(one.room_name, two.room_name); assert.ok(one.room_name.startsWith("qa-"));
    const claims = await new TokenVerifier(key, secret).verify(one.token);
    assert.deepEqual(JSON.parse(claims.metadata!).qa, { version: 1, session_id: h.session, read_only: true });
    assert.deepEqual(one.qa, JSON.parse(claims.metadata!).qa); assert.equal(claims.sub, one.participant_identity);
    assert.deepEqual(claims.video, { room: one.room_name, roomJoin: true, canPublish: true, canSubscribe: true,
      canPublishData: true, canPublishSources: ["microphone"], canUpdateOwnMetadata: false });
    assert.equal(claims.roomConfig, undefined); assert.equal(one.dispatch_mode, "automatic");
    assert.ok(claims.exp! - claims.nbf! <= 300); assert.deepEqual(h.requests, []);
  } finally { await h.close(); }
});
test("isolated takeover and stale release cannot mutate the borrowed UI", async () => {
  const h = await harness();
  try {
    h.ready(); const other = randomUUID();
    const events = await fetch(h.proxy.origin + "/api/livekit/events", { signal: AbortSignal.timeout(5000) });
    const reader = events.body!.getReader();
    await reader.read();
    const first = await (await h.post("/api/livekit/mic", { client_id: h.client, action: "claim" })).json();
    assert.equal(first.mic.revision, "1");
    assert.match(new TextDecoder().decode((await reader.read()).value), new RegExp(h.client));
    await h.post("/api/livekit/mic", { client_id: other, action: "claim" });
    assert.match(new TextDecoder().decode((await reader.read()).value), new RegExp(other));
    await reader.cancel();
    const stale = await (await h.post("/api/livekit/mic", { client_id: h.client, action: "release" })).json();
    assert.equal(stale.mic.client_id, other); assert.equal(stale.mic.revision, "2");
    assert.deepEqual(h.requests, []); assert.equal(h.proxy.receipt().ownerMicCalls, 0);
  } finally { await h.close(); }
});
test("owner mutation attempts fail QA and close an existing ownership stream", async () => {
  const h = await harness();
  try {
    h.ready(); assert.equal(await (await fetch(h.proxy.origin + "/mic")).text(), "borrowed asset");
    const events = await fetch(h.proxy.origin + "/api/livekit/events");
    const reader = events.body!.getReader();
    assert.match(new TextDecoder().decode((await reader.read()).value), /event: ready/);
    assert.equal((await h.post("/api/jobs/fixture/status", {})).status, 403);
    assert.equal((await reader.read()).done, true);
    assert.equal((await fetch(h.proxy.origin + "/api/livekit/qa")).status, 503);
    assert.deepEqual(h.requests, ["GET"]); assert.equal(h.proxy.receipt().mutationAttempts, 1);
  } finally { await h.close(); }
});

test("readiness changing during a mic request leaves isolated state unchanged", async () => {
  let checks = 0;
  const h = await harness({ verifyAgent: async () => ++checks === 1 });
  try {
    assert.equal((await h.post("/api/livekit/mic", { client_id: h.client, action: "claim" })).status, 503);
    assert.equal(h.proxy.receipt().isolatedMicCalls, 0);
    const state = await (await fetch(h.proxy.origin + "/api/livekit/mic")).json();
    assert.equal(state.mic.revision, "0"); assert.equal(state.mic.client_id, null);
  } finally { await h.close(); }
});
test("origins are validated and the runner receives a copy of room receipts", async () => {
  for (const publicOrigin of ["http://phone.example.test", "https://qa.example.test/path", "https://u:p@qa.example.test"]) {
    await assert.rejects(startQaProxy({ upstream: "http://127.0.0.1:1", key, secret,
      serverUrl: "wss://signal.example.test", qaSessionId: randomUUID(), publicOrigin }), /origin/);
  }
  const h = await harness({ upstreamOrigin: "https://borrowed.example.test/" });
  try {
    h.ready(); await h.post("/api/livekit/token", { client_id: h.client });
    assert.equal(h.proxy.rooms.length, 1);
    h.proxy.rooms.length = 0;
    assert.equal(h.proxy.receipt().rooms.length, 1);
  } finally { await h.close(); }
});

test("borrowed GET strips connection-scoped headers and streams the response body", async () => {
  let upstreamHeaders: import("node:http").IncomingHttpHeaders = {};
  let finishBody!: () => void;
  const bodyGate = new Promise<void>(resolve => { finishBody = resolve; });
  const upstream = createServer(async (req, res) => {
    upstreamHeaders = req.headers;
    res.writeHead(200, {
      "Content-Type": "application/octet-stream",
      "X-End-To-End-Response": "preserved",
      Connection: "keep-alive, x-response-hop",
      "Keep-Alive": "timeout=99",
      "Proxy-Authenticate": "fixture-secret",
      Trailer: "X-Response-Trailer",
      "X-Response-Hop": "remove-me",
    });
    res.write("stream-");
    await bodyGate;
    res.end("body");
  });
  await new Promise<void>(resolve => upstream.listen(0, "127.0.0.1", resolve));
  const address = upstream.address();
  if (!address || typeof address === "string") throw new Error("Missing test address");
  const session = randomUUID();
  const proxy = await startQaProxy({ upstream: `http://127.0.0.1:${address.port}`,
    upstreamOrigin: "https://borrowed.example.test", key, secret,
    serverUrl: "wss://signal.example.test", qaSessionId: session, verifyAgent: async () => true });

  let firstChunk!: (chunk: Buffer) => void;
  const first = new Promise<Buffer>(resolve => { firstChunk = resolve; });
  let sawChunk = false;
  const completed = new Promise<{ headers: import("node:http").IncomingHttpHeaders; body: string }>((resolve, reject) => {
    const outgoing = request(proxy.origin + "/asset", { headers: {
      Connection: "keep-alive, x-request-hop",
      "Keep-Alive": "timeout=88",
      "Proxy-Authorization": "fixture-secret",
      TE: "trailers",
      "X-Request-Hop": "remove-me",
      "X-End-To-End-Request": "preserved",
      Host: "untrusted.example.test",
      Origin: "https://untrusted.example.test",
    } }, response => {
      const chunks: Buffer[] = [];
      response.on("data", chunk => {
        const bytes = Buffer.from(chunk); chunks.push(bytes);
        if (!sawChunk) { sawChunk = true; firstChunk(bytes); }
      });
      response.on("end", () => resolve({ headers: response.headers, body: Buffer.concat(chunks).toString() }));
    });
    outgoing.on("error", reject);
    outgoing.end();
  });

  try {
    assert.equal((await first).toString(), "stream-");
    finishBody();
    const response = await completed;
    assert.equal(response.body, "stream-body");
    assert.equal(upstreamHeaders["x-request-hop"], undefined);
    assert.equal(upstreamHeaders["proxy-authorization"], undefined);
    assert.equal(upstreamHeaders.te, undefined);
    assert.equal(upstreamHeaders["x-end-to-end-request"], "preserved");
    assert.equal(upstreamHeaders.host, "borrowed.example.test");
    assert.equal(upstreamHeaders.origin, "https://borrowed.example.test");
    assert.equal(response.headers["x-response-hop"], undefined);
    assert.equal(response.headers["proxy-authenticate"], undefined);
    assert.equal(response.headers.trailer, undefined);
    assert.equal(response.headers["x-end-to-end-response"], "preserved");
    assert.equal(response.headers["content-type"], "application/octet-stream");
  } finally {
    finishBody();
    await proxy.close();
    upstream.closeAllConnections();
    await new Promise<void>(resolve => upstream.close(() => resolve()));
  }
});
