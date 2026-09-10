import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { test } from "node:test";
import { NextRequest } from "next/server";

import {
  authorizeOwnerRequest,
  classifyAuthPath,
  readOwnerAuthConfig,
  type OwnerIdentityVerifier,
} from "../lib/auth/boundary";
import { verifySupabaseIdentity, type ClaimsClientFactory } from "../lib/auth/proxy-session";
import { makeProxy } from "../proxy";

const configuredEnvironment = {
  NEXT_PUBLIC_SUPABASE_URL: "https://project.supabase.co",
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_test",
  JRC_OWNER_USER_IDS: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
};

function request(path: string, method = "GET") {
  return new Request(`https://jobs.example.com${path}`, { method });
}

function verifier(userId: string | null): OwnerIdentityVerifier {
  return async () => userId === null
    ? { kind: "unauthenticated" }
    : { kind: "authenticated", userId };
}

test("private pages and APIs deny unauthenticated callers without trusting a cookie session", async () => {
  const page = await authorizeOwnerRequest(
    request("/?view=all"),
    configuredEnvironment,
    verifier(null),
  );
  assert.ok(page.kind === "deny");
  assert.equal(page.response.status, 307);
  assert.equal(
    page.response.headers.get("location"),
    "https://jobs.example.com/login?next=%2F%3Fview%3Dall",
  );

  for (const path of ["/api/jobs", "/api/events"]) {
    const result = await authorizeOwnerRequest(
      request(path),
      configuredEnvironment,
      verifier(null),
    );
    assert.ok(result.kind === "deny", path);
    assert.equal(result.response.status, 401, path);
    assert.deepEqual(await result.response.json(), { error: "Authentication required." }, path);
  }
});

test("a valid Supabase identity outside the owner allowlist is forbidden", async () => {
  const result = await authorizeOwnerRequest(
    request("/api/profile", "PATCH"),
    configuredEnvironment,
    verifier("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
  );
  assert.ok(result.kind === "deny");
  assert.equal(result.response.status, 403);
  assert.deepEqual(await result.response.json(), { error: "Owner access required." });
});

test("missing or malformed auth configuration fails closed", async () => {
  for (const environment of [
    {},
    { ...configuredEnvironment, JRC_OWNER_USER_IDS: "" },
    { ...configuredEnvironment, JRC_OWNER_USER_IDS: "not-a-user-id" },
    { ...configuredEnvironment, NEXT_PUBLIC_SUPABASE_URL: "not-a-url" },
  ]) {
    assert.equal(readOwnerAuthConfig(environment).ok, false);
    for (const path of ["/", "/api/jobs", "/api/events", "/api/profile"]) {
      const result = await authorizeOwnerRequest(request(path), environment, verifier(null));
      assert.ok(result.kind === "deny", path);
      assert.equal(result.response.status, 503, path);
      assert.equal(result.response.headers.get("cache-control"), "private, no-store", path);
    }
  }
});

test("the configured owner can reach pages, data, mutations, and event streams", async () => {
  for (const [path, method] of [
    ["/", "GET"],
    ["/api/jobs", "GET"],
    ["/api/jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/status", "PATCH"],
    ["/api/profile", "PATCH"],
    ["/api/events", "GET"],
  ] as const) {
    const result = await authorizeOwnerRequest(
      request(path, method),
      configuredEnvironment,
      verifier("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    );
    assert.deepEqual(result, { kind: "allow" }, `${method} ${path}`);
  }
});

test("only the explicit login, callback, recovery, and static paths are public", () => {
  for (const path of [
    "/login",
    "/auth/callback",
    "/auth/recovery",
    "/_next/static/chunk.js",
    "/_next/image",
    "/favicon.ico",
    "/icon.svg",
    "/companies/logo.png",
    "/tech/logo.svg",
  ]) assert.equal(classifyAuthPath(path), "public", path);

  for (const path of [
    "/",
    "/auth/passkeys",
    "/auth/callback/extra",
    "/login/anything",
    "/_next/data/build-id/dashboard.json",
    "/api/jobs",
    "/api/profile",
    "/api/events",
  ]) assert.equal(classifyAuthPath(path), "private", path);
});

test("every current page and route file is covered by the default-private policy", () => {
  const appRoot = join(process.cwd(), "app");
  function walk(directory: string): string[] {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
      const path = join(directory, entry.name);
      return entry.isDirectory() ? walk(path) : [path];
    });
  }

  const routes = walk(appRoot)
    .filter((path) => /\/(page|route)\.tsx?$/.test(path))
    .map((path) => {
      const name = relative(appRoot, path).split(sep).slice(0, -1).join("/");
      return name ? `/${name.replace(/\[[^/]+\]/g, "example")}` : "/";
    });

  assert.ok(routes.length > 0);
  assert.deepEqual(routes.toSorted(), [
    "/",
    "/api/events",
    "/api/jobs",
    "/api/jobs/example",
    "/api/jobs/example/status",
    "/api/profile",
    "/auth/callback",
    "/auth/passkeys",
    "/auth/recovery",
    "/login",
  ]);
  const publicRoutes = new Set(["/login", "/auth/callback", "/auth/recovery"]);
  for (const path of routes) {
    assert.equal(classifyAuthPath(path), publicRoutes.has(path) ? "public" : "private", path);
  }
});

test("the proxy verifies claims and forwards refreshed cookies with anti-cache headers", async () => {
  let claimsCalls = 0;
  const createClient: ClaimsClientFactory = (_url, _key, options) => ({
    auth: {
      async getClaims() {
        claimsCalls += 1;
        options.cookies.setAll(
          [{
            name: "sb-auth-token",
            value: "refreshed",
            options: { httpOnly: true, sameSite: "lax", secure: true, path: "/" },
          }],
          {
            "cache-control": "private, no-cache, no-store, must-revalidate, max-age=0",
            expires: "0",
            pragma: "no-cache",
          },
        );
        return {
          data: { claims: { sub: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" } },
          error: null,
        };
      },
    },
  });
  const configured = readOwnerAuthConfig(configuredEnvironment);
  assert.equal(configured.ok, true);
  if (!configured.ok) return;

  const session = await verifySupabaseIdentity(
    new NextRequest("https://jobs.example.com/api/events"),
    configured.value,
    createClient,
  );
  assert.deepEqual(session.identity, {
    kind: "authenticated",
    userId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  });
  assert.equal(claimsCalls, 1);

  const response = session.response();
  assert.match(response.headers.get("set-cookie") ?? "", /sb-auth-token=refreshed/);
  assert.match(response.headers.get("set-cookie") ?? "", /HttpOnly/);
  assert.equal(
    response.headers.get("cache-control"),
    "private, no-cache, no-store, must-revalidate, max-age=0",
  );
  assert.equal(response.headers.get("expires"), "0");
  assert.equal(response.headers.get("pragma"), "no-cache");
});

function loginClaimsClient(userId: string | null, mode: "return" | "throw" = "return") {
  let calls = 0;
  const factory: ClaimsClientFactory = (_url, _key, options) => ({
    auth: {
      async getClaims() {
        calls += 1;
        options.cookies.setAll(
          [{ name: "sb-auth-token", value: "refreshed", options: { httpOnly: true, path: "/" } }],
          { "cache-control": "private, no-cache, no-store, must-revalidate, max-age=0" },
        );
        if (mode === "throw") throw new Error("transport unavailable");
        return { data: userId ? { claims: { sub: userId } } : null, error: userId ? null : new Error("anonymous") };
      },
    },
  });
  return { factory, calls: () => calls };
}

test("signed-in owner visiting login is redirected with refreshed cookies", async () => {
  const claims = loginClaimsClient("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
  const handler = makeProxy(configuredEnvironment, claims.factory);
  const response = await handler(new NextRequest("https://jobs.example.com/login?next=%2F%3Fview%3Dall"));

  assert.equal(claims.calls(), 1);
  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), "https://jobs.example.com/?view=all");
  assert.match(response.headers.get("set-cookie") ?? "", /sb-auth-token=refreshed/);
  assert.equal(response.headers.get("cache-control"), "private, no-cache, no-store, must-revalidate, max-age=0");
});

test("signed-in login redirects allow only private internal next paths", async () => {
  const cases = [
    ["/login", "/"],
    ["/login?next=%2Fauth%2Fpasskeys", "/auth/passkeys"],
    ["/login?next=%2Flogin", "/"],
    ["/login?next=%2Fauth%2Fcallback%3Fcode%3Dvalue", "/"],
    ["/login?next=%2Fauth%2Frecovery", "/"],
    ["/login?next=https%3A%2F%2Fattacker.example", "/"],
    ["/login?next=%2F%2Fattacker.example", "/"],
    ["/login?next=javascript%3Aalert%281%29", "/"],
  ] as const;
  for (const [source, expected] of cases) {
    const claims = loginClaimsClient("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
    const response = await makeProxy(configuredEnvironment, claims.factory)(
      new NextRequest(`https://jobs.example.com${source}`),
    );
    assert.equal(response.status, 307, source);
    assert.equal(response.headers.get("location"), `https://jobs.example.com${expected}`, source);
  }
});

test("anonymous, non-owner, claim-error, and invalid-config visitors stay on login", async () => {
  const cases = [
    { environment: configuredEnvironment, claims: loginClaimsClient(null) },
    { environment: configuredEnvironment, claims: loginClaimsClient("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb") },
    { environment: configuredEnvironment, claims: loginClaimsClient(null, "throw") },
    { environment: { ...configuredEnvironment, JRC_OWNER_USER_IDS: "" }, claims: loginClaimsClient("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa") },
  ];
  for (const { environment, claims } of cases) {
    const response = await makeProxy(environment, claims.factory)(
      new NextRequest("https://jobs.example.com/login?next=%2F"),
    );
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("location"), null);
    assert.match(response.headers.get("cache-control") ?? "", /private/);
    assert.match(response.headers.get("cache-control") ?? "", /no-store/);
  }
  assert.equal(cases[3].claims.calls(), 0);
});
