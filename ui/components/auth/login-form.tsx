"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { createBrowserAuthClient, passkeySignInMessage } from "../../lib/auth/browser-client";
import {
  authenticateWithPasskey,
  browserPasskeyCeremony,
  startPasskeyAttempt,
  type PasskeyAuthenticationClient,
  type PasskeyCeremony,
  type PasskeyAttempt,
} from "../../lib/auth/passkey-attempt";

interface Props {
  supabaseUrl: string;
  publishableKey: string;
  nextPath: string;
  recoveryEnabled: boolean;
  passkeyClient?: PasskeyAuthenticationClient;
  passkeyCeremony?: PasskeyCeremony;
}

export function LoginForm({
  supabaseUrl,
  publishableKey,
  nextPath,
  recoveryEnabled,
  passkeyClient,
  passkeyCeremony = browserPasskeyCeremony,
}: Props) {
  const supabase = useMemo(
    () => passkeyClient ? null : createBrowserAuthClient(supabaseUrl, publishableKey),
    [passkeyClient, supabaseUrl, publishableKey],
  );
  const authentication = passkeyClient ?? supabase!.auth.passkey;
  const [pending, setPending] = useState<"passkey" | "verifying" | "recovery" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const passkeyAttempt = useRef<PasskeyAttempt | null>(null);

  useEffect(() => () => {
    const attempt = passkeyAttempt.current;
    passkeyAttempt.current = null;
    attempt?.cancel();
  }, []);

  async function signInWithPasskey() {
    if (passkeyAttempt.current) return;
    setPending("passkey");
    setMessage(null);
    const attempt = startPasskeyAttempt(
      (signal, commit) => authenticateWithPasskey(
        authentication,
        passkeyCeremony,
        signal,
        () => passkeyAttempt.current === attempt && commit(),
      ),
      {
        onCommit: () => {
          if (passkeyAttempt.current === attempt) setPending("verifying");
        },
      },
    );
    passkeyAttempt.current = attempt;
    const outcome = await attempt.result;

    // A cancelled attempt may still complete inside a credential provider.
    // Only the current attempt may change UI state or navigate.
    if (passkeyAttempt.current !== attempt) return;
    passkeyAttempt.current = null;

    if (outcome.kind === "verification_timed_out") {
      // Verification is the session-issuing commit point and cannot be safely
      // cancelled. Navigate so the server resolves whether a session landed.
      window.location.replace(nextPath);
      return;
    }
    setPending(null);

    if (outcome.kind === "success") {
      window.location.replace(nextPath);
    } else if (outcome.kind === "error") {
      setMessage(passkeySignInMessage(outcome.error));
    } else if (outcome.kind === "timed_out") {
      setMessage(recoveryEnabled
        ? "Passkey prompt timed out. Try again or use setup or recovery."
        : "Passkey prompt timed out. Try again.");
    } else {
      setMessage(recoveryEnabled
        ? "Passkey sign-in cancelled. You can try again or use setup or recovery."
        : "Passkey sign-in cancelled. You can try again.");
    }
  }

  function cancelPasskey() {
    const attempt = passkeyAttempt.current;
    if (!attempt) return;
    if (!attempt.cancel()) return;
    passkeyAttempt.current = null;
    setPending(null);
    setMessage(recoveryEnabled
      ? "Passkey sign-in cancelled. You can try again or use setup or recovery."
      : "Passkey sign-in cancelled. You can try again.");
  }

  async function sendRecovery() {
    const attempt = passkeyAttempt.current;
    if (attempt && !attempt.cancel()) {
      setMessage("Passkey sign-in is finishing. Wait for it to complete.");
      return;
    }
    passkeyAttempt.current = null;
    setPending("recovery");
    setMessage(null);
    try {
      const response = await fetch("/auth/recovery", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ next: nextPath }),
      });
      if (!response.ok) throw new Error("recovery failed");
      setMessage("Recovery link sent to the configured owner inbox.");
    } catch {
      setMessage("Recovery is unavailable. Ask the operator to enable it for setup or recovery.");
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm leading-6 text-muted-foreground">
        Use the private passkey registered for this workspace.
      </p>
      <button
        type="button"
        onClick={signInWithPasskey}
        disabled={pending !== null}
        className="h-10 w-full rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/85 disabled:opacity-50"
      >
        {pending === "passkey"
          ? "Waiting for passkey…"
          : pending === "verifying"
            ? "Finishing sign-in…"
            : "Sign in with passkey"}
      </button>
      {pending === "passkey" ? (
        <button
          type="button"
          onClick={cancelPasskey}
          className="h-9 w-full rounded-lg border bg-background px-4 text-sm font-medium hover:bg-muted"
        >
          Cancel passkey prompt
        </button>
      ) : null}
      {recoveryEnabled ? (
        <button
          type="button"
          onClick={sendRecovery}
          disabled={pending === "recovery" || pending === "verifying"}
          className="h-9 w-full rounded-lg border bg-background px-4 text-sm font-medium hover:bg-muted disabled:opacity-50"
        >
          {pending === "recovery" ? "Sending…" : "Send setup or recovery link"}
        </button>
      ) : null}
      {message ? <p role="status" className="text-sm leading-5 text-muted-foreground">{message}</p> : null}
    </div>
  );
}
