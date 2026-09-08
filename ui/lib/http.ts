import { z } from "zod";

export class HttpError extends Error {
  constructor(public status: number, message: string, public category: "database" | "invalid_response" | "request" = "request") {
    super(message);
  }
}

export async function safely(run: () => Promise<Response>, operation?: "job_detail"): Promise<Response> {
  try {
    return await run();
  } catch (error) {
    const status = error instanceof HttpError ? error.status : 500;
    if (operation) {
      // Fixed fields only: never log database messages, payloads, URLs or credentials.
      const requestId = crypto.randomUUID();
      console.error(JSON.stringify({ event: "request_failed", operation, requestId, status, category: error instanceof HttpError ? error.category : "unexpected" }));
      const response = json({ error: error instanceof HttpError ? error.message : "Unexpected server error." }, status);
      response.headers.set("x-request-id", requestId);
      return response;
    }
    if (error instanceof HttpError) return json({ error: error.message }, error.status);
    return json({ error: "Unexpected server error." }, 500);
  }
}

export function json(value: unknown, status = 200): Response {
  return Response.json(value, { status, headers: { "cache-control": "no-store" } });
}

export function output<T>(schema: z.ZodType<T>, value: unknown, status = 200): Response {
  const parsed = schema.safeParse(value);
  if (!parsed.success) throw new HttpError(500, "Database returned an invalid response.", "invalid_response");
  return json(parsed.data, status);
}

export function parse<T>(schema: z.ZodType<T>, value: unknown): T {
  const parsed = schema.safeParse(value);
  if (!parsed.success) throw new HttpError(400, "Invalid request.");
  return parsed.data;
}

export async function mutationJson<T>(request: Request, schema: z.ZodType<T>): Promise<T> {
  const origin = request.headers.get("origin");
  if (origin) {
    let supplied: string;
    try { supplied = new URL(origin).origin; } catch { throw new HttpError(403, "Foreign origin rejected."); }
    const local = new URL(request.url);
    local.host = request.headers.get("host") ?? local.host;
    const expected = process.env.UI_ORIGIN ? new URL(process.env.UI_ORIGIN).origin : local.origin;
    if (supplied !== expected) throw new HttpError(403, "Foreign origin rejected.");
  }
  const mediaType = request.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase();
  if (mediaType !== "application/json") throw new HttpError(415, "Content-Type must be application/json.");
  const declared = Number(request.headers.get("content-length") ?? 0);
  if (declared > 16_384) throw new HttpError(413, "Request body is too large.");
  const body = await request.text();
  if (body.length > 16_384) throw new HttpError(413, "Request body is too large.");
  try { return parse(schema, JSON.parse(body)); } catch (error) {
    if (error instanceof HttpError) throw error;
    throw new HttpError(400, "Malformed JSON.");
  }
}
