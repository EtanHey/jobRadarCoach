export interface OwnerAuthConfig {
  supabaseUrl: string;
  publishableKey: string;
  ownerUserIds: ReadonlySet<string>;
}

export type OwnerIdentityResult =
  | { kind: "authenticated"; userId: string }
  | { kind: "unauthenticated" };

export type OwnerIdentityVerifier = (
  config: OwnerAuthConfig,
) => Promise<OwnerIdentityResult>;
export type OwnerAccessDecision =
  | { kind: "allow" }
  | { kind: "deny"; response: Response };

const publicPaths = new Set(["/login", "/auth/callback", "/auth/recovery"]);
const publicPrefixes = ["/_next/static/", "/companies/", "/tech/"];
const publicAssets = new Set(["/_next/image", "/favicon.ico", "/icon.svg"]);
const userIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export function classifyAuthPath(pathname: string): "public" | "private" {
  if (publicPaths.has(pathname) || publicAssets.has(pathname)) return "public";
  return publicPrefixes.some((prefix) => pathname.startsWith(prefix)) ? "public" : "private";
}

export function readOwnerAuthConfig(
  environment: Record<string, string | undefined>,
): { ok: true; value: OwnerAuthConfig } | { ok: false } {
  const url = environment.NEXT_PUBLIC_SUPABASE_URL;
  const publishableKey = environment.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  const ownerUserIds = (environment.JRC_OWNER_USER_IDS ?? "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);

  try {
    if (!url || new URL(url).protocol !== "https:" || !publishableKey || ownerUserIds.length === 0) {
      return { ok: false };
    }
  } catch {
    return { ok: false };
  }
  if (ownerUserIds.some((value) => !userIdPattern.test(value))) return { ok: false };
  return {
    ok: true,
    value: { supabaseUrl: url, publishableKey, ownerUserIds: new Set(ownerUserIds) },
  };
}

function privateResponse(status: number, error: string): Response {
  return Response.json(
    { error },
    { status, headers: { "cache-control": "private, no-store" } },
  );
}
export async function authorizeOwnerRequest(
  request: Request,
  environment: Record<string, string | undefined>,
  verifyIdentity: OwnerIdentityVerifier,
): Promise<OwnerAccessDecision> {
  const url = new URL(request.url);
  if (classifyAuthPath(url.pathname) === "public") return { kind: "allow" };

  const configured = readOwnerAuthConfig(environment);
  if (!configured.ok) {
    return { kind: "deny", response: privateResponse(503, "Authentication is unavailable.") };
  }
  const identity = await verifyIdentity(configured.value);
  if (identity.kind === "unauthenticated") {
    if (url.pathname.startsWith("/api/")) {
      return { kind: "deny", response: privateResponse(401, "Authentication required.") };
    }
    const login = new URL("/login", url.origin);
    login.searchParams.set("next", `${url.pathname}${url.search}`);
    const response = new Response(null, {
      status: 307,
      headers: {
        location: login.toString(),
        "cache-control": "private, no-store",
      },
    });
    return {
      kind: "deny",
      response,
    };
  }
  if (!configured.value.ownerUserIds.has(identity.userId.toLowerCase())) {
    return { kind: "deny", response: privateResponse(403, "Owner access required.") };
  }
  return { kind: "allow" };
}
