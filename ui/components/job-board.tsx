"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { JobDetailResponseSchema, JobListResponseSchema, StatusResponseSchema, type JobDetail, type JobSummary, type StatusPatch } from "@/lib/contracts";
import { BoardHeader, BoardHero, JobsPanel, JobDrawer, type Filter } from "./job-views";

async function request(path: string, options?: RequestInit): Promise<unknown> {
  const response = await fetch(path, { cache: "no-store", ...options });
  if (!response.ok) throw new Error(response.status === 503 ? "The database is unavailable. Try again shortly." : "That request could not be completed. Please try again.");
  return response.json();
}

export function JobBoard() {
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [saving, setSaving] = useState(false);
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [revision, setRevision] = useState(0);
  const selectedRef = useRef(selected);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const reload = useCallback(() => { setLoading(true); setError(""); setRevision((value) => value + 1); }, []);
  function selectJob(id: string | null) {
    selectedRef.current = id;
    setSelected(id); setDetail(null); setDetailError(""); setRejecting(false); setReason("");
  }
  function chooseFilter(value: Filter) { setLoading(true); setError(""); setFilter(value); }


  useEffect(() => {
    const controller = new AbortController();
    request(`/api/jobs?filter=${filter}&limit=250`, { signal: controller.signal })
      .then((body) => setJobs(JobListResponseSchema.parse(body).jobs))
      .catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not load jobs."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filter, revision]);

  useEffect(() => {
    if (!selected) return undefined;
    const controller = new AbortController();
    async function open() {
      try {
        const job = JobDetailResponseSchema.parse(await request(`/api/jobs/${selected}`, { signal: controller.signal })).job;
        if (controller.signal.aborted) return;
        const status = StatusResponseSchema.parse(await request(`/api/jobs/${selected}/status`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "seen" }), signal: controller.signal,
        }));
        if (controller.signal.aborted) return;
        setDetail({ ...job, status: status.status, status_reason: status.reason }); reload();
      } catch (cause) {
        if (!controller.signal.aborted) setDetailError(cause instanceof Error ? cause.message : "Could not open this job.");
      }
    }
    open();
    return () => controller.abort();
  }, [selected, reload]);

  async function changeStatus(patch: StatusPatch) {
    if (!detail || saving) return;
    const id = detail.id;
    setSaving(true); setDetailError("");
    try {
      const result = StatusResponseSchema.parse(await request(`/api/jobs/${id}/status`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
      }));
      if (selectedRef.current === id) {
        setDetail((current) => current?.id === id ? { ...current, status: result.status, status_reason: result.reason } : current);
        setRejecting(false);
      }
      reload();
    } catch (cause) {
      if (selectedRef.current === id) setDetailError(cause instanceof Error ? cause.message : "Could not update status.");
    } finally { setSaving(false); }
  }
  const query = search.trim().toLocaleLowerCase();
  const visible = jobs.filter((job) => [job.title, job.company, job.location, ...job.stack].join(" ").toLocaleLowerCase().includes(query));

  return <div className="min-h-screen bg-[#f5f6f3] text-[#17332b]">
    <BoardHeader />
    <main className="mx-auto max-w-7xl px-5 py-10 sm:px-8 sm:py-14">
      <BoardHero />
      <JobsPanel {...{filter, search, jobs, visible, loading, error, openerRef, selectJob, chooseFilter, setSearch, reload}} />
      <p className="mt-5 text-xs text-[#82907f]">Scores are a starting point. Open a role to see the reasoning and original description.</p>
    </main>
    <JobDrawer {...{selected, openerRef, selectJob, detail, detailError, saving, rejecting, reason, setReason, setRejecting, changeStatus}} />
  </div>;
}
