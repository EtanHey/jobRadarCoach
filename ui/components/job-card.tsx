"use client";

import type { ReactNode, RefObject } from "react";
import { Bookmark } from "lucide-react";
import type { JobSummary } from "@/lib/contracts";
import { scoreCss } from "@/lib/globe-model";
import { workMode } from "@/lib/job-display";
import { statusLabels, type JobStatus } from "@/lib/job-status";
import { cn } from "@/lib/utils";
import { CompanyLogo } from "./company-logo";
import { PostingDates } from "./posting-dates";

type Props = {
  job: JobSummary;
  alternateCount?: number;
  selected?: boolean;
  /** Set in "New for me" when this kept card's status no longer qualifies: dims the content and names the status. */
  keptStatus?: JobStatus | null;
  actions?: ReactNode;
  openerRef: RefObject<HTMLButtonElement | null>;
  selectJob: (id: string | null) => void;
  children: ReactNode;
};

export function JobCard({ job, selected, keptStatus = null, actions, alternateCount = 0, openerRef, selectJob, children }: Props) {
  const experience = job.experience ?? job.seniority ?? "Experience unspecified";
  const place = `${job.location ?? "Location unspecified"} · ${workMode(job.remote)}`;
  // Dim the content, never the frame: hover border and focus ring stay full strength on settled cards.
  const dim = keptStatus ? "opacity-60" : "";
  const keptId = `kept-status-${job.id}`;
  return <article data-posting-id={job.id} data-settled={keptStatus ? "" : undefined} className="relative flex w-full flex-col gap-3 rounded-xl border bg-card p-4 text-card-foreground shadow-sm transition-colors hover:border-ring/50 focus-within:ring-2 focus-within:ring-ring">
    <button type="button" aria-pressed={selected} aria-label={`Open ${job.title} at ${job.company}`} aria-describedby={keptStatus ? keptId : undefined} className="absolute inset-0 rounded-xl outline-none" onClick={event => { openerRef.current = event.currentTarget; selectJob(job.id); }} />
    <div className="pointer-events-none flex flex-wrap items-start gap-3">
      <CompanyLogo company={job.company} className={cn("size-14 sm:size-16", dim)} />
      <div className={cn("min-w-0 max-w-[28rem] flex-[1_1_9rem]", dim)}>
        <p className="truncate text-sm text-muted-foreground">{job.company}</p>
        <h2 className="mt-1 line-clamp-2 h-12 text-lg font-semibold leading-6 sm:h-14 sm:text-xl sm:leading-7" title={job.title}>{job.title}</h2>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <span style={job.score === null ? { border: "2px solid var(--globe-unscored-ring)" } : { backgroundColor: scoreCss(job.score), color: "#08111c" }} aria-label={job.score === null ? "Not scored" : `Fit score ${job.score} out of 100`} className={cn(job.score === null ? "rounded-lg px-2 py-1 text-xs text-muted-foreground" : "rounded-lg px-2 py-1", dim)}>
          {job.score === null ? "Unscored" : <><strong className="text-base tabular-nums">{job.score}</strong><span className="text-[10px]">/100</span></>}
        </span>
        {!keptStatus && job.status === "worth_checking" && <Bookmark size={13} aria-label="Worth checking" className="text-muted-foreground" />}
      </div>
    </div>
    {keptStatus ? <div className="pointer-events-none flex h-5 min-w-0 items-center gap-2">
      <p className={cn("min-w-0 flex-1 truncate text-sm text-muted-foreground", dim)} title={place}>{place}</p>
      {/* A reserved one-line slot: the chip never touches the header, and a long label ellipsizes instead of growing the card. */}
      <span id={keptId} data-kept-status={keptStatus} title={statusLabels[keptStatus]} className="inline-flex h-5 max-w-[45%] shrink-0 items-center rounded-md border bg-muted px-1.5 text-[11px] font-medium text-foreground"><span className="truncate">{statusLabels[keptStatus]}</span></span>
    </div>
      : <p className="pointer-events-none truncate text-sm text-muted-foreground" title={place}>{place}</p>}
    <div className={cn("pointer-events-none relative min-h-[3.625rem] text-muted-foreground [&_button]:pointer-events-auto", dim)}>{job.stack.length ? children : <span className="text-xs">Stack unspecified</span>}</div>
    <div className={cn("pointer-events-none mt-auto grid min-w-0 gap-1 text-xs text-muted-foreground sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-2", dim)}>
      <span className="min-w-0 flex-1 truncate" title={experience}>{experience}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 sm:justify-end">
        <PostingDates postedAt={job.posted_at} firstSeenAt={job.first_seen_at} className="shrink-0" />
        <span className="shrink-0 capitalize">{job.source}</span>
        {alternateCount > 0 && <span className="shrink-0" title="Open to choose another listing">{alternateCount + 1} listings</span>}
      </div>
    </div>
    {actions && <div className="relative z-10">{actions}</div>}
  </article>;
}
