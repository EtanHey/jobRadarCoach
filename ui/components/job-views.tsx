"use client";
import { workMode } from "@/lib/job-display";
import { groupDuplicateJobs, shortListingId } from "@/lib/job-dedup";
import { CompanyLogo } from "@/components/company-logo";
import type { ReactNode, RefObject } from "react";
import Link from "next/link";
import { ArrowUpRight, Search } from "lucide-react";
import type { JobDetail, JobSummary, StatusPatch } from "@/lib/contracts";
import { Button, buttonVariants } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { statusLabels, type JobStatus } from "@/lib/job-status";
import { StatusSelect } from "./status-select";
import { AssessmentSheet } from "./assessment-sheet";
import { JobDescription } from "./job-description";
import { TechnologyChips } from "./technology-chips";
import { JobCard } from "./job-card";
import { ThemeToggle } from "./theme-toggle";
export type Filter = "all" | "new-for-me" | JobStatus;
const filters: Partial<Record<Filter, string>> = { all: "All roles", "new-for-me": "New for me", seen:"Seen", worth_checking:"Worth checking", applied:"Applied", screen:"Screen", interview_technical:"Technical interview", interview_final:"Final interview", offer:"Offer", contract:"Contract", rejected:"Rejected", archived:"Archived", not_relevant:"Not relevant" };
const date = (value: string | null | undefined) => value ? new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "Unknown";
type Enriched = { source?: string; last_seen_at?: string; experience?: string | null; seniority_origin?: string; extraction_state?: string };
type ViewJob = JobSummary & Enriched;
type Opener = RefObject<HTMLButtonElement | null>;
type RowProps = { job: ViewJob; alternateCount?: number; openerRef: Opener; selectJob: (id: string | null) => void };
type ListProps = { filter: Filter; search: string; jobs: JobSummary[]; visible: JobSummary[]; loading: boolean; error: string; openerRef: Opener; selectJob: RowProps["selectJob"]; chooseFilter: (filter: Filter) => void; setSearch: (value: string) => void; reload: () => void; toolbar?: ReactNode; resultLimit?: number; sortLabel?: string; loadedUpdatedAt?: string | null };
type BodyProps = { detail: JobDetail | null; detailError: string; saving: boolean; rejecting: boolean; reason: string; setReason: (value: string) => void; setRejecting: (value: boolean) => void; changeStatus: (patch: StatusPatch) => Promise<boolean> };
type DrawerProps = BodyProps & { relatedJobs?: JobSummary[]; selected: string | null; openerRef: Opener; selectJob: RowProps["selectJob"] };

export function BoardHeader({children}: {children?: ReactNode}) { return <header className="border-b bg-background/90 backdrop-blur"><div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4 sm:px-8"><Link href="/" className="flex items-center gap-3 font-semibold tracking-tight"><span aria-hidden="true" className="grid size-9 place-items-center rounded-xl bg-foreground/10 text-foreground">J</span>Job Radar <span className="hidden font-normal text-muted-foreground sm:inline">/ Coach</span></Link><div className="flex items-center gap-2">{children}<ThemeToggle /></div></div></header> }

const experienceStatus = (job: ViewJob) => job.experience ?? (job.description_available ? "Check description for experience" : "Description unavailable");

function Placeholder({loading}: {loading: boolean}) { return <div className="grid min-h-[35rem] place-items-center px-6 py-16 text-center"><div>{loading ? <><div className="mx-auto size-8 animate-spin rounded-full border-2 border-muted border-t-primary" /><p className="mt-4 text-sm text-muted-foreground">Loading roles…</p></> : <><h2 className="text-xl font-medium">No roles in this view yet.</h2><p className="mt-2 text-sm text-muted-foreground">Try another filter or clear your search.</p></>}</div></div> }
export function JobsPanel({filter, search, jobs, visible, loading, error, openerRef, selectJob, chooseFilter, setSearch, reload, toolbar, resultLimit = 250, sortLabel}: ListProps) { const groups = groupDuplicateJobs(visible); return <section aria-label="Job search"><div className="mb-3 flex flex-wrap items-center justify-between gap-3"><div className="flex max-w-full gap-1 overflow-x-auto" aria-label="Job filters">{(Object.keys(filters) as Filter[]).map((item) => <button key={item} aria-pressed={filter === item} onClick={() => item !== filter && chooseFilter(item)} className={`shrink-0 rounded-lg px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 ${filter === item ? "bg-foreground/10 text-foreground" : "text-muted-foreground hover:bg-muted"}`}>{filters[item]}</button>)}</div><label className="flex w-full items-center gap-2 rounded-lg border bg-card px-3 py-2 sm:w-80"><Search size={16} aria-hidden="true" /><span className="sr-only">Search loaded jobs by title, company, or stack</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search title, company, or stack" className="min-w-0 flex-1 bg-transparent text-sm outline-none" /></label></div>{toolbar}<div className="flex flex-wrap justify-between gap-2 pb-3 text-xs text-muted-foreground"><span aria-live="polite">{loading ? "Loading roles…" : `${groups.length} ${groups.length === 1 ? "role" : "roles"}`}{jobs.length === resultLimit ? ` · latest ${resultLimit.toLocaleString()}` : ""}</span><span>{sortLabel ?? (filter === "new-for-me" ? "Ranked for you" : "Newest first")}</span></div>{error ? <div role="alert" className="min-h-[35rem] rounded-2xl border border-destructive/20 bg-card p-6 text-sm text-destructive">{error}<Button variant="outline" className="ml-3" onClick={reload}>Retry</Button></div> : loading || visible.length === 0 ? <Placeholder loading={loading} /> : <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">{groups.map(({job, alternates}) => <JobCard job={job} alternateCount={alternates.length} key={job.id} openerRef={openerRef} selectJob={selectJob}><TechnologyChips names={job.stack} presentation="card" /></JobCard>)}</div>}</section> }
export function JobDrawer({ selected, relatedJobs = [], openerRef, selectJob, ...bodyProps }: DrawerProps) {
  const { detail, saving, changeStatus, detailError } = bodyProps;
  return <Sheet open={selected !== null} onOpenChange={open => !open && selectJob(null)}>
    <SheetContent finalFocus={openerRef} className="flex gap-0 overflow-hidden p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-2xl">
      <SheetHeader className="max-h-[45dvh] shrink-0 overflow-y-auto border-b bg-background p-4 pr-12">
        <div className="flex items-center gap-3">{detail && <CompanyLogo company={detail.company} className="size-12" />}<SheetDescription>{detail ? `${detail.company} · Listing ${shortListingId(detail.id)}` : "Loading the role…"}</SheetDescription></div>
        <div className="mt-3 flex items-start justify-between gap-3"><SheetTitle className="text-lg leading-snug">{detail?.title ?? "Job details"}</SheetTitle>{detail && <AssessmentSheet key={detail.id} job={detail} />}</div>
        {detail && <>
          <p className="mt-2 text-xs text-muted-foreground">{detail.location ?? "Location unspecified"} · {workMode(detail.remote)}</p>
          <p className="mt-1 text-xs text-muted-foreground">{experienceStatus(detail)}{detail.seniority ? ` · ${detail.seniority}` : ""}</p>
          <div className="mt-3"><TechnologyChips key={detail.id} names={detail.stack} /></div>
        </>}
      </SheetHeader>
      {detailError && <p role="alert" className="shrink-0 bg-destructive/10 px-4 py-2 text-sm text-destructive">{detailError}</p>}
      <section aria-label="Job description" tabIndex={0} className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 outline-offset-[-2px]">
        {detail ? <JobDescription text={detail.raw_jd} /> : <p role="status">{detailError || "Loading job…"}</p>}
      </section>
      {relatedJobs.length > 0 && <details className="shrink-0 border-t bg-background px-4 py-2" aria-label="Other listings for this role">
        <summary className="cursor-pointer py-1 text-xs font-medium">Other listings for this role ({relatedJobs.length})</summary>
        <ul className="mt-2 max-h-28 space-y-2 overflow-y-auto">{relatedJobs.map(job => <li key={job.id}>
          <button aria-label={`Open ${job.title} at ${job.company}, listing ${job.id}`} onClick={() => selectJob(job.id)} className="w-full rounded-lg border px-3 py-2 text-left text-xs hover:bg-muted focus-visible:outline-2">
            <span className="block">{job.location ?? "Location unknown"} · {job.source}</span>
            <span className="mt-1 block text-muted-foreground">{job.posted_at ? `Posted ${date(job.posted_at)} · ` : ""}{statusLabels[job.status]} · {job.score === null ? "Not scored" : `${job.score}/100`} · Listing {shortListingId(job.id)}</span>
          </button>
        </li>)}</ul>
      </details>}
      {detail && <footer className="max-h-[30dvh] shrink-0 space-y-2 overflow-y-auto border-t bg-background p-4">
        <p className="text-xs capitalize text-muted-foreground">Source: {detail.source}</p>
        <div className="flex flex-wrap items-end gap-3">
          <StatusSelect key={detail.id} job={detail} saving={saving || selected === null} changeStatus={changeStatus} />
          <a className={buttonVariants({className:"w-fit"})} href={detail.apply_url ?? detail.url} target="_blank" rel="noopener noreferrer">Apply on company site <ArrowUpRight aria-hidden="true" /></a>
        </div>
        {detail.status_reason && <p className="text-xs text-muted-foreground">Status reason: {detail.status_reason}</p>}
      </footer>}
    </SheetContent>
  </Sheet>;
}
