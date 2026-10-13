"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { GlobeResponseSchema, type GlobeResponse, GlobeJobSchema } from "@/lib/globe-contract";
import { retainGlobeCohort } from "@/lib/globe-cohort";
import { reconcileStatusMutations, type StatusMutation } from "@/lib/job-board-state";
import type { Availability, FoundWithin, JobSummary, StatusResult } from "@/lib/contracts";
import type { BoardFilter } from "@/lib/job-board-preferences";
export function useGlobeData(open: boolean, filter: BoardFilter, availability: Availability, revision: number, retained: JobSummary[], found_within?: FoundWithin) {
  const retainedRef = useRef(retained);
  useEffect(() => { retainedRef.current = retained; }, [retained]);
  const key = `${filter}/${availability}/${found_within ?? ""}`;
  const cohort = useRef<{ key: string; data: GlobeResponse } | null>(null);
  const [result, setResult] = useState<{ key: string; data: GlobeResponse } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  // PATCH replies confirmed while a globe read is in flight, replayed onto it when it lands.
  const inflight = useRef<Map<string, StatusMutation<JobSummary["status"]>> | null>(null);
  useEffect(() => {
    // Leaving a view ends its visit, even when the globe is closed.
    cohort.current = null;
    let active = true;
    queueMicrotask(() => { if (active) setResult(null); });
    return () => { active = false; };
  }, [key]);
  useEffect(() => {
    if (!open) return undefined;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    let active = true;
    queueMicrotask(() => { if (active) setFailure(null); });
    const mutations = inflight.current = new Map();
    fetch(`/api/jobs/globe?${new URLSearchParams({ filter, availability, ...(found_within ? { found_within } : {}) })}`, { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Globe unavailable");
        let incoming = GlobeResponseSchema.parse(await response.json());
        let latest: GlobeResponse | undefined;
        if (filter === "new-for-me") {
          const incomingIds = new Set(incoming.jobs.map(job => job.id));
          const previous = cohort.current?.key === key ? cohort.current.data : null;
          const retainedJobs = [...(previous?.jobs ?? []), ...retainedRef.current.map(job => GlobeJobSchema.parse(job))];
          const missing = new Set(retainedJobs.filter(job => !incomingIds.has(job.id)).map(job => job.id));
          if (missing.size) {
            // Hydrate retained list and globe IDs, including newly inactive roles.
            const all = await fetch(`/api/jobs/globe?${new URLSearchParams({ filter: "all", availability: "all" })}`, { cache: "no-store", signal: controller.signal });
            if (!all.ok) throw new Error("Retained locations unavailable");
            const complete = GlobeResponseSchema.parse(await all.json());
            latest = complete;
            const extraJobs = complete.jobs.filter(job => missing.has(job.id));
            const extraPoints = complete.points.filter(point => missing.has(point.posting_id));
            incoming = { ...incoming, jobs: [...incoming.jobs, ...extraJobs], points: [...incoming.points, ...extraPoints], total_count: incoming.total_count + extraJobs.length, resolved_count: incoming.resolved_count + extraPoints.length, unresolved_count: incoming.unresolved_count + extraJobs.length - extraPoints.length };
          }
        }
        if (!active) return;
        const read = filter === "new-for-me" ? retainGlobeCohort(cohort.current?.key === key ? cohort.current.data : null, incoming, latest) : incoming;
        const jobs = reconcileStatusMutations(read.jobs, mutations);
        const ids = new Set(jobs.map(job => job.id));
        const points = jobs === read.jobs ? read.points : read.points.filter(point => ids.has(point.posting_id));
        const data = jobs === read.jobs ? read : { ...read, jobs, points, total_count: jobs.length, resolved_count: points.length, unresolved_count: jobs.length - points.length };
        cohort.current = { key, data }; setResult({ key, data });
      }).catch(() => { if (active) setFailure("The globe is unavailable. Your list is still here."); })
      .finally(() => { clearTimeout(timeout); if (inflight.current === mutations) inflight.current = null; });
    return () => { active = false; clearTimeout(timeout); controller.abort(); if (inflight.current === mutations) inflight.current = null; };
  }, [open, filter, availability, revision, key, found_within]);
  const patchStatus = useCallback((id: string, status: StatusResult, remove: boolean) => {
    inflight.current?.set(id, { status: status.status, reason: status.reason, remove });
    const current = cohort.current;
    if (!current) return;
    const jobs = current.data.jobs.filter(job => !remove || job.id !== id).map(job => job.id === id ? { ...job, status: status.status, status_reason: status.reason } : job);
    const points = current.data.points.filter(point => !remove || point.posting_id !== id);
    const next = { key: current.key, data: { ...current.data, jobs, points, total_count: jobs.length, resolved_count: points.length, unresolved_count: jobs.length - points.length } };
    cohort.current = next; setResult(next);
  }, []);
  return { patchStatus, data: result?.key === key ? result.data : null, failure };
}
