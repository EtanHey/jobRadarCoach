import { RpcError } from "livekit-client";

export const AGENT_PING_METHOD = "jrc.ping";

// An older agent's explicit unsupported-method reply still proves its RTC loop is alive.
export async function agentResponds(request: () => Promise<string>): Promise<boolean> {
  try { return await request() === "pong"; }
  catch (error) { return error instanceof RpcError && error.code === RpcError.ErrorCode.UNSUPPORTED_METHOD; }
}

export function watchAgentLiveness(options: {
  signal: AbortSignal;
  identity(): string | null;
  isCurrent(): boolean;
  probe(identity: string, timeoutMs: number): Promise<boolean>;
  changed(responsive: boolean): void;
  intervalMs?: number;
  timeoutMs?: number;
}) {
  const interval = options.intervalMs ?? 1000;
  const timeout = options.timeoutMs ?? 1500;
  let stopped = false, misses = 0, responsive = true;
  let next: ReturnType<typeof setTimeout> | undefined;
  let inFlight: { identity: string; result: Promise<boolean> } | undefined;
  let finishPending: ((value: boolean) => void) | undefined;
  const current = () => !stopped && !options.signal.aborted && options.isCurrent();
  const stop = () => {
    stopped = true; clearTimeout(next); finishPending?.(false);
    options.signal.removeEventListener("abort", stop);
  };
  const tick = async () => {
    if (!current()) return;
    const identity = options.identity();
    if (identity) {
      if (!inFlight) {
        const request = { identity, result: Promise.resolve().then(() => options.probe(identity, timeout)).catch(() => false) };
        inFlight = request;
        void request.result.then(() => { if (inFlight === request) inFlight = undefined; });
      }
      const request = inFlight;
      const alive = await new Promise<boolean>((resolve) => {
        const timer = setTimeout(() => finish(false), timeout);
        const finish = (value: boolean) => { clearTimeout(timer); resolve(value); };
        finishPending = finish;
        void request.result.then((value) => finish(request.identity === identity && value));
      });
      finishPending = undefined;
      if (!current()) return;
      if (identity !== options.identity()) { misses = 0; }
      else {
        misses = alive ? 0 : misses + 1;
        const nextResponsive = misses < 2;
        if (nextResponsive !== responsive) { responsive = nextResponsive; options.changed(responsive); }
      }
    }
    if (current()) next = setTimeout(tick, interval);
  };
  options.signal.addEventListener("abort", stop, { once: true });
  void tick();
  return stop;
}
