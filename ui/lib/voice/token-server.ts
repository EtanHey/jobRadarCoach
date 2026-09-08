import "server-only";

import { randomUUID } from "node:crypto";
import { AccessToken, TrackSource } from "livekit-server-sdk";
import { z } from "zod";

import { HttpError } from "../http";

export const VOICE_TOKEN_TTL_SECONDS = 300;

export const VoiceTokenRequestSchema = z.strictObject({
  client_id: z.uuid().transform((value) => value.toLowerCase()),
});

export const VoiceTokenResponseSchema = z.strictObject({
  server_url: z.string(),
  token: z.string(),
  room_name: z.string(),
  participant_identity: z.string(),
  dispatch_mode: z.literal("automatic"),
});

type VoiceEnvironment = Readonly<Record<string, string | undefined>>;

const environmentSchema = z.object({
  LIVEKIT_API_KEY: z.string().trim().min(1).max(256),
  LIVEKIT_API_SECRET: z.string().min(1).max(4096),
  LIVEKIT_PUBLIC_URL: z.string().trim().min(1).max(2048),
});

function configuration(environment: VoiceEnvironment) {
  const parsed = environmentSchema.safeParse(environment);
  if (!parsed.success) throw new HttpError(503, "Voice service configuration is unavailable.");

  let url: URL;
  try {
    url = new URL(parsed.data.LIVEKIT_PUBLIC_URL);
  } catch {
    throw new HttpError(503, "Voice service configuration is unavailable.");
  }
  if (!(["ws:", "wss:"] as string[]).includes(url.protocol)
      || url.username || url.password || url.search || url.hash) {
    throw new HttpError(503, "Voice service configuration is unavailable.");
  }
  return {
    apiKey: parsed.data.LIVEKIT_API_KEY,
    apiSecret: parsed.data.LIVEKIT_API_SECRET,
    publicUrl: url.href.replace(/\/$/, ""),
  };
}

export async function mintVoiceToken(
  clientId: string,
  environment: VoiceEnvironment = process.env,
  createSessionId: () => string = randomUUID,
) {
  const config = configuration(environment);
  const safeClientId = z.uuid().parse(clientId).toLowerCase();
  const sessionId = z.uuid().parse(createSessionId()).toLowerCase();
  const roomName = `job-radar-voice-${safeClientId}-${sessionId}`;
  const participantIdentity = `web:${safeClientId}:${sessionId}`;
  const accessToken = new AccessToken(config.apiKey, config.apiSecret, {
    identity: participantIdentity,
    ttl: VOICE_TOKEN_TTL_SECONDS,
  });
  accessToken.addGrant({
    roomJoin: true,
    room: roomName,
    canPublish: true,
    canPublishSources: [TrackSource.MICROPHONE],
    canSubscribe: true,
    canPublishData: true,
    canUpdateOwnMetadata: false,
  });

  return VoiceTokenResponseSchema.parse({
    server_url: config.publicUrl,
    token: await accessToken.toJwt(),
    room_name: roomName,
    participant_identity: participantIdentity,
    dispatch_mode: "automatic",
  });
}
