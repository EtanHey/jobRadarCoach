import assert from "node:assert/strict";
import { test } from "node:test";
import { NextRequest } from "next/server";

import {
  CONTEXT_NAMESPACE,
  resolveContextSubject,
} from "../lib/auth/context-subject";
import type { ClaimsClientFactory } from "../lib/auth/proxy-session";

const ownerA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ownerB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const environment = {
  NEXT_PUBLIC_SUPABASE_URL: "https://project.supabase.co",
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_test",
  JRC_OWNER_USER_IDS: `${ownerA},${ownerB}`,
};

function claimsClient(
  userId: string | null,
  mode: "return" | "error" | "throw" = "return",
) {
  let calls = 0;
  const factory: ClaimsClientFactory = (_url, _key, options) => ({
    auth: {
      async getClaims() {
        calls += 1;
        options.cookies.setAll(
          [{ name: "sb-auth-token", value: "refreshed", options: { httpOnly: true, path: "/" } }],
          { "x-auth-refresh": "yes" },
        );
        if (mode === "throw") throw new Error("claims transport failed");
        return {
          data: userId ? { claims: { sub: userId } } : null,
          error: mode === "error" ? new Error("claims rejected") : null,
        };
      },
    },
  });
  return { factory, calls: () => calls };
}

function spoofedRequest(path = "/api/context") {
  return new NextRequest(
    `https://jobs.example.com${path}?namespace=attacker.namespace&subject=${ownerB}&scope=admin`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-context-namespace": "attacker.namespace",
        "x-context-subject": ownerB,
      },
      body: JSON.stringify({ namespace: "attacker.namespace", subject: ownerB, scope: "admin" }),
    },
  );
}

test("verified configured owners receive fixed, normalized, isolated context scopes", async () => {
  const firstClaims = claimsClient(ownerA.toUpperCase());
  const secondClaims = claimsClient(ownerB);

  const first = await resolveContextSubject(spoofedRequest(), environment, firstClaims.factory);
  const second = await resolveContextSubject(spoofedRequest(), environment, secondClaims.factory);

  assert.equal(first.kind, "allow");
  assert.equal(second.kind, "allow");
  if (first.kind !== "allow" || second.kind !== "allow") return;
  assert.deepEqual(first.scope, { namespace: CONTEXT_NAMESPACE, subject: ownerA });
  assert.deepEqual(second.scope, { namespace: CONTEXT_NAMESPACE, subject: ownerB });
  assert.notEqual(first.scope.subject, second.scope.subject);
  assert.equal(firstClaims.calls(), 1);
  assert.equal(secondClaims.calls(), 1);
});

test("missing identity, failed claims, non-owner identity, and invalid config deny", async () => {
  const cases = [
    { expected: 401, environment, claims: claimsClient(null) },
    { expected: 401, environment, claims: claimsClient(ownerA, "error") },
    { expected: 401, environment, claims: claimsClient(null, "throw") },
    { expected: 403, environment, claims: claimsClient("cccccccc-cccc-4ccc-8ccc-cccccccccccc") },
    {
      expected: 503,
      environment: { ...environment, JRC_OWNER_USER_IDS: "" },
      claims: claimsClient(ownerA),
    },
  ];

  for (const entry of cases) {
    const result = await resolveContextSubject(
      spoofedRequest(),
      entry.environment,
      entry.claims.factory,
    );
    assert.equal(result.kind, "deny");
    if (result.kind === "deny") assert.equal(result.response.status, entry.expected);
  }
  assert.equal(cases[4].claims.calls(), 0);
});

test("public paths do not bypass context authentication", async () => {
  const claims = claimsClient(null);
  const result = await resolveContextSubject(spoofedRequest("/login"), environment, claims.factory);

  assert.equal(result.kind, "deny");
  if (result.kind === "deny") assert.equal(result.response.status, 401);
  assert.equal(claims.calls(), 1);
});

test("resolver preserves refreshed auth response cookies and headers", async () => {
  const claims = claimsClient(ownerA);
  const result = await resolveContextSubject(spoofedRequest(), environment, claims.factory);

  assert.equal(result.kind, "allow");
  if (result.kind !== "allow") return;
  const response = result.response(Response.json({ ok: true }, { status: 202 }));
  assert.equal(response.status, 202);
  assert.deepEqual(await response.json(), { ok: true });
  assert.match(response.headers.get("set-cookie") ?? "", /sb-auth-token=refreshed/);
  assert.equal(response.headers.get("x-auth-refresh"), "yes");
  assert.equal(response.headers.get("cache-control"), "private, no-store");
});
