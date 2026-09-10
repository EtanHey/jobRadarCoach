import { createBrowserClient } from "@supabase/ssr";

type ErrorLike = {
  cause?: unknown;
  code?: unknown;
  message?: unknown;
  name?: unknown;
  status?: unknown;
};

function errorLike(error: unknown): ErrorLike {
  return typeof error === "object" && error !== null ? error : {};
}

function errorText(value: unknown): string {
  return typeof value === "string" ? value.toLowerCase() : "";
}

export function passkeySignInMessage(error: unknown): string {
  const details = errorLike(error);
  const cause = errorLike(details.cause);
  const code = errorText(details.code);
  const name = errorText(details.name);
  const causeName = errorText(cause.name);
  const message = errorText(details.message);

  if (
    code === "error_invalid_domain" ||
    code === "error_invalid_rp_id" ||
    code === "passkey_disabled" ||
    (message.includes("passkey") && (message.includes("disabled") || message.includes("not enabled"))) ||
    details.status === 404
  ) {
    return "Passkey sign-in is not configured for this site yet.";
  }

  if (
    code.includes("passkey") &&
    (code.includes("not_found") || code.includes("no_credential"))
  ) {
    return "No passkey is enrolled for this workspace. Use the setup or recovery option.";
  }

  if (
    code === "error_ceremony_aborted" ||
    name === "aborterror" ||
    causeName === "aborterror"
  ) {
    return "Passkey prompt was cancelled.";
  }

  if (
    name === "notallowederror" ||
    causeName === "notallowederror"
  ) {
    return "No passkey was selected. The prompt may have been cancelled, or no passkey is registered for this site.";
  }

  if (message.includes("browser does not support webauthn") || name === "notsupportederror") {
    return "This browser does not support passkey sign-in.";
  }

  if (
    name === "authretryablefetcherror" ||
    (typeof details.status === "number" && details.status >= 500)
  ) {
    return "The passkey service is unavailable for this site.";
  }

  return "Passkey sign-in failed. Use setup or recovery if this passkey has not been enrolled.";
}

export function createBrowserAuthClient(supabaseUrl: string, publishableKey: string) {
  return createBrowserClient(supabaseUrl, publishableKey, {
    auth: { experimental: { passkey: true } },
  });
}
