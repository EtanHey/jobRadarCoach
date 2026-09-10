import assert from "node:assert/strict";
import { test } from "node:test";

import { createBrowserAuthClient, passkeySignInMessage } from "../lib/auth/browser-client";

test("the pinned Supabase client exposes the opted-in passkey ceremonies", () => {
  const client = createBrowserAuthClient(
    "https://project.supabase.co",
    "sb_publishable_test",
  );
  assert.equal(typeof client.auth.signInWithPasskey, "function");
  assert.equal(typeof client.auth.registerPasskey, "function");
  assert.equal(typeof client.auth.passkey.list, "function");
});

test("passkey errors distinguish configuration, enrollment, cancellation, and availability", () => {
  assert.equal(
    passkeySignInMessage({ code: "ERROR_INVALID_RP_ID" }),
    "Passkey sign-in is not configured for this site yet.",
  );
  assert.equal(
    passkeySignInMessage({ code: "passkey_not_found" }),
    "No passkey is enrolled for this workspace. Use the setup or recovery option.",
  );
  assert.equal(
    passkeySignInMessage({ code: "ERROR_CEREMONY_ABORTED" }),
    "Passkey prompt was cancelled.",
  );
  assert.equal(
    passkeySignInMessage({
      code: "ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY",
      cause: { name: "NotAllowedError" },
    }),
    "No passkey was selected. The prompt may have been cancelled, or no passkey is registered for this site.",
  );
  assert.equal(
    passkeySignInMessage({ name: "AuthRetryableFetchError" }),
    "The passkey service is unavailable for this site.",
  );
});
