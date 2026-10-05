"use client";
import { useCallback, useEffect, useState } from "react";
import { NewJobCountResponseSchema, type Availability } from "@/lib/contracts";
import { createNewRolesPollGate, NEW_ROLES_POLL_MS, newRolesCountPath } from "@/lib/new-roles";

// Asks how many roles are newer than the loaded list; never touches the list itself.
export function useNewRoles(enabled: boolean, filter: string, availability: Availability, since: string) {
  const path = newRolesCountPath({ filter, availability, since });
  const [result, setResult] = useState<{ path: string; count: number } | null>(null);
  useEffect(() => {
    if (!enabled) return undefined;
    const gate = createNewRolesPollGate();
    gate.reset(Date.now());
    let controller: AbortController | null = null;
    function poll() {
      if (!gate.shouldPoll(Date.now(), document.visibilityState === "hidden")) return;
      controller?.abort();
      const current = controller = new AbortController();
      fetch(path, { cache: "no-store", signal: current.signal })
        .then(response => response.ok ? response.json() : Promise.reject(new Error("New roles unavailable")))
        .then(body => { if (!current.signal.aborted) setResult({ path, count: NewJobCountResponseSchema.parse(body).count }); })
        // A failed count keeps the last answer; the next poll asks again.
        .catch(() => {});
    }
    const visible = () => { if (document.visibilityState === "visible") poll(); };
    const timer = setInterval(poll, NEW_ROLES_POLL_MS);
    window.addEventListener("focus", poll);
    document.addEventListener("visibilitychange", visible);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", poll);
      document.removeEventListener("visibilitychange", visible);
      controller?.abort();
    };
  }, [enabled, path]);
  const dismiss = useCallback(() => setResult({ path, count: 0 }), [path]);
  return { count: enabled && result?.path === path ? result.count : 0, dismiss };
}
