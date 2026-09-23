"use client";

import { useState, type ReactNode, type RefObject } from "react";
import type { JobDetail, JobSummary } from "@/lib/contracts";
import { companyInitials, logoPathForCompany } from "@/lib/company-logos";
import { workMode } from "@/lib/job-display";
import { shortListingId } from "@/lib/job-dedup";
import { statusLabels } from "@/lib/job-status";
import { cn } from "@/lib/utils";
import { AssessmentSheet } from "./assessment-sheet";
import { Button } from "./ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "./ui/sheet";
import { JobDescription } from "./job-description";
import { PostingDates } from "./posting-dates";
import { TechnologyChips } from "./technology-chips";

type Opener = RefObject<HTMLButtonElement | null>;

export type JobDrawerProps = {
  actions?: ReactNode;
  detail: JobDetail | null;
  detailError: string;
  openerRef: Opener;
  relatedJobs?: JobSummary[];
  retryDetail: () => void;
  retryDisabled?: boolean;
  selected: string | null;
  selectedJob?: JobSummary;
  selectJob: (id: string | null) => void;
};

const experienceStatus = (job: JobDetail) => job.experience
  ?? (job.description_available ? "Check description for experience" : "Description unavailable");

function DrawerCompanyLogo({ company }: { company: string }) {
  const src = logoPathForCompany(company);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const frame = "grid size-14 shrink-0 place-items-center overflow-hidden rounded-lg border sm:size-16";

  if (!src || failedSrc === src) {
    return <span role="img" aria-label={`${company} logo unavailable`} data-logo-state={src ? "load-failed" : "unmapped"} className={cn(frame, "bg-muted text-sm font-bold text-muted-foreground")}>{companyInitials(company)}</span>;
  }

  return <span className={frame}>{/* Deliberately portable: this component's import tree cannot depend on Next.js. */}
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src={src} alt={`${company} logo`} width={64} height={64} className="size-full object-contain" onError={() => setFailedSrc(src)} />
  </span>;
}

export function JobDrawer({ actions, detail, detailError, openerRef, relatedJobs = [], retryDetail, retryDisabled = false, selected, selectedJob, selectJob }: JobDrawerProps) {
  const heading = detail ?? selectedJob;
  return <Sheet open={selected !== null} onOpenChange={open => !open && selectJob(null)}>
    <SheetContent finalFocus={openerRef} className="flex gap-0 overflow-hidden p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-2xl">
      <SheetHeader className="max-h-[45dvh] shrink-0 overflow-y-auto border-b bg-background p-4 pr-12">
        <div className="flex items-center gap-3">{heading && <DrawerCompanyLogo company={heading.company} />}<SheetDescription>{heading ? `${heading.company} · Listing ${shortListingId(heading.id)}` : detailError ? "Role unavailable" : "Loading the role…"}</SheetDescription></div>
        <div className="mt-3 flex items-start justify-between gap-3"><SheetTitle className="text-xl leading-snug sm:text-2xl">{heading?.title ?? "Job details"}</SheetTitle>{detail && <AssessmentSheet key={detail.id} job={detail} />}</div>
        {heading && <p className="mt-1 text-sm text-muted-foreground"><PostingDates postedAt={heading.posted_at} firstSeenAt={heading.first_seen_at} /></p>}
        {detail && <>
          <p className="mt-2 text-sm text-muted-foreground">{detail.location ?? "Location unspecified"} · {workMode(detail.remote)}</p>
          <p className="mt-1 text-sm text-muted-foreground">{experienceStatus(detail)}{detail.seniority ? ` · ${detail.seniority}` : ""}</p>
          <div className="mt-3"><TechnologyChips key={detail.id} names={detail.stack} /></div>
        </>}
      </SheetHeader>
      {detailError && <div role="alert" className="shrink-0 space-y-2 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        <p>{detailError}</p>
        <div className="flex flex-wrap items-center gap-3">
          {!detail && <Button variant="outline" disabled={retryDisabled} onClick={retryDetail}>Retry loading role</Button>}
          {detail && <Button variant="outline" disabled={retryDisabled} onClick={retryDetail}>Refresh role</Button>}
          {heading && <a className="underline" href={heading.url} target="_blank" rel="noopener noreferrer">Open original posting</a>}
        </div>
      </div>}
      <section aria-label="Job description" tabIndex={0} className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 outline-offset-[-2px]">
        {detail ? <JobDescription text={detail.raw_jd} /> : !detailError && <p role="status">Loading job…</p>}
      </section>
      {relatedJobs.length > 0 && <details className="shrink-0 border-t bg-background px-4 py-2" aria-label="Other listings for this role">
        <summary className="cursor-pointer py-1 text-xs font-medium">Other listings for this role ({relatedJobs.length})</summary>
        <ul className="mt-2 max-h-28 space-y-2 overflow-y-auto">{relatedJobs.map(job => <li key={job.id}>
          <button aria-label={`Open ${job.title} at ${job.company}, listing ${job.id}`} onClick={() => selectJob(job.id)} className="w-full rounded-lg border px-3 py-2 text-left text-xs hover:bg-muted focus-visible:outline-2">
            <span className="block">{job.location ?? "Location unknown"} · {job.source}</span>
            <span className="mt-1 block text-muted-foreground"><PostingDates postedAt={job.posted_at} firstSeenAt={job.first_seen_at} /> · {statusLabels[job.status]} · {job.score === null ? "Not scored" : `${job.score}/100`} · Listing {shortListingId(job.id)}</span>
          </button>
        </li>)}</ul>
      </details>}
      {actions && <footer className="max-h-[30dvh] shrink-0 space-y-2 overflow-y-auto border-t bg-background p-4">{actions}</footer>}
    </SheetContent>
  </Sheet>;
}
