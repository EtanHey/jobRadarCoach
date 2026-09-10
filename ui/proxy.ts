import { type NextRequest, NextResponse } from "next/server";

import { authorizeOwnerRequest, classifyAuthPath, readOwnerAuthConfig } from "./lib/auth/boundary";
import { safeNextPath } from "./lib/auth/flow";
import { verifySupabaseIdentity, type ClaimsClientFactory } from "./lib/auth/proxy-session";

function privateNext(request: NextRequest): NextResponse {
  const response = NextResponse.next({ request });
  response.headers.set("cache-control", "private, no-store");
  return response;
}

function signedInDestination(request: NextRequest): URL {
  const path = safeNextPath(request.nextUrl.searchParams.get("next"));
  const destination = new URL(path, request.url);
  return classifyAuthPath(destination.pathname) === "private"
    ? destination
    : new URL("/", request.url);
}

export function makeProxy(
  environment: Record<string, string | undefined> = process.env,
  createClaimsClient?: ClaimsClientFactory,
) {
  return async (request: NextRequest) => {
    const pathname = request.nextUrl.pathname;
    if (classifyAuthPath(pathname) === "public" && pathname !== "/login") {
      return NextResponse.next();
    }

    if (pathname === "/login") {
      const configured = readOwnerAuthConfig(environment);
      if (!configured.ok) return privateNext(request);
      const session = await verifySupabaseIdentity(request, configured.value, createClaimsClient);
      if (
        session.identity.kind !== "authenticated"
        || !configured.value.ownerUserIds.has(session.identity.userId.toLowerCase())
      ) return session.response();
      return session.response(NextResponse.redirect(signedInDestination(request), 307));
    }

    let session: Awaited<ReturnType<typeof verifySupabaseIdentity>> | undefined;
    const decision = await authorizeOwnerRequest(request, environment, async (config) => {
      session = await verifySupabaseIdentity(request, config, createClaimsClient);
      return session.identity;
    });

    if (session) return session.response(decision.kind === "deny" ? decision.response : undefined);
    return decision.kind === "deny" ? decision.response : NextResponse.next();
  };
}

export const proxy = makeProxy();

export const config = { matcher: ["/:path*"] };
