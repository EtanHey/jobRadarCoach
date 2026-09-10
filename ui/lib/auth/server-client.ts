import "server-only";

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

import type { OwnerAuthConfig } from "./boundary";

export async function createServerAuthClient(config: OwnerAuthConfig) {
  const cookieStore = await cookies();
  return createServerClient(config.supabaseUrl, config.publishableKey, {
    auth: { experimental: { passkey: true } },
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll(values) {
        for (const { name, value, options } of values) cookieStore.set(name, value, options);
      },
    },
  });
}
