"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { GlobeBoundary } from "./globe-boundary";
import { useGlobeData } from "./use-globe-data";
import { globePoints } from "@/lib/globe-model";
import { countGlobeRoles } from "@/lib/globe-viewport";
import { Button } from "./ui/button";
import { ArrowUpRight } from "lucide-react";
import { JobListResponseSchema, StatusResponseSchema, type JobDetail, type JobSummary, type StatusPatch } from "@/lib/contracts";
import { createBoundedJobListCache, createDetailCoordinator, createListRefreshCoordinator, createRequestFence, jobListCacheKey, jobListRequestPath, retainVisitCohort, uniqueJobsById, updateJobStatus } from "@/lib/job-board-state";
import { boardPreferenceStorage, clearBoardPreferences, defaultBoardPreferences, isDefaultBoardPreferences, preferencesForBoardFilter, preferencesForPipelineStatuses, readBoardPreferences, writeBoardPreferences } from "@/lib/job-board-preferences";
import { loadJobDetail } from "@/lib/job-detail-request";
import { relativeAge } from "@/lib/job-display";
import { relatedDuplicateJobs } from "@/lib/job-dedup";
import { filterJobGroups, type ViewOptions } from "@/lib/job-filters";
import { JobToolbar } from "./job-toolbar";
import { ProfileDrawer } from "./profile-drawer";
import { BoardHeader, JobsPanel, JobDrawer, type Filter } from "./job-views";
import { StatusSelect } from "./status-select";
import { buttonVariants } from "./ui/button";

async function request(path: string, options?: RequestInit): Promise<unknown> {
  const response = await fetch(path, { cache: "no-store", ...options });
  if (!response.ok) {
    const reference = response.headers.get("x-request-id");
    const message = response.status === 503 ? "The database is unavailable. Try again shortly." : "That request could not be completed. Please try again.";
    throw new Error(reference ? `${message} Reference: ${reference}.` : message);
  }
  return response.json();
}

const JobGlobe = dynamic(() => import("./job-globe"), { ssr: false });

type CachedList = { jobs: JobSummary[]; loadedUpdatedAt: string | null };
const listKey = (filter: Filter, availability: ViewOptions["availability"]) => jobListCacheKey({ filter, availability, limit: 1000 });

export function JobBoard() {
  const [preferences, setPreferences] = useState(defaultBoardPreferences);
  const [preferencesReady, setPreferencesReady] = useState(false);
  const { filter, view } = preferences;
  const [loadedUpdatedAt, setLoadedUpdatedAt] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [markSeenOnOpen, setMarkSeenOnOpen] = useState(true);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [detailRevision, setDetailRevision] = useState(0);
  const [saving, setSaving] = useState(false);
  const [revision, setRevision] = useState(0);
  const [globeOpen, setGlobeOpen] = useState(false);
  const [viewport, setViewport] = useState<{ key: string; ids: string[] } | null>(null);
  const [globeMounted, setGlobeMounted] = useState(false);
  const [globeSelected, setGlobeSelected] = useState<string | null>(null);
  const [globeWarning, setGlobeWarning] = useState("");
  const globe = useGlobeData(globeOpen, filter, view.availability, revision, jobs);
  const patchGlobeStatus = globe.patchStatus;
  const globeActive = globeOpen && !globe.failure;
  const displayJobs = globeActive && globe.data ? globe.data.jobs : jobs;
  const groups = useMemo(() => filterJobGroups(displayJobs, view), [displayJobs, view]);
  const points = useMemo(() => globePoints(groups, globe.data?.points ?? []), [groups, globe.data]);
  const viewportKey = `${filter}/${view.availability}`;
  const visiblePostingIds = globeActive && globe.data && viewport?.key === viewportKey ? viewport.ids : undefined;
  const updateViewport = useCallback((ids: string[]) => {
    if (!globeActive || !globe.data) return;
    setViewport(current => current?.key === viewportKey && current.ids.length === ids.length && current.ids.every((id, index) => id === ids[index]) ? current : { key: viewportKey, ids });
  }, [globeActive, globe.data, viewportKey]);
  const globeCounts = globe.data ? countGlobeRoles(groups, points) : null;
  const selectedGlobeGroup = groups.find(group => [group.job, ...group.alternates].some(job => job.id === globeSelected));
  const activeGlobeSelection = selectedGlobeGroup ? globeSelected : null;
  function failGlobe() { setGlobeOpen(false); setGlobeMounted(false); setViewport(null); setGlobeWarning("The globe could not load. Your list is still here."); }
  function focusGlobeRow(id: string | null) {
    setGlobeSelected(id);
    const rowId = groups.find(group => [group.job, ...group.alternates].some(job => job.id === id))?.job.id;
    if (rowId) requestAnimationFrame(() => {
      const row = document.querySelector<HTMLElement>(`[data-posting-id="${rowId}"]`);
      const rail = row?.closest<HTMLElement>(".globe-rail");
      if (row && rail && rail.scrollHeight > rail.clientHeight) rail.scrollTop += row.getBoundingClientRect().top - rail.getBoundingClientRect().top - 3;
    });
  }
  const [connection, setConnection] = useState("Connecting live updates…");
  const [detailCoordinator] = useState(createDetailCoordinator);
  const [refreshWarning, setRefreshWarning] = useState("");
  const detailRequestRef = useRef<AbortController | null>(null);
  const listCacheRef = useRef(createBoundedJobListCache<CachedList>());
  const listRequestFenceRef = useRef(createRequestFence());
  const listRefreshCoordinatorRef = useRef(createListRefreshCoordinator());
  const realtimeReadyRef = useRef(false);
  const readyRetryUsedRef = useRef(false);
  const visitCohortRef = useRef<JobSummary[] | null>(null);
  const preferenceStorageRef = useRef<Storage | null>(null);
  const filterRef = useRef<Filter>(filter);
  const hasLoadedRef = useRef(false);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const invalidateListCache = useCallback(() => { listRequestFenceRef.current.invalidate(); listRefreshCoordinatorRef.current.cancelRequest(); listCacheRef.current.clear(); }, []);
  const requestRefresh = useCallback(() => { invalidateListCache(); setError(""); setRevision((value) => value + 1); }, [invalidateListCache]);
  const retry = useCallback(() => { visitCohortRef.current = null; listCacheRef.current.clear(); hasLoadedRef.current = false; setJobs([]); setLoadedUpdatedAt(null); setRefreshWarning(""); setLoading(true); requestRefresh(); }, [requestRefresh]);
  function selectJob(id: string | null, markSeen = true) {
    setMarkSeenOnOpen(markSeen);
    detailRequestRef.current?.abort();
    detailCoordinator.select(id);
    setSelected(id);
    // Keep the previous body intact during the sheet closing transition.
    if (id !== null) { setDetail(null); setDetailError(""); }
  }
  function openGlobeJob(id: string) {
    focusGlobeRow(id);
    const rowId = points.find(point => point.posting_id === id)?.rowId;
    openerRef.current = document.activeElement instanceof HTMLButtonElement ? document.activeElement
      : document.querySelector<HTMLButtonElement>(`[data-posting-id="${rowId}"] > button`);
    selectJob(id, false);
  }
  function retryDetail() {
    if (!selected || saving) return;
    detailRequestRef.current?.abort();
    detailCoordinator.select(selected);
    setDetailError("");
    setDetailRevision((value) => value + 1);
  }
  function prepareListSource(value: Filter, availability: ViewOptions["availability"]) {
    filterRef.current = value;
    visitCohortRef.current = null;
    const cached = listCacheRef.current.get(listKey(value, availability));
    if (cached) {
      listRefreshCoordinatorRef.current.cancelRequest();
      hasLoadedRef.current = true;
      setJobs(cached.jobs);
      setLoadedUpdatedAt(cached.loadedUpdatedAt);
      setLoading(false);
    } else {
      hasLoadedRef.current = false;
      setJobs([]);
      setLoadedUpdatedAt(null);
      setLoading(true);
    }
    setError(""); setRefreshWarning("");
  }
  function chooseFilter(value: Filter) { if (value === filter) return; prepareListSource(value, view.availability); setPreferences((current) => preferencesForBoardFilter(current, value)); }
  function changeView(next: ViewOptions) {
    const nextFilter = next.statuses.length > 0 ? "all" : filter;
    if (nextFilter !== filter || next.availability !== view.availability) prepareListSource(nextFilter, next.availability);
    setPreferences((current) => preferencesForPipelineStatuses({ ...current, view: next }, next.statuses));
  }
  function setSearch(search: string) { setPreferences((current) => ({ ...current, view: { ...current.view, search } })); }
  function resetView() {
    const storage = preferenceStorageRef.current ?? boardPreferenceStorage(window);
    if (storage) clearBoardPreferences(storage);
    const next = defaultBoardPreferences();
    if (filter !== next.filter || view.availability !== next.view.availability) {
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
    function requestRealtimeListRefresh() {
      if (listRefreshCoordinatorRef.current.requestRefresh()) requestRefresh();
      else listCacheRef.current.clear();
    }
    function refreshListAndDetail() {
      requestRealtimeListRefresh();
      detailRequestRef.current?.abort();
      const read = detailCoordinator.beginRead();
      const id = read.selection.id;
      if (!id) return;
      const controller = new AbortController();
      detailRequestRef.current = controller;
      loadJobDetail(id, controller.signal).then((job) => {
        if (!controller.signal.aborted && detailCoordinator.acceptRead(read)) { setDetail(job); setDetailError(""); }
      }).catch((cause) => { if (!controller.signal.aborted && detailCoordinator.acceptRead(read)) setDetailError(cause instanceof Error ? cause.message : "Could not refresh this job. Try again."); });
    }
    function queueRefresh() { clearTimeout(timer); timer = setTimeout(refreshListAndDetail, 150); }
    events.addEventListener("ready", () => {
      realtimeReadyRef.current = true;
      setConnection("Live updates connected");
      if (listRefreshCoordinatorRef.current.markReady()) requestRealtimeListRefresh();
      else if (!hasLoadedRef.current && !listRefreshCoordinatorRef.current.isRequestPending() && !readyRetryUsedRef.current) {
        readyRetryUsedRef.current = true;
        requestRefresh();
      }
    });
    events.addEventListener("refresh", queueRefresh);
    events.addEventListener("error", () => { listRefreshCoordinatorRef.current.markDisconnected(); setConnection("Reconnecting live updates…"); });
    return () => { events.close(); clearTimeout(timer); detailRequestRef.current?.abort(); };
  }, [detailCoordinator, requestRefresh]);

  useEffect(() => {
    if (!preferencesReady) return undefined;
    const key = listKey(filter, view.availability);
    const cached = listCacheRef.current.get(key);
    if (cached) {
      listRefreshCoordinatorRef.current.cancelRequest();
      hasLoadedRef.current = true;
      setJobs(cached.jobs);
      setLoadedUpdatedAt(cached.loadedUpdatedAt);
      setLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    const generation = listRequestFenceRef.current.capture();
    listRefreshCoordinatorRef.current.beginRequest();
    request(jobListRequestPath({ filter, availability: view.availability, limit: 1000 }), { signal: controller.signal })
      .then((body) => { if (!controller.signal.aborted && listRequestFenceRef.current.isCurrent(generation)) { const next = uniqueJobsById(JobListResponseSchema.parse(body).jobs); const displayed = filter === "new-for-me" ? retainVisitCohort(visitCohortRef.current, next) : next; if (filter === "new-for-me") visitCohortRef.current = displayed; const updatedAt = displayed.reduce<string | null>((last, job) => !last || job.last_seen_at > last ? job.last_seen_at : last, null); listCacheRef.current.set(key, { jobs: displayed, loadedUpdatedAt: updatedAt }); hasLoadedRef.current = true; readyRetryUsedRef.current = false; setRefreshWarning(""); setJobs(displayed); setLoadedUpdatedAt(updatedAt); } })
      .catch((cause: unknown) => { if (!controller.signal.aborted && listRequestFenceRef.current.isCurrent(generation)) { const message = cause instanceof Error ? cause.message : "Could not load jobs."; if (hasLoadedRef.current) setRefreshWarning(`${message} Showing previous results.`); else setError(message); if (realtimeReadyRef.current && !readyRetryUsedRef.current) { readyRetryUsedRef.current = true; queueMicrotask(requestRefresh); } } })
      .finally(() => { if (!controller.signal.aborted && listRequestFenceRef.current.isCurrent(generation)) { const followUp = listRefreshCoordinatorRef.current.finishRequest(); setLoading(false); if (followUp) queueMicrotask(requestRefresh); } });
    return () => controller.abort();
  }, [filter, preferencesReady, requestRefresh, revision, view.availability]);

  useEffect(() => {
    if (!selected) return undefined;
    const identity = detailCoordinator.current();
    if (identity.id !== selected) return undefined;
    const read = detailCoordinator.beginRead();
    const controller = new AbortController();
    let patchStarted = false;
    async function open() {
      try {
        const job = await loadJobDetail(selected!, controller.signal);
        if (controller.signal.aborted) return;
        if (detailCoordinator.acceptRead(read)) setDetail(job);
        if (!markSeenOnOpen) return;
        patchStarted = true;
        const status = StatusResponseSchema.parse(await request(`/api/jobs/${selected}/status`, {
          method: "PATCH", headers: { "Content-Type": "application/json", "X-Job-Radar-Status-Version": "2" }, body: JSON.stringify({ status: "seen", automatic: true }), signal: controller.signal,
        }));
        if (controller.signal.aborted) return;
        if (detailCoordinator.commitMutation(identity)) {
          detailRequestRef.current?.abort();
          visitCohortRef.current = visitCohortRef.current ? updateJobStatus(visitCohortRef.current, selected!, status.status, status.reason) : null;
          setJobs((current) => updateJobStatus(current, selected!, status.status, status.reason));
          setDetail({ ...job, status: status.status, status_reason: status.reason });
          patchGlobeStatus(selected!, status, false);
          requestRefresh();
        }
      } catch (cause) {
        if (!controller.signal.aborted && detailCoordinator.isCurrent(identity) && (patchStarted || detailCoordinator.acceptRead(read))) setDetailError(cause instanceof Error ? cause.message : "Could not open this job.");
      }
    }
    open();
    return () => controller.abort();
  }, [detailCoordinator, requestRefresh, selected, detailRevision, patchGlobeStatus, markSeenOnOpen]);

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
      }
      visitCohortRef.current = visitCohortRef.current ? updateJobStatus(visitCohortRef.current, id, result.status, result.reason) : null;
      setJobs((current) => updateJobStatus(current, id, result.status, result.reason));
      patchGlobeStatus(id, result, filterRef.current === "new-for-me");
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

  const relatedId = selected ?? detail?.id;
  const relatedJobs = relatedId ? relatedDuplicateJobs(displayJobs, relatedId, detail) : [];
  const sortLabel = {found: "Recently found", posted: "Posted date · found when unknown", fit: "Best fit first", seniority: "Junior first · unknown last"}[view.sort];

  return <div className="min-h-screen bg-background text-foreground">
    <BoardHeader><ProfileDrawer onUpdated={requestRefresh} /></BoardHeader>
    <main className="w-full px-4 py-4 sm:px-6 lg:px-8">
      <div className="mb-3 flex items-center gap-2 text-xs text-muted-foreground"><h1 className="mr-auto text-lg font-semibold text-foreground">Your roles</h1><span className="rounded-full bg-muted px-2 py-1">{groups.length} roles</span>{relativeAge(loadedUpdatedAt) && <span className="rounded-full bg-muted px-2 py-1" title="Last time a posting in this view was observed">Updated {relativeAge(loadedUpdatedAt)}</span>}</div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Button variant={globeActive ? "default" : "outline"} aria-pressed={globeActive} onClick={() => { if (!globeActive) setGlobeMounted(true); setGlobeOpen(!globeActive); setViewport(null); setGlobeWarning(""); if (globe.failure) setRevision(value => value + 1); }}>Globe</Button>
        {globeActive && globeCounts && <><span className="rounded-full bg-muted px-3 py-1 text-xs">{globeCounts.unmapped} {globeCounts.unmapped === 1 ? "role" : "roles"} not on globe</span><span className="text-xs text-muted-foreground">{globeCounts.mapped} {globeCounts.mapped === 1 ? "role" : "roles"} mapped{points.length > 5000 ? " · showing a sample of up to 5,000 postings" : ""}</span></>}
        {globeActive && !globe.data && <span role="status" className="text-xs">Loading all posting locations…</span>}
        {(globe.failure || globeWarning) && <span role="alert" className="rounded-lg border border-amber-500 bg-amber-50 px-3 py-2 text-sm text-amber-950">{globeWarning || globe.failure} Use Globe to retry.</span>}
      </div>
      <JobsPanel {...{visiblePostingIds, filter, groups, openerRef, chooseFilter, setSearch, loadedUpdatedAt, sortLabel}} error={globeActive ? "" : error} jobs={displayJobs} loading={globeActive ? !globe.data || !visiblePostingIds : loading} selectJob={globeActive ? focusGlobeRow : selectJob} openDetail={id => selectJob(activeGlobeSelection ?? id)} selectedId={globeActive ? selectedGlobeGroup?.job.id : null} globeOpen={globeActive} globe={globeMounted && <GlobeBoundary onFailure={failGlobe}><JobGlobe active={globeActive} points={points} selected={activeGlobeSelection} onViewportChange={updateViewport} onSelect={openGlobeJob} onFailure={failGlobe} /></GlobeBoundary>} search={view.search} reload={retry} resultLimit={globeActive ? Infinity : 1000} toolbar={<JobToolbar jobs={displayJobs} options={view} onChange={changeView} onReset={resetView} canReset={!isDefaultBoardPreferences(preferences)} />} />
      <p role="status" className="mt-4 text-xs text-muted-foreground">{refreshWarning ? `${connection} ${refreshWarning}` : connection}</p>
    </main>
    <JobDrawer
      retryDetail={retryDetail}
      retryDisabled={saving || selected === null}
      selectedJob={displayJobs.find((job) => job.id === selected)}
      {...{selected, relatedJobs, openerRef, detail, detailError}}
      selectJob={id => selectJob(id, markSeenOnOpen)}
      actions={detail ? <>
        <p className="text-xs capitalize text-muted-foreground">Source: {detail.source}</p>
        <div className="flex flex-wrap items-end gap-3">
          <StatusSelect key={detail.id} job={detail} saving={saving || selected === null} changeStatus={changeStatus} />
          <a className={buttonVariants({className:"w-fit"})} href={detail.apply_url ?? detail.url} target="_blank" rel="noopener noreferrer">Apply on company site <ArrowUpRight aria-hidden="true" /></a>
        </div>
        {detail.status_reason && <p className="text-xs text-muted-foreground">Status reason: {detail.status_reason}</p>}
      </> : undefined}
    />
  </div>;
}
