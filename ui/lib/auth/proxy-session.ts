import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

import type { OwnerAuthConfig, OwnerIdentityResult } from "./boundary";

interface PendingCookie { name: string; value: string; options: CookieOptions }
interface ClaimsClientOptions {
  cookies: {
    getAll(): { name: string; value: string }[];
    setAll(cookies: PendingCookie[], headers: Record<string, string>): void;
  };
}
interface ClaimsClient {
  auth: {
    getClaims(): Promise<{
      data: { claims?: { sub?: unknown } } | null;
      error: unknown;
    }>;
  };
}
export type ClaimsClientFactory = (
  url: string,
  key: string,
  options: ClaimsClientOptions,
) => ClaimsClient;
const defaultClaimsClientFactory: ClaimsClientFactory = (url, key, options) =>
  createServerClient(url, key, options) as unknown as ClaimsClient;

export async function verifySupabaseIdentity(
  request: NextRequest,
  config: OwnerAuthConfig,
  createClaimsClient: ClaimsClientFactory = defaultClaimsClientFactory,
): Promise<{
  identity: OwnerIdentityResult;
  response(result?: Response): NextResponse;
}> {
  const pendingCookies = new Map<string, PendingCookie>();
  const pendingHeaders = new Headers();
  const supabase = createClaimsClient(config.supabaseUrl, config.publishableKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll(cookies, headers) {
        for (const cookie of cookies) {
          request.cookies.set(cookie.name, cookie.value);
          pendingCookies.set(cookie.name, cookie);
        }
        for (const [name, value] of Object.entries(headers)) pendingHeaders.set(name, value);
      },
    },
  });
  let identity: OwnerIdentityResult = { kind: "unauthenticated" };
  try {
    const { data, error } = await supabase.auth.getClaims();
    const userId = typeof data?.claims?.sub === "string" ? data.claims.sub : null;
    if (!error && userId) identity = { kind: "authenticated", userId };
  } catch {
    // Auth transport failures remain unauthenticated and fail closed at the gate.
  }
  return {
    identity,
    response(result) {
      const response = result
        ? new NextResponse(result.body, {
          status: result.status,
          statusText: result.statusText,
          headers: result.headers,
        })
        : NextResponse.next({ request });
      for (const cookie of pendingCookies.values()) {
        response.cookies.set(cookie.name, cookie.value, cookie.options);
      }
      pendingHeaders.forEach((value, name) => response.headers.set(name, value));
      if (!response.headers.has("cache-control")) {
        response.headers.set("cache-control", "private, no-store");
      }
      return response;
    },
  };
}
