"use client";

import { useMemo, useState } from "react";

import { createBrowserAuthClient, passkeySignInMessage } from "../../lib/auth/browser-client";

interface Props {
  supabaseUrl: string;
  publishableKey: string;
  nextPath: string;
  recoveryEnabled: boolean;
}

export function LoginForm({ supabaseUrl, publishableKey, nextPath, recoveryEnabled }: Props) {
  const supabase = useMemo(
    () => createBrowserAuthClient(supabaseUrl, publishableKey),
    [supabaseUrl, publishableKey],
  );
  const [pending, setPending] = useState<"passkey" | "recovery" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function signInWithPasskey() {
    setPending("passkey");
    setMessage(null);
    try {
      const { error } = await supabase.auth.signInWithPasskey();
      if (error) throw error;
      window.location.replace(nextPath);
    } catch (error) {
      setMessage(passkeySignInMessage(error));
      setPending(null);
    }
  }

  async function sendRecovery() {
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
        {pending === "passkey" ? "Waiting for passkey…" : "Sign in with passkey"}
      </button>
      {recoveryEnabled ? (
        <button
          type="button"
          onClick={sendRecovery}
          disabled={pending !== null}
          className="h-9 w-full rounded-lg border bg-background px-4 text-sm font-medium hover:bg-muted disabled:opacity-50"
        >
          {pending === "recovery" ? "Sending…" : "Send setup or recovery link"}
        </button>
      ) : null}
      {message ? <p role="status" className="text-sm leading-5 text-muted-foreground">{message}</p> : null}
    </div>
  );
}
