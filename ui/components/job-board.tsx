"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { focusManager, QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { flushSync } from "react-dom";
import dynamic from "next/dynamic";
import { GlobeBoundary } from "./globe-boundary";
import { useGlobeData } from "./use-globe-data";
import { globePoints } from "@/lib/globe-model";
import { countGlobeRoles } from "@/lib/globe-viewport";
import { loadGlobeStyle } from "@/lib/globe-style";
import { Button } from "./ui/button";
import { ArrowUpRight, Globe } from "lucide-react";
import { JobDetailSchema, JobListResponseSchema, StatusResultSchema, type JobDetail, type StatusPatch } from "@/lib/contracts";
import { jobListRequestPath, refreshVisitCohort, uniqueJobsById } from "@/lib/job-board-state";
import { applyScoreAnyway, applyConfirmedStatus, boardListKey, cachedVisitCohort, confirmedStatusRevision, confirmListRead, jobDetailQueryOptions, patchCachedDetailStatus } from "@/lib/job-board-query";
import { boardPreferenceStorage, clearBoardPreferences, defaultBoardPreferences, isDefaultBoardPreferences, preferencesForBoardFilter, preferencesForPipelineStatuses, readBoardPreferences, writeBoardPreferences } from "@/lib/job-board-preferences";
import { relevanceLabel } from "@/lib/relevance-label";
import { relativeAge } from "@/lib/job-display";
import { countNewRoleCards, newRolesSince } from "@/lib/new-roles";
import { useNewRoles } from "./use-new-roles";
import { NewRolesPill } from "./new-roles-pill";
import { relatedDuplicateJobs } from "@/lib/job-dedup";
import { filterJobGroups, type ViewOptions } from "@/lib/job-filters";
import { LogoDevAttribution } from "./company-logo";
import { provideLogoMissFetcher } from "@/lib/company-logo-cache";
import { JobToolbar } from "./job-toolbar";
import { ProfileDrawer } from "./profile-drawer";
import { BoardHeader, JobsPanel, JobDrawer, type Filter } from "./job-views";
import { StatusSelect } from "./status-select";
import { isStatusPatchNoop, statusMutationRemovesCard, type StatusChangeResult } from "@/lib/job-status";
import { buttonVariants } from "./ui/button";

// The board is the host that may touch the network; logo tiles only confirm a Logo.dev 404 through this.
provideLogoMissFetcher((input, init) => fetch(input, init));

async function request(path: string, options?: RequestInit): Promise<unknown> {
  const response = await fetch(path, { cache: "no-store", ...options });
  if (!response.ok) {
    const reference = response.headers.get("x-request-id");
    const message = response.status === 503 ? "The database is unavailable. Try again shortly." : "That request could not be completed. Please try again.";
    throw new Error(reference ? `${message} Reference: ${reference}.` : message);
  }
  return response.json();
}

// TanStack v5 defaults to visibilitychange; preserve the board's window-focus contract too.
if (typeof window !== "undefined") focusManager.setEventListener(handleFocus => {
  const focus = () => handleFocus();
  window.addEventListener("focus", focus);
  document.addEventListener("visibilitychange", focus);
  return () => { window.removeEventListener("focus", focus); document.removeEventListener("visibilitychange", focus); };
});

const JobGlobe = dynamic(() => import("./job-globe"), { ssr: false });

// The query cache belongs to this mounted board, including the signed-in user's views.
export function JobBoard() {
  const [client] = useState(() => new QueryClient({ defaultOptions: {
    queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false, refetchOnReconnect: false, networkMode: "always" },
    mutations: { retry: false, networkMode: "always" },
  } }));
  return <QueryClientProvider client={client}><Board /></QueryClientProvider>;
}

function Board() {
  const client = useQueryClient();
  const [preferences, setPreferences] = useState(defaultBoardPreferences);
  const [preferencesReady, setPreferencesReady] = useState(false);
  const { filter, view } = preferences;
  const [selected, setSelected] = useState<string | null>(null);
  const [markSeenOnOpen, setMarkSeenOnOpen] = useState(true);
  const [closingDetail, setClosingDetail] = useState<JobDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [detailRevision, setDetailRevision] = useState(0);
  const [revision, setRevision] = useState(0);
  const [globeOpen, setGlobeOpen] = useState(false);
  const globeTransitioning = useRef(false);
  const pendingGlobeToggle = useRef(false);
  const toggleGlobeRef = useRef<() => void>(() => {});
  const firstGlobeOpen = useRef(true);
  const [arrivalRequest, setArrivalRequest] = useState(0);
  const [viewport, setViewport] = useState<{ key: string; positions: string; evaluated: Set<string>; ids: string[] } | null>(null);
  const [globeMounted, setGlobeMounted] = useState(false);
  const [globeSelected, setGlobeSelected] = useState<string | null>(null);
  const [bubble, setBubble] = useState<{ ids: string[]; place: string } | null>(null);
  const [globeSelectionRequest, setGlobeSelectionRequest] = useState(0);
  const [globeSelectionSource, setGlobeSelectionSource] = useState<"point" | "rail">("rail");
  const [cameraAction, setCameraAction] = useState<{ kind: "location" | "reset"; id: number }>({ kind: "reset", id: 0 });
  const [cameraAway, setCameraAway] = useState(false);
  const [globeWarning, setGlobeWarning] = useState("");
  const listQuery = useQuery({
    queryKey: boardListKey(filter, view.availability, view), enabled: preferencesReady,
    queryFn: async ({ signal }) => {
      const started = confirmedStatusRevision(client);
      const previous = filter === "new-for-me" ? cachedVisitCohort(client, view.availability, view.found_within) : null;
      const next = uniqueJobsById(JobListResponseSchema.parse(await request(jobListRequestPath({ filter, availability: view.availability, limit: 1000, fit: view.fit, statuses: view.statuses, sort: view.sort, found_within: view.found_within }), { signal })).jobs);
      const read = filter === "new-for-me" ? await refreshVisitCohort(previous, next, async ids => {
        const query = new URLSearchParams({ filter: "all", availability: "all", limit: "100", ids: ids.join(",") });
        return JobListResponseSchema.parse(await request(`/api/jobs?${query}`, { signal })).jobs;
      }) : next;
      signal.throwIfAborted();
      const jobs = confirmListRead(client, read, filter, started);
      return { jobs, loadedUpdatedAt: jobs.reduce<string | null>((last, job) => !last || job.last_seen_at > last ? job.last_seen_at : last, null) };
    },
  });
  const jobs = useMemo(() => listQuery.data?.jobs ?? [], [listQuery.data]);
  const loadedUpdatedAt = listQuery.data?.loadedUpdatedAt ?? null;
  const loading = listQuery.isPending;
  const listError = listQuery.error?.message ?? "";
  const error = listQuery.data ? "" : listError;
  const refreshWarning = listQuery.data && listError ? `${listError} Showing previous results.` : "";
  // detailRevision scopes one automatic Seen per opening; the read itself is shared with hover prefetch.
  const detailQuery = useQuery({ ...jobDetailQueryOptions(client, selected), enabled: selected !== null });
  const prefetchDetail = useCallback((id: string) => { void client.prefetchQuery(jobDetailQueryOptions(client, id)); }, [client]);
  const detail = selected === null ? closingDetail : detailQuery.data ?? null;
  const globe = useGlobeData(globeOpen, filter, view.availability, revision, jobs);
  const patchGlobeStatus = globe.patchStatus;
  const globeActive = globeOpen && !globe.failure;
  const displayJobs = globeActive && globe.data ? globe.data.jobs : jobs;
  const relatedId = selected ?? detail?.id;
  const relatedJobs = useMemo(() => relatedId ? relatedDuplicateJobs(displayJobs, relatedId, detail) : [], [displayJobs, relatedId, detail]);
  const groups = useMemo(() => filterJobGroups(displayJobs, view), [displayJobs, view]);
  const points = useMemo(() => globePoints(groups, globe.data?.points ?? []), [groups, globe.data]);
  const positionKey = useMemo(() => globe.data?.points.map(point => `${point.posting_id}:${point.lng}:${point.lat}`).sort().join("|") ?? "", [globe.data]);
  const viewportKey = `${filter}/${view.availability}`;
  const visiblePostingIds = globeActive && globe.data && viewport?.key === viewportKey && viewport.positions === positionKey && points.every(point => viewport.evaluated.has(point.posting_id)) ? viewport.ids : undefined;
  const updateViewport = useCallback((ids: string[]) => {
    if (!globeActive || !globe.data) return;
    const evaluated = new Set(points.map(point => point.posting_id));
    setViewport(current => current?.key === viewportKey && current.positions === positionKey && current.evaluated.size === evaluated.size && points.every(point => current.evaluated.has(point.posting_id)) && current.ids.length === ids.length && current.ids.every((id, index) => id === ids[index]) ? current : { key: viewportKey, positions: positionKey, evaluated, ids });
  }, [globeActive, globe.data, points, positionKey, viewportKey]);
  const globeCounts = globe.data ? countGlobeRoles(groups, points) : null;
  const selectedGlobeGroup = groups.find(group => [group.job, ...group.alternates].some(job => job.id === globeSelected));
  const activeGlobeSelection = selectedGlobeGroup ? globeSelected : null;
  useEffect(() => {
    if (!bubble || groups.some(group => bubble.ids.includes(group.job.id))) return;
    let current = true;
    queueMicrotask(() => { if (current) setBubble(null); });
    return () => { current = false; };
  }, [bubble, groups]);
  useEffect(() => {
    const prefetch = () => { void import("./job-globe"); void loadGlobeStyle().catch(() => {}); };
    if ("requestIdleCallback" in window) {
      const handle = window.requestIdleCallback(prefetch, { timeout: 2000 });
      return () => window.cancelIdleCallback(handle);
    }
    const handle = setTimeout(prefetch, 800);
    return () => clearTimeout(handle);
  }, []);
  function failGlobe() { setGlobeOpen(false); setGlobeMounted(false); setViewport(null); setGlobeWarning("The globe could not load. Your list is still here."); }
  function focusGlobeRow(id: string | null, source: "point" | "rail" = "rail") {
    setGlobeSelected(id);
    setGlobeSelectionSource(source);
    setGlobeSelectionRequest(value => value + 1);
    const rowId = groups.find(group => [group.job, ...group.alternates].some(job => job.id === id))?.job.id;
    if (rowId) requestAnimationFrame(() => {
      const row = document.querySelector<HTMLElement>(`[data-posting-id="${rowId}"]`);
      const rail = row?.closest<HTMLElement>(".globe-rail-list");
      if (!row || !rail || rail.scrollHeight <= rail.clientHeight) return;
      // Click-only scroll, block "nearest". The rail header sits above the list, so the list's own edges are the bounds.
      const card = row.getBoundingClientRect(), viewport = rail.getBoundingClientRect();
      const delta = card.top < viewport.top + 3 ? card.top - viewport.top - 3 : card.bottom > viewport.bottom ? card.bottom - viewport.bottom + 3 : 0;
      if (delta) rail.scrollTo({ top: rail.scrollTop + delta, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    });
  }
  const preferenceStorageRef = useRef<Storage | null>(null);
  const filterRef = useRef<Filter>(filter);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const newRolesCutoff = useMemo(() => newRolesSince(jobs), [jobs]);
  const newRoles = useNewRoles(preferencesReady && !loading && !error, filter, view.availability, newRolesCutoff, view.found_within);
  const newRoleCount = useMemo(() => countNewRoleCards(jobs, newRoles.jobs, view), [jobs, newRoles.jobs, view]);
  const refetchList = listQuery.refetch;
  const requestRefresh = useCallback(() => {
    client.removeQueries({ queryKey: ["board-list"], type: "inactive" });
    void client.invalidateQueries({ queryKey: ["board-list"], type: "active", refetchType: "none" });
    void refetchList();
    setRevision(value => value + 1);
  }, [client, refetchList]);
  const retry = useCallback(() => { void client.resetQueries({ queryKey: ["board-list"], type: "active" }); setRevision(value => value + 1); }, [client]);
  const statusMutation = useMutation({
    scope: { id: "board-status" },
    mutationFn: async ({ id, patch }: { id: string; patch: StatusPatch }) => StatusResultSchema.parse(await request(`/api/jobs/${id}/status`, {
      method: "PATCH", headers: { "Content-Type": "application/json", "X-Job-Radar-Status-Version": "2" }, body: JSON.stringify(patch),
    })),
    onSuccess: (result, { id, patch }) => {
      const automatic = "automatic" in patch && Boolean(patch.automatic);
      applyConfirmedStatus(client, id, result, automatic);
      patchCachedDetailStatus(client, id, result);
      patchGlobeStatus(id, result, !automatic && statusMutationRemovesCard(filterRef.current, result.status));
    },
  });
  // Opening a role must not queue behind, or disable, a manual save.
  const scoreAnyway = useMutation({
    mutationFn: async (id: string) => JobDetailSchema.parse(await request(`/api/jobs/${id}/score-anyway`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    })),
    onSuccess(job) {
      applyScoreAnyway(client, job);
      patchGlobeStatus(job.id, { status: job.status, reason: job.status_reason }, true);
      setDetailError("");
      requestRefresh();
    },
    onError(cause) { setDetailError(cause.message); },
  });
  const automaticSeen = useMutation({
    mutationFn: async ({ id, signal }: { id: string; signal: AbortSignal }) => StatusResultSchema.parse(await request(`/api/jobs/${id}/status`, {
      method: "PATCH", headers: { "Content-Type": "application/json", "X-Job-Radar-Status-Version": "2" }, body: JSON.stringify({ status: "seen", automatic: true }), signal,
    })),
  });
  const markSeen = automaticSeen.mutateAsync;
  const saving = statusMutation.isPending;
  const mutateStatus = statusMutation.mutateAsync;
  const automaticSelection = useRef<string | null>(null);
  // Readiness is the loaded role, not the body object: a stale-cache refresh replaces the body
  // mid-PATCH and must not abort this opening's Seen. Close and switch still cancel it.
  const loadedDetailId = detailQuery.data?.id ?? null;
  useEffect(() => {
    if (!selected || !loadedDetailId || !markSeenOnOpen || filter === "not-scored") return;
    const selection = `${selected}/${detailRevision}`;
    if (automaticSelection.current === selection) return;
    automaticSelection.current = selection;
    const controller = new AbortController();
    void markSeen({ id: selected, signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      applyConfirmedStatus(client, selected, result, true);
      patchCachedDetailStatus(client, selected, result);
      patchGlobeStatus(selected, result, false);
    }).catch(cause => {
      if (!controller.signal.aborted) setDetailError(cause instanceof Error ? cause.message : "Could not open this job.");
    });
    return () => controller.abort();
  }, [client, selected, detailRevision, loadedDetailId, markSeenOnOpen, markSeen, patchGlobeStatus, filter]);
  function showNewRoles() {
    newRoles.dismiss();
    // The pill unmounts on click; keep focus and the reader at the top of the refreshed list.
    headingRef.current?.focus({ preventScroll: true });
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";
    window.scrollTo({ top: 0, behavior });
    document.querySelector(".globe-rail-list")?.scrollTo({ top: 0, behavior });
    requestRefresh();
  }
  function selectJob(id: string | null, markSeen = true) {
    setMarkSeenOnOpen(markSeen);
    if (id === null) setClosingDetail(detail);
    else setDetailRevision(value => value + 1);
    setSelected(id);
    // Keep the previous body intact during the sheet closing transition.
    if (id !== null) setDetailError("");
  }
  function openGlobeJob(id: string) {
    focusGlobeRow(id, "point");
    const rowId = points.find(point => point.posting_id === id)?.rowId;
    openerRef.current = document.activeElement instanceof HTMLButtonElement ? document.activeElement
      : document.querySelector<HTMLButtonElement>(`[data-posting-id="${rowId}"] > button`);
    selectJob(id, false);
  }
  function retryDetail() {
    if (!selected || saving) return;
    setDetailError("");
    setDetailRevision(value => value + 1);
    void client.resetQueries({ queryKey: jobDetailQueryOptions(client, selected).queryKey, exact: true });
  }
  function prepareListSource(value: Filter, availability: ViewOptions["availability"]) {
    filterRef.current = value;
    if (value === "new-for-me") client.removeQueries({ queryKey: ["board-list", value, availability] });
  }
  function chooseFilter(value: Filter) { if (value === filter) return; prepareListSource(value, view.availability); setPreferences((current) => preferencesForBoardFilter(current, value)); }
  function changeView(next: ViewOptions) {
    if (next.location !== view.location) setCameraAction(current => ({ kind: "location", id: current.id + 1 }));
    const nextFilter = next.statuses.length > 0 ? "all" : filter;
    if (nextFilter !== filter || next.availability !== view.availability) prepareListSource(nextFilter, next.availability);
    setPreferences((current) => preferencesForPipelineStatuses({ ...current, view: next }, next.statuses));
  }
  function setSearch(search: string) { setPreferences((current) => ({ ...current, view: { ...current.view, search } })); }
  function resetView() {
    setCameraAction(current => ({ kind: "reset", id: current.id + 1 }));
    const storage = preferenceStorageRef.current ?? boardPreferenceStorage(window);
    if (storage) clearBoardPreferences(storage);
    const next = defaultBoardPreferences();
    prepareListSource(next.filter, next.view.availability);
    setPreferences(next);
  }
  function toggleGlobe() {
    if (globeTransitioning.current) { pendingGlobeToggle.current = !pendingGlobeToggle.current; return; }
    const next = !globeActive;
    const swap = () => {
      flushSync(() => {
        if (next) setGlobeMounted(true);
        else setBubble(null);
        setGlobeOpen(next);
        setGlobeWarning("");
        if (globe.failure) { setViewport(null); setRevision(value => value + 1); }
      });
      window.dispatchEvent(new Event("job-globe-layout"));
    };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !document.startViewTransition) {
      swap();
      if (next) firstGlobeOpen.current = false;
      return;
    }
    const visible = [...document.querySelectorAll<HTMLElement>("[data-globe-card]")]
      .filter(card => { const box = card.getBoundingClientRect(); return box.width > 0 && box.bottom > 0 && box.top < innerHeight; })
      .slice(0, 12).map(card => card.dataset.globeCard);
    const nameCards = () => document.querySelectorAll<HTMLElement>("[data-globe-card]").forEach(card => {
      if (visible.includes(card.dataset.globeCard)) {
        card.style.viewTransitionName = `card-${card.dataset.globeCard}`;
        card.style.setProperty("view-transition-class", "globe-card");
      }
    });
    nameCards();
    globeTransitioning.current = true;
    document.documentElement.dataset.globeTransition = next ? "on" : "off";
    const transition = document.startViewTransition(() => { swap(); nameCards(); });
    const finish = () => {
      document.querySelectorAll<HTMLElement>("[data-globe-card]").forEach(card => { card.style.viewTransitionName = ""; card.style.removeProperty("view-transition-class"); });
      delete document.documentElement.dataset.globeTransition;
      globeTransitioning.current = false;
      if (pendingGlobeToggle.current) { pendingGlobeToggle.current = false; queueMicrotask(() => toggleGlobeRef.current()); }
      if (next && firstGlobeOpen.current) setArrivalRequest(value => value + 1);
      if (next) firstGlobeOpen.current = false;
    };
    void transition.finished.then(finish, finish);
  }
  useLayoutEffect(() => { toggleGlobeRef.current = toggleGlobe; });

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      const target = event.target;
      if (target instanceof HTMLElement && (target.isContentEditable || target.closest("input, textarea, select, [role='combobox'], [role='dialog']"))) return;
      if (selected) return;
      if (event.key.toLowerCase() === "g" && !event.repeat) { event.preventDefault(); toggleGlobe(); }
      if (event.key === "Escape" && bubble) { event.preventDefault(); setBubble(null); return; }
      if (event.key === "Escape" && globeSelected) { event.preventDefault(); setGlobeSelected(null); }
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  });

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

  async function changeStatus(patch: StatusPatch): Promise<StatusChangeResult> {
    if (!detail || saving || selected !== detail.id) return { ok: false };
    if (isStatusPatchNoop(detail, patch)) return { ok: true };
    setDetailError("");
    try {
      await mutateStatus({ id: detail.id, patch });
      return { ok: true };
    } catch (cause) {
      // The status select reports this inline; the drawer banner stays for detail-loading errors.
      return { ok: false, error: cause instanceof Error ? cause.message : "Could not update status." };
    }
  }
  if (!preferencesReady) return <div className="min-h-screen bg-background text-foreground">
    <BoardHeader><ProfileDrawer onUpdated={requestRefresh} /></BoardHeader>
    <main className="grid min-h-[35rem] place-items-center px-4 py-16"><p role="status" className="text-sm text-muted-foreground">Restoring saved view…</p></main>
  </div>;

  const sortLabel = {found: "Recently found", posted: "Posted date · found when unknown", fit: "Best fit first", seniority: "Junior first · unknown last"}[view.sort];

  const globeToggle = <Button variant={globeActive ? "default" : "outline"} className={`size-10 p-0 ${globeActive ? "shadow-[inset_0_0_0_2px_color-mix(in_oklch,var(--primary-foreground)_35%,transparent)]" : ""}`} aria-label="Globe" title="Globe" aria-pressed={globeActive} onClick={toggleGlobe}><Globe aria-hidden="true" /></Button>;
  const globeMeta = <>{globeActive && globeCounts && <><span>{globeCounts.mapped} on the globe · {globeCounts.unmapped} without a location</span>{points.length > 5000 && <span>Showing a sample of 5,000 roles</span>}</>}{globeActive && !globe.data && <span role="status">Loading all role locations…</span>}{(globe.failure || globeWarning) && <span role="alert" className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-2 py-1 font-medium text-amber-800 dark:text-amber-200">{globeWarning || globe.failure} Use Globe to retry.</span>}</>;
  return <div className={`bg-background text-foreground ${globeActive ? "board-globe-open" : "min-h-screen"}`}>
    <BoardHeader><ProfileDrawer onUpdated={requestRefresh} /></BoardHeader>
    <main className="board-main w-full px-4 py-3 sm:px-6 lg:px-8">
      <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground"><h1 ref={headingRef} tabIndex={-1} className="mr-auto text-lg font-semibold text-foreground outline-none">Your roles</h1>{globeActive && <span className="board-mobile-globe-counts">{globeMeta}</span>}<span className="board-heading-regular-meta rounded-full bg-muted px-2 py-1">{groups.length} roles</span>{relativeAge(loadedUpdatedAt) && <span className="board-heading-regular-meta rounded-full bg-muted px-2 py-1" title="Last time a role in this view was observed">Updated {relativeAge(loadedUpdatedAt)}</span>}</div>
      <JobsPanel prefetchDetail={prefetchDetail} notice={<NewRolesPill count={newRoleCount} truncated={newRoles.truncated} onShow={showNewRoles} />} {...{visiblePostingIds, filter, groups, openerRef, chooseFilter, setSearch, sortLabel, globeMeta, bubble}} clearBubble={() => setBubble(null)} onWholeWorld={() => { setBubble(null); setCameraAction(current => ({ kind: "location", id: current.id + 1 })); }} error={globeActive ? "" : error} jobs={displayJobs} loading={globeActive ? !globe.data || !visiblePostingIds : loading} selectJob={globeActive ? focusGlobeRow : selectJob} openDetail={id => selectJob(activeGlobeSelection ?? id)} selectedId={globeActive ? selectedGlobeGroup?.job.id : null} globeOpen={globeActive} globe={globeMounted && <GlobeBoundary onFailure={failGlobe}><JobGlobe active={globeActive} dataReady={Boolean(globe.data)} points={points} selected={activeGlobeSelection} selectionRequest={globeSelectionRequest} arrivalRequest={arrivalRequest} selectionSource={globeSelectionSource} location={view.location} cameraAction={cameraAction} onCameraAwayChange={setCameraAway} onViewportChange={updateViewport} onSelect={openGlobeJob} onBubble={(ids, place) => setBubble({ ids, place })} bubbleIds={bubble?.ids ?? []} onClearBubble={() => setBubble(null)} onFailure={failGlobe} /></GlobeBoundary>} search={view.search} reload={retry} resultLimit={globeActive ? Infinity : 1000} toolbar={<JobToolbar filtersCollapsed={preferences.filtersCollapsed ?? false} onFiltersCollapsedChange={filtersCollapsed => setPreferences(current => ({ ...current, filtersCollapsed }))} globeOpen={globeActive} jobs={displayJobs} options={view} onChange={changeView} onReset={resetView} canReset={!isDefaultBoardPreferences(preferences) || (globeActive && cameraAway)} actions={globeToggle} />} />
      {refreshWarning && <p role="status" className="mt-4 text-xs text-muted-foreground">{refreshWarning}</p>}
      {!globeActive && <LogoDevAttribution />}
    </main>
    <JobDrawer
      retryDetail={retryDetail}
      retryDisabled={saving || selected === null}
      selectedJob={displayJobs.find((job) => job.id === selected)}
      {...{selected, relatedJobs, openerRef, detail}}
      detailError={detailError || detailQuery.error?.message || ""}
      selectJob={id => selectJob(id, markSeenOnOpen)}
      actions={detail ? <>
        <p className="text-xs capitalize text-muted-foreground">Source: {detail.source}</p>
        {detail.relevance_filtered && <div className="space-y-2">
          <p className="text-sm">Not scored (filtered): {relevanceLabel(detail.relevance_rule)}</p>
          <Button disabled={scoreAnyway.isPending} onClick={() => scoreAnyway.mutate(detail.id)}>{scoreAnyway.isPending ? "Queuing…" : "Score anyway"}</Button>
          <p className="text-xs text-muted-foreground">Moves this role back to the board for the next analysis run.</p>
        </div>}
        <div className="flex flex-wrap items-end gap-3">
          <StatusSelect key={detail.id} job={detail} saving={saving || selected === null} changeStatus={changeStatus} />
          <a className={buttonVariants({className:"w-fit"})} href={detail.apply_url ?? detail.url} target="_blank" rel="noopener noreferrer">Apply on company site <ArrowUpRight aria-hidden="true" /></a>
        </div>
        {scoreAnyway.isSuccess && scoreAnyway.data.id === detail.id && <p role="status" className="text-xs text-muted-foreground">Queued for scoring. It will return to the board on the next analysis run.</p>}
        {detail.status_reason && <p className="text-xs text-muted-foreground">Status reason: {detail.status_reason}</p>}
      </> : undefined}
    />
  </div>;
}
