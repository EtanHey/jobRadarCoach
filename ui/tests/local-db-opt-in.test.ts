import assert from "node:assert/strict";
import { test } from "node:test";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";

test("local DB commands require deliberate opt-in before any spawn", async (t) => {
  const { database } = await import("../e2e/db/db.mjs");
  const { runSuite } = await import("../e2e/db/run-capped.mjs");
  const { requireLocalDocker } = await import("../e2e/db/local.mjs");
  const spawn = t.mock.method(childProcess, "spawn", () => { throw new Error("Unexpected spawn"); });
  syncBuiltinESMExports();
  const saved = { CI: process.env.CI, JRC_LOCAL_DOCKER: process.env.JRC_LOCAL_DOCKER };
  try {
    delete process.env.CI;
    delete process.env.JRC_LOCAL_DOCKER;
    for (const action of ["up", "seed", "down"]) {
      await assert.rejects(database(action), /DB e2e runs in CI.*JRC_LOCAL_DOCKER=1/);
    }
    await assert.rejects(runSuite(), /DB e2e runs in CI.*JRC_LOCAL_DOCKER=1/);
    assert.equal(spawn.mock.callCount(), 0);
    process.env.JRC_LOCAL_DOCKER = "1";
    assert.doesNotThrow(requireLocalDocker);
    await assert.rejects(database("nope"), /Expected up, seed or down/);
    delete process.env.JRC_LOCAL_DOCKER;
    process.env.CI = "true";
    assert.doesNotThrow(requireLocalDocker);
    await assert.rejects(database("nope"), /Expected up, seed or down/);
    assert.equal(spawn.mock.callCount(), 0);
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    t.mock.restoreAll();
    syncBuiltinESMExports();
  }
});

test("signals during hanging up/seed stop the stack and remove suite handlers", async () => {
  const { runSuite } = await import("../e2e/db/run-capped.mjs");
  const saved = { CI: process.env.CI, JRC_LOCAL_DOCKER: process.env.JRC_LOCAL_DOCKER };
  try {
    delete process.env.CI;
    process.env.JRC_LOCAL_DOCKER = "1";
    for (const action of ["up", "seed"]) for (const signal of ["SIGINT", "SIGTERM"] as const) {
      const before = [process.listenerCount("SIGINT"), process.listenerCount("SIGTERM")];
      const calls: string[][] = [];
      let activeSignal: AbortSignal | undefined;
      const result = runSuite({
        database: async (step: string, options: { signal?: AbortSignal } = {}) => {
          if (step === action) {
            activeSignal = options?.signal;
            queueMicrotask(() => process.emit(signal));
            await new Promise(() => {});
          }
        },
        run: async () => { throw new Error("Must not run after signal"); }, rm: async () => {},
        cli: async (...args: string[]) => { calls.push(args); },
      });
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        await assert.rejects(Promise.race([result, new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error("Signal ignored")), 500);
        })]), new RegExp(signal));
      } finally { clearTimeout(timer); }
      assert.equal(activeSignal?.aborted, true);
      assert.deepEqual(calls, [["stop", "--project-id", "jrc-p12-test-db"]]);
      assert.deepEqual([process.listenerCount("SIGINT"), process.listenerCount("SIGTERM")], before);
    }
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});

test("teardown failure is logged without masking the original failure", async (t) => {
  const { runSuite } = await import("../e2e/db/run-capped.mjs");
  const saved = { CI: process.env.CI, JRC_LOCAL_DOCKER: process.env.JRC_LOCAL_DOCKER };
  const log = t.mock.method(console, "error", () => {});
  try {
    delete process.env.CI;
    process.env.JRC_LOCAL_DOCKER = "1";
    const original = new Error("original failure");
    await assert.rejects(runSuite({
      database: async () => { throw original; }, run: async () => {}, rm: async () => {},
      cli: async () => { throw new Error("cleanup failed"); },
    }), error => error === original);
    assert.match(String(log.mock.calls[0]?.arguments[0]), /cleanup failed/);
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});

test("capped suite stops local stacks after success or failure, preserving volumes", async () => {
  const { runSuite } = await import("../e2e/db/run-capped.mjs");
  const saved = { CI: process.env.CI, JRC_LOCAL_DOCKER: process.env.JRC_LOCAL_DOCKER };
  try {
    process.env.JRC_LOCAL_DOCKER = "1";
    for (const ci of ["false", "true"]) {
      process.env.CI = ci;
      for (const failure of ["none", "up", "seed", "build", "test"]) {
        const calls: string[][] = [];
        const step = async (...args: string[]) => {
          calls.push(args);
          if (args.includes(failure)) throw new Error("synthetic failure");
        };
        const result = runSuite({
          database: async (action: string) => step(action), cli: step, rm: async () => {},
          run: async (args: string[]) => step(args.includes("build") ? "build" : "test"),
        });
        if (failure === "none") await result;
        else await assert.rejects(result, /synthetic failure/);
        const stops = calls.filter(args => args[0] === "stop");
        assert.deepEqual(stops, ci === "true" ? [] : [["stop", "--project-id", "jrc-p12-test-db"]]);
      }
    }
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});
