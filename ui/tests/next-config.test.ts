import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { test } from "node:test";

function runConfig(vercel: string | undefined, extra: Record<string, string | undefined> = {}) {
  const environment: NodeJS.ProcessEnv = { ...process.env, ...extra };
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
  return result;
}

function loadConfig(vercel: string | undefined, extra: Record<string, string | undefined> = {}) {
  const result = runConfig(vercel, extra);
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

test("Vercel functions execute beside the Frankfurt-hosted database", () => {
  const config = JSON.parse(readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));
  assert.deepEqual(config.regions, ["fra1"]);
});

test("a non-publishable Logo.dev key fails the build instead of being inlined into client JavaScript", () => {
  const secret = "sk_synthetic_secret_value";
  const refused = runConfig(undefined, { NEXT_PUBLIC_LOGO_DEV_KEY: secret });
  assert.notEqual(refused.status, 0);
  assert.match(refused.stderr, /NEXT_PUBLIC_LOGO_DEV_KEY must be a Logo\.dev publishable pk_ key/);
  assert.doesNotMatch(refused.stderr + refused.stdout, new RegExp(secret));
  assert.equal(loadConfig(undefined, { NEXT_PUBLIC_LOGO_DEV_KEY: "pk_synthetic_publishable" }).poweredByHeader, false);
  assert.equal(loadConfig(undefined, { NEXT_PUBLIC_LOGO_DEV_KEY: "" }).poweredByHeader, false);
});
