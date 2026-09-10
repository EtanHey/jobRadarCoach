import type { NextRequest } from "next/server";

import { readRecoveryConfig, sendOwnerRecovery } from "../../../lib/auth/flow";
import { createServerAuthClient } from "../../../lib/auth/server-client";

export async function POST(request: NextRequest): Promise<Response> {
  const configured = readRecoveryConfig(process.env);
  if (!configured.ok) return Response.json(
    { error: "Recovery is unavailable." },
    { status: 503, headers: { "cache-control": "private, no-store" } },
  );
  const supabase = await createServerAuthClient(configured.value);
  return sendOwnerRecovery(request, process.env, {
    signInWithOtp: (input) => supabase.auth.signInWithOtp(input),
  });
}
