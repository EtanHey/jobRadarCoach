import "server-only";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { z } from "zod";

import { HttpError } from "../http";

const MAX_BIGINT = "9223372036854775807";
const revisionSchema = z.string().regex(/^(0|[1-9]\d*)$/).refine(
  (value) => value.length < MAX_BIGINT.length || (value.length === MAX_BIGINT.length && value <= MAX_BIGINT),
);
const rawRowSchema = z.object({
  singleton: z.literal(true),
  client_id: z.uuid().nullable(),
  revision: z.union([z.string(), z.number()]),
  updated_at: z.iso.datetime({ offset: true }),
}).strict();

export const MicStateSchema = z.object({
  client_id: z.uuid().nullable(),
  revision: revisionSchema,
  updated_at: z.iso.datetime({ offset: true }),
}).strict();
export const MicResponseSchema = z.object({ mic: MicStateSchema }).strict();
export type MicState = z.infer<typeof MicStateSchema>;

export interface MicStore {
  getCurrent(): Promise<MicState>;
  claim(clientId: string): Promise<MicState>;
  release(clientId: string): Promise<MicState>;
}

type RpcResult = PromiseLike<{ data: unknown; error: unknown }>;
type Rpc = (name: string, args: Record<string, string>) => RpcResult;

function normalizeRevision(value: string | number): string {
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || value < 0) throw new HttpError(500, "Database returned an invalid response.");
    value = String(value);
  }
  const parsed = revisionSchema.safeParse(value);
  if (!parsed.success) throw new HttpError(500, "Database returned an invalid response.");
  return parsed.data;
}

export function parseMicRow(value: unknown): MicState {
  const parsed = rawRowSchema.safeParse(value);
  if (!parsed.success) throw new HttpError(500, "Database returned an invalid response.");
  return {
    client_id: parsed.data.client_id,
    revision: normalizeRevision(parsed.data.revision),
    updated_at: parsed.data.updated_at,
  };
}

function parseRpcRows(value: unknown): MicState {
  if (!Array.isArray(value) || value.length !== 1) {
    throw new HttpError(500, "Database returned an invalid response.");
  }
  return parseMicRow(value[0]);
}

export function compareRevisions(left: string, right: string): number {
  if (left.length !== right.length) return left.length < right.length ? -1 : 1;
  return left === right ? 0 : left < right ? -1 : 1;
}

export function createMicStore(rpc: Rpc): MicStore {
  async function call(name: string, args: Record<string, string>): Promise<MicState> {
    const result = await rpc(name, args);
    if (result.error) throw new HttpError(503, "Database request failed.");
    return parseRpcRows(result.data);
  }
  return {
    getCurrent: () => call("get_active_mic", {}),
    claim: (clientId) => call("claim_active_mic", { client_id: clientId }),
    release: (clientId) => call("release_active_mic", { client_id: clientId }),
  };
}

const envSchema = z.object({
  SUPABASE_URL: z.url(),
  SUPABASE_SERVICE_ROLE_KEY: z.string().min(1),
});

export function getVoiceDatabase(): SupabaseClient {
  const env = envSchema.safeParse(process.env);
  if (!env.success) throw new HttpError(503, "Server realtime configuration is unavailable.");
  return createClient(env.data.SUPABASE_URL, env.data.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

export function getMicStore(): MicStore {
  let db: SupabaseClient | null = null;
  return createMicStore((name, args) => {
    db ??= getVoiceDatabase();
    return db.rpc(name, args);
  });
}
