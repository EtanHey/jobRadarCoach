import { createBrowserClient } from "@supabase/ssr";

export function createBrowserAuthClient(supabaseUrl: string, publishableKey: string) {
  return createBrowserClient(supabaseUrl, publishableKey, {
    auth: { experimental: { passkey: true } },
  });
}
