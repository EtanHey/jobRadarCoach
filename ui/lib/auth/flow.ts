import { z } from "zod";

import { HttpError, json, mutationJson, safely } from "../http";
import { readOwnerAuthConfig, type OwnerAuthConfig } from "./boundary";

export interface RecoveryAuthClient {
  signInWithOtp(input: {
    email: string;
    options: { shouldCreateUser: false; emailRedirectTo: string };
  }): Promise<{ error: unknown }>;
}

export interface CallbackAuthClient {
  exchangeCodeForSession(code: string): Promise<{ error: unknown }>;
  getClaims(): Promise<{
    data: { claims?: { sub?: unknown } } | null;
    error: unknown;
  }>;
  signOut(options: { scope: "local" }): Promise<{ error: unknown }>;
}

interface RecoveryConfig extends OwnerAuthConfig {
  ownerEmail: string;
  uiOrigin: string;
}

function readCallbackConfig(
  environment: Record<string, string | undefined>,
): { ok: true; value: OwnerAuthConfig & { uiOrigin: string } } | { ok: false } {
  const auth = readOwnerAuthConfig(environment);
  const uiOrigin = environment.UI_ORIGIN;
  try {
    if (!auth.ok || !uiOrigin || new URL(uiOrigin).protocol !== "https:" || new URL(uiOrigin).origin !== uiOrigin) {
      return { ok: false };
    }
  } catch {
    return { ok: false };
  }
  return { ok: true, value: { ...auth.value, uiOrigin } };
}

const recoveryInput = z.object({ next: z.string().optional() }).strict();
const emailPattern = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function safeNextPath(value: string | null | undefined): string {
  if (!value?.startsWith("/") || value.startsWith("//") || value.includes("\\")) return "/";
  try {
    const origin = "https://internal.invalid";
    const parsed = new URL(value, origin);
    return parsed.origin === origin ? `${parsed.pathname}${parsed.search}${parsed.hash}` : "/";
  } catch {
    return "/";
  }
}

export function readRecoveryConfig(
  environment: Record<string, string | undefined>,
): { ok: true; value: RecoveryConfig } | { ok: false } {
  const auth = readOwnerAuthConfig(environment);
  const ownerEmail = environment.JRC_OWNER_RECOVERY_EMAIL?.trim();
  const uiOrigin = environment.UI_ORIGIN;
  try {
    if (
      !auth.ok
      || environment.JRC_OWNER_RECOVERY_ENABLED !== "true"
      || !ownerEmail
      || !emailPattern.test(ownerEmail)
      || !uiOrigin
      || new URL(uiOrigin).protocol !== "https:"
      || new URL(uiOrigin).origin !== uiOrigin
    ) return { ok: false };
  } catch {
    return { ok: false };
  }
  return { ok: true, value: { ...auth.value, ownerEmail, uiOrigin } };
}

export async function sendOwnerRecovery(
  request: Request,
  environment: Record<string, string | undefined>,
  client: RecoveryAuthClient,
): Promise<Response> {
  return safely(async () => {
    const configured = readRecoveryConfig(environment);
    if (!configured.ok) throw new HttpError(503, "Recovery is unavailable.");
    if (!request.headers.get("origin")) throw new HttpError(403, "Same-origin request required.");
    const input = await mutationJson(request, recoveryInput);
    const callback = new URL("/auth/callback", configured.value.uiOrigin);
    callback.searchParams.set("next", safeNextPath(input.next));
    const { error } = await client.signInWithOtp({
      email: configured.value.ownerEmail,
      options: { shouldCreateUser: false, emailRedirectTo: callback.toString() },
    });
    if (error) throw new HttpError(503, "Recovery could not be started.");
    return json({ sent: true }, 202);
  });
}

function redirect(origin: string, path: string, error?: string): Response {
  const destination = new URL(path, origin);
  if (error) destination.searchParams.set("error", error);
  return new Response(null, {
    status: 303,
    headers: { location: destination.toString(), "cache-control": "private, no-store" },
  });
}

export async function handleAuthCallback(
  request: Request,
  environment: Record<string, string | undefined>,
  client: CallbackAuthClient,
): Promise<Response> {
  const url = new URL(request.url);
  const configured = readCallbackConfig(environment);
  if (!configured.ok) return json({ error: "Authentication is unavailable." }, 503);
  const code = url.searchParams.get("code");
  if (!code) return redirect(configured.value.uiOrigin, "/login", "invalid_callback");
  const exchange = await client.exchangeCodeForSession(code);
  if (exchange.error) return redirect(configured.value.uiOrigin, "/login", "invalid_callback");
  const { data, error } = await client.getClaims();
  const userId = typeof data?.claims?.sub === "string" ? data.claims.sub.toLowerCase() : null;
  if (error || !userId || !configured.value.ownerUserIds.has(userId)) {
    await client.signOut({ scope: "local" });
    return redirect(configured.value.uiOrigin, "/login", "owner_required");
  }
  return redirect(configured.value.uiOrigin, safeNextPath(url.searchParams.get("next")));
}
