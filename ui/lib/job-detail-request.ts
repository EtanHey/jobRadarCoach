import { JobDetailResponseSchema, type JobDetail } from "./contracts";

export const DETAIL_LOAD_TIMEOUT_MS = 15000;
export const DETAIL_LOAD_TIMEOUT_MESSAGE = "Loading this role took too long. Retry, or open the original posting.";

function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, ms);
    function abort() { clearTimeout(timer); reject(signal.reason); }
    signal.addEventListener("abort", abort, { once: true });
  });
}

// Retry reads only: a deployment can briefly disconnect the local gateway.
export async function loadJobDetail(id: string, signal: AbortSignal, fetcher = fetch, wait = pause, timeoutMs = DETAIL_LOAD_TIMEOUT_MS): Promise<JobDetail> {
  signal.throwIfAborted();
  const controller = new AbortController();
  const cancel = () => controller.abort(signal.reason);
  signal.addEventListener("abort", cancel, { once: true });
  const interrupted = new Promise<never>((_, reject) => {
    controller.signal.addEventListener("abort", () => reject(controller.signal.reason), { once: true });
  });
  const timer = setTimeout(() => controller.abort(new Error(DETAIL_LOAD_TIMEOUT_MESSAGE)), timeoutMs);
  try {
    // Cover the whole read, including queued fetches, response bodies and retry waits.
    return await Promise.race([readJobDetail(id, controller.signal, fetcher, wait), interrupted]);
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", cancel);
  }
}

async function readJobDetail(id: string, signal: AbortSignal, fetcher: typeof fetch, wait: typeof pause): Promise<JobDetail> {
  for (let attempt = 0; ; attempt++) {
    signal.throwIfAborted();
    let response: Response;
    try {
      response = await fetcher(`/api/jobs/${encodeURIComponent(id)}`, { cache: "no-store", signal });
    } catch {
      signal.throwIfAborted();
      if (attempt < 2) { await wait(750 * (attempt + 1), signal); continue; }
      throw new Error("Could not connect to load this role. Check your connection, then retry.");
    }
    if ([502, 503, 504].includes(response.status) && attempt < 2) {
      await wait(750 * (attempt + 1), signal);
      continue;
    }
    if (!response.ok) {
      if (response.status === 404) throw new Error("This role is no longer available. You can check the original posting.");
      throw new Error("Could not load this role. Retry in a moment, or open the original posting.");
    }
    try { return JobDetailResponseSchema.parse(await response.json()).job; }
    catch { signal.throwIfAborted(); throw new Error("The role details could not be read. Retry, or open the original posting."); }
  }
}
