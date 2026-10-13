import assert from "node:assert/strict";
import { test } from "node:test";
import { createPrefetchIntent, PREFETCH_INTENT_MS } from "../../lib/detail-prefetch";

function harness(visible = true) {
  const prefetched: string[] = [];
  const timers = new Map<number, () => void>();
  let next = 0;
  const state = { visible };
  const intent = createPrefetchIntent(id => prefetched.push(id), {
    isVisible: () => state.visible,
    schedule: (run, ms) => { assert.equal(ms, PREFETCH_INTENT_MS); timers.set(++next, run); return next; },
    cancel: handle => { timers.delete(handle as number); },
  });
  const flush = () => { const pending = [...timers.values()]; timers.clear(); pending.forEach(run => run()); };
  return { intent, prefetched, timers, flush, state };
}

test("intent waits for the delay and leaving cancels it", () => {
  const { intent, prefetched, timers, flush } = harness();
  assert.ok(PREFETCH_INTENT_MS >= 100 && PREFETCH_INTENT_MS <= 250);
  intent.start("a");
  assert.deepEqual(prefetched, []);
  intent.end("a");
  assert.equal(timers.size, 0);
  flush();
  assert.deepEqual(prefetched, []);
  intent.start("b");
  flush();
  assert.deepEqual(prefetched, ["b"]);
});

test("moving across cards keeps one pending intent: only the resting card prefetches", () => {
  const { intent, prefetched, timers, flush } = harness();
  for (const id of ["a", "b", "c", "d"]) intent.start(id);
  assert.equal(timers.size, 1);
  flush();
  assert.deepEqual(prefetched, ["d"]);
});

test("a stale leave for another card does not cancel the current intent", () => {
  const { intent, prefetched, flush } = harness();
  intent.start("a");
  intent.start("b");
  intent.end("a");
  flush();
  assert.deepEqual(prefetched, ["b"]);
});

test("a hidden tab never prefetches, even if it hides during the delay", () => {
  const hidden = harness(false);
  hidden.intent.start("a");
  hidden.flush();
  assert.deepEqual(hidden.prefetched, []);
  const hiding = harness();
  hiding.intent.start("a");
  hiding.state.visible = false;
  hiding.flush();
  assert.deepEqual(hiding.prefetched, []);
});

test("dispose clears the pending intent", () => {
  const { intent, prefetched, timers, flush } = harness();
  intent.start("a");
  intent.dispose();
  assert.equal(timers.size, 0);
  flush();
  assert.deepEqual(prefetched, []);
});
