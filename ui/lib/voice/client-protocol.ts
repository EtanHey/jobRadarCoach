import { z } from "zod";

export const OPEN_JOB_RPC_METHOD = "jobradar.open_job.v1";
export const TRANSCRIPTION_TOPIC = "lk.transcription";
export const MAX_OPEN_JOB_PAYLOAD_BYTES = 4_096;

const uuid = z.uuid();
const openJobSchema = z.object({
  version: z.literal(1),
  request_id: uuid,
  posting_id: uuid,
  apply_url: z.string().max(2_048),
}).strict();
const jobResponseSchema = z.object({
  job: z.object({ id: uuid, apply_url: z.string().nullable(), url: z.string() }),
}).strict();

export type OpenJobAcknowledgement =
  | { version: 1; request_id: string; status: "opened" }
  | { version: 1; request_id: string; status: "popup_blocked"; fallback: "clickable_link_rendered" }
  | { version: 1; request_id: string; status: "rejected"; reason: "invalid_payload" | "posting_not_found" | "url_mismatch" | "not_https" };

export class OpenJobProtocolError extends Error {
  constructor() { super("Open job request could not be verified."); }
}

type FetchJob = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type OpenWindow = (url: string, target: string, features: string) => Window | null;

export interface OpenJobRpcOptions {
  trustedAgentIdentity: string;
  fetchJob: FetchJob;
  openWindow: OpenWindow;
  renderFallback: (input: { href: string; requestId: string }) => void | Promise<void>;
  maxRememberedRequests?: number;
}

export interface OpenJobInvocation {
  callerIdentity: string;
  payload: string;
}

function unsafeHostname(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.+$/, "");
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local")
      || host.endsWith(".internal") || host.endsWith(".home.arpa")) return true;
  const ipv4 = host.split(".").map(Number);
  if (ipv4.length === 4 && ipv4.every((part) => Number.isInteger(part) && part >= 0 && part <= 255)) {
    const [a, b] = ipv4;
    return a === 0 || a === 10 || a === 127 || (a === 100 && b >= 64 && b <= 127)
      || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31)
      || (a === 192 && b === 168) || (a === 198 && (b === 18 || b === 19)) || a >= 224;
  }
  if (!host.includes(":")) return !host.includes(".");
  const firstHextet = Number.parseInt(host.split(":", 1)[0], 16);
  return host === "::" || host === "::1" || host.startsWith("::ffff:")
    || Number.isNaN(firstHextet) || firstHextet < 0x2000 || firstHextet > 0x3fff
    || /^2001:db8(?::|$)/.test(host);
}

export function isPublicHttpsUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !unsafeHostname(url.hostname);
  } catch {
    return false;
  }
}

function acknowledgement(value: OpenJobAcknowledgement): string {
  return JSON.stringify(value);
}

function rejected(requestId: string, reason: Extract<OpenJobAcknowledgement, { status: "rejected" }>["reason"]): string {
  return acknowledgement({ version: 1, request_id: requestId, status: "rejected", reason });
}

function parseInvocation(payload: string) {
  if (new TextEncoder().encode(payload).byteLength > MAX_OPEN_JOB_PAYLOAD_BYTES) throw new OpenJobProtocolError();
  let raw: unknown;
  try { raw = JSON.parse(payload); } catch { throw new OpenJobProtocolError(); }
  const requestId = uuid.safeParse(raw && typeof raw === "object" ? (raw as Record<string, unknown>).request_id : undefined);
  if (!requestId.success) throw new OpenJobProtocolError();
  return { requestId: requestId.data, request: openJobSchema.safeParse(raw) };
}

export function createOpenJobRpcHandler(options: OpenJobRpcOptions) {
  const limit = z.number().int().min(1).max(1_000).parse(options.maxRememberedRequests ?? 100);
  const inFlight = new Map<string, Promise<string>>();
  const completed = new Map<string, string>();

  const execute = async (parsed: ReturnType<typeof parseInvocation>): Promise<string> => {
    if (!parsed.request.success) return rejected(parsed.requestId, "invalid_payload");
    const request = parsed.request.data;
    if (!isPublicHttpsUrl(request.apply_url)) return rejected(parsed.requestId, "not_https");

    let response: Response;
    try {
      response = await options.fetchJob(`/api/jobs/${encodeURIComponent(request.posting_id)}`, {
        method: "GET", headers: { accept: "application/json" }, cache: "no-store",
      });
    } catch { throw new OpenJobProtocolError(); }
    if (response.status === 404) return rejected(parsed.requestId, "posting_not_found");
    if (!response.ok) throw new OpenJobProtocolError();

    let body: unknown;
    try { body = await response.json(); } catch { throw new OpenJobProtocolError(); }
    const grounded = jobResponseSchema.safeParse(body);
    if (!grounded.success || grounded.data.job.id !== request.posting_id) throw new OpenJobProtocolError();
    const canonicalUrl = grounded.data.job.apply_url ?? grounded.data.job.url;
    if (!isPublicHttpsUrl(canonicalUrl)) return rejected(parsed.requestId, "not_https");
    if (request.apply_url !== canonicalUrl) return rejected(parsed.requestId, "url_mismatch");

    const handle = options.openWindow(request.apply_url, "_blank", "noopener,noreferrer");
    if (handle !== null) return acknowledgement({ version: 1, request_id: parsed.requestId, status: "opened" });
    await options.renderFallback({ href: request.apply_url, requestId: parsed.requestId });
    return acknowledgement({
      version: 1, request_id: parsed.requestId, status: "popup_blocked", fallback: "clickable_link_rendered",
    });
  };

  return async ({ callerIdentity, payload }: OpenJobInvocation): Promise<string> => {
    if (callerIdentity !== options.trustedAgentIdentity) throw new OpenJobProtocolError();
    const parsed = parseInvocation(payload);
    const cached = completed.get(parsed.requestId);
    if (cached !== undefined) return cached;
    const pending = inFlight.get(parsed.requestId);
    if (pending) return pending;
    if (completed.size + inFlight.size >= limit) throw new OpenJobProtocolError();
    const task = execute(parsed).then((result) => { completed.set(parsed.requestId, result); return result; })
      .finally(() => inFlight.delete(parsed.requestId));
    inFlight.set(parsed.requestId, task);
    return task;
  };
}

export type TranscriptRole = "user" | "agent";
export interface TranscriptSegment {
  senderIdentity: string;
  role: TranscriptRole;
  segmentId: string;
  trackId: string;
  streamId: string;
  lastChunkIndex: number;
  text: string;
  final: boolean;
}

export interface TranscriptChunk {
  topic: string;
  senderIdentity: string;
  role: TranscriptRole;
  streamId: string;
  chunkIndex: number;
  text: string;
  attributes: Record<string, string>;
}

const transcriptChunkSchema = z.object({
  topic: z.string(), senderIdentity: z.string().min(1).max(256), role: z.enum(["user", "agent"]),
  streamId: z.string().min(1).max(256), chunkIndex: z.number().int().nonnegative(), text: z.string(),
  attributes: z.record(z.string(), z.string()),
}).strict();

export function reduceTranscript(
  segments: readonly TranscriptSegment[], chunk: TranscriptChunk, maxSegments = 200,
): readonly TranscriptSegment[] {
  if (chunk.topic !== TRANSCRIPTION_TOPIC) return segments;
  const parsed = transcriptChunkSchema.safeParse(chunk);
  if (!parsed.success) return segments;
  const { attributes } = parsed.data;
  const segmentId = attributes["lk.segment_id"];
  const trackId = attributes["lk.transcribed_track_id"];
  const finalValue = attributes["lk.transcription_final"];
  if (!segmentId || !trackId || (finalValue !== "true" && finalValue !== "false")) return segments;
  const final = finalValue === "true";
  const index = segments.findIndex((item) => item.senderIdentity === chunk.senderIdentity && item.segmentId === segmentId);
  if (index < 0) {
    const next = [...segments, {
      senderIdentity: chunk.senderIdentity, role: chunk.role, segmentId, trackId,
      streamId: chunk.streamId, lastChunkIndex: chunk.chunkIndex, text: chunk.text, final,
    }];
    return next.slice(-z.number().int().min(1).max(1_000).parse(maxSegments));
  }
  const current = segments[index];
  if (current.final && current.streamId !== chunk.streamId) return segments;
  if (current.streamId === chunk.streamId && chunk.chunkIndex <= current.lastChunkIndex) return segments;
  const updated: TranscriptSegment = {
    senderIdentity: chunk.senderIdentity, role: chunk.role, segmentId, trackId,
    streamId: chunk.streamId, lastChunkIndex: chunk.chunkIndex,
    text: current.streamId === chunk.streamId ? current.text + chunk.text : chunk.text,
    final: current.streamId === chunk.streamId ? current.final || final : final,
  };
  const next = [...segments];
  next[index] = updated;
  return next;
}
