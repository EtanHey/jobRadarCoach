export type MicPhase = "closed" | "opening" | "open" | "error";
export interface MicClientState {
  phase: MicPhase;
  ready: boolean;
  owner: string | null;
  revision: string | null;
  error: "claim_failed" | "ownership_lost" | "capture_failed" | "release_failed" | "stream_lost" | null;
}
export interface CaptureHandle { stop(): void }
export interface CaptureAdapter {
  enable(): Promise<CaptureHandle>;
  stop(): void;
}
export interface MicEventStream {
  addEventListener(name: string, listener: (event: MessageEvent) => void): void;
  close(): void;
}
export interface PageLifecycle {
  addEventListener(name: "pagehide", listener: () => void): void;
  removeEventListener(name: "pagehide", listener: () => void): void;
}
export interface MicClientDependencies {
  clientId: string;
  capture: CaptureAdapter;
  fetch?: (input: string, init: RequestInit) => Promise<{ ok: boolean; json(): Promise<unknown> }>;
  openEvents?: (url: string) => MicEventStream;
  page?: PageLifecycle;
}
interface MicState { client_id: string | null; revision: string; updated_at: string }
const MAX_BIGINT = "9223372036854775807";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ISO_OFFSET = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
function exactObject(value: unknown, keys: string[]): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}
function parseMic(value: unknown): MicState {
  if (!exactObject(value, ["client_id", "revision", "updated_at"])) throw new Error("invalid mic state");
  const client = value.client_id;
  const revision = value.revision;
  const updated = value.updated_at;
  if (client !== null && (typeof client !== "string" || !UUID.test(client))) throw new Error("invalid owner");
  if (typeof revision !== "string" || !/^(0|[1-9]\d*)$/.test(revision)
    || revision.length > MAX_BIGINT.length
    || (revision.length === MAX_BIGINT.length && revision > MAX_BIGINT)) throw new Error("invalid revision");
  if (typeof updated !== "string" || !ISO_OFFSET.test(updated) || Number.isNaN(Date.parse(updated))) {
    throw new Error("invalid timestamp");
  }
  return { client_id: client, revision, updated_at: updated };
}
function parseResponse(value: unknown): MicState {
  if (!exactObject(value, ["mic"])) throw new Error("invalid response");
  return parseMic(value.mic);
}
function compareRevision(left: string, right: string): number {
  if (left.length !== right.length) return left.length < right.length ? -1 : 1;
  return left === right ? 0 : left < right ? -1 : 1;
}
export function createMicClient(dependencies: MicClientDependencies) {
  if (!UUID.test(dependencies.clientId)) throw new Error("clientId must be a UUID");
  const request = dependencies.fetch ?? ((input, init) => fetch(input, init));
  const openEvents = dependencies.openEvents ?? ((url) => new EventSource(url) as unknown as MicEventStream);
  const page = dependencies.page ?? (typeof window === "undefined" ? undefined : window);
  const listeners = new Set<(state: MicClientState) => void>();
  let state: MicClientState = { phase: "closed", ready: false, owner: null, revision: null, error: null };
  let desiredOpen = false;
  let generation = 0;
  let enablingFor: number | null = null;
  let active: CaptureHandle | null = null;
  let disposed = false;
  const publish = (patch: Partial<MicClientState>) => {
    state = { ...state, ...patch };
    for (const listener of listeners) listener({ ...state });
  };
  const stopCapture = () => {
    active?.stop();
    active = null;
    dependencies.capture.stop();
  };
  const post = async (action: "claim" | "release", keepalive = false): Promise<MicState> => {
    const response = await request("/api/livekit/mic", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action, client_id: dependencies.clientId }),
      keepalive,
    });
    if (!response.ok) throw new Error("mic request failed");
    return parseResponse(await response.json());
  };
  const applyOwnership = (next: MicState) => {
    if (state.revision !== null && compareRevision(next.revision, state.revision) <= 0) return false;
    if (next.client_id !== dependencies.clientId && desiredOpen) {
      generation += 1;
      desiredOpen = false;
      enablingFor = null;
      stopCapture();
      publish({ owner: next.client_id, revision: next.revision, phase: "error", error: "ownership_lost" });
    } else publish({ owner: next.client_id, revision: next.revision });
    return true;
  };
  const bestEffortRelease = (keepalive = false) => { void post("release", keepalive).catch(() => undefined); };
  const failClosed = (error: NonNullable<MicClientState["error"]>, release = false, ready = state.ready) => {
    generation += 1;
    desiredOpen = false;
    enablingFor = null;
    stopCapture();
    publish({ phase: "error", error, ready });
    if (release) bestEffortRelease();
  };
  const maybeEnable = () => {
    const attempt = generation;
    if (disposed || !desiredOpen || !state.ready || state.owner !== dependencies.clientId
      || enablingFor === attempt || state.phase === "open") return;
    enablingFor = attempt;
    void dependencies.capture.enable().then((handle) => {
      if (disposed || attempt !== generation || !desiredOpen || !state.ready
        || state.owner !== dependencies.clientId) {
        handle.stop();
        return;
      }
      active = handle;
      enablingFor = null;
      publish({ phase: "open", error: null });
    }).catch(() => {
      if (attempt === generation && desiredOpen) failClosed("capture_failed", true);
    });
  };
  const streamLost = () => { if (!disposed) failClosed("stream_lost", false, false); };
  const events = openEvents("/api/livekit/events");
  events.addEventListener("ownership", (event) => {
    if (disposed) return;
    try {
      applyOwnership(parseMic(JSON.parse(event.data)));
      maybeEnable();
    } catch { streamLost(); }
  });
  events.addEventListener("ready", (event) => {
    if (disposed) return;
    try {
      if (!exactObject(JSON.parse(event.data), [])) throw new Error("invalid ready event");
      publish({ ready: true, phase: desiredOpen ? state.phase : "closed", error: null });
      maybeEnable();
    } catch { streamLost(); }
  });
  events.addEventListener("error", streamLost);
  const close = async (): Promise<MicClientState> => {
    if (disposed) return { ...state };
    const attempt = ++generation;
    desiredOpen = false;
    enablingFor = null;
    stopCapture();
    publish({ phase: "closed", error: null });
    try {
      const released = await post("release");
      if (!disposed) applyOwnership(released);
    }
    catch {
      if (attempt === generation && !desiredOpen) publish({ phase: "error", error: "release_failed" });
    }
    return { ...state };
  };
  const open = async (): Promise<MicClientState> => {
    if (disposed) return { ...state };
    const attempt = ++generation;
    desiredOpen = true;
    publish({ phase: "opening", error: null });
    try {
      const claimed = await post("claim");
      if (disposed) {
        if (claimed.client_id === dependencies.clientId) bestEffortRelease(true);
        return { ...state };
      }
      applyOwnership(claimed);
      if (disposed || attempt !== generation || !desiredOpen) {
        if (claimed.client_id === dependencies.clientId && !desiredOpen) bestEffortRelease();
      } else if (state.owner !== dependencies.clientId) {
        failClosed("claim_failed", true);
      } else maybeEnable();
    } catch {
      if (attempt === generation && desiredOpen) failClosed("claim_failed", true);
    }
    return { ...state };
  };
  const onPageHide = () => dispose();
  page?.addEventListener("pagehide", onPageHide);
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    generation += 1;
    desiredOpen = false;
    enablingFor = null;
    stopCapture();
    events.close();
    page?.removeEventListener("pagehide", onPageHide);
    bestEffortRelease(true);
    publish({ phase: "closed", ready: false, error: null });
    listeners.clear();
  };

  return {
    tap: () => desiredOpen || state.phase === "open" || state.phase === "opening" ? close() : open(),
    close,
    suspend: close,
    dispose,
    getState: () => ({ ...state }),
    subscribe(listener: (state: MicClientState) => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
