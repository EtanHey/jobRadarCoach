import "server-only";

import {
  compareRevisions, createMicStore, getVoiceDatabase, parseMicRow, type MicState,
} from "../../../../lib/voice/mic-server";

const encoder = new TextEncoder();
type StreamStatus = "SUBSCRIBED" | "CHANNEL_ERROR" | "TIMED_OUT" | "CLOSED" | string;

export interface MicEventSubscription { close(): void | Promise<void> }
export interface MicEventDependencies {
  snapshot(): Promise<MicState>;
  subscribe(onRow: (row: unknown) => void, onStatus: (status: StreamStatus) => void): MicEventSubscription;
  scheduleHeartbeat?(run: () => void, milliseconds: number): unknown;
  clearHeartbeat?(token: unknown): void;
}

export async function closeOwnedRealtimeClient(
  db: Pick<ReturnType<typeof getVoiceDatabase>, "removeAllChannels">,
): Promise<void> {
  await db.removeAllChannels();
}

function frame(name: "ready" | "ownership" | "error", data: unknown): Uint8Array {
  return encoder.encode(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
}

function defaultDependencies(): MicEventDependencies {
  const db = getVoiceDatabase();
  const store = createMicStore((name, args) => db.rpc(name, args));
  return {
    snapshot: () => store.getCurrent(),
    subscribe(onRow, onStatus) {
      const channel = db.channel(`job-radar-mic-${crypto.randomUUID()}`, {
        config: { postgres_changes_options: { wait: true } },
      });
      channel.on(
        "postgres_changes",
        { event: "*", schema: "public", table: "active_mic" },
        (payload) => onRow(payload.new),
      );
      channel.subscribe(onStatus);
      return { close: () => closeOwnedRealtimeClient(db) };
    },
  };
}

export function makeGetMicEvents(dependencies: MicEventDependencies) {
  return (request: Request): Response => {
    let release: () => void = () => {};
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        let finished = false;
        let initializing = false;
        let latestRevision: string | null = null;
        let subscription: MicEventSubscription | null = null;
        let closePending = false;
        const schedule = dependencies.scheduleHeartbeat ?? ((run, milliseconds) => setInterval(run, milliseconds));
        const clear = dependencies.clearHeartbeat ?? ((token) => clearInterval(token as ReturnType<typeof setInterval>));
        const heartbeat = schedule(() => {
          if (!finished) controller.enqueue(encoder.encode(": heartbeat\n\n"));
        }, 15_000);

        const closeSubscription = () => {
          if (subscription) void Promise.resolve(subscription.close()).catch(() => undefined);
          else closePending = true;
        };
        const finish = (closeStream: boolean) => {
          if (finished) return;
          finished = true;
          clear(heartbeat);
          request.signal.removeEventListener("abort", abort);
          closeSubscription();
          if (closeStream) controller.close();
        };
        const fail = () => {
          if (finished) return;
          controller.enqueue(frame("error", { code: "stream_lost" }));
          finish(true);
        };
        const merge = (value: unknown) => {
          const state = parseMicRow(value);
          if (latestRevision === null || compareRevisions(state.revision, latestRevision) > 0) {
            latestRevision = state.revision;
            controller.enqueue(frame("ownership", state));
          }
        };
        const initialize = async () => {
          if (initializing || finished) return;
          initializing = true;
          try {
            const snapshot = await dependencies.snapshot();
            if (finished) return;
            merge({ singleton: true, ...snapshot });
            if (!finished) controller.enqueue(frame("ready", {}));
          } catch { fail(); }
        };
        const abort = () => finish(true);
        request.signal.addEventListener("abort", abort, { once: true });
        if (request.signal.aborted) {
          finish(true);
          return;
        }
        try {
          subscription = dependencies.subscribe(
            (row) => { if (!finished) { try { merge(row); } catch { fail(); } } },
            (status) => {
              if (status === "SUBSCRIBED") void initialize();
              else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT" || status === "CLOSED") fail();
            },
          );
        } catch { fail(); }
        if (closePending) closeSubscription();
        release = () => finish(false);
      },
      cancel() { release(); },
    });
    return new Response(stream, {
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-store, no-cache, must-revalidate",
        connection: "keep-alive",
        "x-accel-buffering": "no",
      },
    });
  };
}

export function GET(request: Request): Response {
  try {
    return makeGetMicEvents(defaultDependencies())(request);
  } catch {
    return Response.json(
      { error: "Server realtime configuration is unavailable." },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}
