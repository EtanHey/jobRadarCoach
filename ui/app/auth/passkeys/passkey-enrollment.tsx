"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { createBrowserAuthClient } from "../../../lib/auth/browser-client";

export function PasskeyEnrollment({
  supabaseUrl,
  publishableKey,
}: {
  supabaseUrl: string;
  publishableKey: string;
}) {
  const supabase = useMemo(
    () => createBrowserAuthClient(supabaseUrl, publishableKey),
    [supabaseUrl, publishableKey],
  );
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function register() {
    setPending(true);
    setMessage(null);
    try {
      const { error } = await supabase.auth.registerPasskey();
      if (error) throw error;
      setMessage("Passkey registered. You can now use it from the private sign-in page.");
    } catch {
      setMessage("Passkey registration did not complete. Check the production origin and try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm leading-6 text-muted-foreground">
        When the browser asks where to save this passkey, choose 1Password. Enrollment is available only to the authenticated owner.
      </p>
      <button
        type="button"
        onClick={register}
        disabled={pending}
        className="h-10 w-full rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/85 disabled:opacity-50"
      >
        {pending ? "Waiting for 1Password…" : "Create passkey"}
      </button>
      {message ? <p role="status" className="text-sm leading-5 text-muted-foreground">{message}</p> : null}
      <Link href="/" className="inline-block text-sm font-medium text-primary underline-offset-4 hover:underline">
        Return to dashboard
      </Link>
    </div>
  );
}
