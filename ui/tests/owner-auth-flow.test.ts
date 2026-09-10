import assert from "node:assert/strict";
import { test } from "node:test";

import {
  handleAuthCallback,
  readRecoveryConfig,
  safeNextPath,
  sendOwnerRecovery,
  type CallbackAuthClient,
  type RecoveryAuthClient,
} from "../lib/auth/flow";

const environment = {
  NEXT_PUBLIC_SUPABASE_URL: "https://project.supabase.co",
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_test",
  JRC_OWNER_USER_IDS: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  JRC_OWNER_RECOVERY_EMAIL: "owner@example.com",
  JRC_OWNER_RECOVERY_ENABLED: "true",
  UI_ORIGIN: "https://jobs.example.com",
};

test("post-auth redirects stay on an internal path", () => {
  assert.equal(safeNextPath("/?view=all"), "/?view=all");
  for (const value of [
    null,
    "",
    "https://attacker.example/steal",
    "//attacker.example/steal",
    "/\\attacker.example/steal",
    "javascript:alert(1)",
  ]) assert.equal(safeNextPath(value), "/", String(value));
});

test("recovery is available only with the explicit operator gate and complete server config", () => {
  assert.equal(readRecoveryConfig(environment).ok, true);
  for (const override of [
    { JRC_OWNER_RECOVERY_ENABLED: "false" },
    { JRC_OWNER_RECOVERY_EMAIL: "" },
    { JRC_OWNER_RECOVERY_EMAIL: "not-email" },
    { UI_ORIGIN: "http://jobs.example.com" },
    { JRC_OWNER_USER_IDS: "" },
  ]) assert.equal(readRecoveryConfig({ ...environment, ...override }).ok, false);
});

test("recovery sends only to the configured owner without creating an account", async () => {
  const calls: Parameters<RecoveryAuthClient["signInWithOtp"]>[0][] = [];
  const client: RecoveryAuthClient = {
    async signInWithOtp(input) {
      calls.push(input);
      return { error: null };
    },
  };
  const response = await sendOwnerRecovery(
    new Request("https://jobs.example.com/auth/recovery", {
      method: "POST",
      headers: { origin: "https://jobs.example.com", "content-type": "application/json" },
      body: JSON.stringify({ next: "/auth/passkeys" }),
    }),
    environment,
    client,
  );
  assert.equal(response.status, 202);
  assert.deepEqual(calls, [{
    email: "owner@example.com",
    options: {
      shouldCreateUser: false,
      emailRedirectTo: "https://jobs.example.com/auth/callback?next=%2Fauth%2Fpasskeys",
    },
  }]);

  const injected = await sendOwnerRecovery(
    new Request("https://jobs.example.com/auth/recovery", {
      method: "POST",
      headers: { origin: "https://jobs.example.com", "content-type": "application/json" },
      body: JSON.stringify({ email: "attacker@example.com" }),
    }),
    environment,
    client,
  );
  assert.equal(injected.status, 400);
  assert.equal(calls.length, 1);
});

test("recovery rejects missing or foreign Origin before sending", async () => {
  let calls = 0;
  const client: RecoveryAuthClient = {
    async signInWithOtp() { calls += 1; return { error: null }; },
  };
  for (const origin of [undefined, "https://attacker.example"]) {
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (origin) headers.origin = origin;
    const response = await sendOwnerRecovery(
      new Request("https://jobs.example.com/auth/recovery", {
        method: "POST", headers, body: "{}",
      }),
      environment,
      client,
    );
    assert.equal(response.status, 403);
  }
  assert.equal(calls, 0);
});

function callbackClient(userId: string | null, exchangeError = false): CallbackAuthClient {
  return {
    async exchangeCodeForSession() { return { error: exchangeError ? new Error("bad") : null }; },
    async getClaims() {
      return { data: userId ? { claims: { sub: userId } } : null, error: userId ? null : new Error("bad") };
    },
    async signOut() { return { error: null }; },
  };
}

test("callback accepts only a verified allowlisted owner and safe redirect", async () => {
  const accepted = await handleAuthCallback(
    new Request("https://jobs.example.com/auth/callback?code=valid&next=%2Fauth%2Fpasskeys"),
    environment,
    callbackClient("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
  );
  assert.equal(accepted.status, 303);
  assert.equal(accepted.headers.get("location"), "https://jobs.example.com/auth/passkeys");

  const external = await handleAuthCallback(
    new Request("https://attacker.example/auth/callback?code=valid&next=https%3A%2F%2Fattacker.example"),
    environment,
    callbackClient("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
  );
  assert.equal(external.headers.get("location"), "https://jobs.example.com/");
});

test("callback rejects missing codes, failed exchanges, and non-owner identities", async () => {
  for (const [url, client] of [
    ["https://jobs.example.com/auth/callback", callbackClient(null)],
    ["https://jobs.example.com/auth/callback?code=bad", callbackClient(null, true)],
    ["https://jobs.example.com/auth/callback?code=valid", callbackClient("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")],
  ] as const) {
    const response = await handleAuthCallback(new Request(url), environment, client);
    assert.equal(response.status, 303);
    assert.match(response.headers.get("location") ?? "", /^https:\/\/jobs\.example\.com\/login\?error=/);
  }
});
