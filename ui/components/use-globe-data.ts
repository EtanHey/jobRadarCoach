"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { GlobeResponseSchema, type GlobeResponse } from "@/lib/globe-contract";
import { retainGlobeCohort } from "@/lib/globe-cohort";
import type { Availability, JobSummary, StatusResult } from "@/lib/contracts";
import type { BoardFilter } from "@/lib/job-board-preferences";
export function useGlobeData(open: boolean, filter: BoardFilter, availability: Availability, revision: number, retained: JobSummary[]) {
  const retainedRef = useRef(retained);
  useEffect(() => { retainedRef.current = retained; }, [retained]);
  const key = `${filter}/${availability}`;
  const cohort = useRef<{ key: string; data: GlobeResponse } | null>(null);
  const [result, setResult] = useState<{ key: string; data: GlobeResponse } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  useEffect(() => {
    if (!open) { cohort.current = null; return; }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    let active = true;
    queueMicrotask(() => { if (active) setFailure(null); });
    fetch(`/api/jobs/globe?${new URLSearchParams({ filter, availability })}`, { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Globe unavailable");
        let incoming = GlobeResponseSchema.parse(await response.json());
        if (filter === "new-for-me") {
          const incomingIds = new Set(incoming.jobs.map(job => job.id));
          const missing = new Set(retainedRef.current.filter(job => !incomingIds.has(job.id)).map(job => job.id));
          if (missing.size) {
            // Hydrate retained list IDs from the full availability set, never guess their geography.
            const all = await fetch(`/api/jobs/globe?${new URLSearchParams({ filter: "all", availability })}`, { cache: "no-store", signal: controller.signal });
            if (!all.ok) throw new Error("Retained locations unavailable");
            const complete = GlobeResponseSchema.parse(await all.json());
            const extraJobs = complete.jobs.filter(job => missing.has(job.id));
            const extraPoints = complete.points.filter(point => missing.has(point.posting_id));
            incoming = { ...incoming, jobs: [...incoming.jobs, ...extraJobs], points: [...incoming.points, ...extraPoints], total_count: incoming.total_count + extraJobs.length, resolved_count: incoming.resolved_count + extraPoints.length, unresolved_count: incoming.unresolved_count + extraJobs.length - extraPoints.length };
          }
        }
        if (!active) return;
        const data = filter === "new-for-me" ? retainGlobeCohort(cohort.current?.key === key ? cohort.current.data : null, incoming) : incoming;
        cohort.current = { key, data }; setResult({ key, data });
      }).catch(() => { if (active) setFailure("The globe is unavailable. Your list is still here."); })
      .finally(() => clearTimeout(timeout));
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [open, filter, availability, revision, key]);
  const patchStatus = useCallback((id: string, status: StatusResult, remove: boolean) => {
    const current = cohort.current;
    if (!current) return;
    const jobs = current.data.jobs.filter(job => !remove || job.id !== id).map(job => job.id === id ? { ...job, status: status.status, status_reason: status.reason } : job);
    const points = current.data.points.filter(point => !remove || point.posting_id !== id);
    const next = { key: current.key, data: { ...current.data, jobs, points, total_count: jobs.length, resolved_count: points.length, unresolved_count: jobs.length - points.length } };
    cohort.current = next; setResult(next);
  }, []);
  return { patchStatus, data: open && result?.key === key ? result.data : null, failure };
}
