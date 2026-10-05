"use client";
import { useCallback, useEffect, useState } from "react";
import { JobListResponseSchema, type Availability, type JobSummary } from "@/lib/contracts";
import { createNewRolesPollGate, NEW_ROLES_LIMIT, NEW_ROLES_POLL_MS, newRolesRequestPath } from "@/lib/new-roles";

type NewRoles = { jobs: JobSummary[]; truncated: boolean };
const NONE: NewRoles = { jobs: [], truncated: false };

// Reads a bounded page of postings newer than the loaded list; never touches the list itself.
// The answer is keyed by its request, so a changed filter or cursor never shows a stale page.
export function useNewRoles(enabled: boolean, filter: string, availability: Availability, since: string) {
  const path = newRolesRequestPath({ filter, availability, since });
  const [result, setResult] = useState<NewRoles & { path: string } | null>(null);
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
        .then(body => {
          if (current.signal.aborted) return;
          const jobs = JobListResponseSchema.parse(body).jobs;
          setResult({ path, jobs: jobs.slice(0, NEW_ROLES_LIMIT), truncated: jobs.length > NEW_ROLES_LIMIT });
        })
        // A failed poll keeps the last answer; the next poll asks again.
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
  const dismiss = useCallback(() => setResult({ path, ...NONE }), [path]);
  return { ...(enabled && result?.path === path ? result : NONE), dismiss };
}
