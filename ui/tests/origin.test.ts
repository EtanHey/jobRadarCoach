import { test } from "node:test";
import assert from "node:assert/strict";
import { z } from "zod";
import { mutationJson } from "../lib/http";

test("browser Host survives Next internal URL rewriting; foreign Origin is rejected", async () => {
  const make = (origin: string) => new Request("http://localhost:3405/api/jobs", {
    method: "PATCH", headers: { host: "127.0.0.1:3405", origin, "content-type": "application/json" }, body: "{}",
  });
  assert.deepEqual(await mutationJson(make("http://127.0.0.1:3405"), z.object({})), {});
  await assert.rejects(mutationJson(make("https://foreign.example"), z.object({})));
});

test("configured HTTPS tailnet origin survives an internal HTTP proxy", async () => {
  const previous = process.env.UI_ORIGIN;
  process.env.UI_ORIGIN = "https://machine.example.ts.net:8445";
  try {
    const req = new Request("http://localhost:3000/api/profile", {
      method: "PATCH", headers: { origin: process.env.UI_ORIGIN, "content-type": "application/json" }, body: "{}",
    });
    assert.deepEqual(await mutationJson(req, z.object({})), {});
  } finally {
    if (previous === undefined) delete process.env.UI_ORIGIN;
    else process.env.UI_ORIGIN = previous;
  }
});
