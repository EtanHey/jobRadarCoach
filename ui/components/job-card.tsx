"use client";

import type { ReactNode, RefObject } from "react";
import { Recycle } from "lucide-react";
import type { JobSummary } from "@/lib/contracts";
import { scoreCss } from "@/lib/globe-model";
import { relevanceLabel } from "@/lib/relevance-label";
import { repostNote } from "@/lib/job-display";
import { statusDimsCard, statusLabels, type JobStatus } from "@/lib/job-status";
import { cn } from "@/lib/utils";
import { CompanyLogo } from "./company-logo";
import { InfoTip } from "./info-tip";
import { LinkedInClosureBadge } from "./linkedin-closure-badge";
import { PostingDates } from "./posting-dates";
import { WorkModeIcon } from "./work-mode-icon";

type Props = {
  job: JobSummary;
  alternateCount?: number;
  /** Alternates demonstrably listed before this one; drives the repost marker. */
  earlierListings?: number;
  selected?: boolean;
  /** Set in "New for me" when this kept card's status no longer qualifies; marks the card settled. */
  keptStatus?: JobStatus | null;
  logoSize?: "sm" | "md";
  actions?: ReactNode;
  openerRef: RefObject<HTMLButtonElement | null>;
  selectJob: (id: string | null) => void;
  /** Warms the drawer's detail read on mouse/pen hover or keyboard focus; never on touch. */
  prefetchIntent?: { start: (id: string) => void; end: (id: string) => void };
  children: ReactNode;
};

export function JobCard({ job, selected, keptStatus = null, logoSize = "md", actions, alternateCount = 0, earlierListings = 0, openerRef, selectJob, prefetchIntent, children }: Props) {
  const experience = job.experience ?? job.seniority ?? "Experience unspecified";
  const repost = repostNote(job.posted_at, job.last_published_at, earlierListings);
  const location = job.location ?? "Location unspecified";
  // Every view names a non-new status under the score; terminal statuses (and Seen, kept in New for me) dim the
  // content, never the frame, so hover border and focus ring stay full strength.
  const chip = job.status === "new" ? null : statusLabels[job.status];
  const dim = statusDimsCard(job.status) || keptStatus === "seen" ? "opacity-60" : "";
  const chipId = `card-status-${job.id}`;
  return <article data-posting-id={job.id} data-settled={keptStatus ? "" : undefined} onPointerEnter={event => { if (event.pointerType !== "touch") prefetchIntent?.start(job.id); }} onPointerLeave={() => prefetchIntent?.end(job.id)} className="relative flex w-full flex-col gap-3 rounded-xl border bg-card p-4 text-card-foreground shadow-sm transition-[color,background-color,border-color,box-shadow] duration-150 motion-reduce:duration-0 hover:border-ring/50 hover:shadow-md has-[:focus-visible]:border-ring/50 has-[:focus-visible]:shadow-md has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring">
    <button type="button" aria-pressed={selected} aria-label={`Open ${job.title} at ${job.company}`} aria-describedby={chip ? chipId : undefined} className="absolute inset-0 rounded-xl outline-none" onClick={event => { openerRef.current = event.currentTarget; selectJob(job.id); }}
      onFocus={event => { if (event.currentTarget.matches(":focus-visible")) prefetchIntent?.start(job.id); }} onBlur={() => prefetchIntent?.end(job.id)} />
    <div className="pointer-events-none flex flex-wrap items-start gap-3">
      <CompanyLogo company={job.company} applyUrl={job.apply_url} url={job.url} postingId={job.id} size={logoSize} className={dim} />
      <div className={cn("min-w-0 max-w-[28rem] flex-[1_1_9rem]", dim)}>
        <div className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
          <p className="truncate">{job.company}</p>
          {repost && <InfoTip data-repost-marker label={repost} tip={repost} className="shrink-0"><Recycle aria-hidden="true" size={13} /></InfoTip>}
        </div>
        <h2 className="mt-1 line-clamp-2 h-12 text-lg font-semibold leading-6 sm:h-14 sm:text-xl sm:leading-7" title={job.title}>{job.title}</h2>
      </div>
      {/* A small minimum keeps status words readable beside single-digit scores. The chip uses the
          column width and wraps to its full height. */}
      <div className="flex min-w-[4.75rem] shrink-0 flex-col items-end gap-1.5">
        <span style={job.score === null ? { border: "2px solid var(--globe-unscored-ring)" } : { backgroundColor: scoreCss(job.score), color: "#08111c" }} aria-label={job.score === null ? "Not scored" : `Fit score ${job.score} out of 100`} className={cn(job.score === null ? "rounded-lg px-2 py-1 text-xs text-muted-foreground" : "rounded-lg px-2 py-1", dim)}>
          {job.score === null ? job.relevance_filtered ? "Not scored (filtered)" : "Unscored" : <><strong className="text-base tabular-nums">{job.score}</strong><span className="text-[10px]">/100</span></>}
        </span>
        {chip && <span id={chipId} data-card-status={job.status} title={chip} className={cn("w-0 min-w-full rounded-md border px-1 py-0.5 text-center text-[10px] font-medium leading-3 [overflow-wrap:anywhere]", job.status === "seen" ? "text-muted-foreground" : "bg-muted text-foreground", dim)}>{chip}</span>}
      </div>
    </div>
    <p className={cn("pointer-events-none flex h-5 min-w-0 items-center gap-1.5 text-sm text-muted-foreground", dim)}>
      <WorkModeIcon job={job} />
      <span className="min-w-0 truncate" title={location}>{location}</span>
    </p>
    <div className={cn("pointer-events-none relative min-h-[3.625rem] text-muted-foreground [&_button]:pointer-events-auto", dim)}>{job.stack.length ? children : <span className="text-xs">Stack unspecified</span>}</div>
    <div className={cn("pointer-events-none mt-auto flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground", dim)}>
      <span data-experience className="min-w-0 break-words">{experience}</span>
      <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-1">
        <PostingDates postedAt={job.posted_at} lastPublishedAt={job.last_published_at} firstSeenAt={job.first_seen_at} className="shrink-0" />
        <span className="shrink-0 capitalize">{job.source}</span>
        {alternateCount > 0 && <span className="shrink-0" title="Open to choose another listing">{alternateCount + 1} listings</span>}
      </div>
    </div>
    {job.relevance_filtered && <p className="pointer-events-none text-xs text-muted-foreground">{relevanceLabel(job.relevance_rule)}</p>}
    <LinkedInClosureBadge job={job} />
    {actions && <div className="relative z-10">{actions}</div>}
  </article>;
}
