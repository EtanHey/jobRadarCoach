import "server-only";

import { createClient } from "@supabase/supabase-js";
import { z } from "zod";

const envSchema = z.object({
  SUPABASE_URL: z.url(),
  SUPABASE_SERVICE_ROLE_KEY: z.string().min(1),
});
const tables = ["postings", "posting_scores", "posting_status", "profile", "visits"] as const;
const encoder = new TextEncoder();

function event(name: "ready" | "refresh" | "error"): Uint8Array {
  return encoder.encode(`event: ${name}\ndata: {}\n\n`);
}

export function GET(request: Request): Response {
  const env = envSchema.safeParse(process.env);
  if (!env.success) {
    return Response.json(
      { error: "Server realtime configuration is unavailable." },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
  const db = createClient(env.data.SUPABASE_URL, env.data.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  let release: () => void = () => {};
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const channel = db.channel(`job-radar-events-${crypto.randomUUID()}`, {
        config: { postgres_changes_options: { wait: true } },
      });
      let finished = false;
      function send(name: "ready" | "refresh" | "error") {
        if (!finished) controller.enqueue(event(name));
      }

      function finish() {
        if (finished) return;
        finished = true;
        clearInterval(heartbeat);
        request.signal.removeEventListener("abort", finish);
        db.removeChannel(channel).catch(() => undefined);
      }

      function fail() {
        if (finished) return;
        send("error");
        controller.close();
        finish();
      }

      const heartbeat = setInterval(() => {
        if (!finished) controller.enqueue(encoder.encode(": heartbeat\n\n"));
      }, 15_000);
      for (const table of tables) {
        channel.on(
          "postgres_changes",
          { event: "*", schema: "public", table },
          () => send("refresh"),
        );
      }
      channel.subscribe((status) => {
        if (status === "SUBSCRIBED") send("ready");
        else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT" || status === "CLOSED") fail();
      });
      release = finish;
      request.signal.addEventListener("abort", finish, { once: true });
      if (request.signal.aborted) finish();
    },
    cancel() {
      release();
    },
  });

  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-store, no-cache, must-revalidate",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
