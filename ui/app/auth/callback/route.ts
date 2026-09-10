import type { NextRequest } from "next/server";

import { readOwnerAuthConfig } from "../../../lib/auth/boundary";
import { handleAuthCallback } from "../../../lib/auth/flow";
import { createServerAuthClient } from "../../../lib/auth/server-client";

export async function GET(request: NextRequest): Promise<Response> {
  const configured = readOwnerAuthConfig(process.env);
  if (!configured.ok) return Response.json(
    { error: "Authentication is unavailable." },
    { status: 503, headers: { "cache-control": "private, no-store" } },
  );
  const supabase = await createServerAuthClient(configured.value);
  return handleAuthCallback(request, process.env, {
    exchangeCodeForSession: (code) => supabase.auth.exchangeCodeForSession(code),
    getClaims: () => supabase.auth.getClaims(),
    signOut: (options) => supabase.auth.signOut(options),
  });
}
