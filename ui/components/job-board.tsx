"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { JobDetailResponseSchema, JobListResponseSchema, StatusResponseSchema, type JobDetail, type JobSummary, type StatusPatch } from "@/lib/contracts";
import { createDetailCoordinator, retainVisitCohort, uniqueJobsById } from "@/lib/job-board-state";
import { boardPreferenceStorage, clearBoardPreferences, defaultBoardPreferences, isDefaultBoardPreferences, readBoardPreferences, writeBoardPreferences } from "@/lib/job-board-preferences";
import { relativeAge } from "@/lib/job-display";
import { relatedDuplicateJobs } from "@/lib/job-dedup";
import { filterJobGroups, type ViewOptions } from "@/lib/job-filters";
import { JobToolbar } from "./job-toolbar";
import { ProfileDrawer } from "./profile-drawer";
import { BoardHeader, JobsPanel, JobDrawer, type Filter } from "./job-views";

async function request(path: string, options?: RequestInit): Promise<unknown> {
  const response = await fetch(path, { cache: "no-store", ...options });
  if (!response.ok) throw new Error(response.status === 503 ? "The database is unavailable. Try again shortly." : "That request could not be completed. Please try again.");
  return response.json();
}

export function JobBoard() {
  const [preferences, setPreferences] = useState(defaultBoardPreferences);
  const [preferencesReady, setPreferencesReady] = useState(false);
  const { filter, view } = preferences;
  const [loadedUpdatedAt, setLoadedUpdatedAt] = useState<string | null>(null);
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
  const [connection, setConnection] = useState("Connecting live updates…");
  const [detailCoordinator] = useState(createDetailCoordinator);
  const [refreshWarning, setRefreshWarning] = useState("");
  const detailRequestRef = useRef<AbortController | null>(null);
  const visitCohortRef = useRef<JobSummary[] | null>(null);
  const preferenceStorageRef = useRef<Storage | null>(null);
  const filterRef = useRef<Filter>(filter);
  const hasLoadedRef = useRef(false);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const requestRefresh = useCallback(() => { setError(""); setRevision((value) => value + 1); }, []);
  const retry = useCallback(() => { visitCohortRef.current = null; hasLoadedRef.current = false; setJobs([]); setLoadedUpdatedAt(null); setRefreshWarning(""); setLoading(true); requestRefresh(); }, [requestRefresh]);
  function selectJob(id: string | null) {
    detailRequestRef.current?.abort();
    detailCoordinator.select(id);
    setSelected(id);
    // Keep the previous body intact during the sheet closing transition.
    if (id !== null) { setDetail(null); setDetailError(""); setRejecting(false); setReason(""); }
  }
  function chooseFilter(value: Filter) { if (value === filter) return; filterRef.current = value; visitCohortRef.current = null; hasLoadedRef.current = false; setLoadedUpdatedAt(null); setLoading(true); setJobs([]); setError(""); setRefreshWarning(""); setPreferences((current) => ({ filter: value, view: { ...current.view, fit: value === "new-for-me" ? "recommended" : "" } })); }
  function changeView(next: ViewOptions) { setPreferences((current) => ({ ...current, view: next })); }
  function setSearch(search: string) { setPreferences((current) => ({ ...current, view: { ...current.view, search } })); }
  function resetView() {
    const storage = preferenceStorageRef.current ?? boardPreferenceStorage(window);
    if (storage) clearBoardPreferences(storage);
    const next = defaultBoardPreferences();
    if (filter !== next.filter) {
      filterRef.current = next.filter;
      visitCohortRef.current = null;
      hasLoadedRef.current = false;
      setLoadedUpdatedAt(null);
      setLoading(true);
      setJobs([]);
      setError("");
      setRefreshWarning("");
    }
    setPreferences(next);
  }

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      const storage = boardPreferenceStorage(window);
      preferenceStorageRef.current = storage;
      const restored = storage ? readBoardPreferences(storage) : defaultBoardPreferences();
      filterRef.current = restored.filter;
      setPreferences(restored);
      setPreferencesReady(true);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const storage = preferenceStorageRef.current;
    if (preferencesReady && storage) writeBoardPreferences(storage, preferences);
  }, [preferences, preferencesReady]);

  useEffect(() => {
    const events = new EventSource("/api/events");
    let timer: ReturnType<typeof setTimeout> | undefined;
    function refreshListAndDetail() {
      requestRefresh();
      detailRequestRef.current?.abort();
      const read = detailCoordinator.beginRead();
      const id = read.selection.id;
      if (!id) return;
      const controller = new AbortController();
      detailRequestRef.current = controller;
      request(`/api/jobs/${id}`, { signal: controller.signal }).then((body) => {
        if (!controller.signal.aborted && detailCoordinator.acceptRead(read)) { setDetail(JobDetailResponseSchema.parse(body).job); setDetailError(""); }
      }).catch(() => { if (!controller.signal.aborted && detailCoordinator.acceptRead(read)) setDetailError("Could not refresh this job. Close and reopen to retry."); });
    }
    function queueRefresh() { clearTimeout(timer); timer = setTimeout(refreshListAndDetail, 150); }
    events.addEventListener("ready", () => { setConnection("Live updates connected"); queueRefresh(); });
    events.addEventListener("refresh", queueRefresh);
    events.addEventListener("error", () => setConnection("Reconnecting live updates…"));
    return () => { events.close(); clearTimeout(timer); detailRequestRef.current?.abort(); };
  }, [detailCoordinator, requestRefresh]);

  useEffect(() => {
    if (!preferencesReady) return undefined;
    const controller = new AbortController();
    request(`/api/jobs?filter=${filter}&limit=1000`, { signal: controller.signal })
      .then((body) => { if (!controller.signal.aborted) { const next = uniqueJobsById(JobListResponseSchema.parse(body).jobs); const displayed = filter === "new-for-me" ? retainVisitCohort(visitCohortRef.current, next) : next; if (filter === "new-for-me") visitCohortRef.current = displayed; hasLoadedRef.current = true; setRefreshWarning(""); setJobs(displayed); setLoadedUpdatedAt(displayed.reduce<string | null>((last, job) => !last || job.last_seen_at > last ? job.last_seen_at : last, null)); } })
      .catch((cause: unknown) => { if (!controller.signal.aborted) { const message = cause instanceof Error ? cause.message : "Could not load jobs."; if (hasLoadedRef.current) setRefreshWarning(`${message} Showing previous results.`); else setError(message); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filter, preferencesReady, revision]);

  useEffect(() => {
    if (!selected) return undefined;
    const identity = detailCoordinator.current();
    if (identity.id !== selected) return undefined;
    const read = detailCoordinator.beginRead();
    const controller = new AbortController();
    let patchStarted = false;
    async function open() {
      try {
        const job = JobDetailResponseSchema.parse(await request(`/api/jobs/${selected}`, { signal: controller.signal })).job;
        if (controller.signal.aborted) return;
        if (detailCoordinator.acceptRead(read)) setDetail(job);
        patchStarted = true;
        const status = StatusResponseSchema.parse(await request(`/api/jobs/${selected}/status`, {
          method: "PATCH", headers: { "Content-Type": "application/json", "X-Job-Radar-Status-Version": "2" }, body: JSON.stringify({ status: "seen", automatic: true }), signal: controller.signal,
        }));
        if (controller.signal.aborted) return;
        if (detailCoordinator.commitMutation(identity)) {
          detailRequestRef.current?.abort();
          const updateStatus = (current: JobSummary) => current.id === selected ? { ...current, status: status.status, status_reason: status.reason } : current;
          visitCohortRef.current = visitCohortRef.current?.map(updateStatus) ?? null;
          setJobs((current) => current.map(updateStatus));
          setDetail({ ...job, status: status.status, status_reason: status.reason });
        }
        requestRefresh();
      } catch (cause) {
        if (!controller.signal.aborted && detailCoordinator.isCurrent(identity) && (patchStarted || detailCoordinator.acceptRead(read))) setDetailError(cause instanceof Error ? cause.message : "Could not open this job.");
      }
    }
    open();
    return () => controller.abort();
  }, [detailCoordinator, selected, requestRefresh]);

  async function changeStatus(patch: StatusPatch) {
    if (!detail || saving || detailCoordinator.current().id !== detail.id) return false;
    const id = detail.id;
    const identity = detailCoordinator.current();
    setSaving(true); setDetailError("");
    try {
      const result = StatusResponseSchema.parse(await request(`/api/jobs/${id}/status`, {
        method: "PATCH", headers: { "Content-Type": "application/json", "X-Job-Radar-Status-Version": "2" }, body: JSON.stringify(patch),
      }));
      if (identity.id === id && detailCoordinator.commitMutation(identity)) {
        detailRequestRef.current?.abort();
        setDetail((current) => current?.id === id ? { ...current, status: result.status, status_reason: result.reason } : current);
        setRejecting(false);
      }
      if (filterRef.current === "new-for-me") {
        visitCohortRef.current = visitCohortRef.current?.filter((job) => job.id !== id) ?? null;
        setJobs((current) => current.filter((job) => job.id !== id));
      }
      requestRefresh();
      return true;
    } catch (cause) {
      if (detailCoordinator.current().id === id) setDetailError(cause instanceof Error ? cause.message : "Could not update status.");
      return false;
    } finally { setSaving(false); }
  }
  if (!preferencesReady) return <div className="min-h-screen bg-background text-foreground">
    <BoardHeader><ProfileDrawer onUpdated={requestRefresh} /></BoardHeader>
    <main className="grid min-h-[35rem] place-items-center px-4 py-16"><p role="status" className="text-sm text-muted-foreground">Restoring saved view…</p></main>
  </div>;

  const groups = filterJobGroups(jobs, view);
  const relatedId = selected ?? detail?.id;
  const relatedJobs = relatedId ? relatedDuplicateJobs(jobs, relatedId, detail) : [];
  const sortLabel = {found: "Recently found", posted: "Posted date · found when unknown", fit: "Best fit first", seniority: "Junior first · unknown last"}[view.sort];

  return <div className="min-h-screen bg-background text-foreground">
    <BoardHeader><ProfileDrawer onUpdated={requestRefresh} /></BoardHeader>
    <main className="w-full px-4 py-4 sm:px-6 lg:px-8">
      <div className="mb-3 flex items-center gap-2 text-xs text-muted-foreground"><h1 className="mr-auto text-lg font-semibold text-foreground">Your roles</h1><span className="rounded-full bg-muted px-2 py-1">{groups.length} roles</span>{relativeAge(loadedUpdatedAt) && <span className="rounded-full bg-muted px-2 py-1" title="Last time a posting in this view was observed">Updated {relativeAge(loadedUpdatedAt)}</span>}</div>
      <JobsPanel {...{filter, jobs, groups, loading, error, openerRef, selectJob, chooseFilter, setSearch, loadedUpdatedAt, sortLabel}} search={view.search} reload={retry} resultLimit={1000} toolbar={<JobToolbar jobs={jobs} options={view} onChange={changeView} onReset={resetView} canReset={!isDefaultBoardPreferences(preferences)} />} />
      <p role="status" className="mt-4 text-xs text-muted-foreground">{refreshWarning ? `${connection} ${refreshWarning}` : connection}</p>
    </main>
    <JobDrawer {...{selected, relatedJobs, openerRef, selectJob, detail, detailError, saving, rejecting, reason, setReason, setRejecting, changeStatus}} />
  </div>;
}
