import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import { LoginForm } from "../components/auth/login-form";
import type {
  PasskeyAuthenticationClient,
  PasskeyCeremony,
  SerializedPasskeyCredential,
} from "../lib/auth/passkey-attempt";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function button(container: HTMLElement, label: string) {
  return [...container.querySelectorAll("button")].find((candidate) => (
    candidate.textContent === label
  ));
}

test("cancel releases passkey and recovery controls while a late credential cannot verify", async () => {
  const dom = new JSDOM("<div id='root'></div>", { url: "https://jobs.example.com/login" });
  Object.defineProperties(globalThis, {
    document: { configurable: true, value: dom.window.document },
    HTMLElement: { configurable: true, value: dom.window.HTMLElement },
    navigator: { configurable: true, value: dom.window.navigator },
    window: { configurable: true, value: dom.window },
  });
  const container = dom.window.document.querySelector<HTMLElement>("#root");
  assert.ok(container);

  const provider = deferred<SerializedPasskeyCredential>();
  let verifyCalls = 0;
  const client: PasskeyAuthenticationClient = {
    async startAuthentication() {
      return {
        data: {
          challenge_id: "challenge-id",
          expires_at: 1,
          options: { challenge: "Y2hhbGxlbmdl" },
        },
        error: null,
      };
    },
    async verifyAuthentication() {
      verifyCalls += 1;
      return { error: null };
    },
  };
  const ceremony: PasskeyCeremony = { get: () => provider.promise };
  const root = createRoot(container);

  await act(async () => {
    root.render(React.createElement(LoginForm, {
      supabaseUrl: "https://project.supabase.co",
      publishableKey: "sb_publishable_test",
      nextPath: "/",
      recoveryEnabled: true,
      passkeyClient: client,
      passkeyCeremony: ceremony,
    }));
  });
  await act(async () => {
    button(container, "Sign in with passkey")?.click();
    await Promise.resolve();
  });

  assert.equal(button(container, "Waiting for passkey…")?.disabled, true);
  assert.equal(button(container, "Send setup or recovery link")?.disabled, false);
  assert.ok(button(container, "Cancel passkey prompt"));

  await act(async () => { button(container, "Cancel passkey prompt")?.click(); });

  assert.equal(button(container, "Sign in with passkey")?.disabled, false);
  assert.equal(button(container, "Send setup or recovery link")?.disabled, false);
  assert.match(container.querySelector("[role=status]")?.textContent ?? "", /cancelled/i);

  provider.resolve({
    id: "credential",
    rawId: "credential",
    response: {
      authenticatorData: "authenticator-data",
      clientDataJSON: "client-data",
      signature: "signature",
    },
    clientExtensionResults: {},
    type: "public-key",
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

  assert.equal(verifyCalls, 0);
  assert.equal(button(container, "Sign in with passkey")?.disabled, false);
  assert.equal(button(container, "Send setup or recovery link")?.disabled, false);
  await act(async () => { root.unmount(); });
  dom.window.close();
});
