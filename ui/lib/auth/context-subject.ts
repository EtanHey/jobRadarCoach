import "server-only";

import { type NextRequest, NextResponse } from "next/server";

import { readOwnerAuthConfig } from "./boundary";
import {
  verifySupabaseIdentity,
  type ClaimsClientFactory,
} from "./proxy-session";

export const CONTEXT_NAMESPACE = "jobradarcoach.formatting.v1" as const;

export interface AuthenticatedContextScope {
  readonly namespace: typeof CONTEXT_NAMESPACE;
  readonly subject: string;
}

type AuthResponseWrapper = Awaited<
  ReturnType<typeof verifySupabaseIdentity>
>["response"];

export type ContextSubjectResolution =
  | {
    kind: "allow";
    scope: AuthenticatedContextScope;
    response: AuthResponseWrapper;
  }
  | {
    kind: "deny";
    response: NextResponse;
  };

function denied(status: number, error: string): Response {
  return Response.json(
    { error },
    { status, headers: { "cache-control": "private, no-store" } },
  );
}

/**
 * Resolve an authenticated server context scope from fresh Supabase claims.
 * Context scope is an authorization result here; callers cannot select it.
 */
export async function resolveContextSubject(
  request: NextRequest,
  environment: Record<string, string | undefined> = process.env,
  createClaimsClient?: ClaimsClientFactory,
): Promise<ContextSubjectResolution> {
  const configured = readOwnerAuthConfig(environment);
  if (!configured.ok) {
    return {
      kind: "deny",
      response: NextResponse.json(
        { error: "Authentication is unavailable." },
        { status: 503, headers: { "cache-control": "private, no-store" } },
      ),
    };
  }

  const session = await verifySupabaseIdentity(
    request,
    configured.value,
    createClaimsClient,
  );
  if (session.identity.kind === "unauthenticated") {
    return {
      kind: "deny",
      response: session.response(denied(401, "Authentication required.")),
    };
  }

  const subject = session.identity.userId.toLowerCase();
  if (!configured.value.ownerUserIds.has(subject)) {
    return {
      kind: "deny",
      response: session.response(denied(403, "Owner access required.")),
    };
  }

  return {
    kind: "allow",
    scope: { namespace: CONTEXT_NAMESPACE, subject },
    response: session.response,
  };
}
