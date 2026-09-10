export const PASSKEY_ATTEMPT_TIMEOUT_MS = 60_000;

import type {
  AuthPasskeyAuthenticationOptionsResponse,
  VerifyPasskeyAuthenticationParams,
} from "@supabase/supabase-js";

type SuccessfulStart = Extract<AuthPasskeyAuthenticationOptionsResponse, { error: null }>;
type ServerRequestOptions = SuccessfulStart["data"]["options"];
export type SerializedPasskeyCredential = VerifyPasskeyAuthenticationParams["credential"];

export interface PasskeyAuthenticationClient {
  startAuthentication(): Promise<{
    data: SuccessfulStart["data"] | null;
    error: unknown;
  }>;
  verifyAuthentication(input: {
    challengeId: string;
    credential: SerializedPasskeyCredential;
  }): Promise<{ error: unknown }>;
}

export interface PasskeyCeremony {
  get(
    options: ServerRequestOptions,
    signal: AbortSignal,
  ): Promise<SerializedPasskeyCredential>;
}

export type PasskeyAttemptOutcome =
  | { kind: "success" }
  | { kind: "error"; error: unknown }
  | { kind: "cancelled" }
  | { kind: "timed_out" }
  | { kind: "verification_timed_out" };

type TimerHandle = ReturnType<typeof globalThis.setTimeout>;

export interface PasskeyAttempt {
  result: Promise<PasskeyAttemptOutcome>;
  cancel(): boolean;
}

interface PasskeyAttemptOptions {
  timeoutMs?: number;
  onCommit?: () => void;
  setTimer?: (callback: () => void, delay: number) => TimerHandle;
  clearTimer?: (handle: TimerHandle) => void;
}

function abortError() {
  return new DOMException("Passkey ceremony aborted", "AbortError");
}

/**
 * Use Supabase's two-step API so cancellation happens before the session-issuing
 * verification call. A late credential-provider completion can then be ignored
 * without creating a stale session.
 */
export async function authenticateWithPasskey(
  client: PasskeyAuthenticationClient,
  ceremony: PasskeyCeremony,
  signal: AbortSignal,
  commit: () => boolean,
): Promise<{ error: unknown }> {
  const started = await client.startAuthentication();
  if (signal.aborted) throw abortError();
  if (started.error) return { error: started.error };
  if (!started.data) return { error: new Error("Passkey challenge was unavailable") };

  const credential = await ceremony.get(started.data.options, signal);
  if (signal.aborted || !commit()) throw abortError();

  return client.verifyAuthentication({
    challengeId: started.data.challenge_id,
    credential,
  });
}

/**
 * Bound the challenge and credential-provider stages. Once commit succeeds,
 * verification may issue a session and is intentionally no longer cancellable.
 */
export function startPasskeyAttempt(
  signIn: (signal: AbortSignal, commit: () => boolean) => Promise<{ error: unknown }>,
  options: PasskeyAttemptOptions = {},
): PasskeyAttempt {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? PASSKEY_ATTEMPT_TIMEOUT_MS;
  const setTimer = options.setTimer ?? globalThis.setTimeout;
  const clearTimer = options.clearTimer ?? globalThis.clearTimeout;
  let committed = false;
  let finished = false;
  let resolveResult!: (outcome: PasskeyAttemptOutcome) => void;
  let verifyTimeout: TimerHandle | undefined;

  const result = new Promise<PasskeyAttemptOutcome>((resolve) => {
    resolveResult = resolve;
  });

  const finish = (outcome: PasskeyAttemptOutcome) => {
    if (finished) return;
    finished = true;
    clearTimer(timeout);
    if (verifyTimeout !== undefined) clearTimer(verifyTimeout);
    resolveResult(outcome);
  };

  const timeout = setTimer(() => {
    controller.abort();
    finish({ kind: "timed_out" });
  }, timeoutMs);

  const commit = () => {
    if (finished || controller.signal.aborted) return false;
    committed = true;
    clearTimer(timeout);
    verifyTimeout = setTimer(() => finish({ kind: "verification_timed_out" }), timeoutMs);
    options.onCommit?.();
    return true;
  };

  void Promise.resolve()
    .then(() => signIn(controller.signal, commit))
    .then(({ error }) => {
      if (error) finish({ kind: "error", error });
      else finish({ kind: "success" });
    })
    .catch((error: unknown) => finish({ kind: "error", error }));

  return {
    result,
    cancel() {
      if (finished || committed) return false;
      controller.abort();
      finish({ kind: "cancelled" });
      return true;
    },
  };
}

function requestOptionsFromJSON(
  options: ServerRequestOptions,
): PublicKeyCredentialRequestOptions {
  if (
    typeof PublicKeyCredential === "undefined" ||
    typeof PublicKeyCredential.parseRequestOptionsFromJSON !== "function"
  ) {
    throw new DOMException("Browser does not support WebAuthn", "NotSupportedError");
  }
  return PublicKeyCredential.parseRequestOptionsFromJSON(
    options as unknown as PublicKeyCredentialRequestOptionsJSON,
  );
}

export const browserPasskeyCeremony: PasskeyCeremony = {
  async get(options, signal) {
    if (typeof navigator === "undefined" || !navigator.credentials) {
      throw new DOMException("Browser does not support WebAuthn", "NotSupportedError");
    }
    const credential = await navigator.credentials.get({
      publicKey: requestOptionsFromJSON(options),
      signal,
    });
    const passkey = credential as PublicKeyCredential & {
      toJSON?: () => SerializedPasskeyCredential;
    };
    if (!(credential instanceof PublicKeyCredential) || typeof passkey.toJSON !== "function") {
      throw new Error("Browser returned an invalid passkey credential");
    }
    return passkey.toJSON();
  },
};
