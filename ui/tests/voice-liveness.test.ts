import assert from "node:assert/strict";
import { test } from "node:test";
import { RpcError } from "livekit-client";
import { agentResponds, watchAgentLiveness } from "../lib/voice/liveness";

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
test("ping accepts pong and an explicit legacy reply, never local transport errors", async () => {
  assert.equal(await agentResponds(async () => "pong"), true);
  assert.equal(await agentResponds(async () => "wrong"), false);
  assert.equal(await agentResponds(async () => { throw new RpcError(1400, "unsupported"); }), true);
  assert.equal(await agentResponds(async () => { throw new RpcError(1502, "timeout"); }), false);
});

test("two bounded misses report loss; recovery and abort cannot revive an old session", async () => {
  const abort = new AbortController(), states: boolean[] = [];
  let pending = true, current = true, calls = 0;
  let respond: ((alive: boolean) => void) | undefined;
  const stop = watchAgentLiveness({signal: abort.signal, identity: () => "agent", isCurrent: () => current,
    probe: async () => { calls++; if (pending) return new Promise<boolean>((resolve) => { respond = resolve; }); return true; },
    changed: (alive) => states.push(alive), intervalMs: 5, timeoutMs: 10});
  try {
    for (let i = 0; i < 30 && !states.length; i++) await delay(5);
    assert.deepEqual(states, [false]);
    assert.equal(calls, 1, "a stuck RPC is never multiplied");
    pending = false; respond?.(true);
    for (let i = 0; i < 30 && states.length < 2; i++) await delay(5);
    assert.deepEqual(states, [false, true]);
    pending = true; current = false; abort.abort();
    const count = calls; await delay(40);
    assert.equal(calls, count); assert.deepEqual(states, [false, true]);
  } finally { stop(); }
});

test("one slow probe recovers without showing a false outage", async () => {
  const abort = new AbortController(), states: boolean[] = []; let calls = 0;
  const stop = watchAgentLiveness({signal: abort.signal, identity: () => "agent", isCurrent: () => true,
    probe: async () => ++calls > 1, changed: (alive) => states.push(alive), intervalMs: 5, timeoutMs: 10});
  try { await delay(35); assert.ok(calls > 1); assert.deepEqual(states, []); }
  finally { stop(); }
});
