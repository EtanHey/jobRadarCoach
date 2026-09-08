import { mutationJson, output, safely } from "../../../../lib/http";
import {
  mintVoiceToken, VoiceTokenRequestSchema, VoiceTokenResponseSchema,
} from "../../../../lib/voice/token-server";

type TokenEnvironment = Parameters<typeof mintVoiceToken>[1];

export function makePost(environment: TokenEnvironment = process.env) {
  return (request: Request) => safely(async () => {
    const input = await mutationJson(request, VoiceTokenRequestSchema);
    return output(VoiceTokenResponseSchema, await mintVoiceToken(input.client_id, environment));
  });
}

export function POST(request: Request): Promise<Response> {
  return makePost()(request);
}
