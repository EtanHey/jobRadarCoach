// Hover/focus intent for warming a card's detail query. One pending intent at a time:
// sweeping across the grid moves the timer instead of queueing reads.
export const PREFETCH_INTENT_MS = 150;

type Timers = { isVisible: () => boolean; schedule: (run: () => void, ms: number) => unknown; cancel: (handle: unknown) => void };
const browserTimers: Timers = {
  isVisible: () => document.visibilityState === "visible",
  schedule: (run, ms) => setTimeout(run, ms),
  cancel: handle => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export function createPrefetchIntent(prefetch: (id: string) => void, timers: Timers = browserTimers) {
  let pending: { id: string; handle: unknown } | null = null;
  const clear = () => { if (pending) timers.cancel(pending.handle); pending = null; };
  return {
    start(id: string) {
      clear();
      if (!timers.isVisible()) return;
      const handle = timers.schedule(() => {
        pending = null;
        if (timers.isVisible()) prefetch(id);
      }, PREFETCH_INTENT_MS);
      pending = { id, handle };
    },
    end(id: string) { if (pending?.id === id) clear(); },
    dispose: clear,
  };
}
