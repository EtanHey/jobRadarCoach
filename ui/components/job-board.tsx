"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Search } from "lucide-react";
import { JobDetailResponseSchema, JobListResponseSchema, StatusResponseSchema, type JobDetail, type JobSummary, type StatusPatch } from "@/lib/contracts";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";

type Filter = "all" | "new-for-me" | "seen" | "saved" | "applied" | "rejected";
const filters: Record<Filter, string> = { all: "All roles", "new-for-me": "New for me", seen: "Seen", saved: "Saved", applied: "Applied", rejected: "Rejected" };
const date = (value: string | null) => value ? new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "Date unavailable";
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
  const opener = useRef<HTMLButtonElement | null>(null);
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
    if (!selected) return;
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
    <header className="border-b border-[#dce3dc] bg-white"><div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-5 sm:px-8">
      <Link href="/" className="flex items-center gap-3 font-semibold tracking-tight"><span aria-hidden="true" className="grid size-9 place-items-center rounded-xl bg-[#173f31] text-white">J</span>Job Radar <span className="hidden font-normal text-[#76867c] sm:inline">/ Coach</span></Link><span className="rounded-full bg-[#eef3ed] px-3 py-1 text-xs">Your private workspace</span>
    </div></header>
    <main className="mx-auto max-w-7xl px-5 py-10 sm:px-8 sm:py-14">
      <div className="mb-9 flex flex-wrap items-end justify-between gap-5"><div><p className="mb-3 text-xs font-semibold tracking-[0.2em] text-[#687d6e]">THE JOB SEARCH, WITH CONTEXT</p><h1 className="text-3xl font-semibold tracking-tight sm:text-5xl">Find your next good fit.</h1><p className="mt-4 max-w-xl text-sm leading-6 text-[#66766b]">Your roles, your priorities. Review the evidence, keep what matters, and make your next move.</p></div></div>
      <section aria-label="Job search" className="rounded-2xl border border-[#dce3dc] bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#e5eae3] p-5"><div className="flex max-w-full gap-1 overflow-x-auto" aria-label="Job filters">
          {(Object.keys(filters) as Filter[]).map((item) => <button key={item} aria-pressed={filter === item} onClick={() => { if (item !== filter) chooseFilter(item); }} className={`shrink-0 rounded-lg px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 ${filter === item ? "bg-[#193e2f] text-white" : "text-[#6b786f] hover:bg-[#f0f3ed]"}`}>{filters[item]}</button>)}
        </div><label className="flex w-full items-center gap-2 rounded-lg border border-[#e0e5dd] px-3 py-2 sm:w-64"><Search size={16} aria-hidden="true" /><span className="sr-only">Search loaded jobs</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search role, company, stack" className="min-w-0 flex-1 text-sm outline-none" /></label></div>
        <div className="flex justify-between px-5 py-4 text-xs text-[#728175]"><span aria-live="polite">{loading ? "Loading roles…" : `${visible.length} ${visible.length === 1 ? "role" : "roles"} in this view`}{jobs.length === 250 ? " · latest 250" : ""}</span><span>{filter === "new-for-me" ? "Ranked for you" : "Newest first"}</span></div>
        {error && <div role="alert" className="m-5 rounded-xl bg-red-50 p-5 text-sm text-red-800">{error}<Button variant="outline" className="ml-3" onClick={reload}>Retry</Button></div>}
        {!loading && !error && visible.length === 0 && <div className="px-6 py-16 text-center"><h2 className="text-xl font-medium">No roles in this view yet.</h2><p className="mt-2 text-sm text-[#728175]">Try another filter or clear your search.</p></div>}
        {!error && <div className="divide-y divide-[#e7ebe4]">{visible.map((job) => <button key={job.id} onClick={(event) => { opener.current = event.currentTarget; selectJob(job.id); }} className="group flex w-full items-start gap-4 px-5 py-6 text-left hover:bg-[#f8faf6] focus-visible:bg-[#eef4ea] focus-visible:outline-2 sm:px-6">
          <span aria-hidden="true" className="hidden size-11 shrink-0 items-center justify-center rounded-xl border border-[#e2e8dd] bg-[#f3f6ef] text-lg font-semibold text-[#65795b] sm:flex">{job.company.slice(0, 1)}</span>
          <span className="min-w-0 flex-1"><span className="mb-1 block text-xs font-medium text-[#6c7b70]">{job.company}</span><span className="block text-base font-semibold sm:text-lg">{job.title}</span><span className="mt-2 block text-xs text-[#7c887e]">{job.location ?? "Location not extracted"} · {date(job.posted_at)} · <span className="capitalize">{job.status}</span></span><span className="mt-3 flex flex-wrap gap-1.5">{job.stack.slice(0, 4).map((stack) => <span key={stack} className="rounded-md bg-[#f0f3ee] px-2 py-1 text-[11px] text-[#67765e]">{stack}</span>)}</span></span>
          <span className="flex shrink-0 flex-col items-end gap-2"><span className={`rounded-lg px-3 py-2 text-sm font-semibold ${job.score === null ? "bg-[#f3f4ef] text-[#8a9486]" : "bg-[#eaf2df] text-[#4c6e2d]"}`}>{job.score === null ? "Unscored" : `${job.score}/100`}</span><span className="text-xs capitalize text-[#7a8776]">{job.recommendation ?? "Awaiting analysis"}</span><ArrowUpRight aria-hidden="true" size={16} className="mt-2 text-[#a0ad98]" /></span>
        </button>)}</div>}
      </section><p className="mt-5 text-xs text-[#82907f]">Scores are a starting point. Open a role to see the reasoning and original description.</p>
    </main>
    <Sheet open={selected !== null} onOpenChange={(open) => { if (!open) selectJob(null); }}><SheetContent finalFocus={opener} className="overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-2xl">
      <SheetHeader className="border-b p-6 pr-12"><SheetTitle>{detail?.title ?? "Job details"}</SheetTitle><SheetDescription>{detail?.company ?? "Loading the role and its evidence…"}</SheetDescription></SheetHeader>
      <div className="space-y-6 p-6">{detailError && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{detailError}</p>}{detail && <>
        <div className="flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-muted px-3 py-1 capitalize">{detail.status}</span><span className="rounded-full bg-muted px-3 py-1">{detail.location ?? "Location unknown"}</span><span className="rounded-full bg-muted px-3 py-1">{detail.remote === null ? "Remote policy unknown" : detail.remote ? "Remote" : "On site / hybrid"}</span></div>
        <div className="rounded-xl border bg-[#f4f7ef] p-5"><p className="text-xs uppercase tracking-wider text-muted-foreground">Fit assessment</p><p className="mt-2 text-3xl font-semibold">{detail.score === null ? "Not scored yet" : `${detail.score} / 100`}</p><p className="mt-3 text-sm leading-6">{detail.fit_line ?? "Run the batch pipeline to extract and score this posting."}</p>{detail.recommendation && <p className="mt-2 text-sm capitalize">Recommendation: {detail.recommendation}</p>}</div>
        {detail.reasons.length > 0 && <section><h2 className="font-semibold">Why this score</h2><ul className="mt-3 space-y-3">{detail.reasons.map((item, index) => <li key={index} className="rounded-lg border p-3 text-sm"><span className="mb-1 block text-xs capitalize text-muted-foreground">{item.factor.replaceAll("_", " ")} · {item.assessment}</span>{item.detail}</li>)}</ul></section>}
        <div className="flex flex-wrap gap-2"><Button disabled={saving} onClick={() => changeStatus({ status: "saved" })}>Save role</Button><Button variant="outline" disabled={saving} onClick={() => changeStatus({ status: "applied" })}>Mark applied</Button><Button variant="outline" disabled={saving} onClick={() => setRejecting(true)}>Reject</Button></div>
        {rejecting && <form onSubmit={(event) => { event.preventDefault(); if (reason.trim()) changeStatus({ status: "rejected", reason }); }} className="space-y-2"><label htmlFor="reject-reason" className="block text-sm font-medium">Why isn’t this a fit?</label><textarea id="reject-reason" required maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} className="min-h-24 w-full rounded-lg border p-3 text-sm" /><div className="flex gap-2"><Button disabled={saving || !reason.trim()} type="submit">Confirm rejection</Button><Button variant="ghost" type="button" onClick={() => setRejecting(false)}>Cancel</Button></div></form>}
        {detail.status_reason && <p className="text-sm text-muted-foreground">Rejection reason: {detail.status_reason}</p>}
        <a href={detail.apply_url ?? detail.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 text-sm font-semibold underline underline-offset-4">Open original posting <ArrowUpRight size={14} aria-hidden="true" /></a>
        <section><h2 className="mb-3 font-semibold">Job description</h2><p className="whitespace-pre-wrap text-sm leading-7 text-muted-foreground">{detail.raw_jd ?? "No full description has been fetched for this posting yet. Open the original posting for details."}</p></section>
      </>}</div>
    </SheetContent></Sheet>
  </div>;
}
