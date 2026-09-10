import { type NextRequest, NextResponse } from "next/server";

import { authorizeOwnerRequest, classifyAuthPath } from "./lib/auth/boundary";
import { verifySupabaseIdentity } from "./lib/auth/proxy-session";

export async function proxy(request: NextRequest) {
  if (classifyAuthPath(request.nextUrl.pathname) === "public") return NextResponse.next();

  let session: Awaited<ReturnType<typeof verifySupabaseIdentity>> | undefined;
  const decision = await authorizeOwnerRequest(request, process.env, async (config) => {
    session = await verifySupabaseIdentity(request, config);
    return session.identity;
  });

  if (session) return session.response(decision.kind === "deny" ? decision.response : undefined);
  return decision.kind === "deny" ? decision.response : NextResponse.next();
}

export const config = { matcher: ["/:path*"] };
