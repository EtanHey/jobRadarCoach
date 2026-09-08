import { z } from "zod";

import { mutationJson, output, safely } from "../../../../lib/http";
import {
  getMicStore, MicResponseSchema, type MicStore,
} from "../../../../lib/voice/mic-server";

const mutationSchema = z.discriminatedUnion("action", [
  z.object({ action: z.literal("claim"), client_id: z.uuid() }).strict(),
  z.object({ action: z.literal("release"), client_id: z.uuid() }).strict(),
]);

export function makeGetMic(store: MicStore) {
  return () => safely(async () => output(MicResponseSchema, { mic: await store.getCurrent() }));
}

export function makePostMic(store: MicStore) {
  return (request: Request) => safely(async () => {
    const input = await mutationJson(request, mutationSchema);
    const mic = input.action === "claim"
      ? await store.claim(input.client_id)
      : await store.release(input.client_id);
    return output(MicResponseSchema, { mic });
  });
}

export function GET(): Promise<Response> {
  return makeGetMic(getMicStore())();
}

export function POST(request: Request): Promise<Response> {
  return makePostMic(getMicStore())(request);
}
