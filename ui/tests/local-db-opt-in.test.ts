import assert from "node:assert/strict";
import { test } from "node:test";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { PassThrough } from "node:stream";
import { EventEmitter } from "node:events";

test("local DB commands require deliberate opt-in before any spawn", async (t) => {
  const { database } = await import("../e2e/db/db.mjs");
  const { runSuite } = await import("../e2e/db/run-capped.mjs");
  const spawn = t.mock.method(childProcess, "spawn", () => {
    const child = Object.assign(new EventEmitter(), {
      stdin: new PassThrough(), stdout: new PassThrough(), stderr: new PassThrough(),
    });
    queueMicrotask(() => child.emit("exit", 0));
    return child;
  });
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
    await database("down");
    assert.equal(spawn.mock.callCount(), 1);
    delete process.env.JRC_LOCAL_DOCKER;
    process.env.CI = "true";
    await database("down");
    assert.equal(spawn.mock.callCount(), 2);
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    t.mock.restoreAll();
    syncBuiltinESMExports();
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
          database: step, cli: step, rm: async () => {},
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
