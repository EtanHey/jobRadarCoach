import assert from "node:assert/strict";
import { test } from "node:test";

import { createBrowserAuthClient } from "../lib/auth/browser-client";

test("the pinned Supabase client exposes the opted-in passkey ceremonies", () => {
  const client = createBrowserAuthClient(
    "https://project.supabase.co",
    "sb_publishable_test",
  );
  assert.equal(typeof client.auth.signInWithPasskey, "function");
  assert.equal(typeof client.auth.registerPasskey, "function");
  assert.equal(typeof client.auth.passkey.list, "function");
});
