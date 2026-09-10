import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";

function loadConfig(vercel: string | undefined) {
  const environment = { ...process.env };
  if (vercel === undefined) delete environment.VERCEL;
  else environment.VERCEL = vercel;
  const result = spawnSync(
    process.execPath,
    [
      "--import",
      "tsx",
      "--input-type=module",
      "--eval",
      'const loaded = (await import("./next.config.ts")).default; const config = loaded.default ?? loaded; process.stdout.write(JSON.stringify(config));',
    ],
    { cwd: process.cwd(), encoding: "utf8", env: environment },
  );
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout) as { output?: string; poweredByHeader?: boolean };
}

test("Next emits standalone output locally and leaves Vercel output to its adapter", () => {
  const local = loadConfig(undefined);
  const vercel = loadConfig("1");

  assert.equal(local.output, "standalone");
  assert.equal(vercel.output, undefined);
  assert.equal(local.poweredByHeader, false);
  assert.equal(vercel.poweredByHeader, false);
});
